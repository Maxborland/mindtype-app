"""
Windows-специфичная реализация платформенного кода.
Использует Win32 API через ctypes.
"""

import ctypes
import hashlib
import logging
import time
from ctypes import wintypes
from typing import Callable, Optional, Set, List

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Qt, QEvent
from PyQt6.QtWidgets import QApplication

from .base import (
    BasePlatform,
    BaseHotkeyListener,
    BaseHotkeyRecorder,
    BaseWindowManager,
    BaseTextInserter,
)
from ..insertion import (
    ClipboardPasteAdapter,
    InsertionFailure,
    InsertionPipeline,
    InsertionResult,
    UIAutomationValueAdapter,
    UnicodeInputAdapter,
)
from ..insertion.qt_clipboard import (
    capture_clipboard,
    restore_clipboard,
    write_clipboard_text,
)
from ..insertion.uia_windows import set_value_via_uia

logger = logging.getLogger(__name__)


# Windows API
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Константы Windows
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
SW_MINIMIZE = 6
SW_RESTORE = 9

# Key mapping
VK_MAPPING = {
    'backspace': 0x08,
    'tab': 0x09,
    'clear': 0x0C,
    'enter': 0x0D,
    'shift': 0x10,
    'ctrl': 0x11,
    'alt': 0x12,
    'pause': 0x13,
    'caps lock': 0x14,
    'esc': 0x1B,
    'space': 0x20,
    'page up': 0x21,
    'page down': 0x22,
    'end': 0x23,
    'home': 0x24,
    'left': 0x25,
    'up': 0x26,
    'right': 0x27,
    'down': 0x28,
    'print screen': 0x2C,
    'insert': 0x2D,
    'delete': 0x2E,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    'lwin': 0x5B, 'rwin': 0x5C,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
    'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
    'f11': 0x7A, 'f12': 0x7B,
    'num lock': 0x90,
    'scroll lock': 0x91,
}

# Константы для keyboard input
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11


def _stable_hotkey_id(combo: str) -> int:
    """Return a deterministic RegisterHotKey application-range identifier."""
    normalized = combo.lower().replace(" ", "").encode("utf-8")
    digest = hashlib.sha256(normalized).digest()
    return int.from_bytes(digest[:2], "little") % 0xBFFF + 1


class WinEventFilter(QAbstractNativeEventFilter):
    """Фильтр нативных событий Windows для перехвата WM_HOTKEY."""

    def __init__(self, callback: Callable[[int], None]):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            msg_ptr = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG))
            msg = msg_ptr.contents
            if msg.message == WM_HOTKEY:
                self.callback(msg.wParam)
        return False, 0


