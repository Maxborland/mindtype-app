"""
Ollama LLM провайдер (локальные модели).

Поддерживает:
- Llama 3, Mistral, Qwen, и др.
- DeepSeek R1 с встроенным reasoning
- Динамическая загрузка установленных моделей
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
    LLMConnectionError,
    LLMInvalidModelError,
    ReasoningConfig,
    TokenCallback,
    ThinkingCallback,
    parse_thinking_blocks,
    urlopen_with_ssl,
)

logger = logging.getLogger(__name__)

# Модели с встроенным reasoning (выводят <think>...</think>)
REASONING_MODELS = {
    "deepseek-r1",
    "deepseek-r1:latest",
    "deepseek-r1:7b",
    "deepseek-r1:8b",
    "deepseek-r1:14b",
    "deepseek-r1:32b",
    "deepseek-r1:70b",
    "qwq",
    "qwq:latest",
    "qwq:32b",
}


class OllamaProvider(LLMProvider):
    """Ollama API провайдер для локальных моделей."""

    PROVIDER_NAME = "Ollama"
    DEFAULT_URL = "http://localhost:11434"

    def __init__(self, base_url: str = "", timeout: int = 300):
        """
        Args:
            base_url: URL Ollama сервера (по умолчанию localhost:11434)
            timeout: Таймаут запросов (больше для локальных моделей)
        """
        super().__init__(api_key="", base_url=base_url or self.DEFAULT_URL, timeout=timeout)

    def _get_url(self, endpoint: str) -> str:
        """Получить полный URL."""
        base = self.base_url.rstrip("/")
        return f"{base}/api/{endpoint}"

    def _make_request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        stream: bool = False,
    ) -> Any:
        """Выполнить HTTP запрос к Ollama API."""
        headers = {
            "Content-Type": "application/json",
        }

        req_data = json.dumps(data).encode("utf-8") if data else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
            if stream:
                return response
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Не удалось подключиться к Ollama ({self.base_url}): {e.reason}")

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """Обработать HTTP ошибку."""
        try:
            error_data = json.loads(body)
            message = error_data.get("error", body)
        except json.JSONDecodeError:
            message = body

        if status_code == 404:
            raise LLMInvalidModelError(f"Модель не найдена в Ollama: {message}")
        else:
            raise LLMError(f"Ошибка Ollama API ({status_code}): {message}")

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """Загрузить установленные модели из Ollama."""
        try:
            url = self._get_url("tags")
            response = self._make_request(url)
        except LLMError as e:
            logger.warning(f"Не удалось загрузить модели из Ollama: {e}")
            return []

        models = []
        for item in response.get("models", []):
            model_name = item.get("name", "")

            # Определяем поддержку reasoning
            base_name = model_name.split(":")[0].lower()
            supports_reasoning = base_name in {"deepseek-r1", "qwq"}

            # Получаем размер модели
            size_bytes = item.get("size", 0)
            size_gb = size_bytes / (1024 ** 3)

            # Получаем параметры из details
            details = item.get("details", {})
            parameter_size = details.get("parameter_size", "")

            model = LLMModel(
                id=model_name,
                name=self._format_model_name(model_name),
                provider="ollama",
                context_length=self._estimate_context_length(model_name),
                supports_reasoning=supports_reasoning,
                reasoning_type="think" if supports_reasoning else None,
                description=f"{parameter_size}, {size_gb:.1f} GB" if parameter_size else f"{size_gb:.1f} GB",
            )
            models.append(model)

        # Сортируем по имени
        models.sort(key=lambda m: m.name.lower())

        return models

    def _format_model_name(self, model_name: str) -> str:
        """Форматировать имя модели."""
        # llama3:8b -> Llama 3 (8B)
        # deepseek-r1:32b -> DeepSeek R1 (32B)

        parts = model_name.split(":")
        base = parts[0]
        tag = parts[1] if len(parts) > 1 else ""

        # Форматируем базовое имя
        name = base.replace("-", " ").replace("_", " ")
        name = name.title()

        # Добавляем размер если есть
        if tag and tag != "latest":
            size = tag.upper()
            name = f"{name} ({size})"

        return name

    def _estimate_context_length(self, model_name: str) -> int:
        """Оценить размер контекста модели."""
        # Большинство современных моделей имеют 8K+ контекст
        context_hints = {
            "llama3": 8192,
            "llama3.1": 128000,
            "llama3.2": 128000,
            "mistral": 32768,
            "mixtral": 32768,
            "qwen": 32768,
            "qwen2": 128000,
            "deepseek": 64000,
            "deepseek-r1": 64000,
            "phi": 16384,
            "gemma": 8192,
            "gemma2": 8192,
        }

        model_lower = model_name.lower()
        for prefix, length in context_hints.items():
            if prefix in model_lower:
                return length

        return 4096  # По умолчанию

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
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        url = self._get_url("chat")
        response = self._make_request(url, method="POST", data=data)

        content = response.get("message", {}).get("content", "")

        # Для reasoning моделей убираем thinking блоки из вывода
        base_name = model.split(":")[0].lower()
        if base_name in {"deepseek-r1", "qwq"}:
            _, content = parse_thinking_blocks(content)

        return content

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
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        url = self._get_url("chat")

        headers = {
            "Content-Type": "application/json",
        }

        req_data = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

        full_response = []
        in_thinking = False
        thinking_buffer = []

        # Определяем, является ли модель reasoning моделью
        base_name = model.split(":")[0].lower()
        is_reasoning_model = base_name in {"deepseek-r1", "qwq"}

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
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

                    # Ollama возвращает JSON объекты по одному на строку
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()

                        if not line:
                            continue

                        try:
                            event_data = json.loads(line)
                            content = event_data.get("message", {}).get("content", "")

                            if content:
                                if is_reasoning_model:
                                    # Обрабатываем thinking блоки
                                    content = self._process_thinking_stream(
                                        content,
                                        in_thinking,
                                        thinking_buffer,
                                        full_response,
                                        on_token,
                                        on_thinking,
                                    )
                                    # Обновляем состояние
                                    if "<think>" in content:
                                        in_thinking = True
                                    if "</think>" in content:
                                        in_thinking = False
                                else:
                                    full_response.append(content)
                                    on_token(content)

                        except json.JSONDecodeError:
                            pass

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Не удалось подключиться к Ollama: {e.reason}")

        return "".join(full_response)

    def _process_thinking_stream(
        self,
        content: str,
        in_thinking: bool,
        thinking_buffer: List[str],
        full_response: List[str],
        on_token: TokenCallback,
        on_thinking: Optional[ThinkingCallback],
    ) -> str:
        """Обработать стрим с thinking блоками."""
        result = content

        # Начало thinking блока
        if "<think>" in content:
            parts = content.split("<think>", 1)
            if parts[0]:
                full_response.append(parts[0])
                on_token(parts[0])
            if len(parts) > 1:
                thinking_buffer.append(parts[1])
                if on_thinking:
                    on_thinking(parts[1])
            return result

        # Конец thinking блока
        if "</think>" in content:
            parts = content.split("</think>", 1)
            if parts[0]:
                thinking_buffer.append(parts[0])
                if on_thinking:
                    on_thinking(parts[0])
            if len(parts) > 1 and parts[1]:
                full_response.append(parts[1])
                on_token(parts[1])
            thinking_buffer.clear()
            return result

        # Внутри thinking блока
        if in_thinking:
            thinking_buffer.append(content)
            if on_thinking:
                on_thinking(content)
        else:
            full_response.append(content)
            on_token(content)

        return result

    def validate_api_key(self) -> bool:
        """
        Проверить подключение к Ollama.
        Ollama не использует API ключи, проверяем только доступность.
        """
        try:
            url = self._get_url("tags")
            self._make_request(url)
            return True
        except LLMConnectionError:
            return False
        except LLMError:
            return True

    def is_available(self) -> bool:
        """Проверить, доступен ли Ollama сервер."""
        return self.validate_api_key()
