"""
Базовые классы для LLM провайдеров.

Поддерживает:
- OpenAI, Anthropic, Google Gemini, Ollama, OpenRouter
- Reasoning/Thinking mode
- Динамическая загрузка моделей из API
"""

import codecs
import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any, Generator, Tuple, Union

logger = logging.getLogger(__name__)


def create_ssl_context() -> ssl.SSLContext:
    """
    Создать SSL контекст с поддержкой certifi.

    На Windows могут быть проблемы с SSL сертификатами,
    поэтому пробуем использовать certifi если доступен.
    """
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        logger.debug("Используем SSL контекст с certifi")
        return context
    except ImportError:
        # certifi не установлен, используем системные сертификаты
        logger.debug("certifi не найден, используем системные сертификаты")
        return ssl.create_default_context()
    except Exception as e:
        logger.warning(f"Ошибка создания SSL контекста с certifi: {e}")
        return ssl.create_default_context()


# Глобальный SSL контекст для всех провайдеров
_ssl_context: Optional[ssl.SSLContext] = None


def get_ssl_context() -> ssl.SSLContext:
    """Получить глобальный SSL контекст."""
    global _ssl_context
    if _ssl_context is None:
        _ssl_context = create_ssl_context()
    return _ssl_context


def urlopen_with_ssl(request: urllib.request.Request, timeout: int) -> Any:
    """
    Открыть URL с правильным SSL контекстом.

    Args:
        request: HTTP запрос
        timeout: Таймаут в секундах

    Returns:
        HTTP ответ
    """
    return urllib.request.urlopen(request, timeout=timeout, context=get_ssl_context())


