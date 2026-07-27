"""
Кросс-платформенная вставка текста в активное окно.
Автоматически выбирает реализацию в зависимости от ОС.
"""

import sys
from typing import Optional

from .insertion import (
    InsertionFailure,
    InsertionMethod,
    InsertionResult,
)

# Выбираем реализацию в зависимости от платформы
if sys.platform == "win32":
    from .platform.windows import WindowsWindowManager, WindowsTextInserter

    # Создаём глобальные экземпляры
    _window_manager = WindowsWindowManager()
    _text_inserter = WindowsTextInserter(_window_manager)

elif sys.platform == "darwin":
    from .platform.macos import MacOSWindowManager, MacOSTextInserter

    _window_manager = MacOSWindowManager()
    _text_inserter = MacOSTextInserter(_window_manager)

else:
    from .platform.linux import LinuxWindowManager, LinuxTextInserter

    _window_manager = LinuxWindowManager()
    _text_inserter = LinuxTextInserter(_window_manager)


class WindowFocusManager:
    """
    Менеджер фокуса окон.
    Обёртка над платформо-зависимым менеджером для совместимости.
    """

    def __init__(self) -> None:
        self._manager = _window_manager

    def set_our_window(self, hwnd) -> None:
        """Установить handle нашего окна приложения."""
        self._manager.set_our_window(hwnd)

    def save_current_window(self) -> None:
        """Сохранить текущее активное окно."""
        self._manager.save_current_window()

    def restore_window(self) -> bool:
        """Вернуть фокус на сохранённое окно."""
        return self._manager.restore_window()

    def restore_window_soft(self) -> bool:
        """Мягкое восстановление - только минимизируем наше окно."""
        return self._manager.restore_window_soft()

    @property
    def saved_window_title(self) -> str:
        return self._manager.saved_window_title

    @property
    def has_saved_window(self) -> bool:
        return self._manager.has_saved_window


# Глобальный менеджер фокуса
focus_manager = WindowFocusManager()


def insert_text(text: str, delay: float = 0.1) -> bool:
    """
    Вставить текст в активное окно.

    Если было сохранено окно через focus_manager, сначала вернёт на него фокус.

    Args:
        text: Текст для вставки
        delay: Задержка после вставки

    Returns:
        True если успешно
    """
    return _text_inserter.insert_text(text, delay)


def insert_text_result(text: str, delay: float = 0.1) -> InsertionResult:
    """Insert text and retain a typed diagnostic result where supported."""
    detailed = getattr(_text_inserter, "insert_text_result", None)
    if callable(detailed):
        return detailed(text, delay)
    if _text_inserter.insert_text(text, delay):
        return InsertionResult.ok(
            InsertionMethod.CLIPBOARD,
            attempted=(InsertionMethod.CLIPBOARD,),
        )
    return InsertionResult.failed(InsertionFailure.ALL_METHODS_FAILED)


def type_text(text: str) -> bool:
    """
    Напечатать текст посимвольно.

    Args:
        text: Текст для ввода

    Returns:
        True если успешно
    """
    return _text_inserter.type_text(text)


__all__ = [
    "focus_manager",
    "insert_text",
    "insert_text_result",
    "type_text",
    "WindowFocusManager",
]
