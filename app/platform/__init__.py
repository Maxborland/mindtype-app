"""
Кросс-платформенная абстракция для работы с хоткеями, окнами и вставкой текста.
Автоматически выбирает реализацию в зависимости от ОС.
"""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import (
        BasePlatform,
        BaseHotkeyListener,
        BaseHotkeyRecorder,
        BaseWindowManager,
        BaseTextInserter,
    )


def get_platform() -> "BasePlatform":
    """Получить реализацию платформы для текущей ОС."""
    if sys.platform == "win32":
        from .windows import WindowsPlatform
        return WindowsPlatform()
    elif sys.platform == "darwin":
        from .macos import MacOSPlatform
        return MacOSPlatform()
    else:  # Linux и другие Unix
        from .linux import LinuxPlatform
        return LinuxPlatform()


# Глобальный экземпляр платформы
_platform: "BasePlatform" = None


def get_current_platform() -> "BasePlatform":
    """Получить глобальный экземпляр платформы."""
    global _platform
    if _platform is None:
        _platform = get_platform()
    return _platform


def create_hotkey_listener(
    combo: str,
    handler=None,
    *,
    on_press=None,
    on_release=None,
    push_to_talk: bool = False,
) -> "BaseHotkeyListener":
    """Создать слушатель хоткеев для текущей платформы."""
    return get_current_platform().create_hotkey_listener(
        combo,
        handler=handler,
        on_press=on_press,
        on_release=on_release,
        push_to_talk=push_to_talk,
    )


def create_hotkey_recorder(on_recorded) -> "BaseHotkeyRecorder":
    """Создать записыватель хоткеев для текущей платформы."""
    return get_current_platform().create_hotkey_recorder(on_recorded)


def create_window_manager() -> "BaseWindowManager":
    """Создать менеджер окон для текущей платформы."""
    return get_current_platform().create_window_manager()


def create_text_inserter() -> "BaseTextInserter":
    """Создать инструмент вставки текста для текущей платформы."""
    return get_current_platform().create_text_inserter()


__all__ = [
    "get_platform",
    "get_current_platform",
    "create_hotkey_listener",
    "create_hotkey_recorder",
    "create_window_manager",
    "create_text_inserter",
]