class WindowsHotkeyListener(BaseHotkeyListener):
    """Windows реализация слушателя хоткеев через RegisterHotKey."""

    def __init__(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> None:
        super().__init__(
            combo, handler,
            on_press=on_press, on_release=on_release, push_to_talk=push_to_talk
        )

        self._registered_id: Optional[int] = None
        self._filter: Optional[WinEventFilter] = None
        self._check_timer: Optional[QTimer] = None
        self._vk_keys: List[int] = []

        self._parse_combo()
        if not self._vk_code:
            raise ValueError(
                "Глобальный хоткей должен содержать основную клавишу, "
                "а не только модификаторы."
            )

    def _parse_combo(self) -> None:
        parts = self.combo.lower().replace(" ", "").split("+")
        self._vk_keys = []
        self._modifiers = 0
        self._vk_code = 0

        for part in parts:
            if part == "ctrl":
                self._modifiers |= MOD_CONTROL
            elif part == "alt":
                self._modifiers |= MOD_ALT
            elif part == "shift":
                self._modifiers |= MOD_SHIFT
            elif part in ("win", "windows"):
                self._modifiers |= MOD_WIN
            else:
                self._vk_code = VK_MAPPING.get(part, 0)
                if self._vk_code:
                    self._vk_keys.append(self._vk_code)

        # Добавляем модификаторы в список проверяемых клавиш для PTT
        if self._modifiers & MOD_CONTROL:
            self._vk_keys.append(VK_MAPPING['ctrl'])
        if self._modifiers & MOD_ALT:
            self._vk_keys.append(VK_MAPPING['alt'])
        if self._modifiers & MOD_SHIFT:
            self._vk_keys.append(VK_MAPPING['shift'])

    def start(self) -> None:
        if self._registered_id is not None:
            return

        self._registered_id = _stable_hotkey_id(self.combo)

        try:
            success = user32.RegisterHotKey(
                None,
                self._registered_id,
                self._modifiers,
                self._vk_code
            )
        except Exception:
            self._registered_id = None
            raise

        if not success:
            self._registered_id = None
            raise RuntimeError(
                f"Не удалось зарегистрировать хоткей: {self.combo}. "
                "Возможно, он уже используется другим приложением."
            )

        app = QApplication.instance()
        if app:
            self._filter = WinEventFilter(self._on_hotkey_event)
            app.installNativeEventFilter(self._filter)

    def stop(self) -> None:
        if self._registered_id is not None:
            user32.UnregisterHotKey(None, self._registered_id)
            self._registered_id = None

        if self._filter:
            app = QApplication.instance()
            if app:
                app.removeNativeEventFilter(self._filter)
            self._filter = None

        if self._check_timer:
            self._check_timer.stop()
            self._check_timer.deleteLater()
            self._check_timer = None

    def _on_hotkey_event(self, hotkey_id: int) -> None:
        if hotkey_id != self._registered_id:
            return

        if self._on_press:
            self._on_press()
        elif self._handler:
            self._handler()

        if self._push_to_talk:
            self._start_release_check()

    def _start_release_check(self) -> None:
        if self._check_timer:
            return

        self._check_timer = QTimer(self)
        self._check_timer.setInterval(50)
        self._check_timer.timeout.connect(self._check_keys_state)
        self._check_timer.start()

    def _check_keys_state(self) -> None:
        is_pressed = True
        for vk in self._vk_keys:
            if not (user32.GetAsyncKeyState(vk) & 0x8000):
                is_pressed = False
                break

        if not is_pressed:
            if self._check_timer:
                self._check_timer.stop()
                self._check_timer.deleteLater()
                self._check_timer = None
            if self._on_release:
                self._on_release()


class WindowsHotkeyRecorder(BaseHotkeyRecorder):
    """Windows реализация записи хоткеев через Qt events."""

    def __init__(self, on_recorded: Callable[[str], None]) -> None:
        super().__init__(on_recorded)
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
                main_key = combo.split("+")[-1] if combo else ""
                if main_key not in {"ctrl", "alt", "shift", "win", ""}:
                    self.stop()
                    self._on_recorded(combo)
                else:
                    self._pressed_keys.clear()
            return True

        return False

    def _format_combo(self) -> str:
        parts = []
        keys = list(self._pressed_keys)

        if Qt.Key.Key_Control in keys:
            parts.append("ctrl")
            keys.remove(Qt.Key.Key_Control)
        if Qt.Key.Key_Alt in keys:
            parts.append("alt")
            keys.remove(Qt.Key.Key_Alt)
        if Qt.Key.Key_Shift in keys:
            parts.append("shift")
            keys.remove(Qt.Key.Key_Shift)
        if Qt.Key.Key_Meta in keys:
            parts.append("win")
            keys.remove(Qt.Key.Key_Meta)

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
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page up",
            Qt.Key.Key_PageDown: "page down",
        }
        return mapping.get(key_code, "")


class WindowsWindowManager(BaseWindowManager):
    """Windows реализация управления окнами."""

    def get_foreground_window(self) -> int:
        return user32.GetForegroundWindow()

    def is_window_valid(self, window) -> bool:
        return bool(window and user32.IsWindow(window))

    def get_window_title(self, window) -> str:
        if not window:
            return ""
        try:
            length = user32.GetWindowTextLengthW(window) + 1
            buffer = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(window, buffer, length)
            return buffer.value
        except Exception:
            return ""

    def set_foreground_window(self, window) -> bool:
        if not self.is_window_valid(window) or self.is_our_window(window):
            return False

        attached_current = False
        attached_target = False
        current_thread_id = 0
        target_thread_id = 0
        our_thread_id = 0
        try:
            current_hwnd = user32.GetForegroundWindow()

            if current_hwnd == window:
                return True

            current_thread_id = user32.GetWindowThreadProcessId(current_hwnd, None)
            target_thread_id = user32.GetWindowThreadProcessId(window, None)
            our_thread_id = kernel32.GetCurrentThreadId()

            if current_thread_id != our_thread_id:
                user32.AttachThreadInput(our_thread_id, current_thread_id, True)
                attached_current = True

            if target_thread_id != our_thread_id and target_thread_id != current_thread_id:
                user32.AttachThreadInput(our_thread_id, target_thread_id, True)
                attached_target = True

            user32.ShowWindow(window, SW_RESTORE)
            foreground_set = bool(user32.SetForegroundWindow(window))
            user32.BringWindowToTop(window)
            return foreground_set or user32.GetForegroundWindow() == window
        except Exception:
            return False
        finally:
            if attached_target:
                user32.AttachThreadInput(our_thread_id, target_thread_id, False)
            if attached_current:
                user32.AttachThreadInput(our_thread_id, current_thread_id, False)

    def minimize_window(self, window) -> bool:
        if not window:
            return False
        try:
            user32.ShowWindow(window, SW_MINIMIZE)
            return True
        except Exception:
            return False


