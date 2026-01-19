"""
Тесты для модуля text_processor.

Тестирует:
- Инициализацию пайплайна
- Обработку текста
- Свойства ProcessingResult
"""

import pytest
from unittest.mock import patch, MagicMock


class TestTextProcessingPipeline:
    """Тесты для TextProcessingPipeline."""

    def test_pipeline_init(self):
        """Пайплайн должен инициализироваться с конфигом по умолчанию."""
        from app.text_processor.pipeline import TextProcessingPipeline
        from app.text_processor.config import ProcessingConfig

        pipeline = TextProcessingPipeline()

        assert pipeline.config is not None
        assert isinstance(pipeline.config, ProcessingConfig)

    def test_pipeline_init_with_custom_config(self):
        """Пайплайн должен принимать кастомный конфиг."""
        from app.text_processor.pipeline import TextProcessingPipeline
        from app.text_processor.config import ProcessingConfig

        config = ProcessingConfig(
            enable_diarization=False,
            enable_punctuation=True,
            enable_fillers=True,
            language="ru",
        )

        pipeline = TextProcessingPipeline(config=config)

        assert pipeline.config.enable_diarization is False
        assert pipeline.config.enable_punctuation is True
        assert pipeline.config.language == "ru"

    def test_process_text_basic(self):
        """process должен обрабатывать простой текст."""
        from app.text_processor.pipeline import TextProcessingPipeline
        from app.text_processor.config import ProcessingConfig

        # Отключаем диаризацию для простоты теста
        config = ProcessingConfig(
            enable_diarization=False,
            enable_punctuation=False,
            enable_fillers=False,
            enable_normalize=False,
            enable_correct=False,
        )

        pipeline = TextProcessingPipeline(config=config)
        result = pipeline.process("hello world")

        assert result.original_text == "hello world"
        assert result.processed_text == "Hello world"  # Капитализация первой буквы

    def test_process_empty_text(self):
        """process должен корректно обрабатывать пустой текст."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        result = pipeline.process("")

        assert result.original_text == ""
        assert result.processed_text == ""

    def test_process_simple(self):
        """process_simple должен возвращать строку."""
        from app.text_processor.pipeline import TextProcessingPipeline
        from app.text_processor.config import ProcessingConfig

        config = ProcessingConfig(
            enable_diarization=False,
            enable_punctuation=False,
            enable_fillers=False,
            enable_normalize=False,
            enable_correct=False,
        )

        pipeline = TextProcessingPipeline(config=config)
        result = pipeline.process_simple("test text")

        assert isinstance(result, str)
        assert result == "Test text"  # Капитализация


class TestProcessingResult:
    """Тесты для ProcessingResult."""

    def test_processing_result_properties(self):
        """ProcessingResult должен иметь корректные свойства."""
        from app.text_processor.pipeline import ProcessingResult

        result = ProcessingResult(
            original_text="original text here",
            processed_text="processed text",
        )

        assert result.original_text == "original text here"
        assert result.processed_text == "processed text"
        assert result.diarization is None
        assert result.processing_stats == {}

    def test_has_speakers_false_without_diarization(self):
        """has_speakers должен быть False без диаризации."""
        from app.text_processor.pipeline import ProcessingResult

        result = ProcessingResult(
            original_text="text",
            processed_text="text",
        )

        assert result.has_speakers is False

    def test_has_speakers_false_with_single_speaker(self):
        """has_speakers должен быть False с одним спикером."""
        from app.text_processor.pipeline import ProcessingResult
        from app.text_processor.diarization import DiarizationResult

        diarization = DiarizationResult(
            segments=[],
            num_speakers=1,
        )

        result = ProcessingResult(
            original_text="text",
            processed_text="text",
            diarization=diarization,
        )

        assert result.has_speakers is False

    def test_has_speakers_true_with_multiple_speakers(self):
        """has_speakers должен быть True с несколькими спикерами."""
        from app.text_processor.pipeline import ProcessingResult
        from app.text_processor.diarization import DiarizationResult

        diarization = DiarizationResult(
            segments=[],
            num_speakers=2,
        )

        result = ProcessingResult(
            original_text="text",
            processed_text="text",
            diarization=diarization,
        )

        assert result.has_speakers is True

    def test_improvement_ratio(self):
        """improvement_ratio должен вычисляться корректно."""
        from app.text_processor.pipeline import ProcessingResult

        result = ProcessingResult(
            original_text="original",  # 8 символов
            processed_text="proc",  # 4 символа
        )

        assert result.improvement_ratio == 0.5

    def test_improvement_ratio_empty_original(self):
        """improvement_ratio должен быть 1.0 для пустого оригинала."""
        from app.text_processor.pipeline import ProcessingResult

        result = ProcessingResult(
            original_text="",
            processed_text="text",
        )

        assert result.improvement_ratio == 1.0


class TestPipelineComponents:
    """Тесты для компонентов пайплайна."""

    def test_get_components_status(self):
        """get_components_status должен возвращать статус компонентов."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        status = pipeline.get_components_status()

        assert isinstance(status, dict)
        assert "diarization" in status
        assert "punctuation" in status
        assert "fillers" in status
        assert "normalize" in status
        assert "correct" in status

        # Fillers, normalize, correct всегда доступны
        assert status["fillers"] is True
        assert status["normalize"] is True
        assert status["correct"] is True

    def test_configure_updates_config(self):
        """configure должен обновлять конфигурацию."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()

        pipeline.configure(enable_fillers=False, language="en")

        assert pipeline.config.enable_fillers is False
        assert pipeline.config.language == "en"

    def test_component_accessors(self):
        """Должны быть доступны все компоненты через свойства."""
        from app.text_processor.pipeline import TextProcessingPipeline
        from app.text_processor.diarization import SpeakerDiarizer
        from app.text_processor.punctuation import PunctuationRestorer
        from app.text_processor.fillers import FillerRemover
        from app.text_processor.normalizer import TextNormalizer
        from app.text_processor.corrector import ASRCorrector

        pipeline = TextProcessingPipeline()

        assert isinstance(pipeline.diarizer, SpeakerDiarizer)
        assert isinstance(pipeline.punctuation_restorer, PunctuationRestorer)
        assert isinstance(pipeline.filler_remover, FillerRemover)
        assert isinstance(pipeline.normalizer, TextNormalizer)
        assert isinstance(pipeline.corrector, ASRCorrector)


class TestFinalCleanup:
    """Тесты для финальной очистки текста."""

    def test_removes_multiple_spaces(self):
        """_final_cleanup должен убирать множественные пробелы."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        result = pipeline._final_cleanup("hello    world")

        assert "    " not in result
        assert "hello world" in result.lower()

    def test_removes_space_before_punctuation(self):
        """_final_cleanup должен убирать пробелы перед знаками препинания."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        result = pipeline._final_cleanup("hello , world")

        assert " ," not in result
        assert "hello," in result.lower()

    def test_capitalizes_first_letter(self):
        """_final_cleanup должен капитализировать первую букву."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        result = pipeline._final_cleanup("hello world")

        assert result[0] == "H"

    def test_capitalizes_after_period(self):
        """_final_cleanup должен капитализировать после точки."""
        from app.text_processor.pipeline import TextProcessingPipeline

        pipeline = TextProcessingPipeline()
        result = pipeline._final_cleanup("hello. world")

        assert "Hello. World" in result
