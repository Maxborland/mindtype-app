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

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

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
from .mindtype_cloud import MindTypeCloudProvider, LLMNoCreditsError, CreditsInfo


class ProviderType(Enum):
    """Типы LLM провайдеров."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    MINDTYPE_CLOUD = "mindtype_cloud"


@dataclass(frozen=True)
class ProviderDescriptor:
    """Метаданные провайдера: единый источник правды о ключах/полях/плейсхолдерах."""
    id: str
    label: str
    needs_api_key: bool
    needs_base_url: bool
    key_placeholder: str = ""

    @property
    def api_key_field(self) -> str:
        return f"{self.id}_api_key"

    @property
    def model_field(self) -> str:
        return f"{self.id}_model"


# Реестр провайдеров — заменяет разбросанные паттерны f"{provider}_api_key",
# списки no_key_providers и ветвления is_ollama/is_mindtype_cloud.
PROVIDER_REGISTRY = {
    "openai": ProviderDescriptor("openai", "OpenAI", True, False, "sk-..."),
    "anthropic": ProviderDescriptor("anthropic", "Claude (Anthropic)", True, False, "sk-ant-..."),
    "gemini": ProviderDescriptor("gemini", "Gemini (Google)", True, False, "AIza..."),
    "ollama": ProviderDescriptor("ollama", "Ollama (Local)", False, True, ""),
    "openrouter": ProviderDescriptor("openrouter", "OpenRouter (Private)", True, False, "sk-or-..."),
    "mindtype_cloud": ProviderDescriptor("mindtype_cloud", "MindType Cloud", False, False, ""),
}

_cloud_token_source: Optional[Callable[[], Optional[str]]] = None
_cloud_refresh: Optional[Callable[[Optional[str]], None]] = None


def configure_mindtype_cloud_session(
    token_source: Callable[[], Optional[str]],
    refresh: Callable[[Optional[str]], None],
) -> None:
    """Configure the process-wide short-lived session used by cloud LLM calls."""
    global _cloud_token_source, _cloud_refresh
    _cloud_token_source = token_source
    _cloud_refresh = refresh


def get_provider_descriptor(name: str) -> Optional[ProviderDescriptor]:
    """Дескриптор провайдера по строковому id (или None)."""
    return PROVIDER_REGISTRY.get(name)


# Человекочитаемые имена — производны от реестра (один источник правды).
# .get с фолбэком: новый ProviderType без записи в реестре не уронит импорт app.
PROVIDER_NAMES = {
    ptype: (PROVIDER_REGISTRY[ptype.value].label if ptype.value in PROVIDER_REGISTRY else ptype.value)
    for ptype in ProviderType
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

    elif provider_type == ProviderType.MINDTYPE_CLOUD:
        if _cloud_token_source is None or _cloud_refresh is None:
            raise RuntimeError("MindType Cloud session is not configured")
        return MindTypeCloudProvider(
            access_token=_cloud_token_source,
            refresh_access_token=_cloud_refresh,
            timeout=timeout,
        )

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
    # Источник правды — реестр (Ollama без ключа, MindType Cloud — лицензия, не API-ключ)
    desc = PROVIDER_REGISTRY.get(provider_type.value)
    return desc.needs_api_key if desc else True


__all__ = [
    # Провайдеры
    "LLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "MindTypeCloudProvider",

    # Модели и конфигурация
    "LLMModel",
    "ReasoningConfig",
    "ReasoningEffort",
    "CreditsInfo",

    # Исключения
    "LLMError",
    "LLMAuthError",
    "LLMRateLimitError",
    "LLMConnectionError",
    "LLMInvalidModelError",
    "LLMNoCreditsError",

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

    # Константы / реестр
    "PROVIDER_NAMES",
    "PROVIDER_REGISTRY",
    "ProviderDescriptor",
    "get_provider_descriptor",
    "configure_mindtype_cloud_session",

    # SSL
    "get_ssl_context",
]
