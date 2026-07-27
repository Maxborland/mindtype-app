from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QByteArray, QMimeData

from app.insertion import AdapterAttempt, InsertionMethod, InsertionResult
from app.insertion.qt_clipboard import clone_mime_data
from app.insertion.uia_windows import set_value_via_uia
from app.platform.windows import WindowsHotkeyListener, WindowsTextInserter


class FakeWindowManager:
    def __init__(self, *, target=42, valid=True, restored=True, foreground=42):
        self.saved_window = target
        self.valid = valid
        self.restored = restored
        self.foreground = foreground
        self._our_window = 99

    @property
    def has_saved_window(self):
        return self.saved_window is not None

    def is_window_valid(self, window):
        return self.valid and window == self.saved_window

    def is_our_window(self, window):
        return window == self._our_window

    def restore_window(self):
        return self.restored

    def get_foreground_window(self):
        return self.foreground


def test_qt_clipboard_snapshot_clones_text_html_and_custom_formats():
    source = QMimeData()
    source.setData("text/plain", QByteArray(b"plain"))
    source.setData("text/html", QByteArray(b"<b>rich</b>"))
    source.setData(
        'application/x-qt-windows-mime;value="Custom Format"',
        QByteArray(b"\x00\x01custom"),
    )

    snapshot = clone_mime_data(source)
    source.setData("text/plain", QByteArray(b"changed"))

    assert bytes(snapshot.data("text/plain")) == b"plain"
    assert bytes(snapshot.data("text/html")) == b"<b>rich</b>"
    assert bytes(
        snapshot.data(
            'application/x-qt-windows-mime;value="Custom Format"'
        )
    ) == b"\x00\x01custom"


def test_windows_inserter_rejects_stale_target_before_adapter_calls():
    manager = FakeWindowManager(valid=False)
    pipeline = MagicMock()
    inserter = WindowsTextInserter(manager, pipeline=pipeline, sleep=lambda _d: None)

    result = inserter.insert_text_result("text", delay=0)

    assert result.success is False
    assert result.failure.value == "target_invalid"
    pipeline.insert.assert_not_called()


def test_windows_inserter_requires_exact_target_focus():
    manager = FakeWindowManager(foreground=77)
    pipeline = MagicMock()
    inserter = WindowsTextInserter(manager, pipeline=pipeline, sleep=lambda _d: None)

    result = inserter.insert_text_result("text", delay=0)

    assert result.success is False
    assert result.failure.value == "target_not_focused"
    pipeline.insert.assert_not_called()


def test_windows_inserter_keeps_boolean_compatibility_wrapper():
    manager = FakeWindowManager()
    pipeline = MagicMock()
    pipeline.insert.return_value = InsertionResult.ok(
        InsertionMethod.CLIPBOARD,
        attempted=(InsertionMethod.CLIPBOARD,),
    )
    inserter = WindowsTextInserter(manager, pipeline=pipeline, sleep=lambda _d: None)

    assert inserter.insert_text("text", delay=0) is True
    assert inserter.last_result.method is InsertionMethod.CLIPBOARD


def test_uia_value_pattern_sets_text_on_writable_focused_control():
    pattern = MagicMock()
    pattern.CurrentIsReadOnly = False
    pattern.CurrentValue = ""
    unknown_pattern = MagicMock()
    unknown_pattern.QueryInterface.return_value = pattern
    element = MagicMock()
    element.GetCurrentPattern.return_value = unknown_pattern
    automation = MagicMock()
    automation.GetFocusedElement.return_value = element
    value_pattern_interface = object()

    with (
        patch(
            "app.insertion.uia_windows._create_automation",
            return_value=(automation, value_pattern_interface),
        ),
        patch("app.insertion.uia_windows.CoInitialize"),
        patch("app.insertion.uia_windows.CoUninitialize"),
    ):
        assert set_value_via_uia(42, "текст") is True

    element.GetCurrentPattern.assert_called_once_with(10002)
    unknown_pattern.QueryInterface.assert_called_once_with(value_pattern_interface)
    pattern.SetValue.assert_called_once_with("текст")


def test_uia_value_pattern_rejects_read_only_control():
    pattern = MagicMock()
    pattern.CurrentIsReadOnly = True
    unknown_pattern = MagicMock()
    unknown_pattern.QueryInterface.return_value = pattern
    element = MagicMock()
    element.GetCurrentPattern.return_value = unknown_pattern
    automation = MagicMock()
    automation.GetFocusedElement.return_value = element

    with (
        patch(
            "app.insertion.uia_windows._create_automation",
            return_value=(automation, object()),
        ),
        patch("app.insertion.uia_windows.CoInitialize"),
        patch("app.insertion.uia_windows.CoUninitialize"),
    ):
        assert set_value_via_uia(42, "text") is False

    pattern.SetValue.assert_not_called()


def test_uia_value_pattern_does_not_replace_existing_control_text():
    pattern = MagicMock()
    pattern.CurrentIsReadOnly = False
    pattern.CurrentValue = "existing"
    unknown_pattern = MagicMock()
    unknown_pattern.QueryInterface.return_value = pattern
    element = MagicMock()
    element.GetCurrentPattern.return_value = unknown_pattern
    automation = MagicMock()
    automation.GetFocusedElement.return_value = element

    with (
        patch(
            "app.insertion.uia_windows._create_automation",
            return_value=(automation, object()),
        ),
        patch("app.insertion.uia_windows.CoInitialize"),
        patch("app.insertion.uia_windows.CoUninitialize"),
    ):
        assert set_value_via_uia(42, "text") is False

    pattern.SetValue.assert_not_called()


@pytest.mark.parametrize("combo", ["ctrl", "ctrl+alt", "ctrl+unknown"])
def test_windows_hotkey_rejects_modifier_only_or_unknown_combo(combo):
    with pytest.raises(ValueError, match="основную клавишу"):
        WindowsHotkeyListener(combo)


def test_windows_hotkey_uses_and_releases_global_atom():
    listener = WindowsHotkeyListener("ctrl+alt+v")

    with (
        patch("app.platform.windows.kernel32.GlobalAddAtomW", return_value=0xC123),
        patch("app.platform.windows.kernel32.GlobalDeleteAtom") as delete_atom,
        patch("app.platform.windows.user32.RegisterHotKey", return_value=True) as register,
        patch("app.platform.windows.user32.UnregisterHotKey") as unregister,
        patch("app.platform.windows.QApplication.instance", return_value=None),
    ):
        listener.start()
        register.assert_called_once_with(None, 0xC123, listener._modifiers, 0x56)

        listener.stop()

    unregister.assert_called_once_with(None, 0xC123)
    delete_atom.assert_called_once_with(0xC123)


def test_windows_hotkey_releases_atom_when_registration_fails():
    listener = WindowsHotkeyListener("ctrl+alt+v")

    with (
        patch("app.platform.windows.kernel32.GlobalAddAtomW", return_value=0xC123),
        patch("app.platform.windows.kernel32.GlobalDeleteAtom") as delete_atom,
        patch("app.platform.windows.user32.RegisterHotKey", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="Не удалось зарегистрировать"):
            listener.start()

    delete_atom.assert_called_once_with(0xC123)
    assert listener._registered_id is None
    assert listener._atom_id is None
