"""
Кросс-платформенные глобальные хоткеи.
Автоматически выбирает реализацию в зависимости от ОС.
"""

import sys
from typing import Callable, Optional

# Выбираем реализацию в зависимости от платформы
if sys.platform == "win32":
    from .platform.windows import WindowsHotkeyListener as HotkeyListener
    from .platform.windows import WindowsHotkeyRecorder as HotkeyRecorder
elif sys.platform == "darwin":
    from .platform.macos import MacOSHotkeyListener as HotkeyListener
    from .platform.macos import MacOSHotkeyRecorder as HotkeyRecorder
else:
    from .platform.linux import LinuxHotkeyListener as HotkeyListener
    from .platform.linux import LinuxHotkeyRecorder as HotkeyRecorder


def is_admin() -> bool:
    """Проверить, запущено ли приложение с правами администратора."""
    if sys.platform == "win32":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    else:
        # На Linux/macOS проверяем uid
        import os
        return os.getuid() == 0


__all__ = ["HotkeyListener", "HotkeyRecorder", "is_admin"]
