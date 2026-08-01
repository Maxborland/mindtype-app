from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

import pytest

from app.cloud_transcription import CloudTranscriptionClient, MindTypeCloudTranscriber
from app.file_transcriber import FileTranscriptionQueue, PostProcessOptions, SummaryOptions, TranscribeOptions
from app.transcript_store import TranscriptStore, persist_completed_task
from app.transcription_models import FileStatus, FileTask


class _SummaryContractHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    uploaded = bytearray()
    transcript_operation = ""
    summary_operation = ""
    summary_request: dict[str, Any] = {}
    transcription_ack = False
    summary_ack = False
    fail_summary = False

    @classmethod
    def reset(cls) -> None:
        cls.requests = []
        cls.uploaded = bytearray()
        cls.transcript_operation = ""
        cls.summary_operation = ""
        cls.summary_request = {}
        cls.transcription_ack = False
        cls.summary_ack = False
        cls.fail_summary = False

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("content-length", "0")))

    def _json(self, value: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self, body: bytes) -> None:
        type(self).requests.append({"method": self.command, "path": self.path, "body": body})

    def do_POST(self) -> None:
        body = self._body()
        self._record(body)
        parsed = json.loads(body or b"{}")
        cls = type(self)
        if self.path == "/api/license/trial-session":
            assert "license_key" not in parsed
            self._json({
                "access_token": "trial-access",
                "access_expires_at": "2099-01-01T00:00:00.000Z",
                "refresh_token": "trial-refresh",
                "entitlement_lease": "trial-lease",
                "claim_version": 1,
            })
            return
        if self.path == "/v1/uploads":
            self._json({"id": "upload-1", "upload_token": "upload-token", "part_size": parsed["part_size"], "uploaded_parts": []}, 201)
            return
        if self.path == "/v1/uploads/upload-1/complete":
            self._json({"id": "upload-1", "state": "uploaded", "uploaded_parts": [1]})
            return
        if self.path == "/v1/transcriptions":
            cls.transcript_operation = parsed["operation_id"]
            self._json({"id": "transcription-1", "state": "queued", "source_artifact_id": "upload-1"}, 202)
            return
        if self.path == "/v1/summaries":
            cls.summary_operation = parsed["operation_id"]
            cls.summary_request = parsed
            self._json({"id": "summary-1", "state": "queued"}, 202)
            return
        if self.path == "/v1/transcriptions/transcription-1/ack":
            cls.transcription_ack = True
            self._json({"id": "transcription-1", "state": "succeeded"})
            return
        if self.path == "/v1/summaries/summary-1/ack":
            cls.summary_ack = True
            self._json({"id": "summary-1", "state": "succeeded"})
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        body = self._body()
        self._record(body)
        type(self).uploaded.extend(body)
        self._json({"part_number": 1, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)})

    def do_GET(self) -> None:
        body = self._body()
        self._record(body)
        cls = type(self)
        if self.path == "/v1/transcriptions/transcription-1":
            self._json({"id": "transcription-1", "state": "succeeded", "result_artifact_id": "result-1"})
            return
        if self.path == "/v1/transcriptions/transcription-1/result":
            self._json({"result": _canonical(cls.transcript_operation, summary=None)})
            return
        if self.path == "/v1/summaries/summary-1":
            state = "failed" if cls.fail_summary else "succeeded"
            payload: dict[str, Any] = {"id": "summary-1", "state": state}
            if cls.fail_summary:
                payload["error"] = {"code": "PROVIDER_UNAVAILABLE", "message": "summary unavailable"}
            self._json(payload)
            return
        if self.path == "/v1/summaries/summary-1/result":
            self._json({"result": _canonical(cls.summary_operation, summary={
                "text": "## Итог\n- Облачный результат",
                "preset": "custom",
                "generated": True,
                "source_segment_ids": ["segment-1", "segment-2"],
            })})
            return
        self.send_error(404)


def _canonical(operation_id: str, *, summary: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation_id": operation_id,
        "source": {"display_name": "recording", "duration_ms": 2400, "sha256": hashlib.sha256(b"audio").hexdigest(), "channels": []},
        "route": {
            "transcription": {"provider": "mindtype_cloud", "model": "nova-3"},
            "diarization": {"provider": "mindtype_cloud", "model": "nova-3"},
            "summary": {"provider": "mindtype_cloud", "model": "auto"},
        },
        "transcript": {
            "language": "multilingual",
            "confidence": 0.94,
            "segments": [
                {"segment_id": "segment-1", "start_ms": 0, "end_ms": 1200, "text": "Привет", "speaker_id": "SPEAKER_00", "words": []},
                {"segment_id": "segment-2", "start_ms": 1200, "end_ms": 2400, "text": "Hello", "speaker_id": "SPEAKER_01", "words": []},
            ],
        },
        "speakers": [{"speaker_id": "SPEAKER_00", "display_name": "Интервьюер"}, {"speaker_id": "SPEAKER_01", "display_name": "Эксперт"}],
        "summary": summary,
        "warnings": [],
        "provenance": {"server_job_ids": ["provider-job-1"], "created_at": "2026-08-01T00:00:00+00:00"},
    }


@pytest.fixture
def summary_server():
    _SummaryContractHandler.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SummaryContractHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(base_url: str, spool_dir: Path) -> CloudTranscriptionClient:
    return CloudTranscriptionClient(
        base_url=base_url,
        license_key="",
        device_id="trial-device",
        desktop_version="0.9.4",
        platform="win32",
        spool_dir=spool_dir,
        part_size=5 * 1024 * 1024,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
    )


