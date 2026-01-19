"""
macOS-специфичная реализация платформенного кода.
Использует pynput для хоткеев и AppKit для управления окнами.
"""

import subprocess
import time
from typing import Callable, Optional, Set

from PyQt6.QtCore import QObject, QTimer, Qt, QEvent
from PyQt6.QtWidgets import QApplication

import pyperclip

from .base import (
    BasePlatform,
    BaseHotkeyListener,
    BaseHotkeyRecorder,
    BaseWindowManager,
    BaseTextInserter,
)


# Попробуем импортировать pynput
try:
    from pynput import keyboard as pynput_keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# Попробуем импортировать AppKit (только на macOS)
try:
    from AppKit import NSWorkspace, NSRunningApplication
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )
    APPKIT_AVAILABLE = True
except ImportError:
    APPKIT_AVAILABLE = False


def _parse_combo(combo: str) -> tuple:
    """Парсинг комбинации клавиш в формат pynput."""
    parts = combo.lower().replace(" ", "").split("+")
    modifiers = set()
    key = None

    for part in parts:
        if part == "ctrl" or part == "control":
            modifiers.add(pynput_keyboard.Key.ctrl)
        elif part == "alt" or part == "option":
            modifiers.add(pynput_keyboard.Key.alt)
        elif part == "shift":
            modifiers.add(pynput_keyboard.Key.shift)
        elif part == "cmd" or part == "command" or part == "win":
            modifiers.add(pynput_keyboard.Key.cmd)
        elif len(part) == 1:
            key = pynput_keyboard.KeyCode.from_char(part)
        else:
            # Функциональные клавиши
            key_map = {
                'f1': pynput_keyboard.Key.f1,
                'f2': pynput_keyboard.Key.f2,
                'f3': pynput_keyboard.Key.f3,
                'f4': pynput_keyboard.Key.f4,
                'f5': pynput_keyboard.Key.f5,
                'f6': pynput_keyboard.Key.f6,
                'f7': pynput_keyboard.Key.f7,
                'f8': pynput_keyboard.Key.f8,
                'f9': pynput_keyboard.Key.f9,
                'f10': pynput_keyboard.Key.f10,
                'f11': pynput_keyboard.Key.f11,
                'f12': pynput_keyboard.Key.f12,
                'space': pynput_keyboard.Key.space,
                'esc': pynput_keyboard.Key.esc,
                'escape': pynput_keyboard.Key.esc,
                'tab': pynput_keyboard.Key.tab,
                'enter': pynput_keyboard.Key.enter,
                'backspace': pynput_keyboard.Key.backspace,
            }
            if part in key_map:
                key = key_map[part]

    return modifiers, key


