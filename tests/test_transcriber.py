"""Behavior tests for the provider-neutral transcription facade."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.transcriber import (
    Transcriber,
    available_transcriber_backends,
    create_transcriber,
    select_available_backend,
)


class TestBackendFactory:
    def test_optional_backends_are_reported_only_when_installed(self):
        def find_spec(name):
            return object() if name in {
                "transformers",
                "optimum.onnxruntime",
                "onnxruntime",
            } else None

        with patch("app.transcriber.importlib.util.find_spec", side_effect=find_spec):
            with patch("app.transcriber.HAS_FASTER_WHISPER", False):
                backends = available_transcriber_backends()

        assert backends == ["whisper_cpp", "openrouter", "onnx"]

    def test_unavailable_saved_backend_falls_back_to_whisper_cpp(self):
        with patch(
            "app.transcriber.available_transcriber_backends",
            return_value=["whisper_cpp", "openrouter"],
        ):
            assert select_available_backend("onnx") == "whisper_cpp"
            assert select_available_backend("openrouter") == "openrouter"

    def test_explicit_whisper_cpp_backend(self):
        with patch("app.transcriber.WhisperCppTranscriber") as backend:
            result = create_transcriber("whisper_cpp")

        assert result is backend.return_value

    def test_explicit_onnx_backend(self):
        with patch("app.transcriber.WhisperOnnxTranscriber") as backend:
            result = create_transcriber("onnx")

        assert result is backend.return_value

    def test_explicit_faster_whisper_backend(self):
        with patch("app.transcriber.FasterWhisperTranscriber") as backend:
            result = create_transcriber("faster_whisper")

        assert result is backend.return_value

    def test_explicit_openrouter_backend(self):
        with patch(
            "app.transcriber_openrouter.OpenRouterTranscriber"
        ) as backend:
            result = create_transcriber("openrouter")

        assert result is backend.return_value

    def test_auto_prefers_cpp_when_available(self):
        with patch("app.transcriber._prefer_cpp", return_value=True):
            with patch("app.transcriber.WhisperCppTranscriber") as backend:
                result = create_transcriber("auto")

        assert result is backend.return_value

    def test_auto_uses_faster_whisper_when_cpp_is_unavailable(self):
        with patch("app.transcriber._prefer_cpp", return_value=False):
            with patch("app.transcriber.HAS_FASTER_WHISPER", True):
                with patch("app.transcriber.FasterWhisperTranscriber") as backend:
                    result = create_transcriber("auto")

        assert result is backend.return_value


class TestTranscriberFacade:
    def _facade(self):
        backend = MagicMock()
        with patch("app.transcriber.create_transcriber", return_value=backend):
            facade = Transcriber(backend="openrouter")
        return facade, backend

    def test_load_and_transcribe_are_delegated(self):
        facade, backend = self._facade()
        backend.transcribe.return_value = ("текст", "ru", 0.9)

        facade.load_model("model", "int8", "cpu")
        result = facade.transcribe(Path("audio.wav"), "ru", 5, True)

        backend.load_model.assert_called_once_with("model", "int8", "cpu")
        backend.transcribe.assert_called_once_with(
            Path("audio.wav"), "ru", 5, True
        )
        assert result == ("текст", "ru", 0.9)

    def test_timestamp_and_stream_calls_are_delegated(self):
        facade, backend = self._facade()
        backend.transcribe_with_timestamps.return_value = ([], "ru", 1.0)
        backend.transcribe_stream.return_value = iter(
            [("частичный текст", "ru", 0.8)]
        )

        timestamps = facade.transcribe_with_timestamps(
            Path("audio.wav"), "ru", 5, True
        )
        stream = list(
            facade.transcribe_stream(Path("audio.wav"), "ru", 5, True)
        )

        assert timestamps == ([], "ru", 1.0)
        assert stream == [("частичный текст", "ru", 0.8)]

    def test_cancellation_lifecycle_is_forwarded(self):
        facade, backend = self._facade()

        facade.prepare_operation()
        facade.cancel_current()

        backend.prepare_operation.assert_called_once_with()
        backend.cancel_current.assert_called_once_with()

    def test_optional_lifecycle_methods_may_be_absent(self):
        backend = object()
        with patch("app.transcriber.create_transcriber", return_value=backend):
            facade = Transcriber()

        facade.prepare_operation()
        facade.cancel_current()

    def test_download_sources_are_forwarded_when_supported(self):
        facade, backend = self._facade()

        facade.set_download_sources(["https://models.example"])

        backend.set_download_sources.assert_called_once_with(
            ["https://models.example"]
        )

    def test_download_model_returns_backend_result(self, tmp_path):
        facade, backend = self._facade()
        expected = tmp_path / "model.bin"
        backend.download_model.return_value = expected

        result = facade.download_model("tiny", tmp_path)

        assert result == expected
        backend.download_model.assert_called_once_with("tiny", tmp_path, None)
