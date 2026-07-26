from datetime import datetime, timezone
from pathlib import Path

import pytest


def canonical_result(operation_id: str = "operation-1") -> dict:
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "source": {
            "display_name": "meeting.wav",
            "duration_ms": 12_345,
            "sha256": "a" * 64,
            "channels": [],
        },
        "route": {
            "transcription": {
                "provider": "mindtype_cloud",
                "model": "auto",
            }
        },
        "transcript": {
            "language": "ru",
            "confidence": 0.94,
            "segments": [
                {
                    "segment_id": "segment-1",
                    "start_ms": 0,
                    "end_ms": 1_000,
                    "text": "Привет",
                    "speaker_id": "speaker-1",
                    "words": [],
                    "confidence": 0.95,
                    "postprocessed": False,
                }
            ],
        },
        "speakers": [{"speaker_id": "speaker-1", "display_name": "Speaker 1"}],
        "summary": {
            "text": "Приветствие",
            "preset": "pm",
            "generated": True,
            "source_segment_ids": ["segment-1"],
        },
        "warnings": [],
        "provenance": {
            "server_job_ids": ["server-job-1"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def test_canonical_result_accepts_v1_additive_fields() -> None:
    from app.result_schema import validate_canonical_result

    result = canonical_result()
    result["future_minor_field"] = {"safe": True}

    validated = validate_canonical_result(
        result,
        expected_operation_id="operation-1",
    )

    assert validated["operation_id"] == "operation-1"
    assert validated["future_minor_field"] == {"safe": True}


def test_canonical_result_validates_multitrack_source_channels() -> None:
    from app.result_schema import validate_canonical_result

    result = canonical_result()
    result["source"]["channels"] = [
        {
            "source": "microphone",
            "sample_rate": 16000,
            "channels": 1,
            "started_at_monotonic_ns": 10,
            "ended_at_monotonic_ns": 20,
            "sha256": "b" * 64,
        },
        {
            "source": "system",
            "sample_rate": 48000,
            "channels": 2,
            "started_at_monotonic_ns": 11,
            "ended_at_monotonic_ns": 21,
        },
    ]

    validated = validate_canonical_result(result)

    assert validated["source"]["channels"][1]["source"] == "system"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "desktop"),
        ("sample_rate", 0),
        ("channels", 0),
        ("started_at_monotonic_ns", -1),
    ],
)
def test_canonical_result_rejects_invalid_track_metadata(
    field: str,
    value: object,
) -> None:
    from app.result_schema import CanonicalResultError, validate_canonical_result

    result = canonical_result()
    channel = {
        "source": "microphone",
        "sample_rate": 16000,
        "channels": 1,
        "started_at_monotonic_ns": 10,
        "ended_at_monotonic_ns": 20,
    }
    channel[field] = value
    result["source"]["channels"] = [channel]

    with pytest.raises(CanonicalResultError):
        validate_canonical_result(result)


def test_canonical_result_rejects_inverted_track_timestamps() -> None:
    from app.result_schema import CanonicalResultError, validate_canonical_result

    result = canonical_result()
    result["source"]["channels"] = [
        {
            "source": "system",
            "sample_rate": 48000,
            "channels": 2,
            "started_at_monotonic_ns": 20,
            "ended_at_monotonic_ns": 10,
        }
    ]

    with pytest.raises(CanonicalResultError, match="inverted"):
        validate_canonical_result(result)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda result: result.update(schema_version="2.0"),
            "unsupported canonical schema major",
        ),
        (
            lambda result: result["transcript"]["segments"][0].update(
                start_ms=2_000,
                end_ms=1_000,
            ),
            "inverted timestamps",
        ),
        (
            lambda result: result["summary"].update(
                source_segment_ids=["missing-segment"]
            ),
            "unknown transcript segments",
        ),
    ],
)
def test_canonical_result_rejects_unsupported_or_unverifiable_content(
    mutate,
    message: str,
) -> None:
    from app.result_schema import CanonicalResultError, validate_canonical_result

    result = canonical_result()
    mutate(result)

    with pytest.raises(CanonicalResultError, match=message):
        validate_canonical_result(result)


def test_canonical_result_is_atomically_written_without_partial_file(
    tmp_path: Path,
) -> None:
    import json

    from app.result_schema import write_canonical_result

    result_path = tmp_path / "operation" / "result.json"
    written = write_canonical_result(
        result_path,
        canonical_result(),
        expected_operation_id="operation-1",
    )

    assert written == result_path
    assert json.loads(written.read_text(encoding="utf-8"))["schema_version"] == "1.0"
    assert not (result_path.parent / "result.json.part").exists()


def test_canonical_result_rejects_inverted_word_timestamps() -> None:
    from app.result_schema import CanonicalResultError, validate_canonical_result

    result = canonical_result()
    result["transcript"]["segments"][0]["words"] = [
        {
            "start_ms": 900,
            "end_ms": 100,
            "text": "broken",
        }
    ]

    with pytest.raises(CanonicalResultError, match="word has inverted timestamps"):
        validate_canonical_result(result)