class MacOSHotkeyListener(BaseHotkeyListener):
    """macOS реализация слушателя хоткеев через pynput."""

    def __init__(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> None:
        super().__init__(combo, handler, on_press=on_press, on_release=on_release, push_to_talk=push_to_talk)

        if not PYNPUT_AVAILABLE:
            raise RuntimeError("pynput не установлен. Установите: pip install pynput")

        self._listener: Optional[pynput_keyboard.Listener] = None
        self._pressed_keys: Set = set()
        self._hotkey_active = False
        self._modifiers, self._key = _parse_combo(combo)

    def start(self) -> None:
        if self._listener is not None:
            return

        self._listener = pynput_keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._pressed_keys.clear()
        self._hotkey_active = False

    def _on_key_press(self, key) -> None:
        self._pressed_keys.add(key)

        # Проверяем, нажата ли комбинация
        if self._check_hotkey():
            if not self._hotkey_active:
                self._hotkey_active = True
                if self._on_press:
                    self._on_press()
                elif self._handler:
                    self._handler()

    def _on_key_release(self, key) -> None:
        self._pressed_keys.discard(key)

        # Если хоткей был активен и одна из клавиш отпущена
        if self._hotkey_active and self._push_to_talk:
            if not self._check_hotkey():
                self._hotkey_active = False
                if self._on_release:
                    self._on_release()

    def _check_hotkey(self) -> bool:
        """Проверить, нажата ли комбинация хоткея."""
        # Проверяем модификаторы
        for mod in self._modifiers:
            if mod not in self._pressed_keys:
                return False

        # Проверяем основную клавишу
        if self._key:
            if self._key not in self._pressed_keys:
                # Проверяем KeyCode с char
                for pressed in self._pressed_keys:
                    if hasattr(pressed, 'char') and hasattr(self._key, 'char'):
                        if pressed.char == self._key.char:
                            return True
                return False

        return True


class MacOSHotkeyRecorder(BaseHotkeyRecorder, QObject):
    """macOS реализация записи хоткеев через Qt events."""

    def __init__(self, on_recorded: Callable[[str], None]) -> None:
        BaseHotkeyRecorder.__init__(self, on_recorded)
        QObject.__init__(self)
        self._pressed_keys: Set[int] = set()
        self._active = False
        self._app = QApplication.instance()

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._pressed_keys.clear()
        if self._app:
            self._app.installEventFilter(self)

    def stop(self) -> None:
        self._active = False
        if self._app:
            self._app.removeEventFilter(self)
        self._pressed_keys.clear()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._active:
            return False

        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key != Qt.Key.Key_unknown:
                self._pressed_keys.add(key)
            return True

        elif event.type() == QEvent.Type.KeyRelease:
            if self._pressed_keys:
                combo = self._format_combo()
                self.stop()
                self._on_recorded(combo)
            return True

        return False

    def _format_combo(self) -> str:
        parts = []
        keys = list(self._pressed_keys)

        # На macOS используем cmd вместо ctrl для большинства операций
        if Qt.Key.Key_Control in keys:
            parts.append("ctrl")
            keys.remove(Qt.Key.Key_Control)
        if Qt.Key.Key_Meta in keys:
            parts.append("cmd")
            keys.remove(Qt.Key.Key_Meta)
        if Qt.Key.Key_Alt in keys:
            parts.append("alt")
            keys.remove(Qt.Key.Key_Alt)
        if Qt.Key.Key_Shift in keys:
            parts.append("shift")
            keys.remove(Qt.Key.Key_Shift)

        for k in keys:
            txt = self._key_to_string(k)
            if txt:
                parts.append(txt)

        return "+".join(parts)

    def _key_to_string(self, key_code: int) -> str:
        if 0x30 <= key_code <= 0x39:
            return chr(key_code)
        if 0x41 <= key_code <= 0x5A:
            return chr(key_code).lower()

        mapping = {
            Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2", Qt.Key.Key_F3: "f3",
            Qt.Key.Key_F4: "f4", Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6",
            Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8", Qt.Key.Key_F9: "f9",
            Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Backspace: "backspace",
        }
        return mapping.get(key_code, "")


class MacOSWindowManager(BaseWindowManager):
    """macOS реализация управления окнами."""

    def get_foreground_window(self):
        """Получить активное приложение."""
        if APPKIT_AVAILABLE:
            workspace = NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication()
            return app
        return None

    def get_window_title(self, window) -> str:
        """Получить название приложения."""
        if window and APPKIT_AVAILABLE:
            try:
                return window.localizedName()
            except Exception:
                pass
        return ""

    def set_foreground_window(self, window) -> bool:
        """Активировать приложение."""
        if window and APPKIT_AVAILABLE:
            try:
                window.activateWithOptions_(
                    1 << 1  # NSApplicationActivateIgnoringOtherApps
                )
                return True
            except Exception:
                pass
        return False

    def minimize_window(self, window) -> bool:
        """Скрыть приложение."""
        if window and APPKIT_AVAILABLE:
            try:
                window.hide()
                return True
            except Exception:
                pass
        return False


class MacOSTextInserter(BaseTextInserter):
    """macOS реализация вставки текста."""

    def __init__(self, window_manager: MacOSWindowManager) -> None:
        super().__init__(window_manager)
        self._keyboard_controller = None
        if PYNPUT_AVAILABLE:
            self._keyboard_controller = pynput_keyboard.Controller()

    def insert_text(self, text: str, delay: float = 0.1) -> bool:
        if not text:
            return False

        try:
            # Восстанавливаем фокус
            if self._window_manager.has_saved_window:
                self._window_manager.restore_window_soft()
                time.sleep(delay + 0.05)

            # Сохраняем предыдущий буфер обмена
            prev_clip = None
            try:
                prev_clip = pyperclip.paste()
            except Exception:
                pass

            # Копируем текст
            pyperclip.copy(text)
            time.sleep(0.05)

            # Вставляем через Cmd+V
            if self._keyboard_controller:
                with self._keyboard_controller.pressed(pynput_keyboard.Key.cmd):
                    self._keyboard_controller.tap('v')
            else:
                # Fallback через AppleScript
                subprocess.run([
                    'osascript', '-e',
                    'tell application "System Events" to keystroke "v" using command down'
                ], check=False)

            time.sleep(delay)

            # Восстанавливаем буфер обмена
            if prev_clip is not None:
                try:
                    pyperclip.copy(prev_clip)
                except Exception:
                    pass

            return True
        except Exception:
            return False

    def type_text(self, text: str) -> bool:
        if not text:
            return False

        try:
            if self._keyboard_controller:
                self._keyboard_controller.type(text)
            else:
                # Безопасная передача текста через аргументы osascript
                subprocess.run([
                    'osascript', '-e',
                    'on run argv',
                    'tell application "System Events" to keystroke (item 1 of argv)',
                    'end run',
                    text
                ], check=False)
            return True
        except Exception:
            return False


class MacOSPlatform(BasePlatform):
    """macOS платформа."""

    _window_manager: Optional[MacOSWindowManager] = None

    @property
    def name(self) -> str:
        return "macOS"

    def create_hotkey_listener(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> MacOSHotkeyListener:
        return MacOSHotkeyListener(
            combo, handler,
            on_press=on_press, on_release=on_release, push_to_talk=push_to_talk
        )

    def create_hotkey_recorder(
        self,
        on_recorded: Callable[[str], None],
    ) -> MacOSHotkeyRecorder:
        return MacOSHotkeyRecorder(on_recorded)

    def create_window_manager(self) -> MacOSWindowManager:
        if self._window_manager is None:
            self._window_manager = MacOSWindowManager()
        return self._window_manager

    def create_text_inserter(self) -> MacOSTextInserter:
        return MacOSTextInserter(self.create_window_manager())







