"""
Ollama API клиент для локальных LLM.

Поддержка:
- Получение списка моделей
- Streaming генерация
- Chat completions
"""

import json
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


@dataclass
class OllamaModel:
    """Информация о модели Ollama."""
    name: str
    size: int
    modified: str

    @property
    def display_name(self) -> str:
        """Имя для отображения в UI."""
        # Форматируем размер
        size_gb = self.size / (1024 ** 3)
        return f"{self.name} ({size_gb:.1f} GB)"


class OllamaError(Exception):
    """Базовая ошибка Ollama."""
    pass


class OllamaConnectionError(OllamaError):
    """Ошибка подключения к Ollama."""
    pass


class OllamaClient:
    """Клиент для работы с Ollama API."""

    def __init__(self, base_url: str = "http://localhost:11434", timeout: int = 120):
        """
        Args:
            base_url: URL Ollama сервера
            timeout: Таймаут запросов в секундах
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cached_models: Optional[List[OllamaModel]] = None

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None,
    ) -> any:
        """Выполнить HTTP запрос к Ollama API."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}

        req_data = json.dumps(data).encode() if data else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
            return json.loads(response.read().decode())
        except urllib.error.URLError as e:
            raise OllamaConnectionError(f"Не удалось подключиться к Ollama: {e.reason}")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise OllamaError(f"Ошибка Ollama API ({e.code}): {error_body}")

    def list_models(self, force_refresh: bool = False) -> List[OllamaModel]:
        """
        Получить список локальных моделей.

        Args:
            force_refresh: Принудительно обновить кэш

        Returns:
            Список моделей
        """
        if self._cached_models and not force_refresh:
            return self._cached_models

        logger.info("Загрузка списка моделей Ollama...")
        try:
            response = self._make_request("/api/tags")

            models = []
            for model_data in response.get("models", []):
                model = OllamaModel(
                    name=model_data.get("name", ""),
                    size=model_data.get("size", 0),
                    modified=model_data.get("modified_at", ""),
                )
                models.append(model)

            self._cached_models = models
            logger.info(f"Загружено {len(models)} моделей Ollama")
            return models

        except OllamaConnectionError as e:
            logger.error(f"Ollama недоступен: {e}")
            return []
        except Exception as e:
            logger.error(f"Ошибка получения списка моделей: {e}")
            return []

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        stream: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Генерация ответа через chat completion.

        Args:
            messages: Список сообщений [{"role": "user", "content": "..."}]
            model: Название модели
            stream: Использовать streaming
            on_token: Колбэк для каждого токена (только при stream=True)

        Returns:
            Сгенерированный текст
        """
        data = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        if stream and on_token:
            return self._stream_completion(data, on_token)
        else:
            response = self._make_request("/api/chat", method="POST", data=data)
            return response.get("message", {}).get("content", "")

    def _stream_completion(
        self,
        data: Dict,
        on_token: Callable[[str], None],
    ) -> str:
        """Streaming генерация с колбэком для токенов."""
        url = f"{self.base_url}/api/chat"
        headers = {"Content-Type": "application/json"}

        req_data = json.dumps(data).encode()
        request = urllib.request.Request(url, data=req_data, headers=headers, method="POST")

        full_response = []

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                for line in response:
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line.decode())

                        # Проверяем, не завершён ли стрим
                        if chunk.get("done", False):
                            break

                        # Извлекаем контент
                        message = chunk.get("message", {})
                        content = message.get("content", "")

                        if content:
                            full_response.append(content)
                            on_token(content)

                    except json.JSONDecodeError:
                        continue

        except urllib.error.URLError as e:
            raise OllamaConnectionError(f"Ошибка подключения: {e.reason}")
        except Exception as e:
            raise OllamaError(f"Ошибка streaming: {e}")

        return "".join(full_response)

    def generate(
        self,
        prompt: str,
        model: str,
        system: Optional[str] = None,
    ) -> str:
        """
        Простая генерация текста.

        Args:
            prompt: Промпт
            model: Название модели
            system: Системный промпт (опционально)

        Returns:
            Сгенерированный текст
        """
        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        if system:
            data["system"] = system

        response = self._make_request("/api/generate", method="POST", data=data)
        return response.get("response", "")

    def is_available(self) -> bool:
        """Проверить доступность Ollama."""
        try:
            self._make_request("/api/tags")
            return True
        except Exception:
            return False

    def pull_model(self, model_name: str) -> bool:
        """
        Загрузить модель (если её нет).

        Args:
            model_name: Название модели

        Returns:
            True если успешно
        """
        try:
            data = {"name": model_name}
            self._make_request("/api/pull", method="POST", data=data)
            logger.info(f"Модель {model_name} загружена")
            return True
        except Exception as e:
            logger.error(f"Ошибка загрузки модели: {e}")
            return False


# Рекомендуемые модели для голосового ассистента
RECOMMENDED_MODELS = [
    "llama3.2:3b",        # Быстрая, легкая
    "llama3.2:1b",        # Очень быстрая
    "phi3:3.8b",          # Хорошее качество/скорость
    "gemma2:2b",          # Компактная от Google
    "qwen2.5:3b",         # Хорошо работает с русским
    "mistral:7b",         # Качественная, медленнее
]


