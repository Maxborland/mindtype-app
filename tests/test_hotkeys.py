"""
Unit тесты для модуля hotkeys.py и platform/base.py

Тестируем базовые классы и функции без реального доступа к клавиатуре.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch


class TestIsAdmin:
    """Тесты функции is_admin."""

    def test_is_admin_windows_admin(self):
        """На Windows с правами админа возвращает True."""
        from app import hotkeys

        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        with patch.object(hotkeys.sys, "platform", "win32"):
            with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
                assert hotkeys.is_admin() is True

    def test_is_admin_linux_root(self):
        """На Linux с uid=0 возвращает True."""
        from app import hotkeys

        with patch.object(hotkeys.sys, "platform", "linux"):
            with patch("os.getuid", return_value=0, create=True):
                assert hotkeys.is_admin() is True

    def test_is_admin_linux_not_root(self):
        """На Linux с uid!=0 возвращает False."""
        from app import hotkeys

        with patch.object(hotkeys.sys, "platform", "linux"):
            with patch("os.getuid", return_value=1000, create=True):
                assert hotkeys.is_admin() is False


class TestBaseHotkeyListener:
    """Тесты для базового класса HotkeyListener."""

    def test_init_stores_parameters(self):
        """Проверяем сохранение параметров при инициализации."""
        from app.platform.base import BaseHotkeyListener

        handler = MagicMock()
        on_press = MagicMock()
        on_release = MagicMock()

        # Создаём подкласс для тестирования (т.к. base - абстрактный)
        class TestListener(BaseHotkeyListener):
            def start(self): pass
            def stop(self): pass

        listener = TestListener(
            combo="ctrl+alt+m",
            handler=handler,
            on_press=on_press,
            on_release=on_release,
            push_to_talk=True
        )

        assert listener.combo == "ctrl+alt+m"
        assert listener._handler == handler
        assert listener._on_press == on_press
        assert listener._on_release == on_release
        assert listener._push_to_talk is True

    def test_start_not_implemented(self):
        """start() должен быть реализован в подклассе."""
        from app.platform.base import BaseHotkeyListener

        # Создаём минимальный подкласс без реализации
        class MinimalListener(BaseHotkeyListener):
            pass

        listener = MinimalListener("ctrl+m")

        with pytest.raises(NotImplementedError):
            listener.start()

    def test_stop_not_implemented(self):
        """stop() должен быть реализован в подклассе."""
        from app.platform.base import BaseHotkeyListener

        class MinimalListener(BaseHotkeyListener):
            pass

        listener = MinimalListener("ctrl+m")

        with pytest.raises(NotImplementedError):
            listener.stop()


class TestBaseHotkeyRecorder:
    """Тесты для базового класса HotkeyRecorder."""

    def test_init_stores_callback(self):
        """Проверяем сохранение callback при инициализации."""
        from app.platform.base import BaseHotkeyRecorder

        callback = MagicMock()

        class TestRecorder(BaseHotkeyRecorder):
            def start(self): pass
            def stop(self): pass

        recorder = TestRecorder(callback)

        assert recorder._on_recorded == callback


class TestBaseWindowManager:
    """Тесты для базового класса WindowManager."""

    def test_set_our_window(self):
        """Установка handle нашего окна."""
        from app.platform.base import BaseWindowManager

        class TestManager(BaseWindowManager):
            def get_foreground_window(self): return None
            def get_window_title(self, w): return ""
            def set_foreground_window(self, w): return True
            def minimize_window(self, w): return True

        manager = TestManager()
        window_handle = MagicMock()

        manager.set_our_window(window_handle)

        assert manager._our_window == window_handle

    def test_has_saved_window_initially_false(self):
        """has_saved_window изначально False."""
        from app.platform.base import BaseWindowManager

        class TestManager(BaseWindowManager):
            def get_foreground_window(self): return None
            def get_window_title(self, w): return ""
            def set_foreground_window(self, w): return True
            def minimize_window(self, w): return True

        manager = TestManager()

        assert manager.has_saved_window is False

    def test_save_and_restore_window(self):
        """Сохранение и восстановление окна."""
        from app.platform.base import BaseWindowManager

        saved_window = MagicMock()

        class TestManager(BaseWindowManager):
            def get_foreground_window(self): return saved_window
            def get_window_title(self, w): return "Test Window"
            def set_foreground_window(self, w): return True
            def minimize_window(self, w): return True

        manager = TestManager()

        # Сохраняем окно
        manager.save_current_window()

        assert manager.has_saved_window is True
        assert manager.saved_window_title == "Test Window"

        # Восстанавливаем
        result = manager.restore_window()

        assert result is True

    def test_restore_window_soft(self):
        """Мягкое восстановление окна."""
        from app.platform.base import BaseWindowManager

        class TestManager(BaseWindowManager):
            def __init__(self):
                super().__init__()
                self.minimized = False

            def get_foreground_window(self): return None
            def get_window_title(self, w): return ""
            def set_foreground_window(self, w): return True
            def minimize_window(self, w):
                self.minimized = True
                return True

        manager = TestManager()
        our_window = MagicMock()
        manager.set_our_window(our_window)

        result = manager.restore_window_soft()

        assert result is True
        assert manager.minimized is True


class TestBaseTextInserter:
    """Тесты для базового класса TextInserter."""

    def test_init_stores_window_manager(self):
        """Проверяем сохранение window_manager."""
        from app.platform.base import BaseTextInserter, BaseWindowManager

        class TestManager(BaseWindowManager):
            def get_foreground_window(self): return None
            def get_window_title(self, w): return ""
            def set_foreground_window(self, w): return True
            def minimize_window(self, w): return True

        class TestInserter(BaseTextInserter):
            def insert_text(self, text, delay=0.1): return True
            def type_text(self, text): return True

        manager = TestManager()
        inserter = TestInserter(manager)

        assert inserter._window_manager == manager


class TestHotkeyModuleExports:
    """Тесты для экспортов модуля hotkeys."""

    def test_exports_hotkey_listener(self):
        """Модуль экспортирует HotkeyListener."""
        from app.hotkeys import HotkeyListener
        assert HotkeyListener is not None

    def test_exports_hotkey_recorder(self):
        """Модуль экспортирует HotkeyRecorder."""
        from app.hotkeys import HotkeyRecorder
        assert HotkeyRecorder is not None

    def test_exports_is_admin(self):
        """Модуль экспортирует is_admin."""
        from app.hotkeys import is_admin
        assert callable(is_admin)
