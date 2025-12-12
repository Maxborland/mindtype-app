# MindType - AI Speech-to-Text Desktop Application
# Copyright (c) 2024-2025 Butakov Maksim Vladimirovich. All rights reserved.
# Author: Butakov Maksim Vladimirovich <info@mindtype.space>
#
# This software is the confidential and proprietary information of the Author.

import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Для корректного отображения иконки в панели задач Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MindType.App.1.0")

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt, QRectF
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QPen, QBrush

from .audio import AudioRecorder
from .config import ConfigManager, DEFAULT_MODELS_DIR
from .hotkeys import HotkeyListener, HotkeyRecorder
from .inserter import insert_text, focus_manager
from .licensing import LicenseManager, LicenseStatus
from .licensing.activation_dialog import LicenseActivationDialog, LicenseStatusWidget, TrialExpiredDialog
from .overlay import OverlayWidget
from .transcriber import Transcriber
from .translations import (
    get_text,
    UI_LANGUAGES,
    WHISPER_LANGUAGES,
)
from .updater import Updater, UpdateInfo, UpdateStatus


def create_app_icon(size: int = 64, recording: bool = False) -> QIcon:
    """Создать пиксельную иконку приложения в стиле Classic Mac OS."""
    base = 64  # Базовый размер пиксельной сетки
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))  # Прозрачный фон

    painter = QPainter(pixmap)
    px = size / base  # Размер одного "пикселя"

    black = QColor(255, 60, 60) if recording else QColor(0, 0, 0)
    white = QColor(255, 255, 255)

    def fill(x, y, w, h, color):
        painter.fillRect(int(x * px), int(y * px), max(1, int(w * px)), max(1, int(h * px)), color)

    # Белая заливка внутри рамки
    fill(6, 6, 52, 52, white)

    # Рамка окна
    fill(8, 2, 48, 2, black)   # верх
    fill(8, 60, 48, 2, black)  # низ
    fill(2, 8, 2, 48, black)   # лево
    fill(60, 8, 2, 48, black)  # право
    # Углы
    fill(4, 4, 4, 4, black)
    fill(56, 4, 4, 4, black)
    fill(4, 56, 4, 4, black)
    fill(56, 56, 4, 4, black)

    # Микрофон - верхняя дуга
    fill(18, 10, 2, 2, black)
    fill(20, 8, 8, 2, black)
    fill(28, 10, 2, 2, black)

    # Точки сверху
    fill(20, 12, 2, 2, black)
    fill(23, 11, 2, 2, black)
    fill(26, 12, 2, 2, black)

    # Бока микрофона
    fill(16, 12, 2, 22, black)
    fill(30, 12, 2, 22, black)

    # Горизонтальные линии
    fill(16, 16, 16, 2, black)
    fill(16, 20, 16, 2, black)
    fill(16, 24, 16, 2, black)
    fill(16, 28, 16, 2, black)
    fill(16, 32, 16, 2, black)

    # Нижняя дуга головы
    fill(18, 34, 2, 2, black)
    fill(20, 36, 8, 2, black)
    fill(28, 34, 2, 2, black)

    # Держатель (дуга)
    fill(12, 32, 2, 8, black)
    fill(34, 32, 2, 8, black)
    fill(14, 40, 2, 2, black)
    fill(32, 40, 2, 2, black)
    fill(16, 42, 4, 2, black)
    fill(28, 42, 4, 2, black)
    fill(20, 44, 8, 2, black)

    # Ножка
    fill(22, 44, 4, 6, black)

    # Подставка
    fill(16, 50, 16, 2, black)

    # Звуковые волны
    fill(42, 22, 4, 20, black)
    fill(48, 16, 4, 32, black)
    fill(54, 26, 4, 12, black)

    painter.end()
    return QIcon(pixmap)


# Версия приложения
APP_VERSION = "1.0.0"


# Classic Mac OS System 7 Style
STYLESHEET = """
/* ===== CLASSIC MAC OS SYSTEM 7 STYLE ===== */

/* Основной фон и шрифты */
QMainWindow, QWidget {
    background-color: #ffffff;
    color: #000000;
    font-family: "MS Sans Serif", "Geneva", "Arial", sans-serif;
    font-size: 12px;
}

/* Заголовки панелей */
QLabel#panelTitle {
    font-size: 14px;
    font-weight: bold;
    color: #000000;
    padding: 4px 0;
}

/* Обычные метки */
QLabel {
    color: #000000;
    background: transparent;
}

/* Разделитель */
QSplitter::handle {
    background-color: #000000;
    width: 1px;
}

/* Вкладки - классический стиль */
QTabWidget::pane {
    border: 2px solid #000000;
    background-color: #ffffff;
    margin-top: -1px;
}

QTabBar::tab {
    background-color: #dddddd;
    color: #000000;
    padding: 6px 16px;
    border: 1px solid #000000;
    border-bottom: none;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom: 1px solid #ffffff;
    margin-bottom: -1px;
}

QTabBar::tab:!selected {
    margin-top: 2px;
}

/* ComboBox - классический выпадающий список */
QComboBox {
    background-color: #ffffff;
    border: 2px solid #000000;
    border-top-color: #000000;
    border-left-color: #000000;
    border-right-color: #808080;
    border-bottom-color: #808080;
    padding: 4px 8px;
    color: #000000;
    min-height: 18px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
    background-color: #dddddd;
    border-left: 1px solid #000000;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #000000;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 2px solid #000000;
    selection-background-color: #000000;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 4px 8px;
    border: none;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #000000;
    color: #ffffff;
}

/* LineEdit - классическое текстовое поле */
QLineEdit {
    background-color: #ffffff;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    padding: 4px 6px;
    color: #000000;
}

QLineEdit:focus {
    border-color: #000000;
}

QLineEdit:read-only {
    background-color: #dddddd;
}

/* Slider - классический ползунок */
QSlider::groove:horizontal {
    background-color: #dddddd;
    border: 1px solid #000000;
    height: 8px;
}

QSlider::handle:horizontal {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    width: 12px;
    height: 18px;
    margin: -6px 0;
}

QSlider::sub-page:horizontal {
    background-color: #000000;
}

/* Кнопки - классический 3D стиль */
QPushButton {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    padding: 4px 12px;
    color: #000000;
    min-height: 18px;
}

QPushButton:hover {
    background-color: #eeeeee;
}

QPushButton:pressed {
    background-color: #cccccc;
    border-top-color: #000000;
    border-left-color: #000000;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
}

QPushButton:disabled {
    background-color: #dddddd;
    color: #808080;
}

QPushButton#downloadButton {
    background-color: #dddddd;
    font-weight: bold;
}

/* CheckBox - классический чекбокс */
QCheckBox {
    spacing: 8px;
    color: #000000;
}

QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #000000;
}

/* ProgressBar - классический прогресс-бар */
QProgressBar {
    background-color: #ffffff;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    height: 16px;
    text-align: center;
    color: #000000;
}

QProgressBar::chunk {
    background-color: #000000;
}

/* ScrollArea и ScrollBar */
QScrollArea {
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    background-color: #ffffff;
}

QScrollBar:vertical {
    background-color: #dddddd;
    width: 16px;
    border: 1px solid #000000;
}

QScrollBar::handle:vertical {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    min-height: 20px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background-color: #dddddd;
    border: 1px solid #000000;
    height: 16px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background-color: #dddddd;
}

/* Журнал */
QFrame#journalEntry {
    background-color: #ffffff;
    border: 1px solid #000000;
    padding: 4px;
    margin: 2px 0;
}

QLabel#journalTime {
    color: #000000;
    font-size: 11px;
    font-weight: bold;
}

QLabel#journalText {
    color: #000000;
    font-size: 11px;
}

/* Предупреждения */
QLabel#warning {
    color: #000000;
    font-size: 11px;
    font-style: italic;
}

/* Группы (Frame) */
QFrame {
    background-color: transparent;
}

QFrame#settingsCard {
    background-color: #ffffff;
    border: 1px solid #000000;
}
"""