class ReasoningEffort(Enum):
    """Уровень усилий для reasoning mode."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ReasoningConfig:
    """Конфигурация reasoning/thinking mode."""
    enabled: bool = False
    effort: ReasoningEffort = ReasoningEffort.MEDIUM
    budget_tokens: int = 10000  # Для Anthropic/Gemini

    def to_dict(self) -> Dict[str, Any]:
        """Конвертировать в словарь для API."""
        return {
            "enabled": self.enabled,
            "effort": self.effort.value,
            "budget_tokens": self.budget_tokens,
        }


@dataclass
class LLMModel:
    """Информация о модели LLM."""
    id: str
    name: str
    provider: str
    context_length: int = 4096
    supports_reasoning: bool = False
    reasoning_type: Optional[str] = None  # "effort", "thinking", "budget"
    description: str = ""
    pricing_input: float = 0.0  # $ за 1M токенов
    pricing_output: float = 0.0

    @property
    def display_name(self) -> str:
        """Имя для отображения в UI."""
        ctx = f"{self.context_length // 1000}K" if self.context_length >= 1000 else str(self.context_length)
        reasoning_badge = " 🧠" if self.supports_reasoning else ""
        return f"{self.name} ({ctx}){reasoning_badge}"

    @property
    def short_id(self) -> str:
        """Короткий ID без префикса провайдера."""
        if "/" in self.id:
            return self.id.split("/")[-1]
        return self.id


class LLMError(Exception):
    """Базовая ошибка LLM провайдера."""
    pass


class LLMAuthError(LLMError):
    """Ошибка авторизации (неверный API ключ)."""
    pass


class LLMRateLimitError(LLMError):
    """Превышен лимит запросов."""
    pass


class LLMConnectionError(LLMError):
    """Ошибка подключения к API."""
    pass


class LLMInvalidModelError(LLMError):
    """Неверная модель."""
    pass


# Тип для callback'а при стриминге
TokenCallback = Callable[[str], None]
ThinkingCallback = Callable[[str], None]


class LLMProvider(ABC):
    """
    Абстрактный базовый класс для LLM провайдеров.

    Все провайдеры должны реализовать:
    - fetch_models() - загрузка списка моделей из API
    - complete() - генерация ответа
    - stream() - потоковая генерация
    - validate_api_key() - проверка API ключа
    """

    # Имя провайдера для отображения
    PROVIDER_NAME: str = "Unknown"

    # TTL кэша моделей в секундах (1 час)
    MODEL_CACHE_TTL: int = 3600

    def __init__(self, api_key: str = "", base_url: str = "", timeout: int = 180):
        """
        Args:
            api_key: API ключ (не требуется для Ollama)
            base_url: Базовый URL API (для Ollama или custom endpoints)
            timeout: Таймаут запросов в секундах
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

        # Кэш моделей
        self._cached_models: Optional[List[LLMModel]] = None
        self._cache_time: float = 0

    def _cache_expired(self) -> bool:
        """Проверить, истёк ли кэш моделей."""
        return time.time() - self._cache_time > self.MODEL_CACHE_TTL

    def fetch_models(self, force_refresh: bool = False) -> List[LLMModel]:
        """
        Получить список доступных моделей.

        Args:
            force_refresh: Принудительно обновить кэш

        Returns:
            Список моделей
        """
        if self._cached_models and not force_refresh and not self._cache_expired():
            return self._cached_models

        logger.info(f"Загрузка моделей от {self.PROVIDER_NAME}...")
        models = self._fetch_models_from_api()

        self._cached_models = models
        self._cache_time = time.time()

        logger.info(f"Загружено {len(models)} моделей от {self.PROVIDER_NAME}")
        return models

    @abstractmethod
    def _fetch_models_from_api(self) -> List[LLMModel]:
        """
        Загрузить модели из API провайдера.
        Должен быть реализован в каждом провайдере.
        """
        pass

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """
        Сгенерировать ответ (без стриминга).

        Args:
            messages: Список сообщений [{role: "user", content: "..."}]
            model: ID модели
            reasoning: Конфигурация reasoning mode
            max_tokens: Максимальное количество токенов в ответе
            temperature: Температура генерации

        Returns:
            Сгенерированный текст
        """
        pass

    @abstractmethod
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

        Args:
            messages: Список сообщений
            model: ID модели
            on_token: Callback для каждого токена
            reasoning: Конфигурация reasoning mode
            on_thinking: Callback для thinking блоков (если поддерживается)
            max_tokens: Максимальное количество токенов
            temperature: Температура генерации

        Returns:
            Полный сгенерированный текст
        """
        pass

    @abstractmethod
    def validate_api_key(self) -> bool:
        """
        Проверить валидность API ключа.

        Returns:
            True если ключ валиден
        """
        pass

    def supports_reasoning(self, model: str) -> bool:
        """
        Проверить, поддерживает ли модель reasoning mode.

        Args:
            model: ID модели

        Returns:
            True если поддерживает
        """
        models = self.fetch_models()
        for m in models:
            if m.id == model:
                return m.supports_reasoning
        return False

    def get_model_info(self, model: str) -> Optional[LLMModel]:
        """
        Получить информацию о модели.

        Args:
            model: ID модели

        Returns:
            LLMModel или None если не найдена
        """
        models = self.fetch_models()
        for m in models:
            if m.id == model:
                return m
        return None

    # =========================================================================
    # HTTP и SSE утилиты (общие для всех провайдеров)
    # =========================================================================

    def _get_headers(self) -> Dict[str, str]:
        """
        Получить HTTP заголовки для запроса.
        Переопределить в провайдере для кастомных заголовков.
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        stream: bool = False,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Выполнить HTTP запрос к API.

        Args:
            url: URL для запроса
            method: HTTP метод
            data: Данные для отправки (будут сериализованы в JSON)
            stream: Если True, возвращает response объект для стриминга
            extra_headers: Дополнительные заголовки

        Returns:
            JSON ответ или response объект (если stream=True)

        Raises:
            LLMError: При ошибке запроса
        """
        headers = self._get_headers()
        if extra_headers:
            headers.update(extra_headers)

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
            raise LLMConnectionError(f"Ошибка подключения к {self.PROVIDER_NAME}: {e.reason}")

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """
        Обработать HTTP ошибку.
        Переопределить в провайдере для специфичной обработки (например, 402).

        Args:
            status_code: HTTP код ответа
            body: Тело ответа

        Raises:
            LLMAuthError: При 401
            LLMRateLimitError: При 429
            LLMInvalidModelError: При 404
            LLMError: При других ошибках
        """
        try:
            error_data = json.loads(body)
            message = error_data.get("error", {}).get("message", body)
        except json.JSONDecodeError:
            message = body

        if status_code == 401:
            raise LLMAuthError(f"Неверный API ключ {self.PROVIDER_NAME}: {message}")
        elif status_code == 429:
            raise LLMRateLimitError(f"Превышен лимит запросов {self.PROVIDER_NAME}: {message}")
        elif status_code == 404:
            raise LLMInvalidModelError(f"Модель не найдена: {message}")
        else:
            raise LLMError(f"Ошибка {self.PROVIDER_NAME} API ({status_code}): {message}")

    @staticmethod
    def _extract_nested(data: Dict, path: Tuple[Union[str, int], ...]) -> Optional[str]:
        """
        Извлечь значение из вложенной структуры по пути.

        Args:
            data: Словарь с данными
            path: Кортеж ключей/индексов, например ("choices", 0, "delta", "content")

        Returns:
            Извлечённое значение или None
        """
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and isinstance(key, int):
                if 0 <= key < len(current):
                    current = current[key]
                else:
                    return None
            else:
                return None
            if current is None:
                return None
        return current if isinstance(current, str) else None

    def _parse_sse_stream(
        self,
        response,
        on_token: "TokenCallback",
        content_path: Tuple[Union[str, int], ...] = ("choices", 0, "delta", "content"),
    ) -> str:
        """
        Парсинг SSE потока. Общий для OpenAI-совместимых провайдеров.

        Args:
            response: HTTP response объект
            on_token: Callback для каждого токена
            content_path: Путь к content в JSON (по умолчанию OpenAI формат)

        Returns:
            Полный текст ответа
        """
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
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            continue

                        try:
                            data = json.loads(data_str)
                            content = self._extract_nested(data, content_path)
                            if content:
                                full_response.append(content)
                                on_token(content)
                        except json.JSONDecodeError:
                            pass

        return "".join(full_response)


# Утилиты для парсинга ответов

def parse_thinking_blocks(text: str) -> tuple[str, str]:
    """
    Разделить текст на thinking и content части.

    Поддерживает форматы:
    - <think>...</think>
    - <thinking>...</thinking>

    Args:
        text: Полный текст ответа

    Returns:
        (thinking_text, content_text)
    """
    import re

    thinking = ""
    content = text

    # Паттерны для thinking блоков
    patterns = [
        r'<think>(.*?)</think>',
        r'<thinking>(.*?)</thinking>',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            thinking = "\n".join(matches)
            content = re.sub(pattern, "", text, flags=re.DOTALL).strip()
            break

    return thinking, content
