"""Validation and atomic persistence for canonical MindType result JSON."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional


class CanonicalResultError(ValueError):
    """Raised when a result cannot satisfy the supported canonical schema."""


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalResultError(f"{path} must be an object")
    return value


def _require_string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise CanonicalResultError(f"{path} must be a string")
    return value


def _require_nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CanonicalResultError(f"{path} must be a non-negative integer")
    return value


def _validate_confidence(value: Any, path: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
    ):
        raise CanonicalResultError(f"{path} must be between 0 and 1")


def validate_canonical_result(
    payload: Mapping[str, Any],
    *,
    expected_operation_id: Optional[str] = None,
) -> dict[str, Any]:
    result = dict(_require_mapping(payload, "$"))
    version = _require_string(result.get("schema_version"), "schema_version")
    try:
        major_text, _minor_text = version.split(".", maxsplit=1)
        major = int(major_text)
    except (TypeError, ValueError):
        raise CanonicalResultError("schema_version must use major.minor format")
    if major != 1:
        raise CanonicalResultError(f"unsupported canonical schema major: {major}")

    operation_id = _require_string(result.get("operation_id"), "operation_id")
    if expected_operation_id is not None and operation_id != expected_operation_id:
        raise CanonicalResultError("canonical result belongs to another operation")

    source = _require_mapping(result.get("source"), "source")
    _require_string(source.get("display_name"), "source.display_name")
    _require_nonnegative_int(source.get("duration_ms"), "source.duration_ms")
    source_hash = _require_string(source.get("sha256"), "source.sha256")
    if not _SHA256.fullmatch(source_hash):
        raise CanonicalResultError("source.sha256 must be a SHA-256 hex digest")
    if not isinstance(source.get("channels"), list):
        raise CanonicalResultError("source.channels must be an array")

    route = _require_mapping(result.get("route"), "route")
    transcription_route = _require_mapping(
        route.get("transcription"),
        "route.transcription",
    )
    _require_string(
        transcription_route.get("provider"),
        "route.transcription.provider",
    )
    _require_string(
        transcription_route.get("model"),
        "route.transcription.model",
    )
    for stage_name in ("diarization", "summary"):
        if stage_name not in route:
            continue
        stage_route = _require_mapping(route[stage_name], f"route.{stage_name}")
        _require_string(stage_route.get("provider"), f"route.{stage_name}.provider")
        _require_string(stage_route.get("model"), f"route.{stage_name}.model")

    transcript = _require_mapping(result.get("transcript"), "transcript")
    _require_string(transcript.get("language"), "transcript.language")
    _validate_confidence(transcript.get("confidence"), "transcript.confidence")
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        raise CanonicalResultError("transcript.segments must be an array")
    segment_ids: set[str] = set()
    for index, raw_segment in enumerate(segments):
        path = f"transcript.segments[{index}]"
        segment = _require_mapping(raw_segment, path)
        segment_id = _require_string(segment.get("segment_id"), f"{path}.segment_id")
        if segment_id in segment_ids:
            raise CanonicalResultError(f"duplicate segment_id: {segment_id}")
        segment_ids.add(segment_id)
        start_ms = _require_nonnegative_int(segment.get("start_ms"), f"{path}.start_ms")
        end_ms = _require_nonnegative_int(segment.get("end_ms"), f"{path}.end_ms")
        if start_ms > end_ms:
            raise CanonicalResultError(f"{path} has inverted timestamps")
        _require_string(segment.get("text"), f"{path}.text", allow_empty=True)
        speaker_id = segment.get("speaker_id")
        if speaker_id is not None:
            _require_string(speaker_id, f"{path}.speaker_id")
        if "words" in segment and not isinstance(segment["words"], list):
            raise CanonicalResultError(f"{path}.words must be an array")
        _validate_confidence(segment.get("confidence"), f"{path}.confidence")
        if "postprocessed" in segment and not isinstance(
            segment["postprocessed"], bool
        ):
            raise CanonicalResultError(f"{path}.postprocessed must be boolean")

    speakers = result.get("speakers")
    if not isinstance(speakers, list):
        raise CanonicalResultError("speakers must be an array")
    for index, raw_speaker in enumerate(speakers):
        speaker = _require_mapping(raw_speaker, f"speakers[{index}]")
        _require_string(speaker.get("speaker_id"), f"speakers[{index}].speaker_id")

    summary = result.get("summary")
    if summary is not None:
        summary_data = _require_mapping(summary, "summary")
        _require_string(summary_data.get("text"), "summary.text", allow_empty=True)
        _require_string(summary_data.get("preset"), "summary.preset")
        if not isinstance(summary_data.get("generated"), bool):
            raise CanonicalResultError("summary.generated must be boolean")
        references = summary_data.get("source_segment_ids")
        if not isinstance(references, list):
            raise CanonicalResultError("summary.source_segment_ids must be an array")
        unknown_references = {
            reference
            for reference in references
            if not isinstance(reference, str) or reference not in segment_ids
        }
        if unknown_references:
            raise CanonicalResultError(
                "summary references unknown transcript segments"
            )

    if not isinstance(result.get("warnings"), list):
        raise CanonicalResultError("warnings must be an array")
    provenance = _require_mapping(result.get("provenance"), "provenance")
    if not isinstance(provenance.get("server_job_ids"), list):
        raise CanonicalResultError("provenance.server_job_ids must be an array")
    created_at = _require_string(
        provenance.get("created_at"),
        "provenance.created_at",
    )
    try:
        datetime.fromisoformat(created_at)
    except ValueError:
        raise CanonicalResultError("provenance.created_at must be ISO-8601")

    return result


def write_canonical_result(
    path: Path,
    payload: Mapping[str, Any],
    *,
    expected_operation_id: Optional[str] = None,
) -> Path:
    """Validate, flush, and atomically publish canonical JSON."""
    result = validate_canonical_result(
        payload,
        expected_operation_id=expected_operation_id,
    )
    final_path = Path(path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = final_path.with_name(f"{final_path.name}.part")
    try:
        with part_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(
                result,
                output,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(part_path, final_path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise
    return final_path
