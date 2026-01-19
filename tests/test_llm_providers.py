"""
Тесты для LLM провайдеров.

Включает unit тесты для:
- Базового интерфейса LLMProvider
- Каждого провайдера (OpenAI, Anthropic, Gemini, Ollama, OpenRouter)
- Factory функций
- Динамической загрузки моделей
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from app.llm import (
    LLMProvider,
    LLMModel,
    LLMError,
    LLMAuthError,
    LLMConnectionError,
    ReasoningConfig,
    ReasoningEffort,
    ProviderType,
    get_provider,
    get_provider_by_name,
    list_providers,
    requires_api_key,
    parse_thinking_blocks,
)
from app.llm.openai import OpenAIProvider
from app.llm.anthropic import AnthropicProvider
from app.llm.gemini import GeminiProvider
from app.llm.ollama import OllamaProvider
from app.llm.openrouter import OpenRouterProvider


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_openai_models_response():
    """Mock ответ от OpenAI /models endpoint."""
    return {
        "data": [
            {"id": "gpt-4o-mini", "object": "model"},
            {"id": "gpt-4o", "object": "model"},
            {"id": "o1-mini", "object": "model"},
            {"id": "o3-mini", "object": "model"},
            {"id": "text-embedding-ada-002", "object": "model"},  # Should be filtered
        ]
    }


@pytest.fixture
def mock_openrouter_models_response():
    """Mock ответ от OpenRouter /models endpoint."""
    return {
        "data": [
            {
                "id": "openai/gpt-4o-mini",
                "name": "GPT-4o Mini",
                "context_length": 128000,
                "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
            },
            {
                "id": "anthropic/claude-3-haiku",
                "name": "Claude 3 Haiku",
                "context_length": 200000,
                "pricing": {"prompt": "0.00000025", "completion": "0.00000125"},
            },
            {
                "id": "deepseek/deepseek-r1",
                "name": "DeepSeek R1",
                "context_length": 64000,
                "pricing": {"prompt": "0.00000055", "completion": "0.0000022"},
            },
        ]
    }


@pytest.fixture
def mock_gemini_models_response():
    """Mock ответ от Gemini /models endpoint."""
    return {
        "models": [
            {
                "name": "models/gemini-2.0-flash",
                "displayName": "Gemini 2.0 Flash",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 8192,
            },
            {
                "name": "models/gemini-2.0-flash-thinking-exp",
                "displayName": "Gemini 2.0 Flash Thinking",
                "inputTokenLimit": 32768,
                "outputTokenLimit": 8192,
            },
        ]
    }


@pytest.fixture
def mock_ollama_tags_response():
    """Mock ответ от Ollama /api/tags endpoint."""
    return {
        "models": [
            {
                "name": "llama3:8b",
                "size": 4_000_000_000,
                "details": {"parameter_size": "8B"},
            },
            {
                "name": "deepseek-r1:7b",
                "size": 7_000_000_000,
                "details": {"parameter_size": "7B"},
            },
        ]
    }


# =============================================================================
# Test Base Interface
# =============================================================================

class TestLLMModel:
    """Тесты для LLMModel dataclass."""

    def test_model_creation(self):
        """Тест создания модели."""
        model = LLMModel(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            context_length=128000,
        )

        assert model.id == "gpt-4o-mini"
        assert model.name == "GPT-4o Mini"
        assert model.provider == "openai"
        assert model.context_length == 128000

    def test_model_display_name(self):
        """Тест отображаемого имени."""
        model = LLMModel(
            id="test",
            name="Test Model",
            provider="test",
            context_length=128000,
            supports_reasoning=True,
        )

        assert "128K" in model.display_name
        assert "🧠" in model.display_name

    def test_model_short_id(self):
        """Тест короткого ID."""
        model = LLMModel(
            id="openai/gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openrouter",
        )

        assert model.short_id == "gpt-4o-mini"


class TestReasoningConfig:
    """Тесты для ReasoningConfig."""

    def test_default_config(self):
        """Тест конфигурации по умолчанию."""
        config = ReasoningConfig()

        assert config.enabled is False
        assert config.effort == ReasoningEffort.MEDIUM
        assert config.budget_tokens == 10000

    def test_custom_config(self):
        """Тест кастомной конфигурации."""
        config = ReasoningConfig(
            enabled=True,
            effort=ReasoningEffort.HIGH,
            budget_tokens=20000,
        )

        assert config.enabled is True
        assert config.effort == ReasoningEffort.HIGH
        assert config.budget_tokens == 20000

    def test_to_dict(self):
        """Тест конвертации в словарь."""
        config = ReasoningConfig(enabled=True, effort=ReasoningEffort.LOW)
        d = config.to_dict()

        assert d["enabled"] is True
        assert d["effort"] == "low"


class TestParseThinkingBlocks:
    """Тесты для parse_thinking_blocks."""

    def test_no_thinking(self):
        """Тест текста без thinking блоков."""
        text = "Hello, world!"
        thinking, content = parse_thinking_blocks(text)

        assert thinking == ""
        assert content == "Hello, world!"

    def test_think_tag(self):
        """Тест с <think> тегом."""
        text = "<think>Let me think...</think>Here is the answer."
        thinking, content = parse_thinking_blocks(text)

        assert "Let me think" in thinking
        assert "Here is the answer" in content

    def test_thinking_tag(self):
        """Тест с <thinking> тегом."""
        text = "<thinking>Processing...</thinking>Result"
        thinking, content = parse_thinking_blocks(text)

        assert "Processing" in thinking
        assert "Result" in content


# =============================================================================
# Test Provider Factory
# =============================================================================

class TestProviderFactory:
    """Тесты для factory функций."""

    def test_get_provider_openai(self):
        """Тест получения OpenAI провайдера."""
        provider = get_provider(ProviderType.OPENAI, api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_get_provider_anthropic(self):
        """Тест получения Anthropic провайдера."""
        provider = get_provider(ProviderType.ANTHROPIC, api_key="test-key")
        assert isinstance(provider, AnthropicProvider)

    def test_get_provider_gemini(self):
        """Тест получения Gemini провайдера."""
        provider = get_provider(ProviderType.GEMINI, api_key="test-key")
        assert isinstance(provider, GeminiProvider)

    def test_get_provider_ollama(self):
        """Тест получения Ollama провайдера."""
        provider = get_provider(ProviderType.OLLAMA)
        assert isinstance(provider, OllamaProvider)

    def test_get_provider_openrouter(self):
        """Тест получения OpenRouter провайдера."""
        provider = get_provider(ProviderType.OPENROUTER, api_key="test-key")
        assert isinstance(provider, OpenRouterProvider)

    def test_get_provider_by_name(self):
        """Тест получения провайдера по имени."""
        provider = get_provider_by_name("openai", api_key="test-key")
        assert isinstance(provider, OpenAIProvider)

    def test_get_provider_by_name_invalid(self):
        """Тест с неверным именем провайдера."""
        with pytest.raises(ValueError):
            get_provider_by_name("invalid_provider")

    def test_list_providers(self):
        """Тест списка провайдеров."""
        providers = list_providers()

        assert len(providers) == 5
        assert any(p[0] == ProviderType.OPENAI for p in providers)
        assert any(p[0] == ProviderType.ANTHROPIC for p in providers)

    def test_requires_api_key(self):
        """Тест проверки необходимости API ключа."""
        assert requires_api_key(ProviderType.OPENAI) is True
        assert requires_api_key(ProviderType.ANTHROPIC) is True
        assert requires_api_key(ProviderType.OLLAMA) is False


# =============================================================================
# Test OpenAI Provider
# =============================================================================

class TestOpenAIProvider:
    """Тесты для OpenAI провайдера."""

    def test_init(self):
        """Тест инициализации."""
        provider = OpenAIProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert provider.PROVIDER_NAME == "OpenAI"

    @patch('urllib.request.urlopen')
    def test_fetch_models(self, mock_urlopen, mock_openai_models_response):
        """Тест загрузки моделей."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps(mock_openai_models_response).encode()
        mock_urlopen.return_value.__enter__ = Mock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        provider = OpenAIProvider(api_key="test-key")
        models = provider.fetch_models()

        # Проверяем что embedding модели отфильтрованы
        model_ids = [m.id for m in models]
        assert "gpt-4o-mini" in model_ids
        assert "text-embedding-ada-002" not in model_ids

    def test_reasoning_model_detection(self):
        """Тест определения reasoning моделей."""
        provider = OpenAIProvider(api_key="test-key")

        # Мокаем модели
        provider._cached_models = [
            LLMModel(id="gpt-4o-mini", name="GPT-4o Mini", provider="openai"),
            LLMModel(id="o1-mini", name="O1 Mini", provider="openai", supports_reasoning=True),
        ]
        provider._cache_time = float('inf')

        assert provider.supports_reasoning("gpt-4o-mini") is False
        assert provider.supports_reasoning("o1-mini") is True

    @patch('urllib.request.urlopen')
    def test_validate_api_key_valid(self, mock_urlopen):
        """Тест валидации корректного API ключа."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"data": []}'
        mock_urlopen.return_value = mock_response

        provider = OpenAIProvider(api_key="valid-key")
        assert provider.validate_api_key() is True

    @patch('urllib.request.urlopen')
    def test_validate_api_key_invalid(self, mock_urlopen):
        """Тест валидации неверного API ключа."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="", hdrs=None, fp=Mock(read=lambda: b'{"error": {"message": "Invalid"}}')
        )

        provider = OpenAIProvider(api_key="invalid-key")
        assert provider.validate_api_key() is False