def test_trial_cloud_file_summary_persists_before_both_acks(tmp_path: Path, summary_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    client = _client(summary_server, tmp_path / "spool")
    transcriber = MindTypeCloudTranscriber(
        base_url=summary_server,
        license_key="",
        device_id="trial-device",
        desktop_version="0.9.4",
        platform="win32",
        client=client,
    )
    monkeypatch.setattr("app.file_transcriber.get_file_duration", lambda _path: 2.4)
    queue = FileTranscriptionQueue(
        transcriber=transcriber,
        transcribe=TranscribeOptions("cloud", "cloud", "cloud", "auto", 5, True, tmp_path),
        summary=SummaryOptions(enable=True, provider="mindtype_cloud", custom_prompts={"system": "Сделай итог", "short": "Только факты"}),
        postprocess=PostProcessOptions(enable=False),
    )
    task = FileTask(source)
    queue._process_task(task)
    assert task.status is FileStatus.COMPLETED
    assert task.result is not None
    assert task.result.summary == "## Итог\n- Облачный результат"
    assert task.result.cloud_summary_job_id == "summary-1"
    assert _SummaryContractHandler.transcription_ack is False
    assert _SummaryContractHandler.summary_ack is False
    assert _SummaryContractHandler.summary_request["preset"] == "custom"
    assert "Сделай итог" in _SummaryContractHandler.summary_request["custom_prompt"]

    store = TranscriptStore(tmp_path / "mindtype.db")
    document = persist_completed_task(store, task)
    assert document is not None
    assert len(document.summary_variants) == 1
    assert document.summary_variants[0].provider == "mindtype_cloud"
    assert document.summary_variants[0].model == "auto"
    assert {
        item.kind for item in store.list_pending_cloud_cleanups()
    } == {"transcription", "summary"}
    transcriber.acknowledge_result(task.result.cloud_job_id or "")
    store.mark_cloud_cleanup_acknowledged(
        document.id,
        task.result.cloud_job_id or "",
        "transcription",
    )
    transcriber.acknowledge_summary(task.result.cloud_summary_job_id or "")
    store.mark_cloud_cleanup_acknowledged(
        document.id,
        task.result.cloud_summary_job_id or "",
        "summary",
    )
    assert _SummaryContractHandler.transcription_ack is True
    assert _SummaryContractHandler.summary_ack is True
    assert store.list_pending_cloud_cleanups() == ()


def test_failed_cloud_summary_preserves_transcript_for_durable_save(tmp_path: Path, summary_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _SummaryContractHandler.fail_summary = True
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"audio")
    client = _client(summary_server, tmp_path / "spool")
    transcriber = MindTypeCloudTranscriber(base_url=summary_server, license_key="", device_id="trial-device", desktop_version="0.9.4", platform="win32", client=client)
    monkeypatch.setattr("app.file_transcriber.get_file_duration", lambda _path: 2.4)
    queue = FileTranscriptionQueue(
        transcriber=transcriber,
        transcribe=TranscribeOptions("cloud", "cloud", "cloud", "auto", 5, True, tmp_path),
        summary=SummaryOptions(enable=True, provider="mindtype_cloud", custom_prompts={"system": "custom"}),
        postprocess=PostProcessOptions(enable=False),
    )
    task = FileTask(source)
    queue._process_task(task)
    assert task.status is FileStatus.COMPLETED
    assert task.result is not None
    assert "Саммари недоступно" in task.warning
    assert task.error_message == ""
    assert _SummaryContractHandler.transcription_ack is False
    assert _SummaryContractHandler.summary_ack is False

    store = TranscriptStore(tmp_path / "mindtype.db")
    document = persist_completed_task(store, task)
    assert document is not None
    assert document.cloud_job_id == "transcription-1"
    assert store.list_pending_cloud_cleanups()[0].kind == "transcription"

def test_cloud_summary_canonical_uses_processed_text(tmp_path):
    from app.cloud_summary import canonical_from_transcription_result
    from app.transcription_models import TranscriptionResult, TranscriptionSegment

    result = TranscriptionResult(
        file_path=tmp_path / "meeting.wav",
        segments=[
            TranscriptionSegment(start=0.0, end=1.0, text="raw filler"),
            TranscriptionSegment(start=1.0, end=2.0, text="raw facts"),
        ],
        detected_language="ru",
        language_probability=0.9,
        duration=2.0,
        model_used="mindtype_cloud/nova-3",
        processed_text="  Очищенный итог без лишнего текста  ",
    )

    canonical = canonical_from_transcription_result(
        result,
        prefer_existing=False,
    )

    assert canonical["transcript"]["segments"] == [
        {
            "segment_id": "processed-text",
            "start_ms": 0,
            "end_ms": 2000,
            "text": "  Очищенный итог без лишнего текста  ",
            "speaker_id": None,
            "words": [],
        }
    ]


def test_cloud_summary_canonical_uses_text_for_summary_fallback():
    from types import SimpleNamespace
    from app.cloud_summary import canonical_from_transcription_result
    from app.transcription_models import TranscriptionSegment

    result = SimpleNamespace(
        segments=[TranscriptionSegment(start=0.0, end=1.0, text="raw")],
        text_for_summary="CUSTOM EXACT",
        processed_text=None,
        duration=1.0,
    )

    canonical = canonical_from_transcription_result(result, prefer_existing=False)

    assert canonical["transcript"]["segments"][0]["text"] == "CUSTOM EXACT"
