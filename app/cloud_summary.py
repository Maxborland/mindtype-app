"""Canonical MindType Cloud summary client.

This module is intentionally small and composes :class:`CloudTranscriptionClient`
for session/token handling.  It does not acknowledge a summary job while a
caller is still holding the result: callers persist the returned text first and
call :meth:`acknowledge` afterwards.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import time
from typing import Any, Dict, Mapping, Optional
from urllib.parse import quote
from uuid import uuid4

from .cloud_transcription import (
    CloudTranscriptionClient,
    CloudTranscriptionError,
)


@dataclass(frozen=True)
class CloudSummaryOutcome:
    operation_id: str
    job_id: str
    text: str
    preset: str
    generated: bool
    source_segment_ids: list[str]
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    canonical_result: Dict[str, Any]


MAX_CUSTOM_PROMPT_CHARS = 8_000


def serialize_prompt_templates(prompts: Mapping[str, str]) -> str:
    """Serialize the four desktop template fields into one server prompt.

    The Cloud API deliberately accepts one bounded custom prompt. Keeping the
    field labels makes the existing editable desktop templates unambiguous while
    avoiding a second provider-specific schema.
    """

    parts = []
    for key in ("system", "short", "extraction", "aggregation"):
        value = str(prompts.get(key, ""))
        if value.strip():
            parts.append(f"{key.upper()} PROMPT:\n{value}")
    serialized = "\n\n".join(parts)
    if len(serialized) > MAX_CUSTOM_PROMPT_CHARS:
        raise ValueError(
            f"Cloud summary prompts exceed {MAX_CUSTOM_PROMPT_CHARS} characters"
        )
    return serialized


def canonical_from_transcription_result(
    result: Any,
    *,
    operation_id: Optional[str] = None,
    prefer_existing: bool = True,
) -> Dict[str, Any]:
    """Build a valid canonical transcript from a saved desktop result.

    Cloud transcription already provides an exact canonical payload and callers
    should pass that through.  This fallback is for the later library-document
    flow (and local STT + Cloud summary), where SQLite stores normalized segments
    rather than the remote envelope.
    """

    existing = getattr(result, "cloud_canonical_result", None)
    if prefer_existing and isinstance(existing, dict):
        return deepcopy(existing)

    raw_source_text = " ".join(
        str(getattr(segment, "text", ""))
        for segment in getattr(result, "segments", ())
        if str(getattr(segment, "text", "")).strip()
    )
    explicit_processed_text = getattr(result, "processed_text", None)
    summary_text = getattr(result, "text_for_summary", None)
    if not isinstance(summary_text, str) or not summary_text.strip():
        summary_text = explicit_processed_text
    use_processed_payload = (
        isinstance(summary_text, str)
        and bool(summary_text.strip())
        and (
            bool(
                isinstance(explicit_processed_text, str)
                and explicit_processed_text.strip()
            )
            or summary_text != raw_source_text
        )
    )
    processed_text = summary_text if use_processed_payload else ""
    source_text = summary_text if isinstance(summary_text, str) and summary_text.strip() else raw_source_text
    digest = sha256(source_text.encode("utf-8")).hexdigest()
    operation = operation_id or str(uuid4())
    if processed_text:
        # The Cloud summary worker consumes transcript.segments. Use one
        # synthetic segment so post-processing is represented exactly rather
        # than silently falling back to the raw segment text.
        segments = [
            {
                "segment_id": "processed-text",
                "start_ms": 0,
                "end_ms": max(0, int(float(getattr(result, "duration", 0)) * 1000)),
                "text": processed_text,
                "speaker_id": None,
                "words": [],
            }
        ]
    else:
        segments = []
        for index, segment in enumerate(getattr(result, "segments", ()), start=1):
            segments.append(
                {
                    "segment_id": f"segment-{index:04d}",
                    "start_ms": max(0, int(float(getattr(segment, "start", 0)) * 1000)),
                    "end_ms": max(0, int(float(getattr(segment, "end", 0)) * 1000)),
                    "text": str(getattr(segment, "text", "")),
                    "speaker_id": getattr(segment, "speaker", None),
                    "words": [],
                }
            )
    speaker_names = getattr(result, "speaker_names", {}) or {}
    speakers = [
        {"speaker_id": str(speaker_id), "display_name": str(name)}
        for speaker_id, name in speaker_names.items()
    ]
    language = str(getattr(result, "detected_language", None) or "multilingual")
    model_used = str(getattr(result, "model_used", "desktop"))
    duration_ms = max(0, int(float(getattr(result, "duration", 0)) * 1000))
    return {
        "schema_version": "1.0",
        "operation_id": operation,
        "source": {
            "display_name": "local-transcript",
            "duration_ms": duration_ms,
            "sha256": digest,
            "channels": [],
        },
        "route": {
            "transcription": {"provider": model_used.split("/", 1)[0], "model": model_used},
            "summary": {"provider": "mindtype_cloud", "model": "auto"},
        },
        "transcript": {
            "language": language,
            "confidence": float(getattr(result, "language_probability", 0) or 0),
            "segments": segments,
        },
        "speakers": speakers,
        "summary": None,
        "warnings": [],
        "provenance": {
            "server_job_ids": [],
            "created_at": "1970-01-01T00:00:00+00:00",
        },
    }


class CloudSummaryClient:
    """Submit/poll/fetch a provider-neutral Cloud summary job."""

    _ACTIVE_STATES = {"queued", "running", "cancelling"}

    def __init__(
        self,
        client: CloudTranscriptionClient,
        *,
        poll_interval_seconds: Optional[float] = None,
        poll_timeout_seconds: Optional[float] = None,
    ) -> None:
        self.client = client
        self.poll_interval_seconds = (
            client.poll_interval_seconds
            if poll_interval_seconds is None
            else max(0.0, float(poll_interval_seconds))
        )
        self.poll_timeout_seconds = (
            client.poll_timeout_seconds
            if poll_timeout_seconds is None
            else max(1.0, float(poll_timeout_seconds))
        )

    def summarize(
        self,
        *,
        canonical_transcript: Mapping[str, Any],
        preset: str,
        custom_prompt: Optional[str] = None,
        operation_id: Optional[str] = None,
        source_artifact_id: Optional[str] = None,
        input_token_estimate: int = 0,
        max_output_tokens: int = 2_000,
    ) -> CloudSummaryOutcome:
        operation = operation_id or str(uuid4())
        normalized_preset = str(preset or "generic")
        prompt = str(custom_prompt or "").strip()
        if prompt:
            normalized_preset = "custom"
        elif normalized_preset not in {"pm", "student", "generic"}:
            # The desktop may store a localized display label or an empty
            # user-preset id. Keep an empty-prompt request within the Cloud
            # enum instead of sending a guaranteed 400.
            normalized_preset = "generic"
        body: Dict[str, Any] = {
            "operation_id": operation,
            "preset": normalized_preset,
            "input_token_estimate": max(0, int(input_token_estimate)),
            "max_output_tokens": max(1, int(max_output_tokens)),
        }
        if prompt:
            body["custom_prompt"] = prompt
        if source_artifact_id:
            body["source_artifact_id"] = str(source_artifact_id)
        else:
            cloud_transcript = deepcopy(dict(canonical_transcript))
            source = cloud_transcript.get("source")
            if isinstance(source, dict):
                source["display_name"] = "local-transcript"
            body["transcript"] = cloud_transcript

        created = self.client._request_json(  # noqa: SLF001 - composed internal client
            "POST",
            "/v1/summaries",
            token=self.client._access_token(),  # noqa: SLF001
            headers={"Idempotency-Key": f"{operation}:summary"},
            body=body,
        )
        try:
            job_id = str(created["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise CloudTranscriptionError(
                "INVALID_RESPONSE",
                "MindType Cloud returned an incomplete summary job",
            ) from error

        deadline = time.monotonic() + self.poll_timeout_seconds
        try:
            while True:
                self.client._check_cancelled()  # noqa: SLF001
                state = self.client._request_json(  # noqa: SLF001
                    "GET",
                    f"/v1/summaries/{quote(job_id, safe='')}",
                    token=self.client._access_token(),  # noqa: SLF001
                )
                state_name = str(state.get("state", ""))
                if state_name == "succeeded":
                    break
                if state_name in {"failed", "cancelled", "awaiting_funds", "expired"}:
                    error_data = state.get("error") or {}
                    raise CloudTranscriptionError(
                        str(error_data.get("code", state_name.upper())),
                        str(error_data.get("message", f"Cloud summary {state_name}")),
                        retryable=bool(error_data.get("retryable", False)),
                    )
                if state_name not in self._ACTIVE_STATES:
                    raise CloudTranscriptionError(
                        "INVALID_RESPONSE",
                        f"MindType Cloud returned unknown summary state: {state_name}",
                    )
                if time.monotonic() >= deadline:
                    raise CloudTranscriptionError(
                        "TIMEOUT",
                        "MindType Cloud summary timed out",
                        retryable=True,
                    )
                self.client._sleep(self.poll_interval_seconds)  # noqa: SLF001

            payload = self.client._request_json(  # noqa: SLF001
                "GET",
                f"/v1/summaries/{quote(job_id, safe='')}/result",
                token=self.client._access_token(),  # noqa: SLF001
            )
        except CloudTranscriptionError as error:
            if error.code == "CANCELLED":
                try:
                    self.cancel(job_id)
                except Exception:
                    # Preserve the user cancellation as the primary outcome;
                    # the durable ACK/retry path handles cleanup failures.
                    pass
            raise
        canonical = self.client._validate_canonical(  # noqa: SLF001
            payload.get("result"),
            operation,
        )
        summary = canonical.get("summary")
        if not isinstance(summary, dict) or not isinstance(summary.get("text"), str):
            raise CloudTranscriptionError(
                "SCHEMA_UNSUPPORTED",
                "Canonical Cloud summary result is missing summary.text",
            )
        route = canonical.get("route", {}).get("summary", {})
        usage = canonical.get("usage", {})
        return CloudSummaryOutcome(
            operation_id=operation,
            job_id=job_id,
            text=summary["text"],
            preset=str(summary.get("preset", normalized_preset)),
            generated=bool(summary.get("generated", True)),
            source_segment_ids=[str(item) for item in summary.get("source_segment_ids", [])],
            provider=str(route.get("provider", "mindtype_cloud")),
            model=str(route.get("model", "auto")),
            input_tokens=int(usage.get("input_tokens", input_token_estimate) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            canonical_result=canonical,
        )

    def acknowledge(self, job_id: str) -> None:
        self.client._request_json(  # noqa: SLF001
            "POST",
            f"/v1/summaries/{quote(str(job_id), safe='')}/ack",
            token=self.client._access_token(),  # noqa: SLF001
            body={},
        )

    def cancel(self, job_id: str) -> None:
        self.client._request_json(  # noqa: SLF001
            "DELETE",
            f"/v1/summaries/{quote(str(job_id), safe='')}",
            token=self.client._access_token(),  # noqa: SLF001
            check_cancelled=False,
        )
