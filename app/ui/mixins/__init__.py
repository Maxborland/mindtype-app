"""
Миксины для MainWindow.

Этот пакет содержит миксины, разделяющие функциональность MainWindow
на логические блоки для улучшения maintainability.

Структура:
- assistant_mixin.py: логика голосового ассистента
- files_mixin.py: обработка файлов (drag & drop, очередь)
- updates_mixin.py: проверка и загрузка обновлений
- hotkeys_mixin.py: управление горячими клавишами
"""

from .assistant_mixin import AssistantMixin
from .files_mixin import FilesMixin
from .updates_mixin import UpdatesMixin
from .hotkeys_mixin import HotkeysMixin

__all__ = [
    "AssistantMixin",
    "FilesMixin",
    "UpdatesMixin",
    "HotkeysMixin",
]
