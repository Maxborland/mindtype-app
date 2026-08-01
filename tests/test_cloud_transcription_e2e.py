from __future__ import annotations

from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from app.cloud_transcription import (
    CloudTranscriptionCancelled,
    CloudTranscriptionClient,
    CloudTranscriptionError,
    MindTypeCloudTranscriber,
)
from app.file_transcriber import (
    FileTranscriptionQueue,
    PostProcessOptions,
    SummaryOptions,
    TranscribeOptions,
)
from app.transcript_store import TranscriptStore, persist_completed_task
from app.transcription_models import FileStatus, FileTask


class _CloudContractHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    operation_id = ""
    media_sha256 = ""
    uploaded = bytearray()
    acknowledged = False
    cancelled_job = False
    job_created = False

    @classmethod
    def reset(cls) -> None:
        cls.requests = []
        cls.operation_id = ""
        cls.media_sha256 = ""
        cls.uploaded = bytearray()
        cls.acknowledged = False
        cls.cancelled_job = False
        cls.job_created = False

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _read(self) -> bytes:
        length = int(self.headers.get("content-length", "0"))
        return self.rfile.read(length)

    def _record(self, body: bytes) -> None:
        self.__class__.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "idempotency": self.headers.get("idempotency-key"),
                "part_sha256": self.headers.get("x-part-sha256"),
                "body": body,
            }
        )

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        body = self._read()
        self._record(body)
        parsed = json.loads(body or b"{}")
        cls = self.__class__

        if self.path == "/api/license/session":
            assert parsed["license_key"] == "ABCD-EFGH-JKMN-PQRS"
            assert len(parsed["device_id_hash"]) == 64
            assert parsed["platform"] == "windows"
            self._json(
                {
                    "access_token": "access-token",
                    "access_expires_at": "2099-01-01T00:00:00.000Z",
                    "refresh_token": "refresh-token-with-enough-entropy",
                    "entitlement_lease": "lease",
                    "claim_version": 1,
                }
            )
            return

        if self.path == "/v1/uploads":
            assert self.headers["authorization"] == "Bearer access-token"
            cls.media_sha256 = parsed["sha256"]
            assert "filename" not in parsed
            self._json(
                {
                    "id": "upload-1",
                    "state": "uploading",
                    "size": parsed["size"],
                    "sha256": parsed["sha256"],
                    "part_size": parsed["part_size"],
                    "uploaded_parts": [],
                    "replayed": False,
                    "upload_token": "upload-token",
                },
                201,
            )
            return

        if self.path == "/v1/uploads/upload-1/complete":
            assert self.headers["authorization"] == "Bearer upload-token"
            assert parsed["sha256"] == cls.media_sha256
            assert parsed["parts"] == 1
            self._json(
                {
                    "id": "upload-1",
                    "state": "uploaded",
                    "uploaded_parts": [1],
                }
            )
            return

        if self.path == "/v1/transcriptions":
            assert self.headers["authorization"] == "Bearer access-token"
            cls.operation_id = parsed["operation_id"]
            cls.job_created = True
            assert parsed["options"] == {
                "language": "auto",
                "word_timestamps": True,
                "diarization": True,
                "quality_profile": "balanced",
            }
            self._json(
                {
                    "id": "job-1",
                    "state": "queued",
                    "source_artifact_id": "upload-1",
                    "replayed": False,
                },
                202,
            )
            return

        if self.path == "/v1/transcriptions/job-1/ack":
            assert self.headers["authorization"] == "Bearer access-token"
            cls.acknowledged = True
            self._json(
                {
                    "id": "job-1",
                    "state": "succeeded",
                    "acknowledged_at": "2026-07-30T12:00:00.000Z",
                }
            )
            return

        self.send_error(404)

    def do_PUT(self) -> None:
        body = self._read()
        self._record(body)
        if self.path != "/v1/uploads/upload-1/parts/1":
            self.send_error(404)
            return
        assert self.headers["authorization"] == "Bearer upload-token"
        assert self.headers["x-part-sha256"] == hashlib.sha256(body).hexdigest()
        self.__class__.uploaded.extend(body)
        self._json(
            {
                "part_number": 1,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size": len(body),
                "etag": '"part-1"',
            }
        )

    def do_GET(self) -> None:
        body = self._read()
        self._record(body)
        cls = self.__class__
        if self.path == "/v1/transcriptions/job-1":
            self._json(
                {
                    "id": "job-1",
                    "state": "succeeded",
                    "result_artifact_id": "result-1",
                }
            )
            return
        if self.path == "/v1/transcriptions/job-1/result":
            self._json(
                {
                    "result": {
                        "schema_version": "1.0",
                        "operation_id": cls.operation_id,
                        "source": {
                            "display_name": "recording",
                            "duration_ms": 2400,
                            "sha256": cls.media_sha256,
                            "channels": [],
                        },
                        "route": {
                            "transcription": {
                                "provider": "mindtype_cloud",
                                "model": "nova-3",
                            },
                            "diarization": {
                                "provider": "mindtype_cloud",
                                "model": "nova-3",
                            },
                        },
                        "transcript": {
                            "language": "multilingual",
                            "confidence": 0.94,
                            "segments": [
                                {
                                    "segment_id": "segment-1",
                                    "start_ms": 0,
                                    "end_ms": 1200,
                                    "text": "Привет, расскажите о проекте.",
                                    "speaker_id": "SPEAKER_00",
                                    "words": [],
                                },
                                {
                                    "segment_id": "segment-2",
                                    "start_ms": 1200,
                                    "end_ms": 2400,
                                    "text": "Sure, this is MindType.",
                                    "speaker_id": "SPEAKER_01",
                                    "words": [],
                                },
                            ],
                        },
                        "speakers": [
                            {
                                "speaker_id": "SPEAKER_00",
                                "display_name": "Интервьюер",
                            },
                            {
                                "speaker_id": "SPEAKER_01",
                                "display_name": "Эксперт",
                            },
                        ],
                        "summary": None,
                        "warnings": [],
                        "provenance": {
                            "server_job_ids": ["provider-job-1"],
                            "created_at": "2026-07-30T11:59:00.000Z",
                        },
                    }
                }
            )
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        body = self._read()
        self._record(body)
        if self.path == "/v1/transcriptions/job-1":
            self.__class__.cancelled_job = True
            self._json({"id": "job-1", "state": "cancelling"}, 202)
            return
        if self.path == "/v1/uploads/upload-1":
            self._json({"id": "upload-1", "state": "cancelled"})
            return
        self.send_error(404)


