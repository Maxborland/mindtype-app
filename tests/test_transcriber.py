"""
Тесты для модуля транскрипции.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest

# Мокируем тяжёлые зависимости до импорта модуля
sys.modules['ctranslate2'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()
sys.modules['huggingface_hub'] = MagicMock()

from app.transcriber import (
    Transcriber,
    _pick_device,
    _get_repo_id,
    _MODEL_REPO_MAP,
)


class TestPickDevice:
    """Тесты для функции _pick_device()."""

    def test_pick_device_explicit_cuda(self):
        """Тест выбора CUDA если указано явно."""
        result = _pick_device("cuda")
        assert result == "cuda"

    def test_pick_device_explicit_cpu(self):
        """Тест выбора CPU если указано явно."""
        result = _pick_device("cpu")
        assert result == "cpu"

    def test_pick_device_auto_with_cuda(self):
        """Тест автовыбора CUDA если доступна."""
        with patch('app.transcriber.ctranslate2') as mock_ct2:
            mock_ct2.get_device_count.return_value = 1

            result = _pick_device("auto")

            assert result == "cuda"

    def test_pick_device_auto_without_cuda(self):
        """Тест автовыбора CPU если CUDA недоступна."""
        with patch('app.transcriber.ctranslate2') as mock_ct2:
            mock_ct2.get_device_count.return_value = 0

            result = _pick_device("auto")

            assert result == "cpu"

    def test_pick_device_auto_with_exception(self):
        """Тест автовыбора CPU при ошибке проверки CUDA."""
        with patch('app.transcriber.ctranslate2') as mock_ct2:
            mock_ct2.get_device_count.side_effect = Exception("CUDA error")

            result = _pick_device("auto")

            assert result == "cpu"


class TestGetRepoId:
    """Тесты для функции _get_repo_id()."""

    def test_get_repo_id_known_models(self):
        """Тест получения repo_id для известных моделей."""
        assert _get_repo_id("tiny") == "Systran/faster-whisper-tiny"
        assert _get_repo_id("small") == "Systran/faster-whisper-small"
        assert _get_repo_id("medium") == "Systran/faster-whisper-medium"
        assert _get_repo_id("large-v3") == "Systran/faster-whisper-large-v3"

    def test_get_repo_id_distil_models(self):
        """Тест получения repo_id для distil моделей."""
        assert _get_repo_id("distil-large-v2") == "Systran/faster-distil-whisper-large-v2"
        assert _get_repo_id("distil-large-v3") == "Systran/faster-distil-whisper-large-v3"

    def test_get_repo_id_english_models(self):
        """Тест получения repo_id для английских моделей."""
        assert _get_repo_id("tiny.en") == "Systran/faster-whisper-tiny.en"
        assert _get_repo_id("base.en") == "Systran/faster-whisper-base.en"

    def test_get_repo_id_custom_repo(self):
        """Тест если передан кастомный repo_id."""
        result = _get_repo_id("custom/my-model")
        assert result == "custom/my-model"

    def test_get_repo_id_unknown_model(self):
        """Тест для неизвестной модели."""
        result = _get_repo_id("unknown-model")
        assert result == "Systran/faster-whisper-unknown-model"


class TestModelRepoMap:
    """Тесты для маппинга моделей."""

    def test_all_standard_models_mapped(self):
        """Тест что все стандартные модели есть в маппинге."""
        standard_models = [
            "tiny", "tiny.en",
            "base", "base.en",
            "small", "small.en",
            "medium", "medium.en",
            "large-v1", "large-v2", "large-v3", "large",
        ]

        for model in standard_models:
            assert model in _MODEL_REPO_MAP, f"Model {model} not in map"

    def test_distil_models_mapped(self):
        """Тест что distil модели есть в маппинге."""
        distil_models = [
            "distil-large-v2", "distil-large-v3",
            "distil-medium.en", "distil-small.en",
        ]

        for model in distil_models:
            assert model in _MODEL_REPO_MAP, f"Distil model {model} not in map"


class TestTranscriberInit:
    """Тесты для инициализации Transcriber."""

    def test_init_no_model(self):
        """Тест что после инициализации модель не загружена."""
        transcriber = Transcriber()

        assert transcriber.model is None
        assert transcriber.model_size is None
        assert transcriber.compute_type is None
        assert transcriber.device is None


class TestTranscriberLoadModel:
    """Тесты для метода load_model()."""

    def test_load_model_creates_whisper_model(self):
        """Тест что load_model создаёт WhisperModel."""
        transcriber = Transcriber()

        with patch('app.transcriber.WhisperModel') as mock_whisper:
            mock_model = MagicMock()
            mock_whisper.return_value = mock_model

            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                )

            assert transcriber.model is not None
            mock_whisper.assert_called_once()

    def test_load_model_stores_params(self):
        """Тест что load_model сохраняет параметры."""
        transcriber = Transcriber()

        with patch('app.transcriber.WhisperModel'):
            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="small",
                    compute_type="float32",
                    device="cpu",
                )

            assert transcriber.model_size == "small"
            assert transcriber.compute_type == "float32"
            assert transcriber.device == "cpu"

    def test_load_model_reuses_if_same_params(self):
        """Тест что модель не перезагружается при тех же параметрах."""
        transcriber = Transcriber()

        with patch('app.transcriber.WhisperModel') as mock_whisper:
            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                )

                # Второй вызов с теми же параметрами
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                )

            # WhisperModel должен быть вызван только один раз
            assert mock_whisper.call_count == 1

    def test_load_model_reloads_on_different_params(self):
        """Тест что модель перезагружается при разных параметрах."""
        transcriber = Transcriber()

        with patch('app.transcriber.WhisperModel') as mock_whisper:
            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                )

                # Второй вызов с другой моделью
                transcriber.load_model(
                    model_size="small",
                    compute_type="int8",
                    device="auto",
                )

            # WhisperModel должен быть вызван дважды
            assert mock_whisper.call_count == 2

    def test_load_model_with_local_path(self, tmp_path):
        """Тест загрузки локальной модели."""
        transcriber = Transcriber()

        # Создаём локальную директорию модели
        model_dir = tmp_path / "models" / "tiny"
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").touch()

        with patch('app.transcriber.WhisperModel') as mock_whisper:
            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                    models_dir=str(tmp_path / "models"),
                )

            # Проверяем что WhisperModel был вызван с первым аргументом - путём к модели
            call_args = mock_whisper.call_args[0]
            assert "tiny" in call_args[0]

    def test_load_model_with_progress_callback(self):
        """Тест что progress_callback вызывается."""
        transcriber = Transcriber()

        progress_calls = []
        def progress_callback(status, current, total):
            progress_calls.append((status, current, total))

        with patch('app.transcriber.WhisperModel'):
            with patch('app.transcriber._pick_device', return_value='cpu'):
                transcriber.load_model(
                    model_size="tiny",
                    compute_type="int8",
                    device="auto",
                    progress_callback=progress_callback,
                )

        assert len(progress_calls) > 0


class TestTranscriberTranscribe:
    """Тесты для метода transcribe()."""

    def test_transcribe_requires_model(self):
        """Тест что transcribe требует загруженную модель."""
        transcriber = Transcriber()

        with pytest.raises(RuntimeError) as exc_info:
            transcriber.transcribe(
                audio_path=Path("test.wav"),
                language="ru",
                beam_size=5,
                vad_filter=True,
            )

        assert "Модель не загружена" in str(exc_info.value)

    def test_transcribe_returns_tuple(self):
        """Тест что transcribe возвращает кортеж."""
        transcriber = Transcriber()

        # Мок модели
        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "ru"
        mock_info.language_probability = 0.95

        mock_segment = MagicMock()
        mock_segment.text = "Тестовый текст"

        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        transcriber.model = mock_model

        text, lang, prob = transcriber.transcribe(
            audio_path=Path("test.wav"),
            language="ru",
            beam_size=5,
            vad_filter=True,
        )

        assert isinstance(text, str)
        assert lang == "ru"
        assert prob == 0.95

    def test_transcribe_joins_segments(self):
        """Тест что transcribe объединяет сегменты."""
        transcriber = Transcriber()

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.9

        segments = [
            MagicMock(text="Hello "),
            MagicMock(text=" world"),
            MagicMock(text="!"),
        ]

        mock_model.transcribe.return_value = (segments, mock_info)
        transcriber.model = mock_model

        text, _, _ = transcriber.transcribe(
            audio_path=Path("test.wav"),
            language="en",
            beam_size=5,
            vad_filter=True,
        )

        assert "Hello" in text
        assert "world" in text

    def test_transcribe_auto_language(self):
        """Тест транскрипции с автоопределением языка."""
        transcriber = Transcriber()

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.9
        mock_model.transcribe.return_value = ([], mock_info)
        transcriber.model = mock_model

        transcriber.transcribe(
            audio_path=Path("test.wav"),
            language="auto",
            beam_size=5,
            vad_filter=True,
        )

        # Проверяем что language=None при auto
        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs['language'] is None


class TestTranscriberTranscribeStream:
    """Тесты для метода transcribe_stream()."""

    def test_transcribe_stream_requires_model(self):
        """Тест что transcribe_stream требует загруженную модель."""
        transcriber = Transcriber()

        with pytest.raises(RuntimeError) as exc_info:
            list(transcriber.transcribe_stream(
                audio_path=Path("test.wav"),
                language="ru",
                beam_size=5,
                vad_filter=True,
            ))

        assert "Модель не загружена" in str(exc_info.value)

    def test_transcribe_stream_yields_partial(self):
        """Тест что transcribe_stream возвращает промежуточные результаты."""
        transcriber = Transcriber()

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "ru"
        mock_info.language_probability = 0.9

        segments = [
            MagicMock(text="Первое"),
            MagicMock(text="Второе"),
            MagicMock(text="Третье"),
        ]

        mock_model.transcribe.return_value = (iter(segments), mock_info)
        transcriber.model = mock_model

        results = list(transcriber.transcribe_stream(
            audio_path=Path("test.wav"),
            language="ru",
            beam_size=5,
            vad_filter=True,
        ))

        assert len(results) == 3
        # Каждый результат - накопленный текст
        assert "Первое" in results[0][0]
        assert "Второе" in results[1][0]
        assert "Третье" in results[2][0]

    def test_transcribe_stream_skips_empty(self):
        """Тест что пустые сегменты пропускаются."""
        transcriber = Transcriber()

        mock_model = MagicMock()
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.8

        segments = [
            MagicMock(text="Text"),
            MagicMock(text=""),  # Пустой
            MagicMock(text="   "),  # Только пробелы
            MagicMock(text="More"),
        ]

        mock_model.transcribe.return_value = (iter(segments), mock_info)
        transcriber.model = mock_model

        results = list(transcriber.transcribe_stream(
            audio_path=Path("test.wav"),
            language="en",
            beam_size=5,
            vad_filter=True,
        ))

        # Должно быть только 2 результата (непустые)
        assert len(results) == 2


class TestTranscriberDownloadModel:
    """Тесты для метода download_model()."""

    def test_download_model_creates_directory(self, tmp_path):
        """Тест что download_model создаёт директорию."""
        transcriber = Transcriber()
        models_dir = tmp_path / "models"

        with patch('app.transcriber.HfApi') as mock_api:
            mock_api_instance = MagicMock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_repo_files.return_value = ["model.bin", "config.json"]

            with patch('huggingface_hub.hf_hub_download') as mock_download:
                transcriber.download_model("tiny", models_dir)

        assert models_dir.exists()

    def test_download_model_with_progress(self, tmp_path):
        """Тест что progress_callback вызывается при скачивании."""
        transcriber = Transcriber()
        models_dir = tmp_path / "models"

        progress_calls = []
        def progress_callback(status, current, total):
            progress_calls.append((status, current, total))

        with patch('app.transcriber.HfApi') as mock_api:
            mock_api_instance = MagicMock()
            mock_api.return_value = mock_api_instance
            mock_api_instance.list_repo_files.return_value = ["model.bin"]

            with patch('huggingface_hub.hf_hub_download'):
                transcriber.download_model(
                    "tiny",
                    models_dir,
                    progress_callback=progress_callback
                )

        assert len(progress_calls) > 0

    def test_download_model_filters_files(self, tmp_path):
        """Тест что скачиваются только нужные файлы."""
        transcriber = Transcriber()
        models_dir = tmp_path / "models"

        with patch('app.transcriber.HfApi') as mock_api:
            mock_api_instance = MagicMock()
            mock_api.return_value = mock_api_instance
            # Включаем файлы которые не должны скачиваться
            mock_api_instance.list_repo_files.return_value = [
                "model.bin",
                "config.json",
                "tokenizer.json",
                "pytorch_model.bin",  # Не должен скачиваться
                "tf_model.h5",  # Не должен скачиваться
                "README.md",  # Не должен скачиваться
            ]

            with patch('huggingface_hub.hf_hub_download') as mock_download:
                transcriber.download_model("tiny", models_dir)

                # Проверяем что скачаны только нужные файлы
                downloaded_files = [
                    call[1]['filename'] for call in mock_download.call_args_list
                ]
                assert "model.bin" in downloaded_files
                assert "config.json" in downloaded_files
                assert "tokenizer.json" in downloaded_files
                assert "pytorch_model.bin" not in downloaded_files

