from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import urllib.error
import urllib.request
from unittest.mock import MagicMock


def test_cancel_current_process_terminates_then_kills_after_grace_timeout():
    from app.transcriber_cpp import WhisperCppTranscriber

    process = MagicMock()
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="whisper-cli", timeout=0.01),
        0,
    ]
    transcriber = WhisperCppTranscriber.__new__(WhisperCppTranscriber)
    transcriber._process_lock = threading.Lock()
    transcriber._current_process = process
    transcriber._cancel_requested = threading.Event()

    transcriber.cancel_current(grace_timeout=0.01)

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert transcriber._cancel_requested.is_set()


def test_whisper_cpp_download_tries_sources_in_order(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    payload = b"x" * (6 * 1024 * 1024)  # > 5MB sanity threshold in downloader

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._pos = 0
            self.status = 200
            self.headers = {"Content-Length": str(len(data))}

        def read(self, n: int = -1) -> bytes:
            if self._pos >= len(self._data):
                return b""
            if n is None or n < 0:
                n = len(self._data) - self._pos
            chunk = self._data[self._pos : self._pos + n]
            self._pos += len(chunk)
            return chunk

        def getcode(self) -> int:
            return int(self.status)

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

    def fake_urlopen(req: urllib.request.Request, **kwargs):  # type: ignore[override]
        calls.append(req.full_url)
        if "bad.example" in req.full_url:
            raise urllib.error.URLError("blocked")
        return _Resp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    from app.transcriber_cpp import WhisperCppTranscriber

    tr = WhisperCppTranscriber()
    tr.set_download_sources(
        [
            "https://bad.example/models/whispercpp",
            "https://good.example/{repo_id}/resolve/main/{filename}",
        ]
    )

    models_dir = tmp_path / "models"
    path = tr.download_model("small", models_dir=models_dir)

    assert path.exists()
    assert path.name == "ggml-small.bin"
    assert path.stat().st_size == len(payload)
    assert calls[0].endswith("/ggml-small.bin")
    assert calls[1] == "https://good.example/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
