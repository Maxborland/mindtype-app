from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest


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


def test_persistent_server_result_is_mapped_without_cli_process(tmp_path: Path) -> None:
    from app.transcriber_cpp import WhisperCppTranscriber

    model = tmp_path / "ggml-small.bin"
    server = tmp_path / "whisper-server.exe"
    audio = tmp_path / "audio.wav"
    model.write_bytes(b"model")
    server.write_bytes(b"server")
    audio.write_bytes(b"audio")
    runtime = MagicMock()
    runtime.infer.return_value = {
        "text": "Привет, мир",
        "language": "ru",
        "segments": [
            {
                "start": 0.0,
                "end": 1.25,
                "text": "Привет, мир",
                "words": [
                    {
                        "word": "Привет",
                        "start": 0.0,
                        "end": 0.5,
                        "probability": 0.8,
                    }
                ],
            }
        ],
    }
    transcriber = WhisperCppTranscriber.__new__(WhisperCppTranscriber)
    transcriber.model_path = model
    transcriber.server_path = server
    transcriber.threads = 4
    transcriber.device = "auto"
    transcriber.gpu_backend = "vulkan"
    transcriber._server_runtime = runtime

    text, language, confidence = transcriber.transcribe(
        audio, language="auto", beam_size=5
    )
    segments, _, _ = transcriber.transcribe_with_timestamps(
        audio, language="auto", beam_size=5, word_timestamps=True
    )
    streamed = list(
        transcriber.transcribe_stream(audio, language="auto", beam_size=5)
    )

    assert (text, language, confidence) == ("Привет, мир", "ru", 0.8)
    assert segments == [
        {
            "start": 0.0,
            "end": 1.25,
            "text": "Привет, мир",
            "words": runtime.infer.return_value["segments"][0]["words"],
        }
    ]
    assert streamed == [("Привет, мир", "ru", 0.8)]
    assert runtime.infer.call_count == 3


def test_windows_runtime_is_named_vulkan_when_bundled_dll_exists(
    monkeypatch,
) -> None:
    from app.transcriber_cpp import WhisperCppTranscriber

    monkeypatch.setattr("app.transcriber_cpp.sys.platform", "win32")

    assert WhisperCppTranscriber.__new__(
        WhisperCppTranscriber
    )._detect_gpu_backend() in {"vulkan", "cpu"}


def test_failed_audio_conversion_is_not_sent_as_fake_wav(
    tmp_path: Path, monkeypatch
) -> None:
    from app.transcriber_cpp import WhisperCppTranscriber

    source = tmp_path / "broken.mp3"
    source.write_bytes(b"not audio")
    monkeypatch.setattr(
        "app.audio_io.to_wav_16k_mono",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid media")),
    )
    transcriber = WhisperCppTranscriber.__new__(WhisperCppTranscriber)

    with pytest.raises(RuntimeError, match="преобразовать аудио"):
        transcriber._convert_to_wav(source)
