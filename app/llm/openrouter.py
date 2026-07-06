"""
OpenRouter LLM провайдер (PRIVATE ONLY).

Поддерживает:
- Доступ к 300+ моделям через единый API
- ОБЯЗАТЕЛЬНЫЙ режим private-only (data_collection: deny)
- Reasoning mode для поддерживающих моделей
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
    LLMInsufficientFundsError,
    ReasoningConfig,
    TokenCallback,
    ThinkingCallback,
)

logger = logging.getLogger(__name__)

# OpenRouter API endpoints
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_ENDPOINT = f"{OPENROUTER_BASE_URL}/models"
CHAT_ENDPOINT = f"{OPENROUTER_BASE_URL}/chat/completions"
TRANSCRIPTIONS_ENDPOINT = f"{OPENROUTER_BASE_URL}/audio/transcriptions"

# Модели с поддержкой reasoning
REASONING_MODEL_PATTERNS = [
    "o1", "o3",  # OpenAI reasoning
    "deepseek-r1", "deepseek/deepseek-r1",  # DeepSeek
    "qwq",  # Qwen reasoning
]


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter API провайдер.

    ВАЖНО: Всегда использует data_collection: deny для обеспечения
    приватности данных. Это нельзя отключить.
    """

    PROVIDER_NAME = "OpenRouter (Private)"

    def __init__(self, api_key: str, timeout: int = 180):
        super().__init__(api_key=api_key, timeout=timeout)

    def _get_headers(self) -> Dict[str, str]:
        """Заголовки с OpenRouter-специфичными полями."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mindtype.app",
            "X-Title": "MindType",
        }

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """Обработать HTTP ошибку с поддержкой 402 (недостаточно средств)."""
        if status_code == 402:
            try:
                error_data = json.loads(body)
                message = error_data.get("error", {}).get("message", body)
            except json.JSONDecodeError:
                message = body
            raise LLMInsufficientFundsError(f"Недостаточно средств на балансе OpenRouter: {message}")
        # Для остальных кодов используем базовую обработку
        super()._handle_http_error(status_code, body)

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """Загрузить модели из OpenRouter API."""
        try:
            response = self._make_request(MODELS_ENDPOINT)
        except LLMError:
            logger.warning("Не удалось загрузить модели из OpenRouter API")
            return []

        models = []
        for item in response.get("data", []):
            model_id = item.get("id", "")

            # Пропускаем модели без pricing
            pricing = item.get("pricing", {})
            if not pricing:
                continue

            # Парсим цену
            try:
                price_in = float(pricing.get("prompt", "0")) * 1_000_000
                price_out = float(pricing.get("completion", "0")) * 1_000_000
            except (ValueError, TypeError):
                continue

            # Определяем поддержку reasoning
            supports_reasoning = self._model_supports_reasoning(model_id)

            model = LLMModel(
                id=model_id,
                name=item.get("name", model_id),
                provider="openrouter",
                context_length=item.get("context_length", 4096),
                supports_reasoning=supports_reasoning,
                reasoning_type="effort" if supports_reasoning else None,
                description=item.get("description", ""),
                pricing_input=price_in,
                pricing_output=price_out,
            )
            models.append(model)

        # Сортируем по средней цене
        models.sort(key=lambda m: (m.pricing_input + m.pricing_output) / 2)

        logger.info(f"Загружено {len(models)} моделей из OpenRouter")
        return models

    def _model_supports_reasoning(self, model_id: str) -> bool:
        """Проверить, поддерживает ли модель reasoning."""
        model_lower = model_id.lower()
        for pattern in REASONING_MODEL_PATTERNS:
            if pattern in model_lower:
                return True
        return False

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """
        Сгенерировать ответ.

        ВАЖНО: Всегда использует data_collection: deny
        """
        data: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            # ОБЯЗАТЕЛЬНО: Private mode
            "provider": {
                "data_collection": "deny",
                "allow_fallbacks": True,
            },
        }

        # Добавляем reasoning для поддерживающих моделей
        if reasoning and reasoning.enabled and self._model_supports_reasoning(model):
            data["reasoning"] = {
                "effort": reasoning.effort.value,
            }

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
        """
        Сгенерировать ответ со стримингом.

        ВАЖНО: Всегда использует data_collection: deny
        """
        data: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # ОБЯЗАТЕЛЬНО: Private mode
            "provider": {
                "data_collection": "deny",
                "allow_fallbacks": True,
            },
        }

        if reasoning and reasoning.enabled and self._model_supports_reasoning(model):
            data["reasoning"] = {
                "effort": reasoning.effort.value,
            }

        try:
            response = self._make_request(CHAT_ENDPOINT, method="POST", data=data, stream=True)
            return self._parse_sse_stream(response, on_token)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к OpenRouter: {e.reason}")
        return ""

    def _validation_request(self) -> None:
        self._make_request(MODELS_ENDPOINT)

    def transcribe_audio(
        self,
        audio_b64: str,
        audio_format: str,
        model: str,
        language: Optional[str] = None,
        temperature: float = 0.0,
    ) -> str:
        """
        Транскрибировать аудио через STT-эндпоинт OpenRouter.

        Args:
            audio_b64: Аудио в base64 (сырые байты, без data-uri)
            audio_format: Формат аудио (wav, mp3, flac, ...)
            model: ID STT-модели (например openai/whisper-1)
            language: ISO-639-1 код языка; "auto"/None — автоопределение
            temperature: 0.0 для детерминированной расшифровки

        Returns:
            Распознанный текст
        """
        data: Dict[str, Any] = {
            "model": model,
            "input_audio": {"data": audio_b64, "format": audio_format},
            "temperature": temperature,
        }
        if language and language != "auto":
            data["language"] = language

        # Чанки длинного файла шлются десятками — один transient 520/502 у провайдера
        # не должен ронять всю транскрипцию, поэтому повторяем с backoff.
        response = self._make_request(
            TRANSCRIPTIONS_ENDPOINT, method="POST", data=data, retries=3
        )
        return (response.get("text") or "").strip()

    def fetch_transcription_models(self) -> List[LLMModel]:
        """
        Загрузить список STT-моделей (output_modalities=transcription).

        Отдельный парсер (не _fetch_models_from_api), т.к. STT-модели могут
        не иметь стандартного prompt/completion pricing и были бы отброшены.

        Ошибки (LLMAuthError/LLMConnectionError/LLMError) НЕ глотаем — пробрасываем,
        чтобы UI-обработчик показал понятный диалог (иначе пустой список = молчание).
        """
        response = self._make_request(MODELS_ENDPOINT + "?output_modalities=transcription")

        models = []
        for item in response.get("data", []):
            model_id = item.get("id", "")
            if not model_id:
                continue
            models.append(
                LLMModel(
                    id=model_id,
                    name=item.get("name", model_id),
                    provider="openrouter",
                    context_length=item.get("context_length", 0),
                    description=item.get("description", ""),
                )
            )

        models.sort(key=lambda m: m.name.lower())
        logger.info(f"Загружено {len(models)} STT-моделей из OpenRouter")
        return models

    def get_recommended_models(self) -> List[LLMModel]:
        """Получить рекомендуемые модели для саммаризации."""
        all_models = self.fetch_models()

        # Рекомендуемые модели по ID
        recommended_ids = [
            "anthropic/claude-3-haiku",
            "anthropic/claude-3.5-haiku",
            "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-001",
            "qwen/qwen-2.5-72b-instruct",
            "meta-llama/llama-3.1-70b-instruct",
            "mistralai/mistral-small-24b-instruct-2501",
            "deepseek/deepseek-r1",
        ]

        recommended = []
        for model_id in recommended_ids:
            for model in all_models:
                if model.id == model_id:
                    recommended.append(model)
                    break

        return recommended
