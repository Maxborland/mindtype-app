"""
LLM провайдеры для MindType.

Поддерживаемые провайдеры:
- OpenAI (GPT-4o, o1, o3)
- Anthropic (Claude)
- Google (Gemini)
- Ollama (локальные модели)
- OpenRouter (private-only)

Использование:
    from app.llm import get_provider, ProviderType

    provider = get_provider(ProviderType.OPENAI, api_key="...")
    models = provider.fetch_models()
    response = provider.complete(messages, model="gpt-4o-mini")
"""

from enum import Enum
from typing import Optional

from .base import (
    LLMProvider,
    LLMModel,
    LLMError,
    LLMAuthError,
    LLMRateLimitError,
    LLMConnectionError,
    LLMInvalidModelError,
    ReasoningConfig,
    ReasoningEffort,
    TokenCallback,
    ThinkingCallback,
    parse_thinking_blocks,
    get_ssl_context,
)

from .openai import OpenAIProvider
from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider


class ProviderType(Enum):
    """Типы LLM провайдеров."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


# Человекочитаемые имена провайдеров
PROVIDER_NAMES = {
    ProviderType.OPENAI: "OpenAI",
    ProviderType.ANTHROPIC: "Claude (Anthropic)",
    ProviderType.GEMINI: "Gemini (Google)",
    ProviderType.OLLAMA: "Ollama (Local)",
    ProviderType.OPENROUTER: "OpenRouter (Private)",
}


def get_provider(
    provider_type: ProviderType,
    api_key: str = "",
    base_url: str = "",
    timeout: int = 180,
) -> LLMProvider:
    """
    Получить экземпляр LLM провайдера.

    Args:
        provider_type: Тип провайдера
        api_key: API ключ (не требуется для Ollama)
        base_url: Базовый URL (для Ollama или custom endpoints)
        timeout: Таймаут запросов в секундах

    Returns:
        Экземпляр провайдера

    Raises:
        ValueError: Если тип провайдера неизвестен
    """
    if provider_type == ProviderType.OPENAI:
        return OpenAIProvider(api_key=api_key, timeout=timeout)

    elif provider_type == ProviderType.ANTHROPIC:
        return AnthropicProvider(api_key=api_key, timeout=timeout)

    elif provider_type == ProviderType.GEMINI:
        return GeminiProvider(api_key=api_key, timeout=timeout)

    elif provider_type == ProviderType.OLLAMA:
        return OllamaProvider(base_url=base_url, timeout=timeout)

    elif provider_type == ProviderType.OPENROUTER:
        return OpenRouterProvider(api_key=api_key, timeout=timeout)

    else:
        raise ValueError(f"Неизвестный тип провайдера: {provider_type}")


def get_provider_by_name(
    name: str,
    api_key: str = "",
    base_url: str = "",
    timeout: int = 180,
) -> LLMProvider:
    """
    Получить провайдер по строковому имени.

    Args:
        name: Имя провайдера ("openai", "anthropic", "gemini", "ollama", "openrouter")
        api_key: API ключ
        base_url: Базовый URL
        timeout: Таймаут

    Returns:
        Экземпляр провайдера

    Raises:
        ValueError: Если имя провайдера неизвестно
    """
    try:
        provider_type = ProviderType(name.lower())
    except ValueError:
        valid_names = [p.value for p in ProviderType]
        raise ValueError(f"Неизвестный провайдер: {name}. Доступные: {valid_names}")

    return get_provider(provider_type, api_key, base_url, timeout)


def list_providers() -> list[tuple[ProviderType, str]]:
    """
    Получить список доступных провайдеров.

    Returns:
        Список кортежей (тип, человекочитаемое имя)
    """
    return [(p, PROVIDER_NAMES[p]) for p in ProviderType]


def requires_api_key(provider_type: ProviderType) -> bool:
    """
    Проверить, требует ли провайдер API ключ.

    Args:
        provider_type: Тип провайдера

    Returns:
        True если требуется API ключ
    """
    return provider_type != ProviderType.OLLAMA


__all__ = [
    # Провайдеры
    "LLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenRouterProvider",

    # Модели и конфигурация
    "LLMModel",
    "ReasoningConfig",
    "ReasoningEffort",

    # Исключения
    "LLMError",
    "LLMAuthError",
    "LLMRateLimitError",
    "LLMConnectionError",
    "LLMInvalidModelError",

    # Типы
    "ProviderType",
    "TokenCallback",
    "ThinkingCallback",

    # Функции
    "get_provider",
    "get_provider_by_name",
    "list_providers",
    "requires_api_key",
    "parse_thinking_blocks",

    # Константы
    "PROVIDER_NAMES",

    # SSL
    "get_ssl_context",
]
