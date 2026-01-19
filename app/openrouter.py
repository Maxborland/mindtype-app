"""
OpenRouter API клиент для облачной саммаризации.

Поддерживает:
- Получение списка моделей
- Streaming генерация
- Обработка ошибок
"""

import json
import logging
from dataclasses import dataclass
from typing import Callable, Dict, Generator, List, Optional, Any
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# API endpoints
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODELS_ENDPOINT = f"{OPENROUTER_BASE_URL}/models"
CHAT_ENDPOINT = f"{OPENROUTER_BASE_URL}/chat/completions"


@dataclass
class OpenRouterModel:
    """Информация о модели OpenRouter."""
    id: str
    name: str
    context_length: int
    pricing_input: float  # $ за 1M токенов
    pricing_output: float
    description: str = ""

    @property
    def display_name(self) -> str:
        """Имя для отображения в UI."""
        # Убираем префикс провайдера для краткости
        short_name = self.id.split("/")[-1] if "/" in self.id else self.id
        price_str = f"${self.pricing_input:.2f}/{self.pricing_output:.2f}"
        return f"{short_name} ({price_str})"

    @property
    def full_display_name(self) -> str:
        """Полное имя с провайдером."""
        price_str = f"${self.pricing_input:.2f} in / ${self.pricing_output:.2f} out"
        return f"{self.name} — {price_str}"


class OpenRouterError(Exception):
    """Базовая ошибка OpenRouter."""
    pass


class OpenRouterAuthError(OpenRouterError):
    """Ошибка авторизации (неверный API ключ)."""
    pass


class OpenRouterRateLimitError(OpenRouterError):
    """Превышен лимит запросов."""
    pass


class OpenRouterInsufficientCreditsError(OpenRouterError):
    """Недостаточно средств на балансе."""
    pass