@pytest.fixture
def cloud_server():
    _CloudContractHandler.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CloudContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(base_url: str, **kwargs: Any) -> CloudTranscriptionClient:
    return CloudTranscriptionClient(
        base_url=base_url,
        license_key="ABCD-EFGH-JKMN-PQRS",
        device_id="desktop-device",
        desktop_version="0.9.3",
        platform="win32",
        part_size=5 * 1024 * 1024,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_cloud_file_to_durable_library_then_acknowledges_cleanup(
    tmp_path: Path,
    cloud_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "private-meeting.wav"
    source.write_bytes(b"RIFF" + b"multilingual audio" * 128)
    spool_dir = tmp_path / "spool"
    client = _client(cloud_server, spool_dir=spool_dir)
    transcriber = MindTypeCloudTranscriber(
        base_url=cloud_server,
        license_key="unused-because-client-is-injected",
        device_id="unused",
        desktop_version="0.9.3",
        platform="win32",
        client=client,
    )

    monkeypatch.setattr(
        "app.file_transcriber.get_file_duration",
        lambda _path: 2.4,
    )
    queue = FileTranscriptionQueue(
        transcriber=transcriber,
        transcribe=TranscribeOptions(
            model_size="cloud",
            compute_type="cloud",
            device="cloud",
            language="auto",
            beam_size=5,
            vad_filter=True,
            models_dir=tmp_path,
        ),
        summary=SummaryOptions(enable=False),
        postprocess=PostProcessOptions(enable=False),
    )
    task = FileTask(source)
    queue._process_task(task)

    assert task.status == FileStatus.COMPLETED
    assert task.result is not None
    assert task.result.detected_language == "multilingual"
    assert task.result.language_probability == pytest.approx(0.94)
    assert [segment.speaker for segment in task.result.segments] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert task.result.speaker_names == {
        "SPEAKER_00": "Интервьюер",
        "SPEAKER_01": "Эксперт",
    }
    assert task.result.cloud_job_id == "job-1"
    assert task.result.model_used == "mindtype_cloud/nova-3"
    assert bytes(_CloudContractHandler.uploaded) == source.read_bytes()
    assert _CloudContractHandler.acknowledged is False

    database = tmp_path / "transcripts.db"
    store = TranscriptStore(database)
    document = persist_completed_task(store, task)

    assert document is not None
    assert task.library_document_id == document.id
    source.unlink()
    transcriber.acknowledge_result(task.result.cloud_job_id)
    task.result.cloud_cleanup_acknowledged = True

    assert _CloudContractHandler.acknowledged is True
    assert task.result.cloud_cleanup_acknowledged is True
    assert list(spool_dir.iterdir()) == []
    reopened = TranscriptStore(database).get_document(document.id)
    assert reopened is not None
    assert "Привет" in reopened.current_revision.segments[0].text
    assert "MindType" in reopened.current_revision.segments[1].text
    assert reopened.current_revision.speaker_names["SPEAKER_01"] == "Эксперт"

    request_paths = [
        f"{request['method']} {request['path']}"
        for request in _CloudContractHandler.requests
    ]
    assert request_paths == [
        "POST /api/license/session",
        "POST /v1/uploads",
        "PUT /v1/uploads/upload-1/parts/1",
        "POST /v1/uploads/upload-1/complete",
        "POST /v1/transcriptions",
        "GET /v1/transcriptions/job-1",
        "GET /v1/transcriptions/job-1/result",
        "POST /v1/transcriptions/job-1/ack",
    ]


def test_cloud_cancel_requests_server_job_cancellation(
    tmp_path: Path,
    cloud_server: str,
) -> None:
    source = tmp_path / "cancel.wav"
    source.write_bytes(b"RIFF" + b"cancel me" * 64)
    client = _client(
        cloud_server,
        spool_dir=tmp_path / "spool",
        cancel_check=lambda: _CloudContractHandler.job_created,
    )

    with pytest.raises(CloudTranscriptionCancelled):
        client.transcribe_file(source)

    assert _CloudContractHandler.cancelled_job is True

def test_cloud_preflight_rejects_more_than_eight_hours(
    tmp_path: Path,
    cloud_server: str,
) -> None:
    source = tmp_path / "too-long.wav"
    source.write_bytes(b"RIFF" + b"audio")
    client = _client(cloud_server, spool_dir=tmp_path / "spool")

    with pytest.raises(CloudTranscriptionError) as error:
        client.validate_media(source, 8 * 60 * 60 + 0.1)

    assert error.value.code == "INVALID_MEDIA"
    assert _CloudContractHandler.requests == []


def test_cloud_preflight_checks_spool_disk_before_network(
    tmp_path: Path,
    cloud_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"RIFF" + b"audio")
    client = _client(cloud_server, spool_dir=tmp_path / "spool")
    monkeypatch.setattr(
        "app.cloud_transcription.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )

    with pytest.raises(CloudTranscriptionError) as error:
        client.validate_media(source, 60)

    assert error.value.code == "INSUFFICIENT_STORAGE"
    assert _CloudContractHandler.requests == []
