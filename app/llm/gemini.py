"""
Google Gemini LLM провайдер.

Поддерживает:
- Gemini 2.0 Flash, Gemini 1.5 Pro, Gemini 1.5 Flash
- Thinking mode с thinking_budget
- Динамическая загрузка моделей из API
"""

import codecs
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

# Gemini API endpoints
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Модели с поддержкой thinking
THINKING_MODELS = {
    "gemini-2.0-flash-thinking-exp",
    "gemini-2.0-flash-thinking-exp-01-21",
}


class GeminiProvider(LLMProvider):
    """Google Gemini API провайдер."""

    PROVIDER_NAME = "Gemini"

    def __init__(self, api_key: str, timeout: int = 180):
        super().__init__(api_key=api_key, timeout=timeout)

    def _get_headers(self) -> Dict[str, str]:
        """Заголовки Gemini API (использует x-goog-api-key)."""
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """Обработать HTTP ошибку (403 тоже означает неверный ключ)."""
        if status_code == 403:
            try:
                error_data = json.loads(body)
                message = error_data.get("error", {}).get("message", body)
            except json.JSONDecodeError:
                message = body
            raise LLMAuthError(f"Неверный API ключ Gemini: {message}")
        # Для остальных кодов используем базовую обработку
        super()._handle_http_error(status_code, body)

    def _get_url(self, endpoint: str, stream: bool = False) -> str:
        """Получить URL для endpoint."""
        action = "streamGenerateContent" if stream else "generateContent"
        return f"{GEMINI_BASE_URL}/models/{endpoint}:{action}"

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """Загрузить модели из Gemini API."""
        url = f"{GEMINI_BASE_URL}/models"

        try:
            response = self._make_request(url)
        except LLMError:
            logger.warning("Не удалось загрузить модели из Gemini API, используем базовый список")
            return self._get_fallback_models()

        models = []
        for item in response.get("models", []):
            model_name = item.get("name", "")
            # models/gemini-2.0-flash -> gemini-2.0-flash
            model_id = model_name.replace("models/", "")

            # Фильтруем только generative модели
            if not self._is_generative_model(model_id):
                continue

            # Определяем поддержку thinking
            supports_thinking = model_id in THINKING_MODELS or "thinking" in model_id.lower()

            # Получаем context length
            input_limit = item.get("inputTokenLimit", 32768)
            output_limit = item.get("outputTokenLimit", 8192)

            model = LLMModel(
                id=model_id,
                name=item.get("displayName", model_id),
                provider="gemini",
                context_length=input_limit,
                supports_reasoning=supports_thinking,
                reasoning_type="budget" if supports_thinking else None,
                description=item.get("description", ""),
            )
            models.append(model)

        # Сортируем: сначала 2.0, потом 1.5
        models.sort(key=lambda m: self._model_sort_key(m.id))

        return models

    def _is_generative_model(self, model_id: str) -> bool:
        """Проверить, является ли модель generative моделью."""
        generative_prefixes = ["gemini"]
        exclude = ["embedding", "vision", "aqa"]

        model_lower = model_id.lower()

        if any(ex in model_lower for ex in exclude):
            return False

        return any(model_lower.startswith(p) for p in generative_prefixes)

    def _model_sort_key(self, model_id: str) -> tuple:
        """Ключ сортировки для моделей."""
        priority = {
            "gemini-2.0-flash": 0,
            "gemini-2.0-flash-thinking": 1,
            "gemini-1.5-pro": 2,
            "gemini-1.5-flash": 3,
            "gemini-1.0-pro": 4,
        }

        for prefix, p in priority.items():
            if model_id.startswith(prefix):
                return (p, model_id)

        return (99, model_id)

    def _get_fallback_models(self) -> List[LLMModel]:
        """Базовый список моделей если API недоступен."""
        return [
            LLMModel(
                id="gemini-2.0-flash",
                name="Gemini 2.0 Flash",
                provider="gemini",
                context_length=1048576,
                supports_reasoning=False,
                description="Быстрая модель нового поколения",
            ),
            LLMModel(
                id="gemini-2.0-flash-thinking-exp",
                name="Gemini 2.0 Flash Thinking",
                provider="gemini",
                context_length=32768,
                supports_reasoning=True,
                reasoning_type="budget",
                description="Модель с thinking mode",
            ),
            LLMModel(
                id="gemini-1.5-pro",
                name="Gemini 1.5 Pro",
                provider="gemini",
                context_length=2097152,
                supports_reasoning=False,
                description="Самый большой контекст",
            ),
            LLMModel(
                id="gemini-1.5-flash",
                name="Gemini 1.5 Flash",
                provider="gemini",
                context_length=1048576,
                supports_reasoning=False,
                description="Быстрая модель",
            ),
        ]

    def _convert_messages(self, messages: List[Dict[str, str]]) -> tuple[str, List[Dict]]:
        """
        Конвертировать сообщения в формат Gemini.

        Returns:
            (system_instruction, contents)
        """
        system = ""
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system = content
            else:
                # Gemini использует "user" и "model"
                gemini_role = "model" if role == "assistant" else "user"
                contents.append({
                    "role": gemini_role,
                    "parts": [{"text": content}],
                })

        return system, contents

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Сгенерировать ответ."""
        system, contents = self._convert_messages(messages)

        data: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        if system:
            data["systemInstruction"] = {"parts": [{"text": system}]}

        # Thinking config для поддерживающих моделей
        is_thinking_model = model in THINKING_MODELS or "thinking" in model.lower()

        if reasoning and reasoning.enabled and is_thinking_model:
            data["generationConfig"]["thinking_config"] = {
                "thinking_budget": reasoning.budget_tokens,
            }

        url = self._get_url(model, stream=False)
        response = self._make_request(url, method="POST", data=data)

        # Извлекаем текст из ответа
        candidates = response.get("candidates", [])
        if not candidates:
            return ""

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        text_parts = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])

        return "".join(text_parts)

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
        system, contents = self._convert_messages(messages)

        data: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        if system:
            data["systemInstruction"] = {"parts": [{"text": system}]}

        is_thinking_model = model in THINKING_MODELS or "thinking" in model.lower()

        if reasoning and reasoning.enabled and is_thinking_model:
            data["generationConfig"]["thinking_config"] = {
                "thinking_budget": reasoning.budget_tokens,
            }

        url = self._get_url(model, stream=True) + "?alt=sse"

        try:
            response = self._make_request(url, method="POST", data=data, stream=True)
            return self._parse_gemini_sse_stream(response, on_token, on_thinking)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к Gemini: {e.reason}")
        return ""

    def _parse_gemini_sse_stream(
        self,
        response,
        on_token: TokenCallback,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> str:
        """Парсинг SSE потока Gemini с поддержкой thinking."""
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        full_response: List[str] = []

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
                        try:
                            event_data = json.loads(line[6:])
                            candidates = event_data.get("candidates", [])

                            if candidates:
                                content = candidates[0].get("content", {})
                                parts = content.get("parts", [])

                                for part in parts:
                                    # Обычный текст
                                    if "text" in part:
                                        text = part["text"]
                                        full_response.append(text)
                                        on_token(text)

                                    # Thinking (если есть)
                                    if "thought" in part and on_thinking:
                                        on_thinking(part["thought"])

                        except json.JSONDecodeError:
                            pass

        return "".join(full_response)

    def validate_api_key(self) -> bool:
        """Проверить валидность API ключа."""
        try:
            url = f"{GEMINI_BASE_URL}/models"
            self._make_request(url)
            return True
        except LLMAuthError:
            return False
        except LLMError:
            return True