class OpenRouterClient:
    """Клиент для работы с OpenRouter API."""

    def __init__(self, api_key: str, timeout: int = 180):
        """
        Args:
            api_key: API ключ OpenRouter
            timeout: Таймаут запросов в секундах (180 для reasoning mode)
        """
        self.api_key = api_key
        self.timeout = timeout
        self._cached_models: Optional[List[OpenRouterModel]] = None

    def _make_request(
        self,
        url: str,
        method: str = "GET",
        data: Optional[Dict] = None,
        stream: bool = False,
    ) -> Any:
        """Выполнить HTTP запрос к API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mindtype.app",
            "X-Title": "MindType",
        }

        req_data = json.dumps(data).encode() if data else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
            if stream:
                return response  # Вернуть открытый поток
            return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise OpenRouterError(f"Ошибка сети: {e.reason}")

    def _handle_http_error(self, status_code: int, body: str) -> None:
        """Обработать HTTP ошибку."""
        try:
            error_data = json.loads(body)
            message = error_data.get("error", {}).get("message", body)
        except json.JSONDecodeError:
            message = body

        if status_code == 401:
            raise OpenRouterAuthError(f"Неверный API ключ: {message}")
        elif status_code == 402:
            raise OpenRouterInsufficientCreditsError(f"Недостаточно средств: {message}")
        elif status_code == 429:
            raise OpenRouterRateLimitError(f"Превышен лимит запросов: {message}")
        else:
            raise OpenRouterError(f"Ошибка API ({status_code}): {message}")

    def fetch_models(self, force_refresh: bool = False) -> List[OpenRouterModel]:
        """
        Получить список доступных моделей.

        Args:
            force_refresh: Принудительно обновить кэш

        Returns:
            Список моделей, отсортированных по цене
        """
        if self._cached_models and not force_refresh:
            return self._cached_models

        logger.info("Загрузка списка моделей OpenRouter...")
        response = self._make_request(MODELS_ENDPOINT)

        models = []
        for item in response.get("data", []):
            # Пропускаем модели без pricing или не для chat
            pricing = item.get("pricing", {})
            if not pricing:
                continue

            # Парсим цену (приходит в строках как "0.00025" за токен)
            try:
                # Цена за токен -> цена за 1M токенов
                price_in = float(pricing.get("prompt", "0")) * 1_000_000
                price_out = float(pricing.get("completion", "0")) * 1_000_000
            except (ValueError, TypeError):
                continue

            model = OpenRouterModel(
                id=item.get("id", ""),
                name=item.get("name", item.get("id", "")),
                context_length=item.get("context_length", 4096),
                pricing_input=price_in,
                pricing_output=price_out,
                description=item.get("description", ""),
            )
            models.append(model)

        # Сортируем по средней цене
        models.sort(key=lambda m: (m.pricing_input + m.pricing_output) / 2)

        self._cached_models = models
        logger.info(f"Загружено {len(models)} моделей")
        return models

    def get_recommended_models(self) -> List[OpenRouterModel]:
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
        ]

        # Фильтруем доступные
        recommended = []
        for model_id in recommended_ids:
            for model in all_models:
                if model.id == model_id:
                    recommended.append(model)
                    break

        return recommended

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int = 8096,
        temperature: float = 0.7,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
        reasoning: bool = False,
        reasoning_effort: str = "medium",  # low / medium / high
    ) -> str:
        """
        Генерация ответа через chat completion.

        Args:
            messages: Список сообщений [{"role": "user", "content": "..."}]
            model: ID модели
            max_tokens: Максимум токенов в ответе
            temperature: Температура генерации
            stream: Использовать streaming
            on_token: Колбэк для каждого токена (только при stream=True)
            reasoning: Включить режим размышлений (extended thinking)
            reasoning_effort: Глубина размышлений (low/medium/high)

        Returns:
            Сгенерированный текст
        """
        data = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        # Добавляем reasoning если включён
        if reasoning:
            data["reasoning"] = {"effort": reasoning_effort}

        if stream and on_token:
            return self._stream_completion(data, on_token)
        else:
            response = self._make_request(CHAT_ENDPOINT, method="POST", data=data)
            return response["choices"][0]["message"]["content"]

    def _stream_completion(
        self,
        data: Dict,
        on_token: Callable[[str], None],
    ) -> str:
        """Streaming генерация с колбэком для токенов."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mindtype.app",
            "X-Title": "MindType",
        }

        req_data = json.dumps(data).encode()
        request = urllib.request.Request(
            CHAT_ENDPOINT,
            data=req_data,
            headers=headers,
            method="POST"
        )

        full_response = []

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                buffer = ""
                for chunk in self._read_chunks(response):
                    buffer += chunk

                    # Парсим SSE события
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)

                        for line in event.split("\n"):
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str.strip() == "[DONE]":
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
            error_body = e.read().decode() if e.fp else ""
            self._handle_http_error(e.code, error_body)
        except urllib.error.URLError as e:
            raise OpenRouterError(f"Ошибка сети: {e.reason}")

        return "".join(full_response)

    def _read_chunks(self, response, chunk_size: int = 1024) -> Generator[str, None, None]:
        """Читать ответ по частям с корректным декодированием UTF-8."""
        import codecs
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                # Финализируем декодер для получения оставшихся символов
                final = decoder.decode(b"", final=True)
                if final:
                    yield final
                break
            yield decoder.decode(chunk)

    def validate_api_key(self) -> bool:
        """Проверить валидность API ключа."""
        try:
            self.fetch_models(force_refresh=True)
            return True
        except OpenRouterAuthError:
            return False
        except OpenRouterError:
            # Другие ошибки могут быть временными
            return True


def get_balance(api_key: str) -> Optional[float]:
    """
    Получить баланс аккаунта (если доступно).

    Note: OpenRouter не предоставляет прямой API для баланса,
    но возвращает информацию в headers при ошибке 402.
    """
    # TODO: OpenRouter пока не имеет публичного API для баланса
    return None