class WindowsTextInserter(BaseTextInserter):
    """Windows реализация вставки текста."""

    def __init__(
        self,
        window_manager: WindowsWindowManager,
        *,
        pipeline: Optional[InsertionPipeline] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(window_manager)
        self._sleep = sleep
        self._unicode_adapter = UnicodeInputAdapter(
            send_code_unit=self._send_unicode_code_unit
        )
        self._pipeline = pipeline or InsertionPipeline(
            [
                ClipboardPasteAdapter(
                    read_clipboard=capture_clipboard,
                    write_clipboard=write_clipboard_text,
                    restore_clipboard=restore_clipboard,
                    send_paste=self._send_ctrl_v,
                    release_modifiers=self._release_modifiers,
                    sleep=sleep,
                    validate_target=self._target_is_active,
                ),
                self._unicode_adapter,
                UIAutomationValueAdapter(set_value=set_value_via_uia),
            ],
            validate_target=self._target_is_active,
        )
        self.last_result = InsertionResult.failed(InsertionFailure.EMPTY_TEXT)

    def insert_text(self, text: str, delay: float = 0.1) -> bool:
        """Compatibility wrapper for callers that only need success/failure."""
        return self.insert_text_result(text, delay).success

    def insert_text_result(
        self,
        text: str,
        delay: float = 0.1,
    ) -> InsertionResult:
        if not text:
            self.last_result = InsertionResult.failed(
                InsertionFailure.EMPTY_TEXT
            )
            return self.last_result

        try:
            target = self._window_manager.saved_window
            if (
                not target
                or not self._window_manager.is_window_valid(target)
                or self._window_manager.is_our_window(target)
            ):
                self.last_result = InsertionResult.failed(
                    InsertionFailure.TARGET_INVALID
                )
                return self.last_result
            if not self._window_manager.restore_window():
                self.last_result = InsertionResult.failed(
                    InsertionFailure.TARGET_NOT_FOCUSED
                )
                return self.last_result

            self._sleep(delay + 0.1)
            if self._window_manager.get_foreground_window() != target:
                self.last_result = InsertionResult.failed(
                    InsertionFailure.TARGET_NOT_FOCUSED
                )
                return self.last_result

            self.last_result = self._pipeline.insert(
                text,
                target=target,
                delay=delay,
            )
            return self.last_result
        except Exception as e:
            logger.error("Ошибка вставки текста: %s", e)
            self.last_result = InsertionResult.failed(
                InsertionFailure.ALL_METHODS_FAILED,
                error=str(e),
            )
            return self.last_result

    def type_text(self, text: str) -> bool:
        """Напечатать текст посимвольно через SendInput."""
        if not text:
            return False

        result = self._unicode_adapter.attempt(
            text,
            target=self._window_manager.get_foreground_window(),
            delay=0,
        )
        return result.success

    def _release_modifiers(self) -> None:
        """Освободить зажатые модификаторы."""
        modifiers = [0x11, 0x12, 0x10, 0x5B]  # Ctrl, Alt, Shift, Win
        for vk in modifiers:
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def _target_is_active(self, target: object) -> bool:
        return bool(
            self._window_manager.is_window_valid(target)
            and not self._window_manager.is_our_window(target)
            and self._window_manager.get_foreground_window() == target
        )

    def _send_ctrl_v(self) -> None:
        """Отправить Ctrl+V."""
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(0x56, 0, 0, 0)  # V
        user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def _send_unicode_code_unit(self, code_unit: int, key_up: bool) -> bool:
        """Отправить одну UTF-16 code unit через SendInput."""
        # Используем SendInput для unicode символов
        from ctypes import Structure, Union, sizeof

        class KEYBDINPUT(Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(Structure):
            class _INPUT(Union):
                _fields_ = [("ki", KEYBDINPUT)]

            _anonymous_ = ("_input",)
            _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]

        KEYEVENTF_UNICODE = 0x0004
        INPUT_KEYBOARD = 1

        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = 0
        inp.ki.wScan = code_unit
        inp.ki.dwFlags = KEYEVENTF_UNICODE | (
            KEYEVENTF_KEYUP if key_up else 0
        )
        return user32.SendInput(1, ctypes.byref(inp), sizeof(INPUT)) == 1

    def _send_char(self, char: str) -> None:
        """Compatibility helper for a single Unicode character."""
        result = self._unicode_adapter.attempt(char, target=None, delay=0)
        if not result.success:
            raise RuntimeError(result.error or "SendInput failed")


class WindowsPlatform(BasePlatform):
    """Windows платформа."""

    _window_manager: Optional[WindowsWindowManager] = None

    @property
    def name(self) -> str:
        return "Windows"

    def create_hotkey_listener(
        self,
        combo: str,
        handler: Optional[Callable[[], None]] = None,
        *,
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        push_to_talk: bool = False,
    ) -> WindowsHotkeyListener:
        return WindowsHotkeyListener(
            combo, handler,
            on_press=on_press, on_release=on_release, push_to_talk=push_to_talk
        )

    def create_hotkey_recorder(
        self,
        on_recorded: Callable[[str], None],
    ) -> WindowsHotkeyRecorder:
        return WindowsHotkeyRecorder(on_recorded)

    def create_window_manager(self) -> WindowsWindowManager:
        if self._window_manager is None:
            self._window_manager = WindowsWindowManager()
        return self._window_manager

    def create_text_inserter(self) -> WindowsTextInserter:
        return WindowsTextInserter(self.create_window_manager())
