from __future__ import annotations

import re
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from .ui.layouts import FormRow


_CONTROL_TYPES = (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)
_SPACE_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.replace("&", "")).strip(" \t\r\n…")


def _set_derived_name(widget: QWidget, value: str) -> None:
    value = _clean_text(value)
    if not value:
        return
    if (
        not widget.accessibleName()
        or widget.property("mindtypeDerivedAccessibleName")
    ):
        widget.setAccessibleName(value)
        widget.setProperty("mindtypeDerivedAccessibleName", True)


def _button_name(button: QAbstractButton) -> str:
    text = _clean_text(button.text())
    if any(character.isalnum() for character in text):
        return text
    return _clean_text(button.toolTip())


def _controls(parent: QWidget) -> list[QWidget]:
    return [
        widget
        for widget in parent.findChildren(QWidget)
        if isinstance(widget, _CONTROL_TYPES)
        and widget.focusPolicy() is not Qt.FocusPolicy.NoFocus
        and widget.isEnabled()
    ]


def _configure_form_row(row: FormRow) -> None:
    controls = _controls(row)
    if not controls:
        return
    label = _clean_text(row.label.text())
    primary = controls[0]
    row.label.setBuddy(primary)
    _set_derived_name(primary, label)
    for control in controls[1:]:
        if isinstance(control, QAbstractButton):
            _set_derived_name(control, _button_name(control))
        elif not control.accessibleName():
            _set_derived_name(control, label)


def configure_accessibility(root: QWidget) -> None:
    """Apply stable keyboard and screen-reader metadata to a widget tree."""
    rows = []
    if isinstance(root, FormRow):
        rows.append(root)
    rows.extend(root.findChildren(FormRow))

    # Glyph-only buttons are often explicitly marked NoFocus for mouse-only UI.
    # They still need to participate in keyboard navigation.
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if isinstance(widget, QPushButton):
            if widget.focusPolicy() is Qt.FocusPolicy.NoFocus:
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            _set_derived_name(widget, _button_name(widget))
        elif isinstance(widget, QAbstractButton):
            _set_derived_name(widget, _button_name(widget))
        tooltip = _clean_text(widget.toolTip())
        if tooltip and not widget.accessibleDescription():
            widget.setAccessibleDescription(tooltip)

    for row in rows:
        _configure_form_row(row)


__all__ = ["configure_accessibility"]
