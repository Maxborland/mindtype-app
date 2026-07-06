"""
Anthropic Claude LLM провайдер.

Поддерживает:
- Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus
- Extended Thinking (beta) с budget_tokens
- Streaming с thinking блоками
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

# Anthropic API endpoints
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
MESSAGES_ENDPOINT = f"{ANTHROPIC_BASE_URL}/messages"

# API версия
ANTHROPIC_VERSION = "2023-06-01"

# Модели с поддержкой extended thinking
THINKING_MODELS = {
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-latest",
}


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API провайдер."""

    PROVIDER_NAME = "Anthropic"

    def __init__(self, api_key: str, timeout: int = 180):
        super().__init__(api_key=api_key, timeout=timeout)
        self._use_beta = False  # Флаг для extended thinking

    def _get_headers(self) -> Dict[str, str]:
        """Заголовки Anthropic API."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        # Для extended thinking нужен beta header
        if self._use_beta:
            headers["anthropic-beta"] = "interleaved-thinking-2025-05-14"
        return headers

    # Используем базовые _make_request и _handle_http_error из LLMProvider

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """
        Anthropic не имеет публичного API для списка моделей.
        Возвращаем актуальный список моделей.
        """
        return [
            LLMModel(
                id="claude-sonnet-4-20250514",
                name="Claude Sonnet 4",
                provider="anthropic",
                context_length=200000,
                supports_reasoning=True,
                reasoning_type="thinking",
                description="Последняя версия Claude Sonnet с extended thinking",
            ),
            LLMModel(
                id="claude-3-5-sonnet-latest",
                name="Claude 3.5 Sonnet",
                provider="anthropic",
                context_length=200000,
                supports_reasoning=True,
                reasoning_type="thinking",
                description="Claude 3.5 Sonnet - баланс скорости и качества",
            ),
            LLMModel(
                id="claude-3-5-haiku-latest",
                name="Claude 3.5 Haiku",
                provider="anthropic",
                context_length=200000,
                supports_reasoning=False,
                description="Claude 3.5 Haiku - быстрая и экономичная модель",
            ),
            LLMModel(
                id="claude-3-opus-latest",
                name="Claude 3 Opus",
                provider="anthropic",
                context_length=200000,
                supports_reasoning=False,
                description="Claude 3 Opus - самая мощная модель",
            ),
        ]

    def _convert_messages(self, messages: List[Dict[str, str]]) -> tuple[str, List[Dict]]:
        """
        Конвертировать сообщения в формат Anthropic.

        Returns:
            (system_prompt, messages_list)
        """
        system = ""
        converted = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system = content
            else:
                # Anthropic использует "user" и "assistant"
                anthropic_role = "assistant" if role == "assistant" else "user"
                converted.append({
                    "role": anthropic_role,
                    "content": content,
                })

        return system, converted

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Сгенерировать ответ."""
        system, converted_messages = self._convert_messages(messages)

        data: Dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_tokens": max_tokens,
        }

        if system:
            data["system"] = system

        # Extended thinking для поддерживающих моделей
        is_thinking_model = model in THINKING_MODELS or "sonnet" in model.lower()

        if reasoning and reasoning.enabled and is_thinking_model:
            self._use_beta = True
            data["thinking"] = {
                "type": "enabled",
                "budget_tokens": reasoning.budget_tokens,
            }
            # Для thinking нужен больший max_tokens
            data["max_tokens"] = max(max_tokens, 16000)
        else:
            self._use_beta = False
            data["temperature"] = temperature

        response = self._make_request(MESSAGES_ENDPOINT, method="POST", data=data)

        # Извлекаем текст из ответа (может содержать thinking блоки)
        content_blocks = response.get("content", [])
        text_parts = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))

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
        system, converted_messages = self._convert_messages(messages)

        data: Dict[str, Any] = {
            "model": model,
            "messages": converted_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        if system:
            data["system"] = system

        is_thinking_model = model in THINKING_MODELS or "sonnet" in model.lower()

        if reasoning and reasoning.enabled and is_thinking_model:
            self._use_beta = True
            data["thinking"] = {
                "type": "enabled",
                "budget_tokens": reasoning.budget_tokens,
            }
            data["max_tokens"] = max(max_tokens, 16000)
        else:
            self._use_beta = False
            data["temperature"] = temperature

        try:
            response = self._make_request(MESSAGES_ENDPOINT, method="POST", data=data, stream=True)
            return self._parse_anthropic_sse_stream(response, on_token, on_thinking)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Ошибка подключения к Anthropic: {e.reason}")
        return ""

    def _parse_anthropic_sse_stream(
        self,
        response,
        on_token: TokenCallback,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> str:
        """Парсинг SSE потока Anthropic с поддержкой thinking блоков."""
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

                event_type = None
                event_data = None

                for line in event.split("\n"):
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        try:
                            event_data = json.loads(line[6:])
                        except json.JSONDecodeError:
                            pass

                if not event_data:
                    continue

                # Обрабатываем события content_block_delta
                if event_type == "content_block_delta":
                    delta = event_data.get("delta", {})
                    delta_type = delta.get("type")

                    if delta_type == "thinking_delta":
                        # Thinking блок
                        thinking_text = delta.get("thinking", "")
                        if thinking_text and on_thinking:
                            on_thinking(thinking_text)

                    elif delta_type == "text_delta":
                        # Обычный текст
                        text = delta.get("text", "")
                        if text:
                            full_response.append(text)
                            on_token(text)

        return "".join(full_response)

    def _validation_request(self) -> None:
        # Минимальный запрос для проверки ключа
        data = {
            "model": "claude-3-5-haiku-latest",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
        }
        self._make_request(MESSAGES_ENDPOINT, method="POST", data=data)