class TranscribeWorker(QThread):
    progress = pyqtSignal(str, str, float)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(str, str, float, str)
    cancelled = pyqtSignal()  # Сигнал отмены

    def __init__(
        self,
        transcriber: Transcriber,
        audio_path: Path,
        model_size: str,
        compute_type: str,
        device: str,
        cpu_threads: int,
        num_workers: int,
        language: str,
        beam_size: int,
        vad_filter: bool,
        models_dir: Path,
    ) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.audio_path = audio_path
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.models_dir = models_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Отменить транскрипцию."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Проверить, отменена ли транскрипция."""
        return self._cancelled

    def _on_progress(self, status: str, current: int, total: int) -> None:
        self.status_update.emit(status)

    def run(self) -> None:
        last_text = ""
        detected_lang: str = ""
        detected_prob: float = 0.0
        try:
            if self._cancelled:
                self.cancelled.emit()
                return

            self.status_update.emit("loading_model")
            self.transcriber.load_model(
                model_size=self.model_size,
                compute_type=self.compute_type,
                device=self.device,
                cpu_threads=self.cpu_threads,
                num_workers=self.num_workers,
                models_dir=str(self.models_dir),
                progress_callback=self._on_progress,
            )

            if self._cancelled:
                self.cancelled.emit()
                return

            self.status_update.emit("transcribing")
            for partial, lang, prob in self.transcriber.transcribe_stream(
                self.audio_path,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            ):
                if self._cancelled:
                    self.cancelled.emit()
                    return
                last_text = partial
                detected_lang = lang or ""
                detected_prob = prob
                self.progress.emit(partial, detected_lang, prob)
            self.finished.emit(last_text, detected_lang, detected_prob, "")
        except Exception as exc:
            if self._cancelled:
                self.cancelled.emit()
                return
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.finished.emit(last_text, detected_lang, detected_prob, err)


class ModelDownloadWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(str, str)

    def __init__(
        self,
        transcriber: Transcriber,
        model_size: str,
        models_dir: Path,
    ) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.model_size = model_size
        self.models_dir = models_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _on_progress(self, status: str, current: int, total: int) -> None:
        if self._cancelled:
            raise InterruptedError("Download cancelled")
        self.progress.emit(status, current, total)

    def run(self) -> None:
        try:
            path = self.transcriber.download_model(
                self.model_size,
                self.models_dir,
                progress_callback=self._on_progress,
            )
            if self._cancelled:
                self.finished.emit("", "cancelled")
            else:
                self.finished.emit(str(path), "")
        except InterruptedError:
            self.finished.emit("", "cancelled")
        except Exception as exc:
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.finished.emit("", err)


class UpdateCheckWorker(QThread):
    """Воркер для асинхронной проверки обновлений."""
    finished = pyqtSignal(object)  # UpdateInfo

    def __init__(self, updater: Updater) -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        info = self.updater.check_for_updates()
        self.finished.emit(info)


class UpdateDownloadWorker(QThread):
    """Воркер для асинхронного скачивания обновлений."""
    progress = pyqtSignal(int, int)  # downloaded, total
    finished = pyqtSignal(bool, str, str)  # success, path, error

    def __init__(self, updater: Updater) -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        def on_progress(downloaded: int, total: int) -> None:
            self.progress.emit(downloaded, total)

        success, path, error = self.updater.download_update(on_progress)
        self.finished.emit(success, str(path) if path else "", error or "")


class TranscriptionEntry:
    """Запись истории транскрипции."""
    def __init__(self, text: str):
        self.time = datetime.now()
        self.text = text


class TranscriptionHistoryWidget(QWidget):
    """Виджет истории транскрипций с возможностью копирования."""

    def __init__(self, translate_func=None, parent=None):
        super().__init__(parent)
        self._entries: List[TranscriptionEntry] = []
        self._max_entries = 20
        self._translate = translate_func or (lambda x: x)
        self._build_ui()

    def set_translate_func(self, func):
        """Установить функцию перевода."""
        self._translate = func
        self._update_labels()

    def _build_ui(self):
        self.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Заголовок секции
        header = QHBoxLayout()
        self._title_label = QLabel(self._translate("history"))
        self._title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header.addWidget(self._title_label)
        header.addStretch()
        layout.addLayout(header)

        # Последняя транскрипция (крупная)
        last_section = QFrame()
        last_section.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
        """)
        last_layout = QVBoxLayout(last_section)
        last_layout.setContentsMargins(8, 8, 8, 8)
        last_layout.setSpacing(6)

        last_header = QHBoxLayout()
        self._last_label = QLabel(self._translate("last_transcription"))
        self._last_label.setStyleSheet("font-size: 11px;")
        last_header.addWidget(self._last_label)
        last_header.addStretch()

        self._copy_btn = QPushButton(self._translate("copy"))
        self._copy_btn.setMinimumWidth(70)
        self._copy_btn.clicked.connect(self._copy_last)
        last_header.addWidget(self._copy_btn)

        last_layout.addLayout(last_header)

        self._last_text = QLabel(self._translate("no_transcriptions"))
        self._last_text.setStyleSheet("font-size: 12px;")
        self._last_text.setWordWrap(True)
        self._last_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        last_layout.addWidget(self._last_text)

        layout.addWidget(last_section)

        # История (список)
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history_scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        self._history_content = QWidget()
        self._history_content.setStyleSheet("background-color: #ffffff;")
        self._history_layout = QVBoxLayout(self._history_content)
        self._history_layout.setContentsMargins(0, 0, 8, 0)
        self._history_layout.setSpacing(4)
        self._history_layout.addStretch()

        self._history_scroll.setWidget(self._history_content)
        layout.addWidget(self._history_scroll, stretch=1)

    def _update_labels(self):
        """Обновить все переводимые тексты."""
        self._title_label.setText(self._translate("history"))
        self._last_label.setText(self._translate("last_transcription"))
        self._copy_btn.setText(self._translate("copy"))
        if not self._entries:
            self._last_text.setText(self._translate("no_transcriptions"))

    def add_transcription(self, text: str):
        """Добавить новую транскрипцию."""
        if not text.strip():
            return

        entry = TranscriptionEntry(text)
        self._entries.insert(0, entry)

        # Ограничиваем количество
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[:self._max_entries]

        self._rebuild_history()

    def _rebuild_history(self):
        """Перестроить UI истории."""
        # Обновляем последнюю транскрипцию
        if self._entries:
            self._last_text.setText(self._entries[0].text)
        else:
            self._last_text.setText(self._translate("no_transcriptions"))

        # Очищаем старые элементы
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Добавляем записи (начиная со второй)
        for entry in self._entries[1:]:
            widget = self._create_history_item(entry)
            self._history_layout.insertWidget(self._history_layout.count() - 1, widget)

    def _create_history_item(self, entry: TranscriptionEntry) -> QWidget:
        """Создать элемент истории."""
        widget = QFrame()
        widget.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #000000;
            }
            QFrame:hover {
                background-color: #dddddd;
            }
        """)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Время
        time_label = QLabel(entry.time.strftime("%H:%M"))
        time_label.setStyleSheet("font-size: 11px;")
        time_label.setFixedWidth(40)
        layout.addWidget(time_label)

        # Текст (обрезаем если длинный)
        text = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        text_label = QLabel(text)
        text_label.setStyleSheet("font-size: 11px;")
        text_label.setWordWrap(False)
        layout.addWidget(text_label, stretch=1)

        # Делаем весь виджет кликабельным
        widget.mousePressEvent = lambda e, t=entry.text: self._copy_text(t)

        return widget

    def _copy_last(self):
        """Копировать последнюю транскрипцию."""
        if self._entries:
            self._copy_text(self._entries[0].text)

    def _copy_text(self, text: str):
        """Копировать текст в буфер обмена."""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

        # Показываем feedback
        original_text = self._copy_btn.text()
        self._copy_btn.setText(self._translate("copied"))
        QTimer.singleShot(1500, lambda: self._copy_btn.setText(original_text))

    def get_last_text(self) -> str:
        """Получить последнюю транскрипцию."""
        return self._entries[0].text if self._entries else ""


class JournalEntry:
    """Запись в журнале транскрипций."""
    def __init__(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True):
        self.time = datetime.now()
        self.status = status  # "success", "pending", "error"
        self.title_key = title_key  # Ключ перевода или готовый текст
        self.text = text
        self.extra_key = extra_key  # Ключ перевода или готовый текст для доп. инфо
        self.is_translatable = is_translatable  # Нужен ли перевод


