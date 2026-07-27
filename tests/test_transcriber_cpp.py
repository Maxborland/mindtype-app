from __future__ import annotations

from pathlib import Path
import hashlib
import subprocess
import threading
import urllib.error
import urllib.request
import wave
from unittest.mock import MagicMock

import pytest


def _write_pcm16_wav(
    path: Path,
    *,
    channels: int = 1,
    sample_rate: int = 16_000,
    frames: int = 160,
) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\0" * frames * channels * 2)


def test_windows_transcriber_verifies_packaged_runtime(monkeypatch) -> None:
    import app.transcriber_cpp as module

    verify = MagicMock()
    monkeypatch.setattr(module, "verify_packaged_runtime", verify)

    transcriber = module.WhisperCppTranscriber()

    verify.assert_called_once_with()
    assert transcriber.gpu_backend == "cpu"


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

    from app.model_manifest import ModelArtifact
    from app.transcriber_cpp import WhisperCppTranscriber

    artifact = ModelArtifact(
        model_id="small",
        filename="ggml-small.bin",
        version="test",
        url="https://verified.example/ggml-small.bin",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        license="MIT",
        source_revision="a" * 40,
    )
    monkeypatch.setattr(
        "app.transcriber_cpp.get_model_artifact",
        lambda _model: artifact,
    )

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


def test_wrong_full_model_payload_is_discarded_before_next_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    expected = b"x" * (6 * 1024 * 1024)
    corrupt = b"y" * len(expected)
    calls: list[tuple[str, str | None]] = []

    class Response:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._position = 0
            self.status = 200
            self.headers = {"Content-Length": str(len(data))}

        def read(self, size: int = -1) -> bytes:
            if self._position >= len(self._data):
                return b""
            if size < 0:
                size = len(self._data) - self._position
            chunk = self._data[self._position : self._position + size]
            self._position += len(chunk)
            return chunk

        def getcode(self) -> int:
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request: urllib.request.Request, **_kwargs):
        calls.append(
            (
                request.full_url,
                request.get_header("Range"),
            )
        )
        payload = corrupt if "corrupt.example" in request.full_url else expected
        return Response(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    from app.model_manifest import ModelArtifact
    from app.transcriber_cpp import WhisperCppTranscriber

    artifact = ModelArtifact(
        model_id="small",
        filename="ggml-small.bin",
        version="test",
        url="https://verified.example/ggml-small.bin",
        size=len(expected),
        sha256=hashlib.sha256(expected).hexdigest(),
        license="MIT",
        source_revision="a" * 40,
    )
    monkeypatch.setattr(
        "app.transcriber_cpp.get_model_artifact",
        lambda _model: artifact,
    )
    transcriber = WhisperCppTranscriber()
    transcriber.set_download_sources(
        [
            "https://corrupt.example/models",
            "https://good.example/models",
        ]
    )

    model = transcriber.download_model("small", models_dir=tmp_path)

    assert model.read_bytes() == expected
    assert calls[:2] == [
        ("https://corrupt.example/models/ggml-small.bin", None),
        ("https://good.example/models/ggml-small.bin", None),
    ]
    assert not model.with_suffix(".bin.part").exists()


def test_existing_model_with_wrong_hash_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.model_manifest import ModelArtifact, ModelManifestError
    from app.transcriber_cpp import WhisperCppTranscriber

    payload = b"expected model"
    artifact = ModelArtifact(
        model_id="small",
        filename="ggml-small.bin",
        version="test",
        url="https://verified.example/ggml-small.bin",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        license="MIT",
        source_revision="a" * 40,
    )
    monkeypatch.setattr(
        "app.transcriber_cpp.get_model_artifact",
        lambda _model: artifact,
    )
    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"tampered model")
    transcriber = WhisperCppTranscriber()

    with pytest.raises(ModelManifestError):
        transcriber.load_model("small", models_dir=tmp_path)


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


def test_vad_regions_are_transcribed_with_timestamp_offsets(
    tmp_path: Path, monkeypatch
) -> None:
    from app.transcriber_cpp import WhisperCppTranscriber
    from app.vad import SpeechRegion

    model = tmp_path / "ggml-small.bin"
    server = tmp_path / "whisper-server.exe"
    audio = tmp_path / "audio.wav"
    model.write_bytes(b"model")
    server.write_bytes(b"server")
    _write_pcm16_wav(audio)

    class FakeSegmenter:
        def regions(self, _path, **_kwargs):
            return [SpeechRegion(1_000, 2_000), SpeechRegion(3_000, 4_000)]

        def write_region(self, _source, target, _region):
            target.write_bytes(b"region")

    monkeypatch.setattr(
        "app.transcriber_cpp.WebRtcVadSegmenter", FakeSegmenter
    )
    runtime = MagicMock()
    runtime.infer.side_effect = [
        {
            "text": "первая",
            "language": "ru",
            "segments": [
                {
                    "start": 0.1,
                    "end": 0.9,
                    "text": "первая",
                    "words": [{"word": "первая", "start": 0.1, "end": 0.9}],
                }
            ],
        },
        {
            "text": "вторая",
            "language": "ru",
            "segments": [
                {"start": 0.2, "end": 0.8, "text": "вторая", "words": []}
            ],
        },
    ]
    transcriber = WhisperCppTranscriber.__new__(WhisperCppTranscriber)
    transcriber.model_path = model
    transcriber.server_path = server
    transcriber.threads = 4
    transcriber.device = "auto"
    transcriber.gpu_backend = "vulkan"
    transcriber._server_runtime = runtime

    segments, language, _confidence = transcriber.transcribe_with_timestamps(
        audio,
        language="auto",
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )

    assert language == "ru"
    assert [(item["start"], item["end"], item["text"]) for item in segments] == [
        (1.1, 1.9, "первая"),
        (3.2, 3.8, "вторая"),
    ]
    assert segments[0]["words"][0]["start"] == 1.1
    assert segments[0]["words"][0]["end"] == 1.9


def test_vad_normalizes_wav_using_actual_format_not_extension(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.transcriber_cpp import WhisperCppTranscriber

    source = tmp_path / "stereo-44k.wav"
    _write_pcm16_wav(source, channels=2, sample_rate=44_100)
    seen_paths = []

    class FakeSegmenter:
        def regions(self, path, **_kwargs):
            seen_paths.append(path)
            with wave.open(str(path), "rb") as normalized:
                assert normalized.getnchannels() == 1
                assert normalized.getsampwidth() == 2
                assert normalized.getframerate() == 16_000
            return []

    monkeypatch.setattr(
        "app.transcriber_cpp.WebRtcVadSegmenter",
        FakeSegmenter,
    )
    monkeypatch.setattr(
        "app.audio_io.load_16k_mono",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("base WAV normalization must not require librosa")
        ),
    )
    transcriber = WhisperCppTranscriber.__new__(WhisperCppTranscriber)

    result = transcriber._server_inference_regions(
        source,
        language="ru",
        beam_size=5,
        word_timestamps=False,
        vad_filter=True,
    )

    assert result == []
    assert len(seen_paths) == 1
    assert seen_paths[0] != source
    assert source.is_file()
    assert not seen_paths[0].exists()
