"""
Тесты для модуля summarizer.

Тестирует:
- Инициализацию SummarizerConfig со всеми параметрами
- Значения по умолчанию
- Совместимость с параметрами из file_transcriber
"""

import pytest
from app.summarizer import SummarizerConfig, Summarizer, TranscriptChunker, Chunk


class TestSummarizerConfig:
    """Тесты для SummarizerConfig."""

    def test_config_default_values(self):
        """SummarizerConfig должен иметь корректные значения по умолчанию."""
        config = SummarizerConfig()

        assert config.provider == "openrouter"
        assert config.openrouter_api_key == ""
        assert config.openrouter_model == ""
        assert config.openrouter_reasoning is False
        assert config.openrouter_reasoning_effort == "medium"
        assert config.enable_thinking is True
        assert config.temperature == 0.4
        assert config.max_tokens == 8096
        assert config.max_chunk_tokens == 2000
        assert config.overlap_tokens == 200
        assert config.short_threshold == 3000
        assert config.max_language_retries == 3
        assert config.cache_enabled is True
        assert config.cache_size == 100
        assert config.custom_prompts is None

    def test_config_with_all_parameters(self):
        """SummarizerConfig должен принимать все параметры."""
        config = SummarizerConfig(
            provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="anthropic/claude-3-haiku",
            openrouter_reasoning=True,
            openrouter_reasoning_effort="high",
            enable_thinking=False,
            temperature=0.7,
            max_tokens=4096,
            max_chunk_tokens=1500,
            overlap_tokens=100,
            short_threshold=2000,
            max_language_retries=5,
            cache_enabled=False,
            cache_size=50,
            custom_prompts={"system": "Custom prompt"},
        )

        assert config.provider == "openrouter"
        assert config.openrouter_api_key == "test-key"
        assert config.openrouter_model == "anthropic/claude-3-haiku"
        assert config.openrouter_reasoning is True
        assert config.openrouter_reasoning_effort == "high"
        assert config.enable_thinking is False
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.max_chunk_tokens == 1500
        assert config.overlap_tokens == 100
        assert config.short_threshold == 2000
        assert config.max_language_retries == 5
        assert config.cache_enabled is False
        assert config.cache_size == 50
        assert config.custom_prompts == {"system": "Custom prompt"}

    def test_config_from_file_transcriber_params(self):
        """SummarizerConfig должен принимать параметры как в file_transcriber.py."""
        # Эти параметры передаются из FileTranscriptionQueue._summarize_text()
        config = SummarizerConfig(
            enable_thinking=True,
            custom_prompts={"short": "Custom short prompt"},
            provider="openrouter",
            openrouter_api_key="sk-or-test",
            openrouter_model="anthropic/claude-3-haiku",
            openrouter_reasoning=True,
            openrouter_reasoning_effort="medium",
        )

        assert config.enable_thinking is True
        assert config.custom_prompts == {"short": "Custom short prompt"}
        assert config.provider == "openrouter"
        assert config.openrouter_api_key == "sk-or-test"
        assert config.openrouter_model == "anthropic/claude-3-haiku"
        assert config.openrouter_reasoning is True
        assert config.openrouter_reasoning_effort == "medium"


class TestTranscriptChunker:
    """Тесты для TranscriptChunker."""

    def test_chunker_init(self):
        """TranscriptChunker должен инициализироваться с параметрами."""
        chunker = TranscriptChunker(max_tokens=1000, overlap_tokens=100)

        assert chunker.max_tokens == 1000
        assert chunker.overlap_tokens == 100

    def test_estimate_tokens(self):
        """estimate_tokens должен оценивать количество токенов."""
        chunker = TranscriptChunker()

        # Примерно 1.5 токена на слово для русского
        text = "Привет мир это тест"  # 4 слова
        tokens = chunker.estimate_tokens(text)

        assert tokens == 6  # 4 * 1.5 = 6

    def test_chunk_short_text(self):
        """chunk должен возвращать один чанк для короткого текста."""
        chunker = TranscriptChunker(max_tokens=1000)

        text = "Короткий текст"
        chunks = chunker.chunk(text)

        assert len(chunks) == 1
        assert chunks[0].id == 0
        assert chunks[0].text == text

    def test_chunk_long_text_with_speakers(self):
        """chunk должен разбивать длинный текст со спикерами на части."""
        chunker = TranscriptChunker(max_tokens=10, overlap_tokens=5)

        # Создаём длинный текст со спикерами (чанкер разбивает по SPEAKER_XX)
        segments = []
        for i in range(20):
            speaker = f"SPEAKER_0{i % 3}:"
            segments.append(f"{speaker} Это сегмент номер {i} с текстом.")
        text = " ".join(segments)
        chunks = chunker.chunk(text)

        assert len(chunks) > 1
        # Все чанки должны иметь последовательные id
        for i, chunk in enumerate(chunks):
            assert chunk.id == i


class TestChunk:
    """Тесты для Chunk."""

    def test_chunk_init(self):
        """Chunk должен инициализироваться."""
        chunk = Chunk(id=0, text="Test text", token_count=10)

        assert chunk.id == 0
        assert chunk.text == "Test text"
        assert chunk.token_count == 10


class TestSummarizer:
    """Тесты для Summarizer."""

    def test_summarizer_init_default(self):
        """Summarizer должен инициализироваться с дефолтным конфигом."""
        summarizer = Summarizer()

        assert summarizer.config is not None
        assert isinstance(summarizer.config, SummarizerConfig)
        assert summarizer.is_loaded is False

    def test_summarizer_init_with_config(self):
        """Summarizer должен принимать конфиг."""
        config = SummarizerConfig(
            openrouter_api_key="test-key",
            openrouter_model="test-model",
            enable_thinking=False,
        )
        summarizer = Summarizer(config)

        assert summarizer.config.openrouter_api_key == "test-key"
        assert summarizer.config.openrouter_model == "test-model"
        assert summarizer.config.enable_thinking is False

    def test_summarizer_empty_transcript_raises(self):
        """summarize должен выбрасывать ошибку для пустого текста."""
        summarizer = Summarizer()

        with pytest.raises(ValueError, match="пуст"):
            summarizer.summarize("")

        with pytest.raises(ValueError, match="пуст"):
            summarizer.summarize("   ")