class JournalWidget(QWidget):
    """Виджет журнала транскрипций."""

    def __init__(self, translate_func=None, parent=None):
        super().__init__(parent)
        self._entries: List[JournalEntry] = []
        self._max_entries = 50
        self._translate = translate_func or (lambda x: x)
        self._build_ui()

    def set_translate_func(self, func):
        """Установить функцию перевода."""
        self._translate = func
        self._rebuild_ui()

    def _build_ui(self):
        self.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Скроллящаяся область
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        self._content = QWidget()
        self._content.setStyleSheet("background-color: #ffffff;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 8, 0)
        self._content_layout.setSpacing(8)
        self._content_layout.addStretch()

        scroll.setWidget(self._content)
        layout.addWidget(scroll)

    def add_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True):
        """Добавить запись в журнал."""
        entry = JournalEntry(status, title_key, text, extra_key, is_translatable)
        self._entries.insert(0, entry)

        # Ограничиваем количество записей
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[:self._max_entries]

        self._rebuild_ui()

    def _rebuild_ui(self):
        """Перестроить UI журнала."""
        # Удаляем старые виджеты
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Добавляем записи
        for entry in self._entries:
            widget = self._create_entry_widget(entry)
            self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def _create_entry_widget(self, entry: JournalEntry) -> QWidget:
        """Создать виджет записи."""
        widget = QFrame()
        widget.setObjectName("journalEntry")
        widget.setFrameShape(QFrame.Shape.StyledPanel)
        widget.setStyleSheet("""
            QFrame#journalEntry {
                background-color: #ffffff;
                border: 1px solid #000000;
            }
            QFrame#journalEntry QLabel {
                background: transparent;
            }
        """)

        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Время
        time_label = QLabel(entry.time.strftime("%H:%M:%S"))
        time_label.setObjectName("journalTime")
        time_label.setFixedWidth(60)
        time_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(time_label)

        # Статус-индикатор (точка)
        status_dot = QLabel("*")
        status_dot.setStyleSheet("font-size: 12px;")
        status_dot.setFixedWidth(16)
        layout.addWidget(status_dot)

        # Контент
        content_layout = QVBoxLayout()
        content_layout.setSpacing(2)

        # Заголовок со статусом
        title_row = QHBoxLayout()

        status_label = QLabel()
        if entry.status == "success":
            status_label.setText("[OK]")
            status_label.setStyleSheet("font-weight: bold;")
        elif entry.status == "pending":
            status_label.setText("[...]")
        else:
            status_label.setText("[X]")
            status_label.setStyleSheet("font-weight: bold;")
        title_row.addWidget(status_label)

        # Переводим заголовок если нужно
        title_text = self._translate(entry.title_key) if entry.is_translatable else entry.title_key
        title_label = QLabel(title_text)
        title_label.setStyleSheet("font-weight: bold;")
        title_row.addWidget(title_label)
        title_row.addStretch()

        content_layout.addLayout(title_row)

        # Текст (если есть)
        if entry.text:
            text_label = QLabel(entry.text[:100] + "..." if len(entry.text) > 100 else entry.text)
            text_label.setObjectName("journalText")
            text_label.setWordWrap(True)
            content_layout.addWidget(text_label)

        # Дополнительная информация (если есть)
        if entry.extra_key:
            # Переводим extra если нужно
            extra_text = self._translate(entry.extra_key) if entry.is_translatable else entry.extra_key
            extra_label = QLabel(extra_text)
            extra_label.setStyleSheet("font-size: 11px; font-style: italic;")
            content_layout.addWidget(extra_label)

        layout.addLayout(content_layout, stretch=1)

        return widget

    def clear(self):
        """Очистить журнал."""
        self._entries = []
        self._rebuild_ui()


