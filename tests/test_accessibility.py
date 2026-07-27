from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def test_form_row_connects_label_and_names_composite_controls() -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

    from app.accessibility import configure_accessibility
    from app.ui.layouts import FormRow

    container = QWidget()
    layout = QHBoxLayout(container)
    editor = QLineEdit()
    action = QPushButton("↻")
    action.setToolTip("Refresh models")
    action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout.addWidget(editor)
    layout.addWidget(action)
    row = FormRow("Transcription model", container)

    configure_accessibility(row)

    assert row.label.buddy() is editor
    assert editor.accessibleName() == "Transcription model"
    assert action.accessibleName() == "Refresh models"
    assert action.focusPolicy() is not Qt.FocusPolicy.NoFocus


def test_reapplying_accessibility_refreshes_translated_form_name() -> None:
    from PyQt6.QtWidgets import QComboBox

    from app.accessibility import configure_accessibility
    from app.ui.layouts import FormRow

    combo = QComboBox()
    row = FormRow("Audio source", combo)
    configure_accessibility(row)
    row.label.setText("Источник звука")
    configure_accessibility(row)

    assert combo.accessibleName() == "Источник звука"


def test_overlay_exposes_text_status_and_reduced_motion() -> None:
    from app.overlay import OverlayWidget

    overlay = OverlayWidget()
    overlay.set_accessible_texts(
        recording="Запись",
        processing="Обработка",
        success="Готово",
        error="Ошибка",
    )
    overlay.set_reduced_motion(True)

    overlay.show_recording()
    assert overlay.accessibleName() == "Запись"
    assert overlay._fade_animation.duration() == 0
    assert not overlay._anim_timer.isActive()

    overlay.show_processing()
    assert overlay.accessibleName() == "Обработка"

    overlay.show_error("Нет доступа", auto_hide_ms=0)
    assert overlay.accessibleName() == "Ошибка"
    assert overlay.accessibleDescription() == "Нет доступа"

    overlay.hide_overlay()
    assert not overlay.isVisible()


def test_windows_high_contrast_uses_native_system_flag() -> None:
    from app.accessibility import windows_high_contrast_enabled

    def query(_action, _size, pointer, _flags):
        pointer._obj.dwFlags = 1
        return 1

    assert windows_high_contrast_enabled(query=query) is True


def test_failed_high_contrast_query_falls_back_without_crashing() -> None:
    from app.accessibility import windows_high_contrast_enabled

    def query(*_args):
        raise OSError("system setting unavailable")

    assert windows_high_contrast_enabled(query=query) is False
