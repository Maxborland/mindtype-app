"""
Базовые абстрактные классы для платформо-зависимого кода.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from PyQt6.QtCore import QObject


class BaseHotkeyListener(QObject):
    """Базовый класс для слушателя глобальных хоткеев."""

    def __init__(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> None:
        super().__init__()
        self.combo = combo
        self._handler = handler
        self._on_press = on_press
        self._on_release = on_release
        self._push_to_talk = push_to_talk

    def start(self) -> None:
        """Начать слушать хоткей."""
        raise NotImplementedError

    def stop(self) -> None:
        """Остановить слушатель."""
        raise NotImplementedError


class BaseHotkeyRecorder(QObject):
    """Базовый класс для записи новых хоткеев."""

    def __init__(self, on_recorded: Callable[[str], None]) -> None:
        super().__init__()
        self._on_recorded = on_recorded

    def start(self) -> None:
        """Начать запись хоткея."""
        raise NotImplementedError

    def stop(self) -> None:
        """Остановить запись."""
        raise NotImplementedError


class BaseWindowManager(ABC):
    """Базовый класс для управления окнами."""

    def __init__(self) -> None:
        self._saved_window = None
        self._saved_title: str = ""
        self._our_window = None

    def set_our_window(self, window_handle) -> None:
        """Установить handle нашего окна приложения."""
        self._our_window = window_handle

    @abstractmethod
    def get_foreground_window(self):
        """Получить активное окно."""
        pass

    @abstractmethod
    def get_window_title(self, window) -> str:
        """Получить заголовок окна."""
        pass

    @abstractmethod
    def set_foreground_window(self, window) -> bool:
        """Установить окно на передний план."""
        pass

    @abstractmethod
    def minimize_window(self, window) -> bool:
        """Минимизировать окно."""
        pass

    def save_current_window(self) -> None:
        """Сохранить текущее активное окно."""
        self._saved_window = self.get_foreground_window()
        self._saved_title = self.get_window_title(self._saved_window)

    def restore_window(self) -> bool:
        """Вернуть фокус на сохранённое окно."""
        if not self._saved_window:
            return False

        # Сначала минимизируем наше окно
        if self._our_window:
            self.minimize_window(self._our_window)

        return self.set_foreground_window(self._saved_window)

    def restore_window_soft(self) -> bool:
        """Мягкое восстановление - только минимизируем наше окно."""
        if self._our_window:
            self.minimize_window(self._our_window)
            return True
        return False

    @property
    def saved_window_title(self) -> str:
        return self._saved_title

    @property
    def has_saved_window(self) -> bool:
        return self._saved_window is not None


class BaseTextInserter(ABC):
    """Базовый класс для вставки текста."""

    def __init__(self, window_manager: BaseWindowManager) -> None:
        self._window_manager = window_manager

    @abstractmethod
    def insert_text(self, text: str, delay: float = 0.1) -> bool:
        """
        Вставить текст в активное окно.

        Args:
            text: Текст для вставки
            delay: Задержка после вставки

        Returns:
            True если успешно
        """
        pass

    @abstractmethod
    def type_text(self, text: str) -> bool:
        """
        Напечатать текст посимвольно.

        Args:
            text: Текст для ввода

        Returns:
            True если успешно
        """
        pass


class BasePlatform(ABC):
    """Базовый класс платформы."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Название платформы."""
        pass

    @abstractmethod
    def create_hotkey_listener(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> BaseHotkeyListener:
        """Создать слушатель хоткеев."""
        pass

    @abstractmethod
    def create_hotkey_recorder(
        self,
        on_recorded: Callable[[str], None],
    ) -> BaseHotkeyRecorder:
        """Создать записыватель хоткеев."""
        pass

    @abstractmethod
    def create_window_manager(self) -> BaseWindowManager:
        """Создать менеджер окон."""
        pass

    @abstractmethod
    def create_text_inserter(self) -> BaseTextInserter:
        """Создать инструмент вставки текста."""
        pass