# =============================================================================
# Test Anthropic Provider
# =============================================================================

class TestAnthropicProvider:
    """Тесты для Anthropic провайдера."""

    def test_init(self):
        """Тест инициализации."""
        provider = AnthropicProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert provider.PROVIDER_NAME == "Anthropic"

    def test_fetch_models_returns_list(self):
        """Тест что fetch_models возвращает список."""
        provider = AnthropicProvider(api_key="test-key")
        models = provider.fetch_models()

        assert isinstance(models, list)
        assert len(models) > 0

    def test_models_have_required_fields(self):
        """Тест что модели имеют обязательные поля."""
        provider = AnthropicProvider(api_key="test-key")
        models = provider.fetch_models()

        for model in models:
            assert model.id
            assert model.name
            assert model.provider == "anthropic"
            assert model.context_length > 0

    def test_thinking_model_support(self):
        """Тест поддержки thinking моделей."""
        provider = AnthropicProvider(api_key="test-key")
        models = provider.fetch_models()

        # Должна быть хотя бы одна модель с thinking
        thinking_models = [m for m in models if m.supports_reasoning]
        assert len(thinking_models) > 0

    def test_convert_messages(self):
        """Тест конвертации сообщений."""
        provider = AnthropicProvider(api_key="test-key")

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        system, converted = provider._convert_messages(messages)

        assert system == "You are helpful."
        assert len(converted) == 2
        assert converted[0]["role"] == "user"
        assert converted[1]["role"] == "assistant"


