"""
MindType Cloud LLM Provider.

Прокси-провайдер через MindType Gateway с системой кредитов.
Авторизация выполняется только короткоживущей cloud session.
"""

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Union

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
        from ..env import API_BASE_URL
        return API_BASE_URL.rstrip("/") + endpoint
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

    Perpetual license key никогда не используется как bearer credential.
    """

    PROVIDER_NAME = "MindType Cloud"

    def __init__(
        self,
        access_token: Union[str, Callable[[], Optional[str]]],
        *,
        refresh_access_token: Optional[
            Callable[[Optional[str]], None]
        ] = None,
        timeout: int = 180,
    ):
        """
        Args:
            access_token: Короткоживущий токен или in-memory token source
            refresh_access_token: Callback обновления cloud session
            timeout: Таймаут запросов в секундах
        """
        super().__init__(api_key="", timeout=timeout)
        self._access_token = access_token
        self._refresh_access_token = refresh_access_token
        self._credits_balance: Optional[int] = None

    def _token(self) -> str:
        token = (
            self._access_token()
            if callable(self._access_token)
            else self._access_token
        )
        if not token and self._refresh_access_token is not None:
            self._refresh_access_token(None)
            token = (
                self._access_token()
                if callable(self._access_token)
                else self._access_token
            )
        if not token:
            raise LLMAuthError("MindType Cloud session is required")
        return token

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

        body = json.dumps(data).encode("utf-8") if data else None
        for attempt in range(2):
            request_token = self._token()
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {request_token}",
                },
                method=method,
            )
            try:
                response = urlopen_with_ssl(request, timeout=self.timeout)
                return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if (
                    error.code == 401
                    and attempt == 0
                    and self._refresh_access_token is not None
                ):
                    self._refresh_access_token(request_token)
                    continue
                self._raise_http_error(error)
            except urllib.error.URLError as error:
                raise LLMConnectionError(
                    f"Connection error: {error.reason}"
                )
            except (
                LLMAuthError,
                LLMNoCreditsError,
                LLMRateLimitError,
            ):
                raise
            except Exception as error:
                raise LLMError(f"Request failed: {error}")
        raise LLMAuthError("MindType Cloud session refresh failed")

    @staticmethod
    def _raise_http_error(error: urllib.error.HTTPError) -> None:
        try:
            error_body = json.loads(error.read().decode("utf-8"))
            raw_error = error_body.get("error")
            details = raw_error if isinstance(raw_error, dict) else {}
            error_code = str(
                details.get("code")
                or raw_error
                or f"HTTP_{error.code}"
            )
            error_message = str(
                details.get("message")
                or error_body.get("message")
                or error_code
            )
        except Exception:
            error_body = {}
            error_code = f"HTTP_{error.code}"
            error_message = str(error)

        if error.code == 401:
            raise LLMAuthError(error_message)
        if error.code == 402:
            raise LLMNoCreditsError(
                credits_remaining=int(
                    error_body.get("creditsRemaining", 0)
                ),
                buy_url=str(
                    error_body.get(
                        "buyUrl",
                        "https://mindtype.space/buy-credits",
                    )
                ),
            )
        if error.code == 429:
            raise LLMRateLimitError(error_message)
        raise LLMError(f"{error_code}: {error_message}")

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
        response = self._make_request("GET", "/v1/usage")

        self._credits_balance = int(
            response.get("balance_microunits", 0)
        )

        return CreditsInfo(
            credits=self._credits_balance,
            history=response.get("ledger", []),
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
