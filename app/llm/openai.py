"""
OpenAI LLM провайдер.

Поддерживает:
- GPT-4o, GPT-4o-mini, GPT-4-turbo, GPT-3.5-turbo
- O1, O1-mini, O3-mini с reasoning_effort
- Динамическая загрузка моделей из API
"""

import json
import logging
import urllib.error
from typing import Dict, List, Optional, Any

from .base import (
    LLMProvider,
    LLMModel,
    LLMError,
    LLMAuthError,
    LLMConnectionError,
    ReasoningConfig,
    TokenCallback,
    ThinkingCallback,
    urlopen_with_ssl,
)

logger = logging.getLogger(__name__)

# OpenAI API endpoints
OPENAI_BASE_URL = "https://api.openai.com/v1"
MODELS_ENDPOINT = f"{OPENAI_BASE_URL}/models"
CHAT_ENDPOINT = f"{OPENAI_BASE_URL}/chat/completions"

# Модели с поддержкой reasoning
REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3-mini", "o3"}


class OpenAIProvider(LLMProvider):
    """OpenAI API провайдер."""

    PROVIDER_NAME = "OpenAI"

    def __init__(self, api_key: str, timeout: int = 180):
        super().__init__(api_key=api_key, timeout=timeout)

    # Используем базовые _make_request и _handle_http_error из LLMProvider

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """Загрузить модели из OpenAI API."""
        try:
            response = self._make_request(MODELS_ENDPOINT)
        except LLMError:
            # Если не удалось загрузить, вернём базовый список
            logger.warning("Не удалось загрузить модели из OpenAI API, используем базовый список")
            return self._get_fallback_models()

        models = []
        for item in response.get("data", []):
            model_id = item.get("id", "")

            # Фильтруем только chat модели
            if not self._is_chat_model(model_id):
                continue

            # Определяем поддержку reasoning
            supports_reasoning = any(r in model_id for r in REASONING_MODELS)

            model = LLMModel(
                id=model_id,
                name=self._format_model_name(model_id),
                provider="openai",
                context_length=self._get_context_length(model_id),
                supports_reasoning=supports_reasoning,
                reasoning_type="effort" if supports_reasoning else None,
                description=f"OpenAI {model_id}",
            )
            models.append(model)

        # Сортируем: сначала GPT-4o, потом o1/o3, потом остальные
        models.sort(key=lambda m: self._model_sort_key(m.id))

        return models

    def _is_chat_model(self, model_id: str) -> bool:
        """Проверить, является ли модель chat моделью."""
        chat_prefixes = ["gpt-4", "gpt-3.5", "o1", "o3", "chatgpt"]
        exclude = ["instruct", "vision", "audio", "realtime", "embedding", "tts", "whisper", "dall-e"]

        model_lower = model_id.lower()

        if any(ex in model_lower for ex in exclude):
            return False

        return any(model_lower.startswith(p) for p in chat_prefixes)

    def _format_model_name(self, model_id: str) -> str:
        """Форматировать имя модели для отображения."""
        # gpt-4o-mini-2024-07-18 -> GPT-4o Mini
        name = model_id.replace("-", " ").title()

        # Убираем даты
        parts = name.split()
        parts = [p for p in parts if not (len(p) == 4 and p.isdigit())]
        parts = [p for p in parts if not (len(p) == 2 and p.isdigit())]

        name = " ".join(parts)

        # Форматируем известные имена
        replacements = {
            "Gpt 4o": "GPT-4o",
            "Gpt 4o Mini": "GPT-4o Mini",
            "Gpt 4 Turbo": "GPT-4 Turbo",
            "Gpt 3.5 Turbo": "GPT-3.5 Turbo",
            "O1": "O1",
            "O1 Mini": "O1 Mini",
            "O1 Preview": "O1 Preview",
            "O3 Mini": "O3 Mini",
        }

        for old, new in replacements.items():
            if old.lower() in name.lower():
                return new

        return name

    def _get_context_length(self, model_id: str) -> int:
        """Получить размер контекста модели."""
        context_lengths = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "o1": 200000,
            "o1-mini": 128000,
            "o1-preview": 128000,
            "o3-mini": 200000,
        }

        for prefix, length in context_lengths.items():
            if model_id.startswith(prefix):
                return length

        return 8192  # По умолчанию

    def _model_sort_key(self, model_id: str) -> tuple:
        """Ключ сортировки для моделей."""
        priority = {
            "gpt-4o-mini": 0,
            "gpt-4o": 1,
            "o3-mini": 2,
            "o1-mini": 3,
            "o1": 4,
            "gpt-4-turbo": 5,
            "gpt-4": 6,
            "gpt-3.5-turbo": 7,
        }

        for prefix, p in priority.items():
            if model_id.startswith(prefix):
                return (p, model_id)

        return (99, model_id)

    def _get_fallback_models(self) -> List[LLMModel]:
        """Базовый список моделей если API недоступен."""
        return [
            LLMModel(
                id="gpt-4o-mini",
                name="GPT-4o Mini",
                provider="openai",
                context_length=128000,
                supports_reasoning=False,
            ),
            LLMModel(
                id="gpt-4o",
                name="GPT-4o",
                provider="openai",
                context_length=128000,
                supports_reasoning=False,
            ),
            LLMModel(
                id="o3-mini",
                name="O3 Mini",
                provider="openai",
                context_length=200000,
                supports_reasoning=True,
                reasoning_type="effort",
            ),
            LLMModel(
                id="o1-mini",
                name="O1 Mini",
                provider="openai",
                context_length=128000,
                supports_reasoning=True,
                reasoning_type="effort",
            ),
        ]

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Сгенерировать ответ."""
        data: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # Reasoning models не поддерживают temperature
        is_reasoning_model = any(r in model for r in REASONING_MODELS)
        if not is_reasoning_model:
            data["temperature"] = temperature

        # Добавляем reasoning_effort для o1/o3 моделей
        if reasoning and reasoning.enabled and is_reasoning_model:
            data["reasoning_effort"] = reasoning.effort.value

        response = self._make_request(CHAT_ENDPOINT, method="POST", data=data)

        return response["choices"][0]["message"]["content"]

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        on_token: TokenCallback,
        reasoning: Optional[ReasoningConfig] = None,
        on_thinking: Optional[ThinkingCallback] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Сгенерировать ответ со стримингом."""
        data: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        is_reasoning_model = any(r in model for r in REASONING_MODELS)
        if not is_reasoning_model:
            data["temperature"] = temperature

        if reasoning and reasoning.enabled and is_reasoning_model:
            data["reasoning_effort"] = reasoning.effort.value

        try:
            response = self._make_request(CHAT_ENDPOINT, method="POST", data=data, stream=True)
            return self._parse_sse_stream(response, on_token)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к OpenAI: {e.reason}")
        return ""

    def _validation_request(self) -> None:
        self._make_request(MODELS_ENDPOINT)