# =============================================================================
# Test Gemini Provider
# =============================================================================

class TestGeminiProvider:
    """Тесты для Gemini провайдера."""

    def test_init(self):
        """Тест инициализации."""
        provider = GeminiProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert provider.PROVIDER_NAME == "Gemini"

    @patch('urllib.request.urlopen')
    def test_fetch_models(self, mock_urlopen, mock_gemini_models_response):
        """Тест загрузки моделей."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps(mock_gemini_models_response).encode()
        mock_urlopen.return_value = mock_response

        provider = GeminiProvider(api_key="test-key")
        models = provider.fetch_models()

        assert len(models) == 2

        # Проверяем thinking модель
        thinking_models = [m for m in models if m.supports_reasoning]
        assert len(thinking_models) == 1
        assert "thinking" in thinking_models[0].id

    def test_convert_messages(self):
        """Тест конвертации сообщений."""
        provider = GeminiProvider(api_key="test-key")

        messages = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ]

        system, contents = provider._convert_messages(messages)

        assert system == "Be helpful."
        assert len(contents) == 1
        assert contents[0]["role"] == "user"


# =============================================================================
# Test Ollama Provider
# =============================================================================

class TestOllamaProvider:
    """Тесты для Ollama провайдера."""

    def test_init_default_url(self):
        """Тест инициализации с URL по умолчанию."""
        provider = OllamaProvider()
        assert provider.base_url == "http://localhost:11434"

    def test_init_custom_url(self):
        """Тест инициализации с кастомным URL."""
        provider = OllamaProvider(base_url="http://192.168.1.100:11434")
        assert provider.base_url == "http://192.168.1.100:11434"

    @patch('urllib.request.urlopen')
    def test_fetch_models(self, mock_urlopen, mock_ollama_tags_response):
        """Тест загрузки моделей."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps(mock_ollama_tags_response).encode()
        mock_urlopen.return_value = mock_response

        provider = OllamaProvider()
        models = provider.fetch_models()

        assert len(models) == 2

        # Проверяем reasoning модель (deepseek-r1)
        reasoning_models = [m for m in models if m.supports_reasoning]
        assert len(reasoning_models) == 1
        assert "deepseek" in reasoning_models[0].id

    def test_format_model_name(self):
        """Тест форматирования имени модели."""
        provider = OllamaProvider()

        assert "Llama" in provider._format_model_name("llama3:8b")
        assert "8B" in provider._format_model_name("llama3:8b")

    @patch('urllib.request.urlopen')
    def test_connection_error(self, mock_urlopen):
        """Тест ошибки подключения."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        provider = OllamaProvider()
        assert provider.is_available() is False


# =============================================================================
# Test OpenRouter Provider
# =============================================================================

class TestOpenRouterProvider:
    """Тесты для OpenRouter провайдера."""

    def test_init(self):
        """Тест инициализации."""
        provider = OpenRouterProvider(api_key="test-key")
        assert provider.api_key == "test-key"
        assert "Private" in provider.PROVIDER_NAME

    @patch('urllib.request.urlopen')
    def test_fetch_models(self, mock_urlopen, mock_openrouter_models_response):
        """Тест загрузки моделей."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps(mock_openrouter_models_response).encode()
        mock_urlopen.return_value = mock_response

        provider = OpenRouterProvider(api_key="test-key")
        models = provider.fetch_models()

        assert len(models) == 3

        # Проверяем что модели отсортированы по цене
        prices = [(m.pricing_input + m.pricing_output) / 2 for m in models]
        assert prices == sorted(prices)

    def test_private_only_enforcement(self):
        """Тест что data_collection: deny всегда включен."""
        provider = OpenRouterProvider(api_key="test-key")

        # Проверяем в complete (через мок)
        with patch.object(provider, '_make_request') as mock_request:
            mock_request.return_value = {"choices": [{"message": {"content": "test"}}]}

            provider.complete(
                messages=[{"role": "user", "content": "test"}],
                model="test-model",
            )

            # Проверяем что data_collection: deny был передан
            call_args = mock_request.call_args
            data = call_args[1]["data"]

            assert "provider" in data
            assert data["provider"]["data_collection"] == "deny"

    def test_reasoning_model_detection(self):
        """Тест определения reasoning моделей."""
        provider = OpenRouterProvider(api_key="test-key")

        assert provider._model_supports_reasoning("deepseek/deepseek-r1") is True
        assert provider._model_supports_reasoning("openai/o1-mini") is True
        assert provider._model_supports_reasoning("openai/gpt-4o-mini") is False


# =============================================================================
# Test Model Caching
# =============================================================================

class TestModelCaching:
    """Тесты для кэширования моделей."""

    @patch('urllib.request.urlopen')
    def test_caching_works(self, mock_urlopen):
        """Тест что кэширование работает."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"data": []}'
        mock_urlopen.return_value = mock_response

        provider = OpenAIProvider(api_key="test-key")

        # Первый вызов
        provider.fetch_models()
        assert mock_urlopen.call_count == 1

        # Второй вызов - должен использовать кэш
        provider.fetch_models()
        assert mock_urlopen.call_count == 1

    @patch('urllib.request.urlopen')
    def test_force_refresh(self, mock_urlopen):
        """Тест принудительного обновления кэша."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"data": []}'
        mock_urlopen.return_value = mock_response

        provider = OpenAIProvider(api_key="test-key")

        # Первый вызов
        provider.fetch_models()

        # Force refresh
        provider.fetch_models(force_refresh=True)
        assert mock_urlopen.call_count == 2