class MicLevelWidget(QWidget):
    """Индикатор уровня микрофона с цветовой шкалой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 20)
        self._level = 0.0
        self._peak = 0.0
        self._peak_decay = 0.02

    def set_level(self, level: float) -> None:
        """Установить уровень (0.0 - 1.0)."""
        self._level = max(0.0, min(1.0, level))
        # Обновляем пик
        if self._level > self._peak:
            self._peak = self._level
        else:
            self._peak = max(0.0, self._peak - self._peak_decay)
        self.update()

    def reset(self) -> None:
        """Сбросить уровень."""
        self._level = 0.0
        self._peak = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QPainter, QColor, QPainterPath, QLinearGradient, QBrush

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        radius = 4

        # Фон
        bg_path = QPainterPath()
        bg_path.addRoundedRect(0, 0, w, h, radius, radius)
        painter.fillPath(bg_path, QColor(30, 30, 35, 200))

        # Градиент для индикатора уровня
        level_width = max(0, int((w - 4) * self._level))
        if level_width > 0:
            gradient = QLinearGradient(2, 0, w - 2, 0)
            gradient.setColorAt(0.0, QColor(80, 200, 120))     # Зелёный
            gradient.setColorAt(0.6, QColor(200, 200, 80))     # Жёлтый
            gradient.setColorAt(0.85, QColor(255, 140, 80))    # Оранжевый
            gradient.setColorAt(1.0, QColor(255, 80, 80))      # Красный

            level_path = QPainterPath()
            level_path.addRoundedRect(2, 2, level_width, h - 4, radius - 1, radius - 1)
            painter.fillPath(level_path, QBrush(gradient))

        # Индикатор пика (вертикальная линия)
        if self._peak > 0.05:
            peak_x = 2 + int((w - 4) * self._peak)
            peak_color = QColor(255, 255, 255, 180)
            painter.setPen(peak_color)
            painter.drawLine(peak_x, 3, peak_x, h - 3)

        # Рамка
        painter.setPen(QColor(60, 60, 65))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, radius, radius)


class MainWindow(QMainWindow):
    hotkey_press_signal = pyqtSignal()
    hotkey_release_signal = pyqtSignal()
    hotkey_recorded_signal = pyqtSignal(str)
    waveform_signal = pyqtSignal(list)
    mic_level_signal = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("MindType")
        self.setWindowIcon(create_app_icon(64))
        self.setFixedSize(600, 600)

        self.config = ConfigManager()
        self.audio = AudioRecorder()
        self.transcriber = Transcriber()
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.hotkey_recorder: Optional[HotkeyRecorder] = None

        # Determine models directory
        exe_path = Path(sys.executable).resolve()
        exe_dir = exe_path.parent

        # Check if we're in Nuitka standalone dist (MindType.exe next to python.exe)
        is_nuitka_dist = (exe_dir / "MindType.exe").exists()
        is_compiled = getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__") or is_nuitka_dist

        if is_compiled:
            self.models_dir = exe_dir / "models"
        else:
            self.models_dir = Path(self.config.config.get("models_dir", str(DEFAULT_MODELS_DIR)))

        # Ensure models directory exists
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._transcribe_thread: Optional[TranscribeWorker] = None
        self._download_thread: Optional[ModelDownloadWorker] = None
        self.last_text: str = ""
        self._auto_insert_pending = False
        self._recording_hotkey = False
        self._recording_start_time = None  # Время начала записи для учёта trial
        self._really_quit = False  # Флаг для полного выхода
        self._transcription_in_progress = False  # Флаг активной транскрипции

        # Текущий язык интерфейса
        self._ui_lang = self.config.config.get("ui_language", "ru")

        # Система лицензирования
        self.license_manager = LicenseManager()

        # Система обновлений
        self.updater = Updater()
        self._update_check_worker: Optional[UpdateCheckWorker] = None
        self._update_download_worker: Optional[UpdateDownloadWorker] = None

        # Overlay виджет
        self.overlay = OverlayWidget()
        self._apply_overlay_settings()

        # Системный трей
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._setup_tray()

        self._build_ui()
        self._connect_signals()
        self._load_initial_state()
        self._init_hotkey()
        self._setup_focus_manager()

        # Check if models exist, show download dialog if not
        QTimer.singleShot(500, self._check_models_on_startup)

    def _check_models_on_startup(self) -> None:
        """Check if any models are available, prompt to download if not."""
        if not self._has_any_model():
            self._show_first_run_dialog()

    def _has_any_model(self) -> bool:
        """Check if at least one model is downloaded."""
        if not self.models_dir.exists():
            return False
        for subdir in self.models_dir.iterdir():
            if subdir.is_dir() and (subdir / "model.bin").exists():
                return True
        return False

    def _show_first_run_dialog(self) -> None:
        """Show dialog to download model on first run."""
        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("first_run_title"))
        dialog.setFixedWidth(480)
        dialog.setModal(True)

        # Classic Mac OS style
        dialog.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
            QLabel {
                color: #000000;
                font-family: "Chicago", "Geneva", sans-serif;
            }
            QComboBox {
                padding: 4px 8px;
                border: 2px solid #000000;
                background: #ffffff;
                font-family: "Chicago", "Geneva", sans-serif;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #000000;
            }
            QPushButton {
                padding: 6px 16px;
                border: 2px solid #000000;
                background: #ffffff;
                font-family: "Chicago", "Geneva", sans-serif;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #000000;
                color: #ffffff;
            }
            QPushButton:disabled {
                border-color: #888888;
                color: #888888;
            }
            QProgressBar {
                border: 2px solid #000000;
                background: #ffffff;
                text-align: center;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #000000;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Welcome message
        welcome = QLabel(self._t("first_run_welcome"))
        welcome.setWordWrap(True)
        layout.addWidget(welcome)

        # Model selection
        model_label = QLabel(self._t("first_run_select_model"))
        model_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(model_label)

        # Dropdown for model selection
        self._first_run_model_combo = QComboBox()

        models_info = [
            ("tiny", "~75 MB", self._t("model_tiny_desc")),
            ("small", "~150 MB", self._t("model_small_desc")),
            ("medium", "~1.5 GB", self._t("model_medium_desc")),
            ("large-v3", "~3 GB", self._t("model_large_desc")),
        ]

        for model_id, size, desc in models_info:
            # Check if model is already downloaded
            model_path = self.models_dir / model_id
            is_downloaded = model_path.exists() and (model_path / "model.bin").exists()

            if is_downloaded:
                label = f"[OK] {model_id} ({size}) - {desc}"
            else:
                label = f"{model_id} ({size}) - {desc}"

            self._first_run_model_combo.addItem(label, model_id)

        layout.addWidget(self._first_run_model_combo)

        # Progress section (hidden initially)
        self._first_run_progress = QProgressBar()
        self._first_run_progress.setVisible(False)
        layout.addWidget(self._first_run_progress)

        self._first_run_status = QLabel("")
        self._first_run_status.setVisible(False)
        self._first_run_status.setWordWrap(True)
        layout.addWidget(self._first_run_status)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._first_run_download_btn = QPushButton(self._t("download_model"))
        self._first_run_download_btn.clicked.connect(lambda: self._start_first_run_download(dialog))
        btn_layout.addWidget(self._first_run_download_btn)

        self._first_run_skip_btn = QPushButton(self._t("skip"))
        self._first_run_skip_btn.clicked.connect(lambda: self._cancel_first_run_download(dialog))
        btn_layout.addWidget(self._first_run_skip_btn)

        layout.addLayout(btn_layout)

        dialog.exec()

        # Cancel download if still running when dialog closes
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()

    def _cancel_first_run_download(self, dialog) -> None:
        """Cancel download and close dialog."""
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
        dialog.reject()

    def _populate_model_combo(self) -> None:
        """Populate model combo box with download status indicators."""
        self.model_box.clear()
        models = ["large-v3", "medium", "small", "tiny", "distil-large-v2", "distil-large-v3"]

        for name in models:
            model_path = self.models_dir / name
            is_downloaded = model_path.exists() and (model_path / "model.bin").exists()

            if is_downloaded:
                self.model_box.addItem(f"[OK] {name}", name)
            else:
                self.model_box.addItem(name, name)

    def _set_model_combo_value(self, model_name: str) -> None:
        """Set model combo box value by model name (data)."""
        for i in range(self.model_box.count()):
            if self.model_box.itemData(i) == model_name:
                self.model_box.setCurrentIndex(i)
                return
        # Fallback: try to find by text
        idx = self.model_box.findText(model_name)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)

    def _start_first_run_download(self, dialog) -> None:
        """Start downloading the selected model."""
        self._first_run_progress.setVisible(True)
        self._first_run_status.setVisible(True)
        self._first_run_download_btn.setEnabled(False)
        self._first_run_model_combo.setEnabled(False)
        self._first_run_skip_btn.setText(self._t("cancel"))

        selected_model = self._first_run_model_combo.currentData()

        worker = ModelDownloadWorker(
            self.transcriber, selected_model, self.models_dir
        )
        worker.progress.connect(self._on_first_run_progress)
        worker.finished.connect(lambda path, err: self._on_first_run_finished(dialog, path, err, selected_model))
        self._download_thread = worker
        worker.start()

    def _on_first_run_progress(self, status: str, current: int, total: int) -> None:
        self._first_run_progress.setValue(current)
        self._first_run_status.setText(status)

    def _on_first_run_finished(self, dialog, path: str, err: str, selected_model: str) -> None:
        if err == "cancelled":
            # Download was cancelled, just close dialog
            return
        elif err:
            self._first_run_status.setText(f"Error: {err}")
            self._first_run_download_btn.setEnabled(True)
            self._first_run_model_combo.setEnabled(True)
            self._first_run_skip_btn.setEnabled(True)
        else:
            # Update config with downloaded model and refresh combo
            self.config.update(model_size=selected_model)
            self._populate_model_combo()  # Refresh to show [OK]
            self._set_model_combo_value(selected_model)
            dialog.accept()

    def _t(self, key: str) -> str:
        """Получить перевод для текущего языка."""
        return get_text(key, self._ui_lang)

    def _build_ui(self) -> None:
        # Применяем стиль Classic Mac OS
        self.setStyleSheet(STYLESHEET)

        # Главный контейнер
        central = QWidget()
        central.setStyleSheet("background-color: #ffffff;")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Вкладки - всё в одном месте
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), self._t("basic"))
        self.tabs.addTab(self._build_additional_tab(), self._t("additional"))
        self.tabs.addTab(self._build_history_tab(), self._t("history"))
        main_layout.addWidget(self.tabs)

        self.setCentralWidget(central)

    def _build_basic_tab(self) -> QWidget:
        """Построить вкладку основных настроек."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")
        layout = QGridLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(8)
        layout.setColumnStretch(1, 1)

        row = 0

        # Аудио вход
        self.audio_input_label = QLabel(self._t("audio_input"))
        self.mic_box = QComboBox()
        layout.addWidget(self.audio_input_label, row, 0)
        layout.addWidget(self.mic_box, row, 1)
        row += 1

        # Хоткей
        self.hotkey_label = QLabel(self._t("hotkey"))
        hotkey_row = QHBoxLayout()
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setPlaceholderText("ctrl+alt+v")
        self.hotkey_edit.setReadOnly(True)
        self.hotkey_record_btn = QPushButton(self._t("record_hotkey"))
        hotkey_row.addWidget(self.hotkey_edit)
        hotkey_row.addWidget(self.hotkey_record_btn)
        layout.addWidget(self.hotkey_label, row, 0)
        layout.addLayout(hotkey_row, row, 1)
        row += 1

        # Язык приложения
        self.ui_lang_label = QLabel(self._t("ui_language"))
        self.ui_lang_box = QComboBox()
        for code, name in UI_LANGUAGES.items():
            self.ui_lang_box.addItem(name, code)
        layout.addWidget(self.ui_lang_label, row, 0)
        layout.addWidget(self.ui_lang_box, row, 1)
        row += 1

        # Язык транскрипции
        self.trans_lang_label = QLabel(self._t("transcription_language"))
        self.trans_lang_box = QComboBox()
        for code, name in WHISPER_LANGUAGES.items():
            display = f"{name} ({code.upper()})" if code != "auto" else name
            self.trans_lang_box.addItem(display, code)
        layout.addWidget(self.trans_lang_label, row, 0)
        layout.addWidget(self.trans_lang_box, row, 1)
        row += 1

        # Модель
        self.model_label = QLabel(self._t("model"))
        self.model_box = QComboBox()
        self._populate_model_combo()
        layout.addWidget(self.model_label, row, 0)
        layout.addWidget(self.model_box, row, 1)
        row += 1

        # Предупреждение о distil
        self.distil_warning = QLabel(self._t("distil_en_only"))
        self.distil_warning.setObjectName("warning")
        layout.addWidget(self.distil_warning, row, 1)
        row += 1

        # Квантование
        self.quant_label = QLabel(self._t("quantization"))
        self.compute_box = QComboBox()
        for ct in ["auto", "int8", "int8_float16", "float16", "float32"]:
            self.compute_box.addItem(ct)
        layout.addWidget(self.quant_label, row, 0)
        layout.addWidget(self.compute_box, row, 1)
        row += 1

        # Устройство
        self.device_label = QLabel(self._t("device"))
        self.device_box = QComboBox()
        for dev in ["auto", "cuda", "cpu"]:
            self.device_box.addItem(dev)
        layout.addWidget(self.device_label, row, 0)
        layout.addWidget(self.device_box, row, 1)
        row += 1

        # Кнопка скачивания модели
        self.download_btn = QPushButton(self._t("download_model"))
        self.download_btn.setObjectName("downloadButton")
        layout.addWidget(self.download_btn, row, 0, 1, 2)
        row += 1

        # Прогресс скачивания
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(True)
        layout.addWidget(self.download_progress, row, 0, 1, 2)
        row += 1

        self.download_status_label = QLabel("")
        layout.addWidget(self.download_status_label, row, 0, 1, 2)
        row += 1

        # Статус лицензии
        self.license_status_label = QLabel(self._t("license_status"))
        self.license_status_widget = LicenseStatusWidget(
            self.license_manager,
            translate_func=self._t
        )
        self.license_status_widget.clicked.connect(self._show_license_dialog)
        layout.addWidget(self.license_status_label, row, 0)
        layout.addWidget(self.license_status_widget, row, 1)
        row += 1

        # Разделитель
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #cccccc;")
        layout.addWidget(separator, row, 0, 1, 2)
        row += 1

        # Обновления
        self.update_label = QLabel(self._t("current_version"))
        update_row = QHBoxLayout()

        # Получаем версию из env
        try:
            from .env import APP_VERSION
            current_ver = APP_VERSION
        except ImportError:
            current_ver = "1.0.0"

        self.update_version_label = QLabel(f"v{current_ver}")
        self.update_version_label.setStyleSheet("font-weight: bold;")
        update_row.addWidget(self.update_version_label)
        update_row.addStretch()

        self.check_update_btn = QPushButton(self._t("check_updates"))
        self.check_update_btn.clicked.connect(self._check_for_updates)
        update_row.addWidget(self.check_update_btn)

        layout.addWidget(self.update_label, row, 0)
        layout.addLayout(update_row, row, 1)
        row += 1

        # Статус обновления
        self.update_status_label = QLabel("")
        self.update_status_label.setStyleSheet("font-size: 11px;")
        self.update_status_label.setVisible(False)
        layout.addWidget(self.update_status_label, row, 0, 1, 2)
        row += 1

        # Прогресс-бар обновления
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setVisible(False)
        layout.addWidget(self.update_progress, row, 0, 1, 2)
        row += 1

        # Кнопка поддержки
        self.support_label = QLabel(self._t("contact_support"))
        self.support_btn = QPushButton("help@mindtype.space")
        self.support_btn.setStyleSheet("font-size: 11px;")
        self.support_btn.clicked.connect(self._on_contact_support)
        layout.addWidget(self.support_label, row, 0)
        layout.addWidget(self.support_btn, row, 1)
        row += 1

        layout.setRowStretch(row, 1)
        return tab

    def _build_additional_tab(self) -> QWidget:
        """Построить вкладку дополнительных настроек."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        # === Секция Производительность ===
        perf_section = QWidget()
        perf_layout = QGridLayout(perf_section)
        perf_layout.setContentsMargins(0, 0, 0, 0)
        perf_layout.setSpacing(8)
        perf_layout.setColumnStretch(1, 1)

        perf_row = 0

        # Заголовок секции
        self.perf_section_label = QLabel(self._t("performance_section"))
        self.perf_section_label.setStyleSheet("font-weight: bold;")
        perf_layout.addWidget(self.perf_section_label, perf_row, 0, 1, 2)
        perf_row += 1

        # VAD Filter (чекбокс)
        self.vad_label = QLabel(self._t("vad_filter"))
        self.vad_toggle = QCheckBox()
        self.vad_toggle.setChecked(True)
        perf_layout.addWidget(self.vad_label, perf_row, 0)
        perf_layout.addWidget(self.vad_toggle, perf_row, 1)
        perf_row += 1

        # Размер луча
        self.beam_label = QLabel(self._t("beam_size"))
        beam_row = QHBoxLayout()
        self.beam_slider = QSlider(Qt.Orientation.Horizontal)
        self.beam_slider.setRange(1, 10)
        self.beam_slider.setValue(5)
        self.beam_value_label = QLabel("5")
        self.beam_value_label.setFixedWidth(30)
        beam_row.addWidget(self.beam_slider)
        beam_row.addWidget(self.beam_value_label)
        perf_layout.addWidget(self.beam_label, perf_row, 0)
        perf_layout.addLayout(beam_row, perf_row, 1)
        perf_row += 1

        # Путь модели
        self.model_path_label = QLabel(self._t("model_path"))
        self.models_path_edit = QLineEdit()
        self.models_path_edit.setText(str(self.models_dir))
        self.models_path_edit.setReadOnly(True)
        perf_layout.addWidget(self.model_path_label, perf_row, 0)
        perf_layout.addWidget(self.models_path_edit, perf_row, 1)
        perf_row += 1

        layout.addWidget(perf_section)

        # === Секция Overlay ===
        overlay_section = QWidget()
        overlay_layout = QGridLayout(overlay_section)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(8)
        overlay_layout.setColumnStretch(1, 1)

        overlay_row = 0

        # Заголовок секции
        self.overlay_section_label = QLabel(self._t("overlay_section"))
        self.overlay_section_label.setStyleSheet("font-weight: bold;")
        overlay_layout.addWidget(self.overlay_section_label, overlay_row, 0, 1, 2)
        overlay_row += 1

        # Позиция
        self.position_label = QLabel(self._t("position"))
        self.overlay_position_box = QComboBox()
        positions = [
            ("bottom-center", "bottom_center"),
            ("top-center", "top_center"),
            ("bottom-right", "bottom_right"),
            ("bottom-left", "bottom_left"),
            ("top-right", "top_right"),
            ("top-left", "top_left"),
        ]
        for key, text_key in positions:
            self.overlay_position_box.addItem(self._t(text_key), key)
        overlay_layout.addWidget(self.position_label, overlay_row, 0)
        overlay_layout.addWidget(self.overlay_position_box, overlay_row, 1)
        overlay_row += 1

        # Отступ
        self.margin_label = QLabel(self._t("margin"))
        margin_row = QHBoxLayout()
        self.overlay_margin_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_margin_slider.setRange(0, 100)
        self.overlay_margin_slider.setValue(20)
        self.overlay_margin_value = QLabel("20")
        self.overlay_margin_value.setFixedWidth(40)
        margin_row.addWidget(self.overlay_margin_slider)
        margin_row.addWidget(self.overlay_margin_value)
        overlay_layout.addWidget(self.margin_label, overlay_row, 0)
        overlay_layout.addLayout(margin_row, overlay_row, 1)
        overlay_row += 1

        # Усиление волны
        self.wave_gain_label = QLabel(self._t("wave_gain"))
        gain_row = QHBoxLayout()
        self.overlay_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_gain_slider.setRange(10, 100)
        self.overlay_gain_slider.setValue(15)
        self.overlay_gain_value = QLabel("1.5")
        self.overlay_gain_value.setFixedWidth(40)
        gain_row.addWidget(self.overlay_gain_slider)
        gain_row.addWidget(self.overlay_gain_value)
        overlay_layout.addWidget(self.wave_gain_label, overlay_row, 0)
        overlay_layout.addLayout(gain_row, overlay_row, 1)
        overlay_row += 1

        # Прозрачность
        self.opacity_label = QLabel(self._t("opacity"))
        opacity_row = QHBoxLayout()
        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(50, 255)
        self.overlay_opacity_slider.setValue(230)
        self.overlay_preview_btn = QPushButton(self._t("preview"))
        opacity_row.addWidget(self.overlay_opacity_slider)
        opacity_row.addWidget(self.overlay_preview_btn)
        overlay_layout.addWidget(self.opacity_label, overlay_row, 0)
        overlay_layout.addLayout(opacity_row, overlay_row, 1)
        overlay_row += 1

        layout.addWidget(overlay_section)
        layout.addStretch()

        return tab

    def _on_ui_language_changed(self, idx: int) -> None:
        """Сменить язык интерфейса."""
        code = self.ui_lang_box.currentData()
        if code and code != self._ui_lang:
            self._ui_lang = code
            self.config.update(ui_language=code)
            self._update_ui_texts()

    def _build_history_tab(self) -> QWidget:
        """Построить вкладку истории и журнала."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        # === История транскрипций ===
        self.transcription_history = TranscriptionHistoryWidget(translate_func=self._t)
        layout.addWidget(self.transcription_history, stretch=3)

        # === Журнал ===
        journal_header = QHBoxLayout()
        self.journal_title = QLabel(self._t("journal"))
        self.journal_title.setStyleSheet("font-weight: bold;")
        journal_header.addWidget(self.journal_title)
        journal_header.addStretch()

        self.clear_journal_btn = QPushButton(self._t("clear_journal"))
        self.clear_journal_btn.clicked.connect(self._clear_journal)
        journal_header.addWidget(self.clear_journal_btn)
        layout.addLayout(journal_header)

        self.journal = JournalWidget(translate_func=self._t)
        layout.addWidget(self.journal, stretch=2)

        return tab

    def _clear_journal(self):
        """Очистить журнал событий."""
        self.journal.clear()

    def _connect_signals(self) -> None:
        self.download_btn.clicked.connect(self._toggle_download)

        # Push-to-Talk сигналы
        self.hotkey_press_signal.connect(self._handle_hotkey_press)
        self.hotkey_release_signal.connect(self._handle_hotkey_release)
        self.hotkey_recorded_signal.connect(self._on_hotkey_recorded)
        self.waveform_signal.connect(self._update_waveform)

        # Настройки
        self.ui_lang_box.currentIndexChanged.connect(self._on_ui_lang_change)
        self.trans_lang_box.currentIndexChanged.connect(self._on_trans_lang_change)
        self.model_box.currentIndexChanged.connect(self._on_model_change)
        self.compute_box.currentTextChanged.connect(lambda v: self.config.update(compute_type=v))
        self.device_box.currentTextChanged.connect(lambda v: self.config.update(device=v))
        self.mic_box.currentTextChanged.connect(self._on_mic_change)
        self.hotkey_record_btn.clicked.connect(self._start_hotkey_recording)

        # Дополнительные
        self.vad_toggle.toggled.connect(lambda v: self.config.update(vad_filter=v))
        self.beam_slider.valueChanged.connect(self._on_beam_change)

        # Overlay настройки
        self.overlay_position_box.currentIndexChanged.connect(self._on_overlay_position_change)
        self.overlay_margin_slider.valueChanged.connect(self._on_overlay_margin_change)
        self.overlay_gain_slider.valueChanged.connect(self._on_overlay_gain_change)
        self.overlay_opacity_slider.valueChanged.connect(self._on_overlay_opacity_change)
        self.overlay_preview_btn.clicked.connect(self._test_overlay)

        # Сигналы уровня микрофона
        self.mic_level_signal.connect(self._update_mic_level)

        # Отмена транскрипции через overlay
        self.overlay.cancelled.connect(self._cancel_transcription)

    def _load_initial_state(self) -> None:
        cfg = self.config.config

        # Язык интерфейса
        ui_lang = cfg.get("ui_language", "ru")
        idx = self.ui_lang_box.findData(ui_lang)
        if idx >= 0:
            self.ui_lang_box.setCurrentIndex(idx)

        # Язык транскрипции
        trans_lang = cfg.get("language", "ru")
        idx = self.trans_lang_box.findData(trans_lang)
        if idx >= 0:
            self.trans_lang_box.setCurrentIndex(idx)

        # Модель и устройства
        self._set_model_combo_value(cfg.get("model_size", "large-v3"))
        self.compute_box.setCurrentText(cfg.get("compute_type", "int8"))
        self.device_box.setCurrentText(cfg.get("device", "auto"))

        # Хоткей
        hotkey = cfg.get("hotkey", "ctrl+alt+v")
        self.hotkey_edit.setText(hotkey)

        # Дополнительные
        self.vad_toggle.setChecked(bool(cfg.get("vad_filter", True)))
        beam = int(cfg.get("beam_size", 5))
        self.beam_slider.setValue(beam)
        self.beam_value_label.setText(str(beam))

        # Микрофоны
        self._load_mics()
        mic = cfg.get("microphone")
        if mic:
            idx = self.mic_box.findText(mic)
            if idx >= 0:
                self.mic_box.setCurrentIndex(idx)

        # Overlay настройки
        position = cfg.get("overlay_position", "bottom-center")
        pos_idx = self.overlay_position_box.findData(position)
        if pos_idx >= 0:
            self.overlay_position_box.setCurrentIndex(pos_idx)

        margin = int(cfg.get("overlay_margin", 20))
        self.overlay_margin_slider.setValue(margin)
        self.overlay_margin_value.setText(str(margin))

        gain = float(cfg.get("overlay_wave_gain", 1.5))
        self.overlay_gain_slider.setValue(int(gain * 10))
        self.overlay_gain_value.setText(f"{gain:.1f}")

        opacity = int(cfg.get("overlay_opacity", 230))
        self.overlay_opacity_slider.setValue(opacity)

        self.config.update(models_dir=str(self.models_dir))

    def _load_mics(self) -> None:
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        for dev in self.audio.list_input_devices():
            self.mic_box.addItem(dev)
        self.mic_box.blockSignals(False)

    def _on_mic_change(self, value: str) -> None:
        self.config.update(microphone=value)
        # Обновляем описание микрофона в UI
        if hasattr(self, 'mic_desc_label'):
            mic_name = value.split(":")[1].strip() if ":" in value else value
            self.mic_desc_label.setText(mic_name)

    def _update_mic_level(self, level: float) -> None:
        """Обновить индикатор уровня микрофона (Qt thread)."""
        # Мониторинг микрофона убран из нового UI
        pass

    def _on_ui_lang_change(self, index: int) -> None:
        """Обработчик изменения языка интерфейса."""
        lang = self.ui_lang_box.itemData(index)
        if lang and lang != self._ui_lang:
            self._ui_lang = lang
            self.config.update(ui_language=lang)
            self._update_ui_texts()

    def _on_trans_lang_change(self, index: int) -> None:
        """Обработчик изменения языка транскрипции."""
        lang = self.trans_lang_box.itemData(index)
        if lang:
            self.config.update(language=lang)

    def _on_model_change(self, index: int) -> None:
        """Обработчик изменения модели."""
        model = self.model_box.itemData(index)
        if model:
            self.config.update(model_size=model)

    def _on_beam_change(self, value: int) -> None:
        """Обработчик изменения beam size."""
        self.beam_value_label.setText(str(value))
        self.config.update(beam_size=value)

    def _on_overlay_position_change(self, index: int) -> None:
        """Обработчик изменения позиции overlay."""
        position = self.overlay_position_box.itemData(index)
        self.config.update(overlay_position=position)
        self.overlay.set_corner(position)

    def _on_overlay_margin_change(self, value: int) -> None:
        """Обработчик изменения отступа overlay."""
        self.overlay_margin_value.setText(str(value))
        self.config.update(overlay_margin=value)
        self.overlay.set_margin(value)

    def _on_overlay_gain_change(self, value: int) -> None:
        """Обработчик изменения усиления волн."""
        gain = value / 10.0
        self.overlay_gain_value.setText(f"{gain:.1f}")
        self.config.update(overlay_wave_gain=gain)
        self.overlay.set_wave_gain(gain)

    def _on_overlay_opacity_change(self, value: int) -> None:
        """Обработчик изменения прозрачности фона."""
        self.config.update(overlay_opacity=value)
        self.overlay.set_bg_opacity(value)

    def _test_overlay(self) -> None:
        """Показать превью overlay для теста настроек."""
        self.overlay.show_recording()
        import random
        test_levels = [random.uniform(0.1, 0.5) for _ in range(32)]
        self.overlay.update_waveform(test_levels)
        QTimer.singleShot(3000, self.overlay.hide_overlay)

    def _update_ui_texts(self) -> None:
        """Обновить все тексты интерфейса."""
        # Вкладки
        self.tabs.setTabText(0, self._t("basic"))
        self.tabs.setTabText(1, self._t("additional"))
        self.tabs.setTabText(2, self._t("history"))

        # Основная вкладка
        self.audio_input_label.setText(self._t("audio_input"))
        self.hotkey_label.setText(self._t("hotkey"))
        self.hotkey_record_btn.setText(self._t("record_hotkey"))
        self.ui_lang_label.setText(self._t("ui_language"))
        self.trans_lang_label.setText(self._t("transcription_language"))
        self.model_label.setText(self._t("model"))
        self.distil_warning.setText(self._t("distil_en_only"))
        self.quant_label.setText(self._t("quantization"))
        self.device_label.setText(self._t("device"))
        self.download_btn.setText(self._t("download_model"))
        self.license_status_label.setText(self._t("license_status"))

        # Дополнительная вкладка
        self.perf_section_label.setText(self._t("performance_section"))
        self.vad_label.setText(self._t("vad_filter"))
        self.beam_label.setText(self._t("beam_size"))
        self.model_path_label.setText(self._t("model_path"))

        self.overlay_section_label.setText(self._t("overlay_section"))
        self.position_label.setText(self._t("position"))
        self.margin_label.setText(self._t("margin"))
        self.wave_gain_label.setText(self._t("wave_gain"))
        self.opacity_label.setText(self._t("opacity"))
        self.overlay_preview_btn.setText(self._t("preview"))

        # Обновляем позиции в комбобоксе
        current_pos = self.overlay_position_box.currentData()
        self.overlay_position_box.clear()
        positions = [
            ("bottom-center", "bottom_center"),
            ("top-center", "top_center"),
            ("bottom-right", "bottom_right"),
            ("bottom-left", "bottom_left"),
            ("top-right", "top_right"),
            ("top-left", "top_left"),
        ]
        for key, text_key in positions:
            self.overlay_position_box.addItem(self._t(text_key), key)
        idx = self.overlay_position_box.findData(current_pos)
        if idx >= 0:
            self.overlay_position_box.setCurrentIndex(idx)

        # История транскрипций
        self.transcription_history.set_translate_func(self._t)

        # Журнал
        self.journal_title.setText(self._t("journal"))
        self.clear_journal_btn.setText(self._t("clear_journal"))
        self.journal.set_translate_func(self._t)

        # Системный трей
        self._update_tray_menu_texts()

        # Лицензия
        self.license_status_widget.set_translate_func(self._t)

        # Обновления
        self.update_label.setText(self._t("current_version"))
        if self.updater.status != UpdateStatus.AVAILABLE:
            self.check_update_btn.setText(self._t("check_updates"))

        # Поддержка
        self.support_label.setText(self._t("contact_support"))

    def _setup_focus_manager(self) -> None:
        """Настроить менеджер фокуса с handle нашего окна."""
        hwnd = int(self.winId())
        focus_manager.set_our_window(hwnd)
        self._add_journal_entry("success", "ready", is_translatable=True)

    def _setup_tray(self) -> None:
        """Настроить системный трей."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_app_icon(64, recording=False))
        self.tray_icon.setToolTip("MindType")

        # Контекстное меню
        tray_menu = QMenu()

        # Показать окно
        self.tray_show_action = QAction(self._t("show_window"), self)
        self.tray_show_action.triggered.connect(self._tray_show_window)
        tray_menu.addAction(self.tray_show_action)

        # Начать запись
        self.tray_record_action = QAction(self._t("start_recording"), self)
        self.tray_record_action.triggered.connect(self._tray_start_recording)
        tray_menu.addAction(self.tray_record_action)

        tray_menu.addSeparator()

        # Выход
        self.tray_exit_action = QAction(self._t("exit"), self)
        self.tray_exit_action.triggered.connect(self._tray_exit)
        tray_menu.addAction(self.tray_exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Обработчик активации иконки в трее."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_show_window(self) -> None:
        """Показать главное окно."""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_start_recording(self) -> None:
        """Начать запись из трея."""
        if not self.audio.recording:
            focus_manager.save_current_window()
            self._start_recording_with_overlay()

    def _tray_exit(self) -> None:
        """Полностью закрыть приложение."""
        self._really_quit = True
        self.close()

    def _update_tray_icon(self, recording: bool) -> None:
        """Обновить иконку в трее."""
        if self.tray_icon:
            self.tray_icon.setIcon(create_app_icon(64, recording=recording))

    def _update_tray_menu_texts(self) -> None:
        """Обновить тексты меню трея."""
        if self.tray_icon:
            self.tray_show_action.setText(self._t("show_window"))
            self.tray_record_action.setText(self._t("start_recording"))
            self.tray_exit_action.setText(self._t("exit"))

    def _apply_overlay_settings(self) -> None:
        """Применить настройки overlay из конфига."""
        cfg = self.config.config
        self.overlay.set_corner(cfg.get("overlay_position", "bottom-center"))
        self.overlay.set_margin(int(cfg.get("overlay_margin", 20)))
        self.overlay.set_wave_gain(float(cfg.get("overlay_wave_gain", 1.5)))
        self.overlay.set_bg_opacity(int(cfg.get("overlay_opacity", 230)))

    def _init_hotkey(self) -> None:
        combo = self.config.config.get("hotkey", "ctrl+alt+v")
        self.hotkey_listener = HotkeyListener(
            combo,
            on_press=self._emit_hotkey_press,
            on_release=self._emit_hotkey_release,
            push_to_talk=True,
        )
        try:
            self.hotkey_listener.start()
            self._add_journal_entry("success", "hotkey_activated", extra_key="push_to_talk", is_translatable=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)

    def _start_hotkey_recording(self) -> None:
        """Начать запись нового хоткея."""
        if self._recording_hotkey:
            return

        if self.hotkey_listener:
            self.hotkey_listener.stop()

        self._recording_hotkey = True

        # Обновляем UI для индикации записи
        self.hotkey_edit.setText(self._t("press_combination"))
        self.hotkey_record_btn.setEnabled(False)

        def on_recorded(combo: str) -> None:
            self.hotkey_recorded_signal.emit(combo)

        self.hotkey_recorder = HotkeyRecorder(on_recorded)
        self.hotkey_recorder.start()

    def _on_hotkey_recorded(self, combo: str) -> None:
        """Обработчик записанного хоткея (Qt thread)."""
        self._recording_hotkey = False

        # Восстанавливаем UI
        self.hotkey_record_btn.setEnabled(True)

        if self.hotkey_recorder:
            self.hotkey_recorder.stop()
            self.hotkey_recorder = None

        # Обновляем хоткей
        self.hotkey_edit.setText(combo)

        self.config.update(hotkey=combo)

        self.hotkey_listener = HotkeyListener(
            combo,
            on_press=self._emit_hotkey_press,
            on_release=self._emit_hotkey_release,
            push_to_talk=True,
        )
        try:
            self.hotkey_listener.start()
            self._add_journal_entry("success", "hotkey_set", extra_key=combo, is_translatable=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)

    def _emit_hotkey_press(self) -> None:
        """Вызывается из keyboard thread при нажатии хоткея."""
        if not self._recording_hotkey:
            self.hotkey_press_signal.emit()

    def _emit_hotkey_release(self) -> None:
        """Вызывается из keyboard thread при отпускании хоткея."""
        if not self._recording_hotkey:
            self.hotkey_release_signal.emit()

    def _handle_hotkey_press(self) -> None:
        """Обработчик нажатия хоткея (Qt thread)."""
        # Проверяем лицензию перед записью
        info = self.license_manager.get_license_info()
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            # Показываем блокирующий диалог
            self._show_trial_expired_dialog()
            return

        # Если идёт транскрипция - отменяем её
        if self._transcription_in_progress:
            self._cancel_transcription()
            return

        if not self.audio.recording:
            focus_manager.save_current_window()
            self._add_journal_entry(
                "pending",
                "transcribing",
                extra_key=f"{focus_manager.saved_window_title}",
                is_translatable=True
            )
            self._start_recording_with_overlay()

    def _handle_hotkey_release(self) -> None:
        """Обработчик отпускания хоткея (Qt thread)."""
        if self.audio.recording:
            self._stop_recording_with_auto_insert()

    def _start_recording_with_overlay(self) -> None:
        """Начать запись с показом overlay."""
        if self.audio.recording:
            return
        try:
            device_id = self._selected_device_id()

            def on_level(levels: List[float]) -> None:
                self.waveform_signal.emit(levels)

            self.audio.start(device=device_id, level_callback=on_level)
            self._recording_start_time = datetime.now()  # Запоминаем время начала
            self.overlay.show_recording()
            self._update_tray_icon(recording=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)
            self.overlay.show_error(self._t("error"))

    def _stop_recording_with_auto_insert(self) -> None:
        """Остановить запись и включить автовставку."""
        if not self.audio.recording:
            return

        self._auto_insert_pending = True
        self._transcription_in_progress = True  # Начинаем транскрипцию
        path = self.audio.stop()

        # Учитываем время записи для trial
        if hasattr(self, '_recording_start_time') and self._recording_start_time:
            duration = (datetime.now() - self._recording_start_time).total_seconds()
            self.license_manager.add_transcription_time(duration)
            self._recording_start_time = None

        self.overlay.show_processing()

        if not path:
            self._add_journal_entry("error", "error", text="no_audio", is_translatable=True)
            self.overlay.show_error(self._t("error"))
            self._auto_insert_pending = False
            return

        self._run_transcription(path)

    def _update_waveform(self, levels: List[float]) -> None:
        """Обновить waveform в overlay (Qt thread)."""
        self.overlay.update_waveform(levels)

    def _run_transcription(self, audio_path: Path) -> None:
        cfg = self.config.config
        worker = TranscribeWorker(
            self.transcriber,
            audio_path,
            model_size=cfg.get("model_size", "large-v3"),
            compute_type=cfg.get("compute_type", "int8"),
            device=cfg.get("device", "auto"),
            cpu_threads=int(cfg.get("cpu_threads", 4)),
            num_workers=int(cfg.get("num_workers", 1)),
            language=cfg.get("language", "ru"),
            beam_size=int(cfg.get("beam_size", 5)),
            vad_filter=bool(cfg.get("vad_filter", True)),
            models_dir=self.models_dir,
        )
        worker.progress.connect(self._on_transcribe_progress)
        worker.status_update.connect(self._on_transcribe_status)
        worker.finished.connect(self._on_transcribed)
        worker.finished.connect(lambda *_: audio_path.unlink(missing_ok=True))
        self._transcribe_thread = worker
        worker.start()

    def _on_transcribe_status(self, status: str) -> None:
        # status приходит как ключ перевода (loading_model, transcribing)
        self._add_journal_entry("pending", status, is_translatable=True)

    def _on_transcribe_progress(self, text: str, lang: str, prob: float) -> None:
        pass  # Прогресс отображается в overlay

    def _on_transcribed(self, text: str, lang: str, prob: float, err: str) -> None:
        self._update_tray_icon(recording=False)
        self._transcription_in_progress = False  # Транскрипция завершена

        if err:
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            self.overlay.show_error(self._t("error"))
            self._auto_insert_pending = False
            return

        self.last_text = text

        # Добавляем в историю транскрипций
        if text:
            self.transcription_history.add_transcription(text)

        # Обновляем последнюю запись в журнале
        self._add_journal_entry(
            "success" if text else "pending",
            "transcription" if text else "transcribing",
            is_translatable=True
        )

        if self._auto_insert_pending and text:
            self._auto_insert_pending = False
            QTimer.singleShot(150, lambda: self._do_auto_insert(text))
        else:
            self.overlay.show_success()

    def _do_auto_insert(self, text: str) -> None:
        """Автовставка после транскрипции с восстановлением фокуса."""
        if not text:
            self.overlay.show_success()
            return

        ok = insert_text(text)
        if ok:
            self._add_journal_entry("success", "auto_insert_done", is_translatable=True)
            self.overlay.show_success()
        else:
            self._add_journal_entry("error", "error", text="insert_failed", is_translatable=True)
            self.overlay.show_error(self._t("error"))

    def _cancel_transcription(self) -> None:
        """Отменить текущую транскрипцию."""
        if not self._transcription_in_progress:
            return

        # Отменяем worker
        if self._transcribe_thread and self._transcribe_thread.isRunning():
            self._transcribe_thread.cancel()

        self._transcription_in_progress = False
        self._auto_insert_pending = False
        self._update_tray_icon(recording=False)

        # Показываем сообщение об отмене
        self._add_journal_entry("pending", "cancelled", is_translatable=True)
        self.overlay.hide_overlay()

    def _add_journal_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True) -> None:
        """Добавить запись в журнал."""
        self.journal.add_entry(status, title_key, text, extra_key, is_translatable)

    def _toggle_download(self) -> None:
        """Toggle between starting and canceling download."""
        if self._download_thread and self._download_thread.isRunning():
            # Cancel download
            self._download_thread.cancel()
            self.download_btn.setText(self._t("download_model"))
            self.download_btn.setEnabled(False)  # Disable until thread finishes
        else:
            # Start download
            self._download_model()

    def _download_model(self) -> None:
        model_size = self.model_box.currentData() or self.model_box.currentText().replace("[OK] ", "")
        self.download_btn.setText(self._t("cancel"))
        self.download_progress.setValue(0)
        self.download_status_label.setText("...")
        worker = ModelDownloadWorker(
            self.transcriber, model_size, self.models_dir
        )
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        self._download_thread = worker
        worker.start()
        self._add_journal_entry("pending", "downloading", extra_key=model_size, is_translatable=True)

    def _on_download_progress(self, status: str, current: int, total: int) -> None:
        self.download_progress.setValue(current)
        self.download_status_label.setText(status)

    def _on_download_finished(self, path: str, err: str) -> None:
        self.download_btn.setEnabled(True)
        self.download_btn.setText(self._t("download_model"))

        if err and err != "cancelled":
            self.download_progress.setValue(0)
            self.download_status_label.setText(f"Error: {err[:50]}...")
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            return
        if err == "cancelled":
            self.download_progress.setValue(0)
            self.download_status_label.setText(self._t("cancelled"))
            return
        self.download_progress.setValue(100)
        self.download_status_label.setText("[OK]")
        # Refresh model combo to show [OK] indicator
        current_model = self.model_box.currentData() or self.model_box.currentText().replace("[OK] ", "")
        self._populate_model_combo()
        self._set_model_combo_value(current_model)
        self._add_journal_entry("success", "model_ready", is_translatable=True)

    def _selected_device_id(self) -> Optional[int]:
        current = self.mic_box.currentText()
        if not current:
            return None
        try:
            idx_str = current.split(":")[0]
            return int(idx_str)
        except Exception:
            return None

    def _show_license_dialog(self) -> None:
        """Показать диалог активации лицензии."""
        info = self.license_manager.get_license_info()

        if info.status == LicenseStatus.TRIAL_EXPIRED:
            self._show_trial_expired_dialog()
        else:
            dialog = LicenseActivationDialog(
                self.license_manager,
                translate_func=self._t,
                parent=self
            )
            dialog.license_activated.connect(self._on_license_activated)
            dialog.exec()

    def _show_trial_expired_dialog(self) -> None:
        """Показать блокирующий диалог истёкшего trial."""
        dialog = TrialExpiredDialog(
            self.license_manager,
            translate_func=self._t,
            parent=self
        )
        dialog.license_activated.connect(self._on_license_activated)
        dialog.exec()

    def _on_license_activated(self) -> None:
        """Обработчик активации лицензии."""
        self.license_status_widget.refresh()
        self._add_journal_entry("success", "license_active", is_translatable=True)

    def _on_contact_support(self) -> None:
        """Открыть почтовый клиент для связи с поддержкой."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("mailto:help@mindtype.space"))

    def _check_for_updates(self) -> None:
        """Проверить наличие обновлений."""
        if self._update_check_worker and self._update_check_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("checking_updates"))
        self.update_status_label.setVisible(False)

        self._update_check_worker = UpdateCheckWorker(self.updater)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_check_worker.start()

        self._add_journal_entry("pending", "checking_updates", is_translatable=True)

    def _on_update_check_finished(self, info: UpdateInfo) -> None:
        """Обработчик завершения проверки обновлений."""
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText(self._t("check_updates"))

        if info.error:
            self.update_status_label.setText(self._t("network_error"))
            self.update_status_label.setStyleSheet("font-size: 11px; color: #cc0000;")
            self.update_status_label.setVisible(True)
            self._add_journal_entry("error", "update_error", text=info.error, is_translatable=True)
            return

        if info.available:
            self.update_status_label.setText(
                f"{self._t('update_available')}: v{info.version}"
            )
            self.update_status_label.setStyleSheet("font-size: 11px; color: #006600; font-weight: bold;")
            self.update_status_label.setVisible(True)

            # Показываем кнопку обновления
            self.check_update_btn.setText(self._t("update_now"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._download_update)

            self._add_journal_entry("success", "update_available",
                                   extra_key=f"v{info.version}", is_translatable=True)

            # Показываем диалог с информацией
            if info.release_notes:
                QMessageBox.information(
                    self,
                    self._t("update_available"),
                    f"{self._t('update_version').replace('{version}', info.version)}\n\n"
                    f"{info.release_notes}"
                )
        else:
            self.update_status_label.setText(self._t("no_updates"))
            self.update_status_label.setStyleSheet("font-size: 11px;")
            self.update_status_label.setVisible(True)
            self._add_journal_entry("success", "no_updates", is_translatable=True)

    def _download_update(self) -> None:
        """Скачать обновление."""
        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("downloading_update"))
        self.update_progress.setValue(0)
        self.update_progress.setVisible(True)

        self._update_download_worker = UpdateDownloadWorker(self.updater)
        self._update_download_worker.progress.connect(self._on_update_download_progress)
        self._update_download_worker.finished.connect(self._on_update_download_finished)
        self._update_download_worker.start()

        self._add_journal_entry("pending", "downloading_update", is_translatable=True)

    def _on_update_download_progress(self, downloaded: int, total: int) -> None:
        """Обработчик прогресса скачивания."""
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.update_progress.setValue(percent)

            # Показываем размер
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.update_status_label.setText(
                f"{self._t('downloading_update')} {downloaded_mb:.1f} / {total_mb:.1f} MB"
            )

    def _on_update_download_finished(self, success: bool, path: str, error: str) -> None:
        """Обработчик завершения скачивания."""
        self.update_progress.setVisible(False)
        self.check_update_btn.setEnabled(True)

        if success:
            self.update_status_label.setText(self._t("update_ready"))
            self.update_status_label.setStyleSheet("font-size: 11px; color: #006600; font-weight: bold;")
            self.check_update_btn.setText(self._t("update_now"))

            # Предлагаем установить
            reply = QMessageBox.question(
                self,
                self._t("update_ready"),
                self._t("update_ready") + "\n\n" +
                "Приложение будет закрыто для установки обновления.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._add_journal_entry("success", "update_ready", is_translatable=True)
                self.updater.install_update()
        else:
            self.update_status_label.setText(f"{self._t('update_error')}: {error}")
            self.update_status_label.setStyleSheet("font-size: 11px; color: #cc0000;")
            self.check_update_btn.setText(self._t("check_updates"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._check_for_updates)
            self._add_journal_entry("error", "update_error", text=error, is_translatable=True)

    def closeEvent(self, event) -> None:
        """Закрытие приложения или сворачивание в трей."""
        # Если трей доступен и не нажат Exit - сворачиваем в трей
        if self.tray_icon and not self._really_quit:
            event.ignore()
            self.hide()
            return

        # Полное закрытие
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.hotkey_recorder:
            self.hotkey_recorder.stop()
        self.audio.stop_monitoring()
        self.overlay.hide()
        if self.tray_icon:
            self.tray_icon.hide()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(create_app_icon(64))  # Иконка для всего приложения

    # Проверяем лицензию перед запуском
    license_manager = LicenseManager()
    has_access, info = license_manager.check_access()

    if not has_access:
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            # Показываем блокирующий диалог (нельзя закрыть)
            dialog = TrialExpiredDialog(license_manager)
            result = dialog.exec()
            # Если диалог закрылся без активации - выходим
            final_info = license_manager.get_license_info()
            if final_info.status != LicenseStatus.VALID:
                sys.exit(1)
        else:
            # Показываем обычный диалог активации
            dialog = LicenseActivationDialog(license_manager)
            result = dialog.exec()
            if dialog.should_block_app():
                sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
