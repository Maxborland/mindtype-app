"""Exercise the real desktop cloud client against docker-compose.local.yml."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.licensing.session import LicenseSessionClient
from app.operation_coordinator import OperationCoordinator
from app.operation_models import OperationStage, OperationStatus
from app.operation_store import OperationStore
from app.providers.mindtype_cloud import (
    MindTypeCloudClient,
    MindTypeCloudExecutor,
)
from app.spool import SpoolManager


BASE_URL = "http://127.0.0.1:33100"


def write_fixture(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 16_000)


def main() -> None:
    device_id = hashlib.sha256(
        b"mindtype-local-desktop-device"
    ).hexdigest()
    session = LicenseSessionClient(BASE_URL).create_session(
        license_key="ABCD-EFGH-JKMP-2345",
        device_id_hash=device_id,
        desktop_version="0.0.0-local",
        platform="win32",
    )
    operation_id = f"mindtype-desktop-e2e-{uuid.uuid4()}"

    with tempfile.TemporaryDirectory(prefix="mindtype-desktop-e2e-") as root:
        root_path = Path(root)
        original = root_path / "customer interview.wav"
        write_fixture(original)
        coordinator = OperationCoordinator(
            store=OperationStore(root_path / "operations.sqlite3"),
            spool=SpoolManager(root_path / "spool"),
        )
        operation = coordinator.create_file_operation(
            original,
            route={
                "transcription": {
                    "provider": "mindtype_cloud",
                    "model": "auto",
                },
                "diarization": {
                    "provider": "mindtype_cloud",
                    "model": "auto",
                },
                "summary": {
                    "provider": "mindtype_cloud",
                    "model": "auto",
                },
            },
            operation_id=operation_id,
        )
        client = MindTypeCloudClient(
            BASE_URL,
            access_token=session.access_token,
            retry_delays=(0, 0, 0, 0, 0),
        )
        executor = MindTypeCloudExecutor(
            client=client,
            coordinator=coordinator,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            operation = executor.advance_transcription(
                operation_id,
                options={
                    "language": "ru",
                    "word_timestamps": True,
                    "diarization": True,
                    "quality_profile": "balanced",
                },
                summary_options={
                    "preset": "pm",
                    "input_token_estimate": 100,
                    "max_output_tokens": 800,
                },
            )
            if operation.status is OperationStatus.COMPLETED:
                break
            if operation.status in {
                OperationStatus.FAILED,
                OperationStatus.CANCELLED,
                OperationStatus.RETRYABLE,
            }:
                raise RuntimeError(
                    f"operation stopped in {operation.status.value}: "
                    f"{operation.last_error_code}"
                )
            time.sleep(0.5)
        else:
            raise TimeoutError("desktop cloud operation timed out")

        if operation.canonical_result_path is None:
            raise RuntimeError("canonical result path was not saved")
        result = json.loads(
            operation.canonical_result_path.read_text(encoding="utf-8")
        )
        if result["source"]["display_name"] != original.name:
            raise RuntimeError("local display name was not restored")
        if result["summary"]["generated"] is not True:
            raise RuntimeError("summary was not preserved")
        if operation.source_asset_path.exists():
            raise RuntimeError("acknowledged spool source was not removed")

        local_original = root_path / "local transcript.wav"
        write_fixture(local_original)
        local_operation_id = f"mindtype-local-summary-e2e-{uuid.uuid4()}"
        local_operation = coordinator.create_file_operation(
            local_original,
            route={
                "transcription": {
                    "provider": "local",
                    "model": "whisper-server",
                },
                "summary": {
                    "provider": "mindtype_cloud",
                    "model": "auto",
                },
            },
            operation_id=local_operation_id,
        )
        coordinator.begin_attempt(
            local_operation_id,
            stage=OperationStage.TRANSCRIBE,
        )
        local_transcript = {
            "schema_version": "1.0",
            "operation_id": local_operation_id,
            "source": {
                "display_name": local_original.name,
                "duration_ms": 1000,
                "sha256": local_operation.source_sha256,
                "channels": [],
            },
            "route": local_operation.route,
            "transcript": {
                "language": "ru",
                "confidence": 0.95,
                "segments": [
                    {
                        "segment_id": "segment-local-1",
                        "start_ms": 0,
                        "end_ms": 1000,
                        "text": "Локально распознанный текст.",
                        "speaker_id": None,
                        "words": [],
                        "confidence": 0.95,
                        "postprocessed": False,
                    }
                ],
            },
            "speakers": [],
            "summary": None,
            "warnings": [],
            "provenance": {
                "server_job_ids": [],
                "created_at": "2026-07-26T12:00:00+00:00",
            },
        }
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            local_operation = executor.advance_summary(
                local_operation_id,
                canonical_transcript=local_transcript,
                options={
                    "preset": "pm",
                    "input_token_estimate": 100,
                    "max_output_tokens": 800,
                },
            )
            if local_operation.status is OperationStatus.COMPLETED:
                break
            if local_operation.status in {
                OperationStatus.FAILED,
                OperationStatus.CANCELLED,
                OperationStatus.RETRYABLE,
            }:
                raise RuntimeError(
                    "local transcript cloud summary stopped in "
                    f"{local_operation.status.value}: "
                    f"{local_operation.last_error_code}"
                )
            time.sleep(0.5)
        else:
            raise TimeoutError("local transcript cloud summary timed out")
        local_result = json.loads(
            local_operation.canonical_result_path.read_text(encoding="utf-8")
        )
        if (
            local_result["route"]["transcription"]["provider"] != "local"
            or local_result["summary"]["generated"] is not True
        ):
            raise RuntimeError("hybrid local/cloud route was not preserved")
        if local_operation.source_asset_path.exists():
            raise RuntimeError("hybrid source was not removed after ACK")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "operation_id": operation_id,
                    "display_name": result["source"]["display_name"],
                    "segments": len(result["transcript"]["segments"]),
                    "summary_generated": result["summary"]["generated"],
                    "source_cleaned_after_ack": True,
                    "local_stt_cloud_summary": True,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
