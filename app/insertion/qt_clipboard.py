"""Lossless clipboard snapshots through Qt's Windows MIME bridge."""

from __future__ import annotations

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QApplication


def clone_mime_data(source: QMimeData) -> QMimeData:
    clone = QMimeData()
    for format_name in source.formats():
        clone.setData(format_name, source.data(format_name))
    return clone


def _clipboard():
    application = QApplication.instance()
    if application is None:
        raise RuntimeError("clipboard access requires a QApplication")
    return application.clipboard()


def capture_clipboard() -> QMimeData:
    return clone_mime_data(_clipboard().mimeData())


def write_clipboard_text(text: str) -> None:
    payload = QMimeData()
    payload.setText(text)
    _clipboard().setMimeData(payload)


def restore_clipboard(snapshot: object) -> None:
    if not isinstance(snapshot, QMimeData):
        raise TypeError("clipboard snapshot is not QMimeData")
    _clipboard().setMimeData(clone_mime_data(snapshot))
