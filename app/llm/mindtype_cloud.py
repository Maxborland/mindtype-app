"""
MindType Cloud LLM Provider.

Прокси-провайдер через MindType Gateway с системой кредитов.
Клиентам нужен только лицензионный ключ, не API ключи.
"""

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Dict, List, Optional, Generator

from .base import (
    LLMProvider,
    LLMModel,
    LLMError,
    LLMAuthError,
    LLMRateLimitError,
    LLMConnectionError,
    ReasoningConfig,
    TokenCallback,
    ThinkingCallback,
    urlopen_with_ssl,
)

logger = logging.getLogger(__name__)


# API URL - переопределяется из env.py
def get_api_url(endpoint: str = "") -> str:
    """Get the MindType API base URL."""
    try:
        from ..env import API_URL
        return API_URL + endpoint
    except ImportError:
        return "https://mindtype.space" + endpoint


class LLMNoCreditsError(LLMError):
    """Недостаточно кредитов для запроса."""

    def __init__(self, credits_remaining: int = 0, buy_url: str = ""):
        super().__init__("No credits remaining")
        self.credits_remaining = credits_remaining
        self.buy_url = buy_url


@dataclass
class CreditsInfo:
    """Информация о балансе кредитов."""

    credits: int
    history: List[Dict] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []


class MindTypeCloudProvider(LLMProvider):
    """
    Провайдер через MindType Gateway с кредитами.

    Использует лицензионный ключ вместо API ключа.
    Кредиты списываются за каждую уникальную встречу.
    """

    PROVIDER_NAME = "MindType Cloud"

    def __init__(self, license_key: str = "", timeout: int = 180):
        """
        Args:
            license_key: Лицензионный ключ MindType
            timeout: Таймаут запросов в секундах
        """
        super().__init__(api_key=license_key, timeout=timeout)
        self.license_key = license_key
        self._credits_balance: Optional[int] = None

    @property
    def credits_balance(self) -> Optional[int]:
        """Текущий баланс кредитов (кэшированный)."""
        return self._credits_balance

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
    ) -> Dict:
        """
        Выполнить HTTP запрос к MindType API.

        Args:
            method: HTTP метод (GET, POST)
            endpoint: Эндпоинт API (например, /api/llm/complete)
            data: Тело запроса для POST

        Returns:
            Ответ API как словарь

        Raises:
            LLMAuthError: Неверный лицензионный ключ
            LLMNoCreditsError: Недостаточно кредитов
            LLMRateLimitError: Превышен лимит запросов
            LLMConnectionError: Ошибка подключения
            LLMError: Другие ошибки
        """
        url = get_api_url(endpoint)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.license_key}",
        }

        body = json.dumps(data).encode("utf-8") if data else None

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            response = urlopen_with_ssl(request, timeout=self.timeout)
            response_data = json.loads(response.read().decode("utf-8"))
            return response_data

        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode("utf-8"))
                error_code = error_body.get("error", "")
                error_message = error_body.get("message", str(e))
            except Exception:
                error_code = ""
                error_message = str(e)

            if e.code == 401:
                raise LLMAuthError(error_message)
            elif e.code == 402:
                # No credits
                raise LLMNoCreditsError(
                    credits_remaining=error_body.get("creditsRemaining", 0),
                    buy_url=error_body.get("buyUrl", "https://mindtype.space/buy-credits"),
                )
            elif e.code == 429:
                raise LLMRateLimitError(error_message)
            else:
                raise LLMError(f"{error_code}: {error_message}")

        except urllib.error.URLError as e:
            raise LLMConnectionError(f"Connection error: {e.reason}")

        except Exception as e:
            raise LLMError(f"Request failed: {e}")

    def _fetch_models_from_api(self) -> List[LLMModel]:
        """
        Возвращает список доступных моделей.

        MindType Cloud использует автоматический выбор модели,
        поэтому возвращаем только одну "auto" модель.
        """
        return [
            LLMModel(
                id="auto",
                name="Auto (Recommended)",
                provider="mindtype",
                context_length=128000,
                supports_reasoning=False,
                description="Automatic model selection by MindType Cloud",
            )
        ]

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "auto",
        reasoning: Optional[ReasoningConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        task: str = "general",
        meeting_id: Optional[str] = None,
    ) -> str:
        """
        Сгенерировать ответ через MindType Cloud.

        Args:
            messages: Список сообщений
            model: ID модели (игнорируется, используется auto)
            reasoning: Конфигурация reasoning (не поддерживается в Cloud)
            max_tokens: Максимальное количество токенов
            temperature: Температура генерации
            task: Тип задачи (summarize, extract, aggregate, general)
            meeting_id: UUID встречи для группировки (1 кредит на встречу)

        Returns:
            Сгенерированный текст
        """
        data = {
            "messages": messages,
            "task": task,
            "maxTokens": max_tokens,
            "temperature": temperature,
        }

        if meeting_id:
            data["meetingId"] = meeting_id

        response = self._make_request("POST", "/api/llm/complete", data)

        # Обновляем кэшированный баланс
        if "creditsRemaining" in response:
            self._credits_balance = response["creditsRemaining"]

        return response.get("content", "")

    def stream(
        self,
        messages: List[Dict[str, str]],
        model: str = "auto",
        on_token: Optional[TokenCallback] = None,
        reasoning: Optional[ReasoningConfig] = None,
        on_thinking: Optional[ThinkingCallback] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        task: str = "general",
        meeting_id: Optional[str] = None,
    ) -> str:
        """
        MindType Cloud не поддерживает стриминг.
        Вызывает complete() и возвращает результат.
        """
        result = self.complete(
            messages=messages,
            model=model,
            reasoning=reasoning,
            max_tokens=max_tokens,
            temperature=temperature,
            task=task,
            meeting_id=meeting_id,
        )

        # Эмулируем стриминг - отправляем весь результат сразу
        if on_token:
            on_token(result)

        return result

    def validate_api_key(self) -> bool:
        """
        Проверить валидность лицензионного ключа.

        Returns:
            True если ключ валиден
        """
        try:
            self.get_balance()
            return True
        except LLMAuthError:
            return False
        except Exception as e:
            logger.warning(f"License validation error: {e}")
            return False

    def get_balance(self) -> CreditsInfo:
        """
        Получить баланс кредитов.

        Returns:
            CreditsInfo с балансом и историей

        Raises:
            LLMAuthError: Неверный лицензионный ключ
        """
        response = self._make_request("GET", "/api/credits/balance")

        self._credits_balance = response.get("credits", 0)

        return CreditsInfo(
            credits=self._credits_balance,
            history=response.get("history", []),
        )

    def has_credits(self) -> bool:
        """
        Проверить, есть ли кредиты.

        Использует кэшированное значение если доступно,
        иначе делает запрос к API.
        """
        if self._credits_balance is not None:
            return self._credits_balance > 0

        try:
            info = self.get_balance()
            return info.credits > 0
        except Exception:
            return False

    def refresh_balance(self) -> int:
        """
        Обновить баланс кредитов.

        Returns:
            Текущий баланс кредитов
        """
        info = self.get_balance()
        return info.credits
