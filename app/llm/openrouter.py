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
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any
import codecs

from .base import (
    LLMProvider,
    LLMModel,
    LLMError,
    LLMAuthError,
    LLMRateLimitError,
    LLMConnectionError,
    LLMInvalidModelError,
    ReasoningConfig,
    TokenCallback,
    ThinkingCallback,
    urlopen_with_ssl,
)

logger = logging.getLogger(__name__)

# OpenRouter API endpoints
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_ENDPOINT = f"{OPENROUTER_BASE_URL}/models"
CHAT_ENDPOINT = f"{OPENROUTER_BASE_URL}/chat/completions"

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

    def _make_request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        stream: bool = False,
    ) -> Any:
        """Выполнить HTTP запрос к OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mindtype.app",
            "X-Title": "MindType",
        }

        req_data = json.dumps(data).encode("utf-8") if data else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            response = urlopen_with_ssl(request, timeout=self.timeout)
            if stream:
                return response
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к OpenRouter: {e.reason}")

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """Обработать HTTP ошибку."""
        try:
            error_data = json.loads(body)
            message = error_data.get("error", {}).get("message", body)
        except json.JSONDecodeError:
            message = body

        if status_code == 401:
            raise LLMAuthError(f"Неверный API ключ OpenRouter: {message}")
        elif status_code == 402:
            raise LLMError(f"Недостаточно средств на балансе OpenRouter: {message}")
        elif status_code == 429:
            raise LLMRateLimitError(f"Превышен лимит запросов OpenRouter: {message}")
        elif status_code == 404:
            raise LLMInvalidModelError(f"Модель не найдена: {message}")
        else:
            raise LLMError(f"Ошибка OpenRouter API ({status_code}): {message}")

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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mindtype.app",
            "X-Title": "MindType",
        }

        req_data = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(CHAT_ENDPOINT, data=req_data, headers=headers, method="POST")

        full_response = []

        try:
            with urlopen_with_ssl(request, timeout=self.timeout) as response:
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                buffer = ""

                while True:
                    chunk = response.read(1024)
                    if not chunk:
                        final = decoder.decode(b"", final=True)
                        if final:
                            buffer += final
                        break
                    buffer += decoder.decode(chunk)

                    # Парсим SSE события
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)

                        for line in event.split("\n"):
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    continue

                                try:
                                    event_data = json.loads(data_str)
                                    delta = event_data.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")

                                    if content:
                                        full_response.append(content)
                                        on_token(content)

                                except json.JSONDecodeError:
                                    pass

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к OpenRouter: {e.reason}")

        return "".join(full_response)

    def validate_api_key(self) -> bool:
        """Проверить валидность API ключа."""
        try:
            self._make_request(MODELS_ENDPOINT)
            return True
        except LLMAuthError:
            return False
        except LLMError:
            return True

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
