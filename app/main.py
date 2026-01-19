# MindType - AI Speech-to-Text Desktop Application
# Copyright (c) 2024-2025 Butakov Maksim Vladimirovich. All rights reserved.
# Author: Butakov Maksim Vladimirovich <info@mindtype.space>
#
# This software is the confidential and proprietary information of the Author.

import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Для корректного отображения иконки в панели задач Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MindType.App.1.0")

# === FEATURE FLAG: Голосовой ассистент ===
# Установить False для отключения ассистента из билда
ASSISTANT_FEATURE_ENABLED = False

# Смещение оверлея ассистента относительно основного оверлея по вертикали
ASSISTANT_OVERLAY_OFFSET = 50

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt, QRectF, QUrl, QSize
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QPen, QBrush, QDesktopServices, QDragEnterEvent, QDropEvent

from .audio import AudioRecorder
from .config import ConfigManager, DEFAULT_MODELS_DIR
from .accelerator import has_npu, detect_available_providers
from .file_transcriber import (
    FileTranscriptionQueue,
    FileTask,
    FileStatus,
    ALL_EXTENSIONS,
    is_supported_file,
)
from .hotkeys import HotkeyListener, HotkeyRecorder
from .inserter import insert_text, focus_manager
from .licensing import LicenseManager, LicenseStatus
from .licensing.activation_dialog import LicenseActivationDialog, LicenseStatusWidget, TrialExpiredDialog
from .overlay import OverlayWidget
from .report_generator import ReportGenerator
from .transcriber import Transcriber
from .translations import (
    get_text,
    UI_LANGUAGES,
    WHISPER_LANGUAGES,
)
# Импорты ассистента (условные)
if ASSISTANT_FEATURE_ENABLED:
    from .assistant import VoiceAssistant, AssistantConfig, AssistantState, PERSONALITY_TEMPLATES
    from .assistant_overlay import AssistantOverlayWidget
    from .dialog_history import get_dialog_history_manager, Dialog
else:
    # Заглушки для типов
    VoiceAssistant = None  # type: ignore
    AssistantConfig = None  # type: ignore
    AssistantState = None  # type: ignore
    PERSONALITY_TEMPLATES = {}
    AssistantOverlayWidget = None  # type: ignore
    get_dialog_history_manager = None  # type: ignore
    Dialog = None  # type: ignore
from .tts import get_tts_engine, is_edge_tts_available, RUSSIAN_VOICES
from .wake_word import is_openwakeword_available, WakeWordDetector
from .updater import Updater, UpdateInfo

# Импорты из UI модуля
from .ui.styles import STYLESHEET
from .ui.icons import create_app_icon
from .ui.workers import (
    TranscribeWorker,
    ModelDownloadWorker,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    FileTranscriptionWorker,
)
# Миксины доступны для будущего рефакторинга:
# from .ui.mixins import AssistantMixin, FilesMixin, UpdatesMixin, HotkeysMixin


# Версия приложения (импортируется из version.py)
from .version import __version__ as APP_VERSION


# =============================================================================
# UI КОМПОНЕНТЫ
# Примечание: STYLESHEET, create_app_icon и воркеры вынесены в модуль app.ui
# =============================================================================


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


class AssistantDialogHistoryWidget(QWidget):
    """Виджет истории диалогов ассистента."""

    dialog_selected = pyqtSignal(object)  # Сигнал при выборе диалога (Dialog)
    continue_clicked = pyqtSignal(object)  # Сигнал при нажатии "Продолжить"
    delete_clicked = pyqtSignal(str)  # Сигнал при удалении (dialog_id)

    def __init__(self, translate_func=None, parent=None):
        super().__init__(parent)
        self._translate = translate_func or (lambda x: x)
        self._dialogs: List[Dialog] = []
        self._selected_dialog: Optional[Dialog] = None
        self._build_ui()

    def set_translate_func(self, func):
        """Установить функцию перевода."""
        self._translate = func
        self._update_labels()

    def _build_ui(self):
        self.setStyleSheet("background-color: #ffffff;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # === Левая панель: список диалогов ===
        left_panel = QFrame()
        left_panel.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
        """)
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Заголовок
        header = QFrame()
        header.setFixedHeight(24)
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:0.5 #808080, stop:1 #000000);
                border: none;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 2, 8, 2)
        self._title_label = QLabel(self._translate("assistant_dialogs"))
        self._title_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 10px;")
        header_layout.addWidget(self._title_label)
        left_layout.addWidget(header)

        # Список диалогов
        self._dialog_scroll = QScrollArea()
        self._dialog_scroll.setWidgetResizable(True)
        self._dialog_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dialog_scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        self._dialog_list = QWidget()
        self._dialog_list.setStyleSheet("background-color: #ffffff;")
        self._dialog_list_layout = QVBoxLayout(self._dialog_list)
        self._dialog_list_layout.setContentsMargins(4, 4, 4, 4)
        self._dialog_list_layout.setSpacing(4)
        self._dialog_list_layout.addStretch()

        self._dialog_scroll.setWidget(self._dialog_list)
        left_layout.addWidget(self._dialog_scroll, stretch=1)

        # Кнопка "Очистить всё"
        self._clear_all_btn = QPushButton(self._translate("clear_all_dialogs"))
        self._clear_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #000000;
                padding: 4px 8px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #c0c0c0;
            }
        """)
        self._clear_all_btn.clicked.connect(self._on_clear_all)
        left_layout.addWidget(self._clear_all_btn)

        layout.addWidget(left_panel)

        # === Правая панель: просмотр диалога ===
        right_panel = QFrame()
        right_panel.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
        """)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Заголовок
        preview_header = QFrame()
        preview_header.setFixedHeight(24)
        preview_header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:0.5 #808080, stop:1 #000000);
                border: none;
            }
        """)
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(8, 2, 8, 2)
        self._preview_label = QLabel(self._translate("dialog_preview"))
        self._preview_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 10px;")
        preview_header_layout.addWidget(self._preview_label)
        right_layout.addWidget(preview_header)

        # Контент диалога
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        self._preview_content = QWidget()
        self._preview_content.setStyleSheet("background-color: #ffffff;")
        self._preview_layout = QVBoxLayout(self._preview_content)
        self._preview_layout.setContentsMargins(8, 8, 8, 8)
        self._preview_layout.setSpacing(6)

        self._placeholder_label = QLabel(self._translate("select_dialog"))
        self._placeholder_label.setStyleSheet("color: #808080; font-style: italic;")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._placeholder_label)
        self._preview_layout.addStretch()

        self._preview_scroll.setWidget(self._preview_content)
        right_layout.addWidget(self._preview_scroll, stretch=1)

        # Кнопки управления
        controls = QFrame()
        controls.setStyleSheet("QFrame { background-color: #ffffff; border-top: 1px solid #808080; }")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(8, 6, 8, 6)
        controls_layout.setSpacing(8)

        self._continue_btn = QPushButton(self._translate("continue_dialog"))
        self._continue_btn.setEnabled(False)
        self._continue_btn.clicked.connect(self._on_continue)
        controls_layout.addWidget(self._continue_btn)

        self._delete_btn = QPushButton(self._translate("delete_dialog"))
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        controls_layout.addWidget(self._delete_btn)

        controls_layout.addStretch()
        right_layout.addWidget(controls)

        layout.addWidget(right_panel, stretch=1)

    def _update_labels(self):
        """Обновить переводимые тексты."""
        self._title_label.setText(self._translate("assistant_dialogs"))
        self._preview_label.setText(self._translate("dialog_preview"))
        self._clear_all_btn.setText(self._translate("clear_all_dialogs"))
        self._continue_btn.setText(self._translate("continue_dialog"))
        self._delete_btn.setText(self._translate("delete_dialog"))
        if not self._selected_dialog:
            self._placeholder_label.setText(self._translate("select_dialog"))

    def refresh(self):
        """Обновить список диалогов из менеджера."""
        history_manager = get_dialog_history_manager()
        self._dialogs = history_manager.get_all_dialogs()
        self._rebuild_dialog_list()

    def _rebuild_dialog_list(self):
        """Перестроить список диалогов."""
        # Очищаем список
        while self._dialog_list_layout.count() > 1:
            item = self._dialog_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._dialogs:
            no_dialogs = QLabel(self._translate("no_dialogs"))
            no_dialogs.setStyleSheet("color: #808080; font-style: italic; font-size: 10px;")
            no_dialogs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dialog_list_layout.insertWidget(0, no_dialogs)
            return

        for dialog in self._dialogs:
            item = self._create_dialog_item(dialog)
            self._dialog_list_layout.insertWidget(self._dialog_list_layout.count() - 1, item)

    def _create_dialog_item(self, dialog: Dialog) -> QWidget:
        """Создать элемент списка диалогов."""
        item = QFrame()
        item.setObjectName(f"dialog_{dialog.id}")
        item.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #808080;
            }
            QFrame:hover {
                background-color: #e0e0e0;
            }
        """)
        item.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(item)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        # Заголовок (обрезанный)
        title = dialog.title or "Новый диалог"
        title_label = QLabel(title[:30] + "..." if len(title) > 30 else title)
        title_label.setStyleSheet("font-weight: bold; font-size: 10px; background: transparent;")
        layout.addWidget(title_label)

        # Дата
        try:
            dt = datetime.fromisoformat(dialog.timestamp)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = dialog.timestamp[:16]
        date_label = QLabel(date_str)
        date_label.setStyleSheet("color: #808080; font-size: 9px; background: transparent;")
        layout.addWidget(date_label)

        # Клик для выбора
        item.mousePressEvent = lambda e, d=dialog: self._on_dialog_selected(d)

        return item

    def _on_dialog_selected(self, dialog: Dialog):
        """Обработка выбора диалога."""
        self._selected_dialog = dialog
        self._continue_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        self._show_dialog_preview(dialog)
        self.dialog_selected.emit(dialog)

    def _show_dialog_preview(self, dialog: Dialog):
        """Показать предпросмотр диалога."""
        # Очищаем preview
        while self._preview_layout.count() > 0:
            item = self._preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # System prompt (если есть)
        if dialog.system_prompt:
            sys_frame = QFrame()
            sys_frame.setStyleSheet("""
                QFrame {
                    background-color: #f0f0f0;
                    border: 1px dashed #808080;
                }
            """)
            sys_layout = QVBoxLayout(sys_frame)
            sys_layout.setContentsMargins(6, 4, 6, 4)
            sys_label = QLabel("System: " + dialog.system_prompt[:100] + ("..." if len(dialog.system_prompt) > 100 else ""))
            sys_label.setWordWrap(True)
            sys_label.setStyleSheet("font-size: 9px; color: #606060; background: transparent;")
            sys_layout.addWidget(sys_label)
            self._preview_layout.addWidget(sys_frame)

        # Сообщения
        for msg in dialog.messages:
            bubble = self._create_message_bubble(msg.role, msg.content)
            self._preview_layout.addWidget(bubble)

        self._preview_layout.addStretch()

    def _create_message_bubble(self, role: str, content: str) -> QWidget:
        """Создать пузырёк сообщения."""
        outer = QWidget()
        row = QHBoxLayout(outer)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        bubble = QFrame()
        bubble.setStyleSheet("""
            QFrame {
                border: 1px solid #000000;
                background-color: %s;
            }
        """ % ("#dddddd" if role == "user" else "#ffffff"))
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(6, 4, 6, 4)

        label = QLabel(content[:200] + ("..." if len(content) > 200 else ""))
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 10px; color: #000000; background: transparent;")
        bubble_layout.addWidget(label)

        if role == "user":
            row.addStretch()
            row.addWidget(bubble, stretch=0)
        else:
            row.addWidget(bubble, stretch=0)
            row.addStretch()

        return outer

    def _on_continue(self):
        """Продолжить выбранный диалог."""
        if self._selected_dialog:
            self.continue_clicked.emit(self._selected_dialog)

    def _on_delete(self):
        """Удалить выбранный диалог."""
        if self._selected_dialog:
            dialog_id = self._selected_dialog.id
            history_manager = get_dialog_history_manager()
            history_manager.delete_dialog(dialog_id)
            self._selected_dialog = None
            self._continue_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            # Очищаем preview
            while self._preview_layout.count() > 0:
                item = self._preview_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._placeholder_label = QLabel(self._translate("select_dialog"))
            self._placeholder_label.setStyleSheet("color: #808080; font-style: italic;")
            self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._preview_layout.addWidget(self._placeholder_label)
            self._preview_layout.addStretch()
            self.refresh()
            self.delete_clicked.emit(dialog_id)

    def _on_clear_all(self):
        """Очистить всю историю."""
        history_manager = get_dialog_history_manager()
        history_manager.clear_all()
        self._selected_dialog = None
        self._continue_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        self.refresh()
        # Очищаем preview
        while self._preview_layout.count() > 0:
            item = self._preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._placeholder_label = QLabel(self._translate("select_dialog"))
        self._placeholder_label.setStyleSheet("color: #808080; font-style: italic;")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._placeholder_label)
        self._preview_layout.addStretch()


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


class PromptCustomizationDialog(QMainWindow):
    """Диалог настройки промптов для AI саммаризации."""

    def __init__(self, config_manager, translate_func=None, parent=None):
        super().__init__(parent)
        self._t = translate_func or (lambda x: x)
        self.config = config_manager

        self.setWindowTitle(self._t("customize_prompts"))
        self.setFixedSize(700, 550)

        # Загружаем пресеты
        from .summary_presets import PRESETS, get_preset_prompts, DEFAULT_PRESET
        self._presets = PRESETS
        self._get_preset_prompts = get_preset_prompts
        self._default_preset = DEFAULT_PRESET

        # Текущий пресет из конфига
        self._current_preset = self.config.config.get("summary_preset", DEFAULT_PRESET)
        if self._current_preset not in self._presets:
            self._current_preset = DEFAULT_PRESET

        self._build_ui()
        self._load_prompts()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Заголовок
        title = QLabel(self._t("prompt_settings"))
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        # Выбор пресета
        preset_layout = QHBoxLayout()
        preset_label = QLabel(self._t("preset") + ":")
        preset_label.setStyleSheet("font-weight: bold;")
        preset_layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(200)
        for preset_id, preset_data in self._presets.items():
            # Формат: "Название — описание" (переведённые)
            name = self._t(preset_data.get('name_key', preset_id))
            desc = self._t(preset_data.get('description_key', ''))
            display_text = f"{name} — {desc}"
            self.preset_combo.addItem(display_text, preset_id)
        # Устанавливаем текущий пресет
        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == self._current_preset:
                self.preset_combo.setCurrentIndex(i)
                break
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        # Табы для разных промптов
        self.prompt_tabs = QTabWidget()
        self.prompt_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #000000;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #e0e0e0;
                border: 1px solid #000000;
                padding: 4px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #ffffff;
                border-bottom: none;
            }
        """)

        # Создаём вкладки для каждого промпта
        self.prompt_editors = {}

        prompt_names = [
            ("system", self._t("prompt_system")),
            ("short", self._t("prompt_short")),
            ("extraction", self._t("prompt_extraction")),
            ("aggregation", self._t("prompt_aggregation")),
        ]

        from PyQt6.QtWidgets import QTextEdit

        for key, name in prompt_names:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)

            # Описание
            desc = QLabel(self._get_prompt_description(key))
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #666666; font-size: 11px; margin-bottom: 8px;")
            tab_layout.addWidget(desc)

            # Редактор
            editor = QTextEdit()
            editor.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                    border: 1px solid #808080;
                    background-color: #ffffff;
                }
            """)
            tab_layout.addWidget(editor)

            # Кнопка сброса
            reset_btn = QPushButton(self._t("reset_to_default"))
            reset_btn.clicked.connect(lambda checked, k=key: self._reset_prompt(k))
            tab_layout.addWidget(reset_btn)

            self.prompt_editors[key] = editor
            self.prompt_tabs.addTab(tab, name)

        layout.addWidget(self.prompt_tabs)

        # Кнопки
        buttons_layout = QHBoxLayout()

        # Кнопка сброса всех промптов
        reset_all_btn = QPushButton(self._t("reset_all_prompts"))
        reset_all_btn.clicked.connect(self._reset_all_prompts)
        buttons_layout.addWidget(reset_all_btn)

        buttons_layout.addStretch()

        save_btn = QPushButton(self._t("save"))
        save_btn.setStyleSheet("font-weight: bold;")
        save_btn.clicked.connect(self._save_prompts)
        buttons_layout.addWidget(save_btn)

        cancel_btn = QPushButton(self._t("cancel"))
        cancel_btn.clicked.connect(self.close)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        self.setCentralWidget(central)

    def _get_prompt_description(self, key: str) -> str:
        desc_keys = {
            "system": "prompt_desc_system",
            "short": "prompt_desc_short",
            "extraction": "prompt_desc_extraction",
            "aggregation": "prompt_desc_aggregation",
        }
        return self._t(desc_keys.get(key, ""))

    def _get_current_preset_prompts(self) -> dict:
        """Получить промпты текущего пресета."""
        return self._get_preset_prompts(self._current_preset)

    def _on_preset_changed(self, index: int):
        """Обработка смены пресета."""
        preset_id = self.preset_combo.itemData(index)
        if preset_id and preset_id != self._current_preset:
            self._current_preset = preset_id
            # Заполняем редакторы промптами из нового пресета
            preset_prompts = self._get_current_preset_prompts()
            for key, editor in self.prompt_editors.items():
                editor.setPlainText(preset_prompts.get(key, ""))

    def _load_prompts(self):
        """Загрузить промпты из конфига или использовать пресет."""
        saved = self.config.config.get("custom_prompts", {})
        preset_prompts = self._get_current_preset_prompts()

        for key, editor in self.prompt_editors.items():
            # Если есть сохранённый кастомный промпт — используем его, иначе из пресета
            text = saved.get(key, preset_prompts.get(key, ""))
            editor.setPlainText(text)

    def _reset_prompt(self, key: str):
        """Сбросить промпт к значению из текущего пресета."""
        preset_prompts = self._get_current_preset_prompts()
        if key in self.prompt_editors and key in preset_prompts:
            self.prompt_editors[key].setPlainText(preset_prompts[key])

    def _reset_all_prompts(self):
        """Сбросить все промпты к значениям текущего пресета."""
        preset_prompts = self._get_current_preset_prompts()
        for key, editor in self.prompt_editors.items():
            if key in preset_prompts:
                editor.setPlainText(preset_prompts[key])
        # Очищаем кастомные промпты в конфиге
        self.config.update(custom_prompts={}, summary_preset=self._current_preset)
        # Показываем сообщение
        preset_name = self._presets[self._current_preset]["name"]
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Готово", f"Все промпты сброшены к пресету «{preset_name}».")

    def _save_prompts(self):
        """Сохранить промпты и пресет в конфиг."""
        preset_prompts = self._get_current_preset_prompts()
        custom_prompts = {}

        for key, editor in self.prompt_editors.items():
            text = editor.toPlainText().strip()
            # Сохраняем только если отличается от пресета
            if text and text != preset_prompts.get(key, ""):
                custom_prompts[key] = text

        self.config.update(custom_prompts=custom_prompts, summary_preset=self._current_preset)
        self.close()


class DropZoneWidget(QFrame):
    """Зона drag-and-drop для файлов в стиле Classic Mac OS."""
    files_dropped = pyqtSignal(list)  # List[Path]
    clicked = pyqtSignal()

    def __init__(self, translate_func=None, parent=None):
        super().__init__(parent)
        self._translate = translate_func or (lambda x: x)
        self.setAcceptDrops(True)
        self.setMinimumHeight(100)
        self._build_ui()

    def set_translate_func(self, func):
        self._translate = func
        self._update_texts()

    def _create_folder_icon(self) -> QPixmap:
        """Создать пиксельную иконку папки в стиле Classic Mac OS."""
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        black = QColor(0, 0, 0)

        # Папка - классический стиль
        # Верхняя вкладка
        painter.fillRect(4, 6, 10, 4, black)
        # Основной прямоугольник (рамка)
        painter.fillRect(2, 10, 28, 2, black)  # верх
        painter.fillRect(2, 26, 28, 2, black)  # низ
        painter.fillRect(2, 10, 2, 18, black)  # лево
        painter.fillRect(28, 10, 2, 18, black)  # право
        # Внутренняя часть (белая)
        painter.fillRect(4, 12, 24, 14, QColor(255, 255, 255))
        # Линии внутри папки
        painter.fillRect(6, 16, 20, 2, black)
        painter.fillRect(6, 22, 14, 2, black)

        painter.end()
        return pixmap

    def _build_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
            }
            QFrame:hover {
                background-color: #f0f0f0;
            }
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        # Пиксельная иконка папки
        icon_label = QLabel()
        icon_label.setPixmap(self._create_folder_icon())
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(icon_label)

        # Основной текст
        self._main_label = QLabel(self._translate("drag_drop_files"))
        self._main_label.setStyleSheet("font-weight: bold; font-size: 12px; border: none; background: transparent;")
        self._main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._main_label)

        # Подсказка
        self._sub_label = QLabel(self._translate("or_click_to_select"))
        self._sub_label.setStyleSheet("font-size: 11px; color: #808080; border: none; background: transparent;")
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub_label)

        # Форматы
        self._formats_label = QLabel(self._translate("supported_formats"))
        self._formats_label.setStyleSheet("font-size: 10px; color: #808080; border: none; background: transparent;")
        self._formats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formats_label.setWordWrap(True)
        layout.addWidget(self._formats_label)

    def _update_texts(self):
        self._main_label.setText(self._translate("drag_drop_files"))
        self._sub_label.setText(self._translate("or_click_to_select"))
        self._formats_label.setText(self._translate("supported_formats"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            # Проверяем, есть ли поддерживаемые файлы
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if is_supported_file(path):
                    event.acceptProposedAction()
                    self.setStyleSheet("""
                        QFrame {
                            background-color: #dddddd;
                            border: 2px solid #000000;
                        }
                    """)
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
            }
            QFrame:hover {
                background-color: #f0f0f0;
            }
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
            }
            QFrame:hover {
                background-color: #f0f0f0;
            }
        """)

        files = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and is_supported_file(path):
                files.append(path)
            elif path.is_dir():
                # Рекурсивно ищем файлы в папке
                for ext in ALL_EXTENSIONS:
                    files.extend(path.rglob(f"*{ext}"))

        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()


class FileQueueItemWidget(QFrame):
    """Элемент очереди файлов."""
    remove_clicked = pyqtSignal(object)  # FileTask
    open_clicked = pyqtSignal(object)  # FileTask

    def __init__(self, task: FileTask, translate_func=None, parent=None):
        super().__init__(parent)
        self.task = task
        self._translate = translate_func or (lambda x: x)
        self._close_icon = self._create_close_icon()
        self._open_icon = self._create_open_icon()
        self._build_ui()
        self.update_status()

    def _create_close_icon(self) -> QIcon:
        """Пиксельная ч/б иконка-крестик."""
        size = 12
        pm = QPixmap(size, size)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(2, 2, size - 3, size - 3)
        p.drawLine(size - 3, 2, 2, size - 3)
        p.end()
        return QIcon(pm)

    def _create_open_icon(self) -> QIcon:
        """Пиксельная ч/б иконка 'открыть'."""
        w, h = 12, 12
        pm = QPixmap(w, h)
        pm.fill(QColor(0, 0, 0, 0))
        p = QPainter(pm)
        black = QColor(0, 0, 0)
        # Стрелка вправо в квадратных скобках: [>]
        p.fillRect(2, 2, 2, 8, black)      # левая скобка
        p.fillRect(8, 4, 2, 4, black)      # основание стрелки
        p.fillRect(6, 5, 2, 2, black)      # середина
        p.fillRect(10, 5, 2, 2, black)     # наконечник
        p.end()
        return QIcon(pm)

    def set_translate_func(self, func):
        self._translate = func
        self.update_status()

    def _create_file_icon(self, is_video: bool) -> QPixmap:
        """Создать пиксельную иконку файла."""
        size = 20
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        black = QColor(0, 0, 0)

        # Документ с уголком
        painter.fillRect(2, 0, 14, 2, black)   # верх
        painter.fillRect(2, 18, 16, 2, black)  # низ
        painter.fillRect(2, 0, 2, 20, black)   # лево
        painter.fillRect(16, 4, 2, 16, black)  # право
        # Уголок
        painter.fillRect(14, 0, 2, 2, black)
        painter.fillRect(16, 2, 2, 2, black)
        painter.fillRect(14, 2, 2, 2, black)

        # Внутренние линии (контент)
        if is_video:
            # Треугольник play
            painter.fillRect(7, 6, 2, 8, black)
            painter.fillRect(9, 7, 2, 6, black)
            painter.fillRect(11, 8, 2, 4, black)
        else:
            # Ноты
            painter.fillRect(6, 6, 2, 8, black)
            painter.fillRect(12, 8, 2, 6, black)
            painter.fillRect(4, 12, 4, 2, black)
            painter.fillRect(10, 12, 4, 2, black)

        painter.end()
        return pixmap

    def _build_ui(self):
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #000000;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Иконка типа файла (пиксельная)
        icon_label = QLabel()
        icon_label.setPixmap(self._create_file_icon(self.task.is_video))
        icon_label.setFixedWidth(24)
        icon_label.setStyleSheet("border: none;")
        layout.addWidget(icon_label)

        # Информация о файле
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        # Имя файла
        self._name_label = QLabel(self.task.file_name)
        self._name_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        info_layout.addWidget(self._name_label)

        # Статус
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-size: 11px; color: #808080;")
        info_layout.addWidget(self._status_label)

        layout.addLayout(info_layout, stretch=1)

        # Прогресс-бар
        self._progress = QProgressBar()
        self._progress.setFixedWidth(80)
        self._progress.setFixedHeight(16)
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        # Кнопка открыть/удалить
        self._action_btn = QPushButton("×")
        self._action_btn.setFixedSize(24, 24)
        self._action_btn.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                border: 1px solid #000000;
                background: #ffffff;
                padding: 0;
            }
            QPushButton:hover {
                background: #000000;
                color: #ffffff;
            }
        """)
        self._action_btn.setText("")
        self._action_btn.setIconSize(QSize(12, 12))
        self._action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_btn)

    def _on_action_clicked(self):
        if self.task.status == FileStatus.COMPLETED:
            self.open_clicked.emit(self.task)
        elif self.task.status in (FileStatus.PENDING, FileStatus.ERROR, FileStatus.CANCELLED):
            self.remove_clicked.emit(self.task)

    def update_status(self):
        """Обновить отображение статуса."""
        status_map = {
            FileStatus.PENDING: ("status_pending", "#808080"),
            FileStatus.EXTRACTING: ("status_extracting", "#0066cc"),
            FileStatus.TRANSCRIBING: ("status_transcribing", "#0066cc"),
            FileStatus.SUMMARIZING: ("status_summarizing", "#9900cc"),
            FileStatus.GENERATING: ("status_generating", "#0066cc"),
            FileStatus.COMPLETED: ("status_completed", "#008800"),
            FileStatus.ERROR: ("status_error", "#cc0000"),
            FileStatus.CANCELLED: ("status_cancelled", "#808080"),
        }

        key, color = status_map.get(self.task.status, ("status_pending", "#808080"))
        status_text = self._translate(key)

        if self.task.status == FileStatus.ERROR and self.task.error_message:
            status_text += f": {self.task.error_message[:50]}"

        self._status_label.setText(status_text)
        self._status_label.setStyleSheet(f"font-size: 11px; color: {color};")

        # Прогресс
        self._progress.setValue(self.task.progress)

        # Кнопка
        if self.task.status == FileStatus.COMPLETED:
            self._action_btn.setIcon(self._open_icon)
            self._action_btn.setToolTip(self._translate("open_folder"))
        else:
            self._action_btn.setIcon(self._close_icon)
            self._action_btn.setToolTip(self._translate("remove_from_queue"))

        # Прогресс-бар visibility
        self._progress.setVisible(self.task.status in (
            FileStatus.EXTRACTING,
            FileStatus.TRANSCRIBING,
            FileStatus.SUMMARIZING,
            FileStatus.GENERATING,
            FileStatus.PENDING,
        ))


class MainWindow(QMainWindow):
    hotkey_press_signal = pyqtSignal()
    hotkey_release_signal = pyqtSignal()
    hotkey_recorded_signal = pyqtSignal(str)
    waveform_signal = pyqtSignal(list)
    mic_level_signal = pyqtSignal(float)
    thinking_signal = pyqtSignal(str)  # Для AI thinking output
    # Сигналы ассистента (для thread-safe обновления UI)
    assistant_state_signal = pyqtSignal(object)  # AssistantState
    assistant_transcript_signal = pyqtSignal(str)
    assistant_response_signal = pyqtSignal(str)
    assistant_level_signal = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("MindType")
        self.setWindowIcon(create_app_icon(64))
        self.setFixedSize(600, 600)

        self.config = ConfigManager()
        self.audio = AudioRecorder()
        backend = self.config.config.get("transcriber_backend", "auto")
        self.transcriber = Transcriber(backend=backend)
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

        # Инициализация UI элементов ассистента (будут созданы позже в _build_ui)
        self.assistant_enable_check = None

        # Система обновлений
        self.updater = Updater()
        self._update_check_worker: Optional[UpdateCheckWorker] = None
        self._update_download_worker: Optional[UpdateDownloadWorker] = None

        # Overlay виджет
        self.overlay = OverlayWidget()
        self._apply_overlay_settings()

        # Оверлей диалога ассистента (System 7 style)
        self.assistant_overlay = None
        if ASSISTANT_FEATURE_ENABLED:
            self.assistant_overlay = AssistantOverlayWidget()
            # Используем те же настройки позиции/отступа, что и у overlay транскрипции
            cfg = self.config.config
            self.assistant_overlay.set_corner(cfg.get("overlay_position", "bottom-center"))
            # Чуть выше, чтобы не пересекаться с основным overlay
            self.assistant_overlay.set_margin(int(cfg.get("overlay_margin", 20)) + ASSISTANT_OVERLAY_OFFSET)
            self.assistant_overlay.hide_overlay()
            # Сигналы от оверлея подключаются в _connect_assistant_signals()

        # Системный трей
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._setup_tray()

        # Голосовой ассистент
        self.voice_assistant = None
        self._assistant_hotkey_listener = None
        self._assistant_hotkey_recorder = None
        if ASSISTANT_FEATURE_ENABLED:
            self._init_voice_assistant()
            self._init_assistant_hotkey()

        # Инициализация переменных для вкладки файлов
        self._file_tasks: List[FileTask] = []
        # key = resolved Path to input file
        self._file_widgets: dict[Path, "FileQueueItemWidget"] = {}
        self._file_queue: Optional[FileTranscriptionQueue] = None
        self._file_worker: Optional[FileTranscriptionWorker] = None
        self._output_dir = Path.home() / "Documents" / "MindType Transcriptions"

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

        # Проверяем ggml-*.bin файлы в корне (whisper.cpp модели)
        for f in self.models_dir.iterdir():
            if f.is_file() and f.name.startswith("ggml-") and f.name.endswith(".bin"):
                return True

        # Проверяем подпапки с HuggingFace моделями
        for subdir in self.models_dir.iterdir():
            if not subdir.is_dir():
                continue

            # HuggingFace модели содержат config.json
            if (subdir / "config.json").exists():
                # Дополнительно проверяем наличие весов модели
                has_weights = (
                    (subdir / "model.bin").exists() or
                    (subdir / "model.safetensors").exists() or
                    (subdir / "pytorch_model.bin").exists() or
                    any(f.name.endswith(".safetensors") for f in subdir.iterdir() if f.is_file())
                )
                if has_weights:
                    return True
                # Если есть только config.json без весов - модель не полностью загружена
                # но config.json достаточно для определения что модель начала качаться
                # Для пользователя важнее не показывать диалог если модель есть
                # Проверим размер папки - если > 50MB, считаем что модель есть
                try:
                    total_size = sum(f.stat().st_size for f in subdir.rglob("*") if f.is_file())
                    if total_size > 50 * 1024 * 1024:  # 50 MB
                        return True
                except Exception:
                    pass

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

    def _init_voice_assistant(self) -> None:
        """Инициализировать голосового ассистента."""
        try:
            cfg = self.config.config

            # Создаем конфигурацию ассистента
            assistant_config = AssistantConfig(
                wake_word=cfg.get("assistant_wake_word", "hey_jarvis"),
                wake_word_threshold=cfg.get("assistant_wake_threshold", 0.5),
                beep_on_wake=cfg.get("assistant_beep_on_wake", True),
                tts_voice=cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural"),
                tts_rate=cfg.get("assistant_tts_rate", 0),
                tts_language=cfg.get("assistant_tts_language", "ru"),
                # Используем общие настройки OpenRouter
                openrouter_model=cfg.get("openrouter_model", "anthropic/claude-3-haiku"),
                openrouter_api_key=cfg.get("openrouter_api_key", ""),
                system_prompt=cfg.get("assistant_system_prompt", PERSONALITY_TEMPLATES["friendly"]["prompt"]),
                normalize_numbers=cfg.get("assistant_normalize_numbers", True),
                normalize_dates=cfg.get("assistant_normalize_dates", True),
                normalize_translit=cfg.get("assistant_normalize_translit", True),
                normalize_abbreviations=cfg.get("assistant_normalize_abbrev", True),
                microphone_device=self._get_current_mic_index(),
                recording_timeout=cfg.get("assistant_recording_timeout", 3.0),
                # Параметры модели транскрипции
                model_size=cfg.get("model_size", "large-v3"),
                compute_type=cfg.get("compute_type", "int8"),
                device=cfg.get("device", "auto"),
                models_dir=str(self.models_dir),
                beam_size=int(cfg.get("beam_size", 5)),
                vad_filter=False,  # Отключен для ассистента, команды короткие
            )

            # Создаем ассистента
            self.voice_assistant = VoiceAssistant(assistant_config)
            # Передаем transcriber
            self.voice_assistant.set_transcriber(self.transcriber)
            # Подключаем callbacks через сигналы (thread-safe)
            # Callback'и вызываются из фонового потока, поэтому emit'им сигналы
            self.voice_assistant.set_state_callback(lambda s: self.assistant_state_signal.emit(s))
            self.voice_assistant.set_transcript_callback(lambda t: self.assistant_transcript_signal.emit(t))
            self.voice_assistant.set_response_callback(lambda r: self.assistant_response_signal.emit(r))
            self.voice_assistant.set_level_callback(lambda l: self.assistant_level_signal.emit(l))

            # Запускаем если включен
            if cfg.get("assistant_enabled", False):
                self.voice_assistant.start()

        except Exception as e:
            logger.error(f"Ошибка инициализации голосового ассистента: {e}")
            self.voice_assistant = None

    def _on_assistant_state_changed(self, state) -> None:
        """Обновление оверлея ассистента при смене состояния."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return

        from .assistant_overlay import AssistantOverlayState

        # Не показываем, если ассистент выключен
        if not self.config.config.get("assistant_enabled", False):
            return

        # Маппинг состояний ассистента на состояния оверлея
        state_map = {
            AssistantState.IDLE: AssistantOverlayState.HIDDEN,
            AssistantState.CALIBRATING: AssistantOverlayState.CALIBRATING,
            AssistantState.LISTENING: AssistantOverlayState.LISTENING,
            AssistantState.TRANSCRIBING: AssistantOverlayState.TRANSCRIBING,
            AssistantState.PROCESSING: AssistantOverlayState.THINKING,
            AssistantState.SPEAKING: AssistantOverlayState.SPEAKING,
            AssistantState.WAITING: AssistantOverlayState.WAITING,
            AssistantState.ERROR: AssistantOverlayState.ERROR,
        }

        target_state = state_map.get(state, AssistantOverlayState.HIDDEN)
        self.assistant_overlay.set_state(target_state)

        # Логика автоскрытия для IDLE/ERROR переехала в AssistantOverlayWidget (через таймеры)
        # но мы можем оставить спец. обработку если нужно
        if state == AssistantState.ERROR:
            # Можно вывести сообщение об ошибке в лог или статусную строку
            pass

    def _on_assistant_transcript(self, text: str) -> None:
        """Добавить сообщение пользователя в оверлей."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return
        if not self.config.config.get("assistant_enabled", False):
            return
        self.assistant_overlay.append_message("user", text)

    def _on_assistant_response(self, text: str) -> None:
        """Добавить ответ ассистента в оверлей."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return
        if not self.config.config.get("assistant_enabled", False):
            return
        self.assistant_overlay.append_message("assistant", text)

    def _on_assistant_overlay_stop(self) -> None:
        """Стоп из оверлея: прервать текущую операцию и начать слушать заново."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "interrupt"):
            self.voice_assistant.interrupt(start_listening=True)  # type: ignore[attr-defined]
        else:
            self.voice_assistant.stop()

    def _on_assistant_overlay_cancel(self) -> None:
        """Отмена из оверлея: просто остановить всё и уйти в IDLE."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "interrupt"):
            self.voice_assistant.interrupt(start_listening=False)  # type: ignore[attr-defined]
        else:
            self.voice_assistant.stop()
        if self.assistant_overlay:
            self.assistant_overlay.hide_overlay()

    def _on_assistant_overlay_send(self) -> None:
        """Принудительная отправка аудио на обработку."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "force_send"):
            self.voice_assistant.force_send()  # type: ignore[attr-defined]

    def _on_assistant_overlay_new_dialog(self) -> None:
        """Новый диалог: очистить контекст и UI."""
        if self.assistant_overlay:
            self.assistant_overlay.clear_messages()
        if self.voice_assistant:
            self.voice_assistant.clear_history()

    def _on_assistant_overlay_closed(self) -> None:
        """Пользователь закрыл оверлей: остановить всё и скрыть."""
        if self.voice_assistant:
            if hasattr(self.voice_assistant, "interrupt"):
                self.voice_assistant.interrupt(start_listening=False)
            else:
                self.voice_assistant.stop()
        if self.assistant_overlay:
            self.assistant_overlay.hide_overlay()

    def _load_assistant_settings(self) -> None:
        """Загрузить настройки ассистента в UI."""
        # Проверяем, что UI ассистента уже создан
        if self.assistant_enable_check is None:
            return

        cfg = self.config.config

        # Включение
        self.assistant_enable_check.setChecked(cfg.get("assistant_enabled", False))

        # Hotkey
        self.assistant_hotkey_edit.setText(cfg.get("assistant_hotkey", "ctrl+shift+a"))

        # Wake word
        self.assistant_use_wake_word_check.setChecked(cfg.get("assistant_use_wake_word", True))
        wake_word = cfg.get("assistant_wake_word", "hey_jarvis")
        idx = self.assistant_wake_combo.findData(wake_word)
        if idx >= 0:
            self.assistant_wake_combo.setCurrentIndex(idx)
        self.assistant_beep_check.setChecked(cfg.get("assistant_beep_on_wake", True))

        # TTS
        tts_lang = cfg.get("assistant_tts_language", "ru")
        idx = self.assistant_tts_lang_combo.findData(tts_lang)
        if idx >= 0:
            self.assistant_tts_lang_combo.setCurrentIndex(idx)
        self._load_tts_voices(tts_lang)

        tts_voice = cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural")
        idx = self.assistant_voice_combo.findData(tts_voice)
        if idx >= 0:
            self.assistant_voice_combo.setCurrentIndex(idx)

        tts_rate = cfg.get("assistant_tts_rate", 0)
        self.assistant_speed_slider.setValue(tts_rate)
        self._update_speed_label(tts_rate)

        # Личность
        personality = cfg.get("assistant_personality", "friendly")
        idx = self.assistant_personality_combo.findData(personality)
        if idx >= 0:
            self.assistant_personality_combo.setCurrentIndex(idx)

        system_prompt = cfg.get("assistant_system_prompt", PERSONALITY_TEMPLATES["friendly"]["prompt"])
        self.assistant_system_prompt_edit.setText(system_prompt)

    def _load_tts_voices(self, language: str) -> None:
        """Загрузить голоса TTS для выбранного языка."""
        self.assistant_voice_combo.clear()

        if not is_edge_tts_available():
            self.assistant_voice_combo.addItem("Edge TTS не установлен", "")
            return

        try:
            tts_engine = get_tts_engine()
            # Получаем голоса для языка (первые 2 символа из locale)
            voices = tts_engine.get_voices(language)

            if not voices:
                self.assistant_voice_combo.addItem("Нет доступных голосов", "")
                return

            for voice in voices[:10]:  # Ограничим до 10 голосов
                self.assistant_voice_combo.addItem(voice.display_name, voice.short_name)

        except Exception as e:
            logger.error(f"Ошибка загрузки TTS голосов: {e}")
            self.assistant_voice_combo.addItem("Ошибка загрузки", "")

    def _update_speed_label(self, value: int) -> None:
        """Обновить метку скорости речи."""
        speed_factor = 1.0 + (value / 100.0)
        self.assistant_speed_label.setText(f"{speed_factor:.1f}x")

    def _connect_assistant_signals(self) -> None:
        """Подключить сигналы ассистента."""
        if not ASSISTANT_FEATURE_ENABLED:
            return

        # Проверяем, что UI создан
        if self.assistant_enable_check is None:
            return

        # Сигналы для thread-safe обновления UI из фоновых потоков
        self.assistant_state_signal.connect(self._on_assistant_state_changed)
        self.assistant_transcript_signal.connect(self._on_assistant_transcript)
        self.assistant_response_signal.connect(self._on_assistant_response)
        if self.assistant_overlay:
            self.assistant_level_signal.connect(self.assistant_overlay.update_level)

            # Сигналы от оверлея
            self.assistant_overlay.cancelled.connect(self._on_assistant_overlay_cancel)
            self.assistant_overlay.stop_clicked.connect(self._on_assistant_overlay_stop)
            self.assistant_overlay.new_dialog_clicked.connect(self._on_assistant_overlay_new_dialog)
            self.assistant_overlay.closed.connect(self._on_assistant_overlay_closed)
            self.assistant_overlay.send_clicked.connect(self._on_assistant_overlay_send)

        # Включение/выключение
        self.assistant_enable_check.toggled.connect(self._on_assistant_enable_toggle)

        # Hotkey
        self.assistant_hotkey_record_btn.clicked.connect(self._on_record_assistant_hotkey)

        # Wake word
        self.assistant_use_wake_word_check.toggled.connect(
            lambda v: self.config.update(assistant_use_wake_word=v)
        )
        self.assistant_wake_combo.currentIndexChanged.connect(
            lambda: self.config.update(assistant_wake_word=self.assistant_wake_combo.currentData())
        )
        self.assistant_beep_check.toggled.connect(
            lambda v: self.config.update(assistant_beep_on_wake=v)
        )

        # TTS
        self.assistant_tts_lang_combo.currentIndexChanged.connect(self._on_assistant_tts_lang_change)
        self.assistant_voice_combo.currentIndexChanged.connect(
            lambda: self.config.update(assistant_tts_voice=self.assistant_voice_combo.currentData())
        )
        self.assistant_speed_slider.valueChanged.connect(self._on_assistant_speed_change)
        self.assistant_test_voice_btn.clicked.connect(self._on_test_assistant_voice)

        # Нормализация - удалено, всегда включено

        # Личность
        self.assistant_personality_combo.currentIndexChanged.connect(self._on_assistant_personality_change)
        self.assistant_system_prompt_edit.textChanged.connect(self._on_assistant_prompt_change)

    def _on_assistant_enable_toggle(self, enabled: bool) -> None:
        """Обработка включения/выключения ассистента."""
        self.config.update(assistant_enabled=enabled)

        if self.voice_assistant:
            if enabled:
                if not is_openwakeword_available():
                    QMessageBox.warning(
                        self,
                        "openWakeWord не установлен",
                        "Для работы голосового ассистента необходимо установить openWakeWord:\n\npip install openwakeword"
                    )
                    self.assistant_enable_check.setChecked(False)
                    return

                if not is_edge_tts_available():
                    QMessageBox.warning(
                        self,
                        "edge-tts не установлен",
                        "Для работы голосового ассистента необходимо установить edge-tts:\n\npip install edge-tts"
                    )
                    self.assistant_enable_check.setChecked(False)
                    return

                self.voice_assistant.start()
            else:
                self.voice_assistant.stop()

    def _on_assistant_tts_lang_change(self) -> None:
        """Обработка смены языка TTS."""
        lang = self.assistant_tts_lang_combo.currentData()
        self.config.update(assistant_tts_language=lang)
        self._load_tts_voices(lang)

    def _on_assistant_speed_change(self, value: int) -> None:
        """Обработка изменения скорости речи."""
        self.config.update(assistant_tts_rate=value)
        self._update_speed_label(value)

    def _on_test_assistant_voice(self) -> None:
        """Тест голоса ассистента."""
        if not is_edge_tts_available():
            QMessageBox.warning(self, "Ошибка", "edge-tts не установлен")
            return

        voice = self.assistant_voice_combo.currentData()
        rate = self.assistant_speed_slider.value()

        try:
            tts = get_tts_engine()
            tts.set_voice(voice)
            tts.set_rate(rate)

            test_text = "Привет! Я твой голосовой ассистент."
            tts.speak(test_text, blocking=False)
        except Exception as e:
            logger.error(f"Ошибка теста голоса: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось протестировать голос:\n{e}")

    def _on_assistant_personality_change(self) -> None:
        """Обработка смены шаблона личности."""
        personality = self.assistant_personality_combo.currentData()
        self.config.update(assistant_personality=personality)

        if personality != "custom" and personality in PERSONALITY_TEMPLATES:
            prompt = PERSONALITY_TEMPLATES[personality]["prompt"]
            self.assistant_system_prompt_edit.setText(prompt)

    def _on_assistant_prompt_change(self) -> None:
        """Обработка изменения system prompt."""
        prompt = self.assistant_system_prompt_edit.toPlainText()
        self.config.update(assistant_system_prompt=prompt)

    def _on_record_assistant_hotkey(self) -> None:
        """Записать новые горячие клавиши для ассистента."""
        self.assistant_hotkey_record_btn.setEnabled(False)
        self.assistant_hotkey_edit.setText("Нажмите клавиши...")

        # Используем тот же рекордер что для основного hotkey
        def on_hotkey_recorded(combo: str) -> None:
            self.assistant_hotkey_edit.setText(combo)
            self.config.update(assistant_hotkey=combo)
            self.assistant_hotkey_record_btn.setEnabled(True)
            self._reinit_assistant_hotkey()

        self._assistant_hotkey_recorder = HotkeyRecorder(on_hotkey_recorded)
        self._assistant_hotkey_recorder.start()

    def _init_assistant_hotkey(self) -> None:
        """Инициализировать горячие клавиши ассистента."""
        hotkey_combo = self.config.config.get("assistant_hotkey", "ctrl+shift+a")
        if not hotkey_combo:
            return

        try:
            if hasattr(self, '_assistant_hotkey_listener') and self._assistant_hotkey_listener:
                self._assistant_hotkey_listener.stop()

            self._assistant_hotkey_listener = HotkeyListener(
                hotkey_combo,
                handler=self._on_assistant_hotkey_press,
            )
            self._assistant_hotkey_listener.start()
            logger.info(f"[Assistant] Горячие клавиши ассистента зарегистрированы: {hotkey_combo}")
        except Exception as e:
            logger.error(f"[Assistant] Ошибка регистрации горячих клавиш: {e}")

    def _reinit_assistant_hotkey(self) -> None:
        """Переинициализировать горячие клавиши ассистента."""
        self._init_assistant_hotkey()

    def _on_assistant_hotkey_press(self) -> None:
        """Обработка нажатия горячих клавиш ассистента."""
        logger.info("[Assistant] 🎹 Горячие клавиши нажаты! Активирую ассистента...")

        if not self.voice_assistant:
            logger.warning("[Assistant] Ассистент не инициализирован")
            return

        if not self.config.config.get("assistant_enabled", False):
            logger.warning("[Assistant] Ассистент отключён в настройках")
            return

        # Публичная активация: если ассистент говорит — прервёт и начнёт слушать
        if hasattr(self.voice_assistant, "activate"):
            self.voice_assistant.activate()
        else:
            # Fallback для старых версий
            if hasattr(self.voice_assistant, "_on_wake_word_detected"):
                self.voice_assistant._on_wake_word_detected()
            else:
                logger.error("[Assistant] Метод активации не найден")

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

        # Вкладки - порядок: Основные, Саммари, Настройки
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), self._t("basic"))
        self.tabs.addTab(self._build_files_tab(), self._t("files_tab"))
        self.tabs.addTab(self._build_additional_tab(), self._t("additional"))
        main_layout.addWidget(self.tabs)

        # Журнал событий (внизу окна)
        main_layout.addWidget(self._build_journal_section())

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

        # Скролл для всего контента
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        content = QWidget()
        content.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(content)
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

        # Квантование/Оптимизация
        self.quant_label = QLabel(self._t("quantization"))
        self.compute_box = QComboBox()
        for ct in ["auto", "int8", "int8_float16", "float16", "float32"]:
            self.compute_box.addItem(ct)
        perf_layout.addWidget(self.quant_label, perf_row, 0)
        perf_layout.addWidget(self.compute_box, perf_row, 1)
        perf_row += 1

        # Устройство (Accelerator)
        self.accel_label = QLabel(self._t("device"))
        self.accel_box = QComboBox()
        for mode in ["auto", "npu", "gpu", "cpu"]:
            self.accel_box.addItem(mode)
        perf_layout.addWidget(self.accel_label, perf_row, 0)
        perf_layout.addWidget(self.accel_box, perf_row, 1)
        perf_row += 1

        # Статус NPU
        if has_npu():
            npu_status = QLabel(f"✓ NPU обнаружен ({detect_available_providers()[0]})")
            npu_status.setStyleSheet("color: green; font-size: 10px;")
            perf_layout.addWidget(npu_status, perf_row, 1)
            perf_row += 1

        # Бэкенд транскрипции
        self.backend_label = QLabel("Бэкенд Whisper")
        self.backend_box = QComboBox()
        self.backend_box.addItem("Whisper.cpp (быстро)", "whisper_cpp")
        self.backend_box.addItem("Faster-Whisper (CUDA)", "faster_whisper")
        self.backend_box.addItem("ONNX Runtime (NPU)", "onnx")
        perf_layout.addWidget(self.backend_label, perf_row, 0)
        perf_layout.addWidget(self.backend_box, perf_row, 1)
        perf_row += 1

        # Модель
        self.model_label = QLabel(self._t("model"))
        self.model_box = QComboBox()
        self._populate_model_combo()
        perf_layout.addWidget(self.model_label, perf_row, 0)
        perf_layout.addWidget(self.model_box, perf_row, 1)
        perf_row += 1

        # Предупреждение о distil
        self.distil_warning = QLabel(self._t("distil_en_only"))
        self.distil_warning.setObjectName("warning")
        perf_layout.addWidget(self.distil_warning, perf_row, 1)
        perf_row += 1

        # Кнопка скачивания модели
        self.download_btn = QPushButton(self._t("download_model"))
        self.download_btn.setObjectName("downloadButton")
        perf_layout.addWidget(self.download_btn, perf_row, 0, 1, 2)
        perf_row += 1

        # Прогресс скачивания
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(True)
        perf_layout.addWidget(self.download_progress, perf_row, 0, 1, 2)
        perf_row += 1

        self.download_status_label = QLabel("")
        perf_layout.addWidget(self.download_status_label, perf_row, 0, 1, 2)
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

        # === Секция AI Provider ===
        ai_section = QWidget()
        ai_layout = QGridLayout(ai_section)
        ai_layout.setContentsMargins(0, 0, 0, 0)
        ai_layout.setSpacing(8)
        ai_layout.setColumnStretch(1, 1)

        ai_row = 0

        # Заголовок секции
        self.ai_section_label = QLabel(self._t("ai_provider"))
        self.ai_section_label.setStyleSheet("font-weight: bold;")
        ai_layout.addWidget(self.ai_section_label, ai_row, 0, 1, 2)
        ai_row += 1

        # Выбор провайдера
        self.provider_label = QLabel(self._t("llm_provider"))
        self.provider_combo = QComboBox()
        self.provider_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid #000000;
                padding: 4px 8px;
                background-color: #ffffff;
                min-width: 200px;
            }
            QComboBox::drop-down {
                border: none;
                border-left: 2px solid #000000;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                border: 2px solid #000000;
                background-color: #ffffff;
                selection-background-color: #000000;
                selection-color: #ffffff;
            }
        """)
        # Добавляем провайдеры
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.addItem("Claude (Anthropic)", "anthropic")
        self.provider_combo.addItem("Gemini (Google)", "gemini")
        self.provider_combo.addItem("Ollama (Local)", "ollama")
        self.provider_combo.addItem("OpenRouter (Private)", "openrouter")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        ai_layout.addWidget(self.provider_label, ai_row, 0)
        ai_layout.addWidget(self.provider_combo, ai_row, 1)
        ai_row += 1

        # API ключ
        self.api_key_label = QLabel(self._t("api_key"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setStyleSheet("""
            QLineEdit {
                border: 2px solid #000000;
                padding: 4px 8px;
                background-color: #ffffff;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        ai_layout.addWidget(self.api_key_label, ai_row, 0)
        ai_layout.addWidget(self.api_key_edit, ai_row, 1)
        ai_row += 1

        # Base URL (для Ollama)
        self.base_url_label = QLabel(self._t("base_url"))
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("http://localhost:11434")
        self.base_url_edit.setStyleSheet("""
            QLineEdit {
                border: 2px solid #000000;
                padding: 4px 8px;
                background-color: #ffffff;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        ai_layout.addWidget(self.base_url_label, ai_row, 0)
        ai_layout.addWidget(self.base_url_edit, ai_row, 1)
        ai_row += 1

        # Выбор модели с поиском
        self.model_select_label = QLabel(self._t("openrouter_model"))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)  # Editable для поиска
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_combo.lineEdit().setPlaceholderText(self._t("search_model"))
        self.model_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid #000000;
                padding: 4px 8px;
                background-color: #ffffff;
                min-width: 250px;
            }
            QComboBox::drop-down {
                border: none;
                border-left: 2px solid #000000;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                border: 2px solid #000000;
                background-color: #ffffff;
                selection-background-color: #000000;
                selection-color: #ffffff;
            }
        """)
        self.model_combo.addItem(self._t("select_model"), "")

        self.refresh_models_btn = QPushButton(self._t("refresh_models"))
        self.refresh_models_btn.setStyleSheet("""
            QPushButton {
                border: 2px solid #000000;
                padding: 4px 12px;
                background-color: #ffffff;
                border-top-color: #ffffff;
                border-left-color: #ffffff;
                border-right-color: #808080;
                border-bottom-color: #808080;
            }
            QPushButton:pressed {
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
            }
            QPushButton:disabled { color: #808080; }
        """)
        self.refresh_models_btn.clicked.connect(self._on_refresh_models)

        model_row.addWidget(self.model_combo, stretch=1)
        model_row.addWidget(self.refresh_models_btn)
        ai_layout.addWidget(self.model_select_label, ai_row, 0)
        ai_layout.addLayout(model_row, ai_row, 1)
        ai_row += 1

        # Reasoning mode
        reasoning_row = QHBoxLayout()
        self.reasoning_checkbox = QCheckBox(self._t("reasoning_mode"))
        self.reasoning_checkbox.setToolTip(self._t("reasoning_tooltip"))
        self.reasoning_checkbox.stateChanged.connect(self._on_reasoning_changed)
        reasoning_row.addWidget(self.reasoning_checkbox)

        # Effort комбобокс
        self.effort_label = QLabel(self._t("reasoning_effort"))
        self.effort_combo = QComboBox()
        self.effort_combo.addItem(self._t("effort_low"), "low")
        self.effort_combo.addItem(self._t("effort_medium"), "medium")
        self.effort_combo.addItem(self._t("effort_high"), "high")
        self.effort_combo.setCurrentIndex(1)  # medium по умолчанию
        self.effort_combo.setStyleSheet("""
            QComboBox {
                border: 2px solid #000000;
                padding: 2px 6px;
                background-color: #ffffff;
                min-width: 80px;
            }
        """)
        self.effort_combo.currentIndexChanged.connect(self._on_effort_changed)
        reasoning_row.addWidget(self.effort_label)
        reasoning_row.addWidget(self.effort_combo)
        reasoning_row.addStretch()
        ai_layout.addLayout(reasoning_row, ai_row, 0, 1, 2)
        ai_row += 1

        # Загрузка сохранённых настроек провайдера
        cfg = self.config.config

        # Загружаем выбранный провайдер
        saved_provider = cfg.get("llm_provider", "openrouter")
        provider_idx = self.provider_combo.findData(saved_provider)
        if provider_idx >= 0:
            self.provider_combo.setCurrentIndex(provider_idx)

        # Загружаем API ключ для текущего провайдера
        self._load_provider_settings(saved_provider)

        # Загрузка reasoning настроек
        self.reasoning_checkbox.setChecked(cfg.get("llm_reasoning_enabled", True))
        effort = cfg.get("llm_reasoning_effort", "medium")
        effort_idx = self.effort_combo.findData(effort)
        if effort_idx >= 0:
            self.effort_combo.setCurrentIndex(effort_idx)

        # Обновляем доступность полей при переключении
        self.api_key_edit.textChanged.connect(self._on_api_key_changed)
        self.base_url_edit.textChanged.connect(self._on_base_url_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)

        # Обновляем видимость полей для текущего провайдера
        self._update_provider_fields()

        layout.addWidget(ai_section)
        layout.addStretch()

        scroll.setWidget(content)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

        return tab

    def _build_assistant_tab(self) -> QWidget:
        """Построить вкладку голосового ассистента (Classic Mac OS System 7 style)."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")

        # Скролл для всего контента
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: #ffffff; border: none; }")

        content = QWidget()
        content.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        # Главный чекбокс включения ассистента
        self.assistant_enable_check = QCheckBox(self._t("assistant_enable"))
        self.assistant_enable_check.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.assistant_enable_check)

        # === Wake Word секция ===
        wake_group = QGroupBox(self._t("assistant_wake_word"))
        wake_group.setStyleSheet("""
            QGroupBox {
                border: 2px solid #000000;
                border-radius: 0px;
                margin-top: 8px;
                background-color: #ffffff;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #ffffff;
            }
        """)
        wake_layout = QGridLayout()
        wake_layout.setContentsMargins(8, 12, 8, 8)
        wake_layout.setSpacing(8)
        wake_layout.setColumnStretch(1, 1)

        row = 0
        # Чекбокс "Использовать Wake Word"
        self.assistant_use_wake_word_check = QCheckBox(self._t("assistant_use_wake_word"))
        wake_layout.addWidget(self.assistant_use_wake_word_check, row, 0, 1, 2)
        row += 1

        # Фраза активации
        wake_phrase_label = QLabel(self._t("assistant_phrase") + ":")
        self.assistant_wake_combo = QComboBox()
        self.assistant_wake_combo.addItem("hey jarvis", "hey_jarvis")
        self.assistant_wake_combo.addItem("alexa", "alexa")
        self.assistant_wake_combo.addItem("hey mycroft", "hey_mycroft")
        wake_layout.addWidget(wake_phrase_label, row, 0)
        wake_layout.addWidget(self.assistant_wake_combo, row, 1)
        row += 1

        # Звуковой сигнал
        self.assistant_beep_check = QCheckBox(self._t("assistant_beep"))
        wake_layout.addWidget(self.assistant_beep_check, row, 0, 1, 2)
        row += 1

        wake_group.setLayout(wake_layout)
        layout.addWidget(wake_group)

        # === Горячие клавиши секция ===
        hotkey_group = QGroupBox(self._t("assistant_hotkey"))
        hotkey_group.setStyleSheet(wake_group.styleSheet())
        hotkey_layout = QGridLayout()
        hotkey_layout.setContentsMargins(8, 12, 8, 8)
        hotkey_layout.setSpacing(8)
        hotkey_layout.setColumnStretch(1, 1)

        row = 0
        # Горячие клавиши
        hotkey_label = QLabel(self._t("assistant_hotkey_label"))
        self.assistant_hotkey_edit = QLineEdit()
        self.assistant_hotkey_edit.setReadOnly(True)
        self.assistant_hotkey_edit.setPlaceholderText("ctrl+shift+a")
        self.assistant_hotkey_record_btn = QPushButton(self._t("assistant_hotkey_record"))
        self.assistant_hotkey_record_btn.setFixedWidth(80)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.assistant_hotkey_edit)
        hotkey_row.addWidget(self.assistant_hotkey_record_btn)

        hotkey_layout.addWidget(hotkey_label, row, 0)
        hotkey_layout.addLayout(hotkey_row, row, 1)
        row += 1

        hotkey_group.setLayout(hotkey_layout)
        layout.addWidget(hotkey_group)

        # === Голос TTS секция ===
        voice_group = QGroupBox(self._t("assistant_voice"))
        voice_group.setStyleSheet(wake_group.styleSheet())
        voice_layout = QGridLayout()
        voice_layout.setContentsMargins(8, 12, 8, 8)
        voice_layout.setSpacing(8)
        voice_layout.setColumnStretch(1, 1)

        row = 0
        # Язык голоса
        voice_lang_label = QLabel(self._t("assistant_tts_language") + ":")
        self.assistant_tts_lang_combo = QComboBox()
        # Популярные языки для TTS
        tts_languages = [
            ("ru", "Русский (ru-RU)"),
            ("en", "English (en-US)"),
            ("de", "Deutsch (de-DE)"),
            ("fr", "Français (fr-FR)"),
            ("es", "Español (es-ES)"),
            ("zh", "中文 (zh-CN)"),
            ("ja", "日本語 (ja-JP)"),
        ]
        for code, name in tts_languages:
            self.assistant_tts_lang_combo.addItem(name, code)
        voice_layout.addWidget(voice_lang_label, row, 0)
        voice_layout.addWidget(self.assistant_tts_lang_combo, row, 1)
        row += 1

        # Выбор голоса
        voice_label = QLabel(self._t("assistant_tts_voice") + ":")
        self.assistant_voice_combo = QComboBox()
        voice_layout.addWidget(voice_label, row, 0)
        voice_layout.addWidget(self.assistant_voice_combo, row, 1)
        row += 1

        # Скорость речи
        speed_label = QLabel(self._t("assistant_tts_speed") + ":")
        speed_row = QHBoxLayout()
        self.assistant_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.assistant_speed_slider.setRange(-50, 50)
        self.assistant_speed_slider.setValue(0)
        self.assistant_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.assistant_speed_slider.setTickInterval(25)
        self.assistant_speed_label = QLabel("1.0x")
        self.assistant_speed_label.setFixedWidth(50)
        speed_row.addWidget(self.assistant_speed_slider)
        speed_row.addWidget(self.assistant_speed_label)
        voice_layout.addWidget(speed_label, row, 0)
        voice_layout.addLayout(speed_row, row, 1)
        row += 1

        # Кнопка теста голоса
        self.assistant_test_voice_btn = QPushButton(self._t("assistant_test_voice"))
        voice_layout.addWidget(self.assistant_test_voice_btn, row, 0, 1, 2)
        row += 1

        voice_group.setLayout(voice_layout)
        layout.addWidget(voice_group)

        # === Личность секция ===
        personality_group = QGroupBox(self._t("assistant_personality"))
        personality_group.setStyleSheet(wake_group.styleSheet())
        personality_layout = QVBoxLayout()
        personality_layout.setContentsMargins(8, 12, 8, 8)
        personality_layout.setSpacing(8)

        # Шаблон личности
        template_label = QLabel(self._t("assistant_personality_template") + ":")
        self.assistant_personality_combo = QComboBox()
        self.assistant_personality_combo.addItem(self._t("assistant_personality_friendly"), "friendly")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_professional"), "professional")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_creative"), "creative")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_programmer"), "programmer")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_custom"), "custom")
        template_row = QHBoxLayout()
        template_row.addWidget(template_label)
        template_row.addWidget(self.assistant_personality_combo, stretch=1)
        personality_layout.addLayout(template_row)

        # System Prompt
        prompt_label = QLabel(self._t("assistant_system_prompt") + ":")
        personality_layout.addWidget(prompt_label)

        from PyQt6.QtWidgets import QTextEdit
        self.assistant_system_prompt_edit = QTextEdit()
        self.assistant_system_prompt_edit.setMaximumHeight(80)
        self.assistant_system_prompt_edit.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
                padding: 4px;
                color: #000000;
            }
        """)
        personality_layout.addWidget(self.assistant_system_prompt_edit)

        personality_group.setLayout(personality_layout)
        layout.addWidget(personality_group)

        layout.addStretch()

        scroll.setWidget(content)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

        return tab

    def _build_files_tab(self) -> QWidget:
        """Построить вкладку транскрибции файлов."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        # === Зона Drag & Drop ===
        self.drop_zone = DropZoneWidget(translate_func=self._t)
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.drop_zone.clicked.connect(self._on_select_files_clicked)
        layout.addWidget(self.drop_zone)

        # === Настройки вывода ===
        settings_layout = QGridLayout()
        settings_layout.setSpacing(8)

        # Формат вывода
        self.output_format_label = QLabel(self._t("output_format"))
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        settings_layout.addWidget(self.output_format_label, 0, 0)
        settings_layout.addWidget(self.output_format_combo, 0, 1)

        # Папка сохранения
        self.output_folder_label = QLabel(self._t("output_folder"))
        output_folder_row = QHBoxLayout()
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        # По умолчанию - папка "Документы"
        default_output = Path.home() / "Documents" / "MindType Transcriptions"
        self.output_folder_edit.setText(str(default_output))
        self._output_dir = default_output

        self.browse_folder_btn = QPushButton(self._t("browse"))
        self.browse_folder_btn.clicked.connect(self._on_browse_output_folder)
        output_folder_row.addWidget(self.output_folder_edit)
        output_folder_row.addWidget(self.browse_folder_btn)
        settings_layout.addWidget(self.output_folder_label, 1, 0)
        settings_layout.addLayout(output_folder_row, 1, 1)

        # Включить суммаризацию
        self.enable_summary_checkbox = QCheckBox(self._t("enable_summary"))
        self.enable_summary_checkbox.setChecked(True)
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        settings_layout.addWidget(self.enable_summary_checkbox, 2, 0, 1, 2)

        # Кнопка настройки промптов
        self.customize_prompts_btn = QPushButton(self._t("customize_prompts"))
        self.customize_prompts_btn.clicked.connect(self._on_customize_prompts)
        settings_layout.addWidget(self.customize_prompts_btn, 3, 0, 1, 2)

        layout.addLayout(settings_layout)

        # === Очередь файлов ===
        queue_header = QHBoxLayout()
        self.queue_title_label = QLabel(self._t("processing_queue"))
        self.queue_title_label.setStyleSheet("font-weight: bold;")
        queue_header.addWidget(self.queue_title_label)
        queue_header.addStretch()

        self.clear_queue_btn = QPushButton(self._t("clear_queue"))
        self.clear_queue_btn.clicked.connect(self._on_clear_queue)
        queue_header.addWidget(self.clear_queue_btn)

        layout.addLayout(queue_header)

        # Список файлов
        self._file_queue_scroll = QScrollArea()
        self._file_queue_scroll.setWidgetResizable(True)
        self._file_queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._file_queue_scroll.setStyleSheet("QScrollArea { border: 1px solid #000000; }")

        self._file_queue_content = QWidget()
        self._file_queue_content.setStyleSheet("background-color: #ffffff;")
        self._file_queue_layout = QVBoxLayout(self._file_queue_content)
        self._file_queue_layout.setContentsMargins(4, 4, 4, 4)
        self._file_queue_layout.setSpacing(4)

        # Placeholder
        self._no_files_label = QLabel(self._t("no_files_in_queue"))
        self._no_files_label.setStyleSheet("color: #808080; padding: 20px;")
        self._no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_queue_layout.addWidget(self._no_files_label)
        self._file_queue_layout.addStretch()

        self._file_queue_scroll.setWidget(self._file_queue_content)
        layout.addWidget(self._file_queue_scroll, stretch=1)

        # === Блок AI Thinking (Classic Mac OS style) ===
        self._thinking_frame = QFrame()
        self._thinking_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
        """)
        self._thinking_frame.setVisible(False)  # Скрыт по умолчанию
        thinking_layout = QVBoxLayout(self._thinking_frame)
        thinking_layout.setContentsMargins(0, 0, 0, 0)
        thinking_layout.setSpacing(0)

        # Заголовок окна (Classic Mac style)
        thinking_header_frame = QFrame()
        thinking_header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #000000, stop:0.5 #808080, stop:1 #000000);
                border: none;
                padding: 2px 4px;
            }
        """)
        thinking_header_frame.setFixedHeight(22)
        thinking_header = QHBoxLayout(thinking_header_frame)
        thinking_header.setContentsMargins(8, 2, 4, 2)

        self._thinking_title = QLabel("AI Thinking")
        self._thinking_title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        thinking_header.addWidget(self._thinking_title)
        thinking_header.addStretch()

        # Кнопка закрытия (Classic Mac style)
        close_thinking_btn = QPushButton()
        close_thinking_btn.setFixedSize(12, 12)
        close_thinking_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #000000;
            }
            QPushButton:hover {
                background-color: #c0c0c0;
            }
        """)
        close_thinking_btn.clicked.connect(lambda: self._thinking_frame.setVisible(False))
        thinking_header.addWidget(close_thinking_btn)
        thinking_layout.addWidget(thinking_header_frame)

        # Текстовое поле для вывода (Classic Mac style)
        from PyQt6.QtWidgets import QTextEdit
        self._thinking_output = QTextEdit()
        self._thinking_output.setReadOnly(True)
        self._thinking_output.setMinimumHeight(100)
        self._thinking_output.setMaximumHeight(150)
        self._thinking_output.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #000000;
                border: none;
                border-top: 1px solid #808080;
                font-family: "Geneva", "VT323", "Courier New", monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        thinking_layout.addWidget(self._thinking_output)

        # Буфер для накопления текста
        self._thinking_buffer = ""

        layout.addWidget(self._thinking_frame)

        # === Кнопки управления ===
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        self.start_processing_btn = QPushButton(self._t("start_processing"))
        self.start_processing_btn.setStyleSheet("font-weight: bold;")
        self.start_processing_btn.clicked.connect(self._on_start_processing)
        self.start_processing_btn.setEnabled(False)
        buttons_layout.addWidget(self.start_processing_btn)

        self.stop_processing_btn = QPushButton(self._t("stop_processing"))
        self.stop_processing_btn.clicked.connect(self._on_stop_processing)
        self.stop_processing_btn.setEnabled(False)
        self.stop_processing_btn.setVisible(False)
        buttons_layout.addWidget(self.stop_processing_btn)

        layout.addLayout(buttons_layout)

        return tab

    def _on_ui_language_changed(self, idx: int) -> None:
        """Сменить язык интерфейса."""
        code = self.ui_lang_box.currentData()
        if code and code != self._ui_lang:
            self._ui_lang = code
            self.config.update(ui_language=code)
            self._update_ui_texts()

    def _build_journal_section(self) -> QWidget:
        """Построить секцию журнала событий."""
        section = QWidget()
        section.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)

        # Заголовок журнала
        journal_header = QHBoxLayout()
        self.journal_title = QLabel(self._t("journal"))
        self.journal_title.setStyleSheet("font-weight: bold;")
        journal_header.addWidget(self.journal_title)
        journal_header.addStretch()

        self.clear_journal_btn = QPushButton(self._t("clear_journal"))
        self.clear_journal_btn.clicked.connect(self._clear_journal)
        journal_header.addWidget(self.clear_journal_btn)
        layout.addLayout(journal_header)

        # Виджет журнала
        self.journal = JournalWidget(translate_func=self._t)
        self.journal.setMaximumHeight(120)  # Ограничиваем высоту
        layout.addWidget(self.journal)

        return section

    def _build_history_tab(self) -> QWidget:
        """Построить вкладку истории и журнала."""
        tab = QWidget()
        tab.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)

        # === История транскрипций ===
        self.transcription_history = TranscriptionHistoryWidget(translate_func=self._t)
        layout.addWidget(self.transcription_history, stretch=2)

        # === История диалогов ассистента ===
        self.assistant_dialog_history = AssistantDialogHistoryWidget(translate_func=self._t)
        self.assistant_dialog_history.continue_clicked.connect(self._on_continue_dialog)
        self.assistant_dialog_history.delete_clicked.connect(self._on_dialog_deleted)
        layout.addWidget(self.assistant_dialog_history, stretch=3)

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
        layout.addWidget(self.journal, stretch=1)

        return tab

    def _clear_journal(self):
        """Очистить журнал событий."""
        self.journal.clear()

    def _on_continue_dialog(self, dialog: Dialog):
        """Продолжить диалог из истории."""
        if not ASSISTANT_FEATURE_ENABLED or not self.voice_assistant:
            return
        # Загружаем диалог в ассистента
        self.voice_assistant.load_dialog(dialog)
        # Показываем оверлей с историей
        if self.assistant_overlay:
            self.assistant_overlay.clear_messages()
            for msg in dialog.messages:
                self.assistant_overlay.append_message(msg.role, msg.content)
            self.assistant_overlay.set_state_text("Готов")
            self.assistant_overlay.show_overlay()
        logger.info(f"[Main] Продолжен диалог: {dialog.title}")

    def _on_dialog_deleted(self, dialog_id: str):
        """Диалог удалён из истории."""
        logger.info(f"[Main] Диалог удалён: {dialog_id}")

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
        self.accel_box.currentTextChanged.connect(lambda v: self.config.update(accelerator=v))
        self.backend_box.currentIndexChanged.connect(lambda i: self.config.update(transcriber_backend=self.backend_box.itemData(i)))
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

        # Сигнал AI thinking
        self.thinking_signal.connect(self._update_thinking_output)

        # Отмена транскрипции через overlay
        self.overlay.cancelled.connect(self._cancel_transcription)

        # Сигналы голосового ассистента
        self._connect_assistant_signals()

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
        self.accel_box.setCurrentText(cfg.get("accelerator", "auto"))
        backend = cfg.get("transcriber_backend", "whisper_cpp")
        idx = self.backend_box.findData(backend)
        if idx >= 0:
            self.backend_box.setCurrentIndex(idx)

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

        # Загрузка настроек ассистента
        self._load_assistant_settings()

    def _load_mics(self) -> None:
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        for dev in self.audio.list_input_devices():
            self.mic_box.addItem(dev)
        self.mic_box.blockSignals(False)

    def _get_current_mic_index(self) -> Optional[int]:
        """Получить индекс текущего микрофона."""
        current_mic = self.config.config.get("microphone")
        if not current_mic:
            return None

        # Извлекаем номер из строки формата "0: Microphone Name"
        try:
            if ":" in current_mic:
                index_str = current_mic.split(":")[0].strip()
                return int(index_str)
        except (ValueError, IndexError):
            pass

        return None

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

    def _update_thinking_output(self, text: str) -> None:
        """Обновить блок AI thinking (Qt thread)."""
        if not hasattr(self, '_thinking_frame'):
            return

        # Показываем блок если скрыт
        if not self._thinking_frame.isVisible():
            self._thinking_frame.setVisible(True)
            self._thinking_output.clear()
            self._thinking_buffer = ""

        # Накапливаем текст в буфер
        self._thinking_buffer += text

        # Выводим только полные строки (или специальные маркеры)
        if "\n" in self._thinking_buffer or text.startswith("["):
            # Разбиваем на строки
            lines = self._thinking_buffer.split("\n")

            # Выводим все полные строки кроме последней (она может быть неполной)
            for line in lines[:-1]:
                if line.strip():
                    self._thinking_output.append(line)

            # Оставляем последнюю неполную строку в буфере
            self._thinking_buffer = lines[-1]

        # Прокручиваем вниз
        scrollbar = self._thinking_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

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
        if self.assistant_overlay:
            self.assistant_overlay.set_corner(position)

    def _on_overlay_margin_change(self, value: int) -> None:
        """Обработчик изменения отступа overlay."""
        self.overlay_margin_value.setText(str(value))
        self.config.update(overlay_margin=value)
        self.overlay.set_margin(value)
        if self.assistant_overlay:
            self.assistant_overlay.set_margin(value + ASSISTANT_OVERLAY_OFFSET)

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
        # Вкладки (порядок: Основные, Саммари, Настройки)
        self.tabs.setTabText(0, self._t("basic"))
        self.tabs.setTabText(1, self._t("files_tab"))
        self.tabs.setTabText(2, self._t("additional"))

        # Основная вкладка
        self.audio_input_label.setText(self._t("audio_input"))
        self.hotkey_label.setText(self._t("hotkey"))
        self.hotkey_record_btn.setText(self._t("record_hotkey"))
        self.ui_lang_label.setText(self._t("ui_language"))
        self.trans_lang_label.setText(self._t("transcription_language"))
        self.license_status_label.setText(self._t("license_status"))

        # Дополнительная вкладка - модель и устройство
        self.model_label.setText(self._t("model"))
        self.distil_warning.setText(self._t("distil_en_only"))
        self.quant_label.setText(self._t("quantization"))
        self.accel_label.setText(self._t("device"))
        self.download_btn.setText(self._t("download_model"))

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

        # Вкладка файлов
        self.drop_zone.set_translate_func(self._t)
        self.output_format_label.setText(self._t("output_format"))
        self.output_folder_label.setText(self._t("output_folder"))
        self.browse_folder_btn.setText(self._t("browse"))
        self.queue_title_label.setText(self._t("processing_queue"))
        self.clear_queue_btn.setText(self._t("clear_queue"))
        self.start_processing_btn.setText(self._t("start_processing"))
        self.stop_processing_btn.setText(self._t("stop_processing"))
        self._no_files_label.setText(self._t("no_files_in_queue"))

        # Обновляем формат комбобокса
        current_format = self.output_format_combo.currentData()
        self.output_format_combo.clear()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        idx = self.output_format_combo.findData(current_format)
        if idx >= 0:
            self.output_format_combo.setCurrentIndex(idx)

        # AI саммари
        self.enable_summary_checkbox.setText(self._t("enable_summary"))
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        self.customize_prompts_btn.setText(self._t("customize_prompts"))

        # Обновляем виджеты файлов
        for widget in self._file_widgets.values():
            widget.set_translate_func(self._t)

        # История транскрипций (если вкладка включена)
        if hasattr(self, 'transcription_history'):
            self.transcription_history.set_translate_func(self._t)

        # История диалогов ассистента (если вкладка включена)
        if hasattr(self, 'assistant_dialog_history'):
            self.assistant_dialog_history.set_translate_func(self._t)

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
        from .crash_reporter import add_breadcrumb
        add_breadcrumb("Hotkey pressed - starting recording")

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
        from .crash_reporter import add_breadcrumb
        add_breadcrumb(f"Transcription completed: {'error' if err else 'success'}")

        self._update_tray_icon(recording=False)
        self._transcription_in_progress = False  # Транскрипция завершена

        if err:
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            self.overlay.show_error(self._t("error"))
            self._auto_insert_pending = False
            return

        self.last_text = text

        # Добавляем в историю транскрипций (если вкладка История включена)
        if text and hasattr(self, 'transcription_history'):
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

    # === Обработчики вкладки "Файлы" ===

    def _task_key(self, path: Path) -> Path:
        """Нормализованный ключ для задач/виджетов (абсолютный путь)."""
        try:
            return path.resolve()
        except Exception:
            return path.absolute()

    def _on_files_dropped(self, files: list) -> None:
        """Обработчик drop файлов."""
        # Исключаем только файлы в процессе или ожидающие обработки
        processing_statuses = (FileStatus.PENDING, FileStatus.EXTRACTING, 
                               FileStatus.TRANSCRIBING, FileStatus.SUMMARIZING, 
                               FileStatus.GENERATING)
        existing = {
            self._task_key(t.file_path) for t in self._file_tasks
            if t.status in processing_statuses
        }
        for file_path in files:
            key = self._task_key(file_path)
            if key not in existing:
                # Удаляем старую завершённую задачу с тем же путём если есть
                self._file_tasks = [t for t in self._file_tasks 
                                    if self._task_key(t.file_path) != key]
                # Удаляем старый виджет
                old_widget = self._file_widgets.pop(key, None)
                if old_widget:
                    old_widget.deleteLater()
                # Создаём новую задачу
                task = FileTask(file_path=file_path)
                self._file_tasks.append(task)
                self._add_file_widget(task)
                existing.add(key)

        self._update_file_queue_ui()

    def _on_select_files_clicked(self) -> None:
        """Открыть диалог выбора файлов."""
        extensions = " ".join(f"*{ext}" for ext in ALL_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("select_files"),
            str(Path.home()),
            f"Media Files ({extensions})"
        )

        if files:
            self._on_files_dropped([Path(f) for f in files])

    def _on_browse_output_folder(self) -> None:
        """Открыть диалог выбора папки вывода."""
        folder = QFileDialog.getExistingDirectory(
            self,
            self._t("output_folder"),
            str(self._output_dir)
        )

        if folder:
            self._output_dir = Path(folder)
            self.output_folder_edit.setText(folder)

    def _on_reasoning_changed(self, state: int) -> None:
        """Обработать изменение reasoning mode."""
        is_enabled = state == 2  # Qt.CheckState.Checked
        self.effort_label.setEnabled(is_enabled)
        self.effort_combo.setEnabled(is_enabled)
        self.config.update(llm_reasoning_enabled=is_enabled)

    def _on_effort_changed(self, index: int) -> None:
        """Сохранить выбранный effort."""
        effort = self.effort_combo.currentData()
        if effort:
            self.config.update(llm_reasoning_effort=effort)

    def _on_provider_changed(self, index: int) -> None:
        """Обработать смену провайдера."""
        provider = self.provider_combo.currentData()
        if not provider:
            return

        # Сохраняем в конфиг
        self.config.update(llm_provider=provider)

        # Обновляем видимость полей
        self._update_provider_fields()

        # Загружаем настройки для нового провайдера
        self._load_provider_settings(provider)

        # Очищаем список моделей
        self.model_combo.clear()
        self.model_combo.addItem(self._t("select_model"), "")

    def _update_provider_fields(self) -> None:
        """Обновить видимость полей в зависимости от провайдера."""
        provider = self.provider_combo.currentData()

        # Ollama не требует API ключа, но требует base_url
        is_ollama = provider == "ollama"

        self.api_key_label.setVisible(not is_ollama)
        self.api_key_edit.setVisible(not is_ollama)
        self.base_url_label.setVisible(is_ollama)
        self.base_url_edit.setVisible(is_ollama)

        # Обновляем placeholder для API ключа
        placeholders = {
            "openai": "sk-...",
            "anthropic": "sk-ant-...",
            "gemini": "AIza...",
            "openrouter": "sk-or-...",
        }
        self.api_key_edit.setPlaceholderText(placeholders.get(provider, ""))

    def _load_provider_settings(self, provider: str) -> None:
        """Загрузить настройки для провайдера."""
        cfg = self.config.config

        # API ключ
        key_field = f"{provider}_api_key"
        api_key = cfg.get(key_field, "")
        self.api_key_edit.setText(api_key)

        # Base URL (для Ollama)
        if provider == "ollama":
            base_url = cfg.get("ollama_base_url", "http://localhost:11434")
            self.base_url_edit.setText(base_url)

        # Модель
        model_field = f"{provider}_model"
        saved_model = cfg.get(model_field, "")
        if saved_model:
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")
            self.model_combo.addItem(saved_model, saved_model)
            self.model_combo.setCurrentIndex(1)

    def _on_api_key_changed(self, value: str) -> None:
        """Сохранить API ключ для текущего провайдера."""
        provider = self.provider_combo.currentData()
        if provider and provider != "ollama":
            key_field = f"{provider}_api_key"
            self.config.update(**{key_field: value})

    def _on_base_url_changed(self, value: str) -> None:
        """Сохранить base URL для Ollama."""
        self.config.update(ollama_base_url=value)

    def _on_model_changed(self, value: str) -> None:
        """Сохранить выбранную модель."""
        provider = self.provider_combo.currentData()
        if provider:
            model_field = f"{provider}_model"
            # Получаем ID модели из data, а не текст
            model_id = self.model_combo.currentData()
            if model_id:
                self.config.update(**{model_field: model_id})

    def _on_refresh_models(self) -> None:
        """Загрузить список моделей для текущего провайдера."""
        provider = self.provider_combo.currentData()
        if not provider:
            return

        # Для Ollama не нужен API ключ
        if provider != "ollama":
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                QMessageBox.warning(
                    self,
                    self._t("error"),
                    self._t("api_key_required")
                )
                return
        else:
            api_key = ""

        # Показываем индикатор загрузки
        self.refresh_models_btn.setEnabled(False)
        self.refresh_models_btn.setText(self._t("loading_models"))
        QApplication.processEvents()

        try:
            from .llm import get_provider_by_name, LLMAuthError, LLMError, LLMConnectionError
            from PyQt6.QtWidgets import QCompleter

            # Создаём провайдер
            base_url = self.base_url_edit.text().strip() if provider == "ollama" else ""
            llm_provider = get_provider_by_name(
                name=provider,
                api_key=api_key,
                base_url=base_url,
            )

            # Загружаем модели
            models = llm_provider.fetch_models(force_refresh=True)

            # Сохраняем модели
            self._llm_models = models

            # Очищаем и заполняем комбобокс
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")

            model_names = []
            for model in models:
                # Формируем отображаемое имя
                display = model.display_name
                self.model_combo.addItem(display, model.id)
                model_names.append(display)

            # Добавляем completer для поиска
            completer = QCompleter(model_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.model_combo.setCompleter(completer)

            # Восстанавливаем сохранённый выбор
            model_field = f"{provider}_model"
            saved_model = self.config.config.get(model_field, "")
            if saved_model:
                idx = self.model_combo.findData(saved_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)

        except LLMAuthError:
            QMessageBox.critical(
                self,
                self._t("error"),
                self._t("invalid_api_key")
            )
        except LLMConnectionError as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                f"{self._t('connection_error')}: {e}"
            )
        except LLMError as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                f"{self._t('api_error')}: {e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                str(e)
            )
        finally:
            self.refresh_models_btn.setEnabled(True)
            self.refresh_models_btn.setText(self._t("refresh_models"))

    def _on_model_selected(self, index: int) -> None:
        """Сохранить выбранную модель."""
        model_id = self.model_combo.currentData()
        if model_id:
            self.config.update(openrouter_model=model_id)

    def _on_customize_prompts(self) -> None:
        """Открыть диалог настройки промптов."""
        dialog = PromptCustomizationDialog(self.config, translate_func=self._t, parent=self)
        dialog.show()

    def _on_clear_queue(self) -> None:
        """Очистить очередь файлов."""
        # Оставляем только файлы в процессе обработки
        self._file_tasks = [
            t for t in self._file_tasks
            if t.status in (FileStatus.EXTRACTING, FileStatus.TRANSCRIBING, 
                            FileStatus.SUMMARIZING, FileStatus.GENERATING)
        ]
        self._rebuild_file_queue_ui()

    def _on_start_processing(self) -> None:
        """Начать обработку файлов."""
        from .crash_reporter import add_breadcrumb

        if not self._file_tasks:
            return

        pending_tasks = [t for t in self._file_tasks if t.status == FileStatus.PENDING]
        if not pending_tasks:
            return

        add_breadcrumb(f"Starting file processing: {len(pending_tasks)} files")

        # Создаём директорию вывода
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Запоминаем параметры запуска, чтобы понимать, что авто-открывать
        self._file_processing_batch_size = len(pending_tasks)
        self._file_output_format = self.output_format_combo.currentData()
        self._last_completed_task: Optional[FileTask] = None

        # Создаём очередь
        cfg = self.config.config

        # Загружаем промпты из пресета и объединяем с кастомными
        from .summary_presets import get_preset_prompts
        preset_id = cfg.get("summary_preset", "pm")
        preset_prompts = get_preset_prompts(preset_id)
        custom_prompts_saved = cfg.get("custom_prompts", {})
        # Кастомные промпты перезаписывают промпты из пресета
        custom_prompts = {**preset_prompts, **custom_prompts_saved} if custom_prompts_saved else preset_prompts

        self._file_queue = FileTranscriptionQueue(
            transcriber=self.transcriber,
            model_size=cfg.get("model_size", "large-v3"),
            compute_type=cfg.get("compute_type", "int8"),
            device=cfg.get("device", "auto"),
            language=cfg.get("language", "ru"),
            beam_size=int(cfg.get("beam_size", 5)),
            vad_filter=bool(cfg.get("vad_filter", True)),
            models_dir=self.models_dir,
            enable_summary=self.enable_summary_checkbox.isChecked(),
            on_thinking=lambda text: self.thinking_signal.emit(text),  # Всегда включен
            enable_thinking=True,  # Всегда включен
            custom_prompts=custom_prompts,
            # OpenRouter настройки
            summary_provider="openrouter",
            openrouter_api_key=cfg.get("openrouter_api_key", ""),
            openrouter_model=cfg.get("openrouter_model", ""),
            openrouter_reasoning=True,  # Всегда включен, сила выбирается в настройках
            openrouter_reasoning_effort=cfg.get("openrouter_reasoning_effort", "medium"),
            # Постобработка (диаризация, пунктуация и т.д.)
            enable_postprocessing=cfg.get("enable_postprocessing", True),
            postprocessing_diarization=cfg.get("postprocessing_diarization", True),
            postprocessing_punctuation=cfg.get("postprocessing_punctuation", True),
            postprocessing_fillers=cfg.get("postprocessing_fillers", True),
            postprocessing_normalize=cfg.get("postprocessing_normalize", True),
            postprocessing_correct=cfg.get("postprocessing_correct", True),
        )

        # Добавляем файлы
        for task in pending_tasks:
            self._file_queue._tasks.append(task)
            self._file_queue._queue.put(task)

        # Создаём и запускаем воркер
        self._file_worker = FileTranscriptionWorker(
            queue=self._file_queue,
            output_dir=self._output_dir,
            output_format=self.output_format_combo.currentData(),
            ui_language=self._ui_lang,
        )
        self._file_worker.task_progress.connect(self._on_file_task_progress)
        self._file_worker.task_completed.connect(self._on_file_task_completed)
        self._file_worker.all_completed.connect(self._on_all_files_completed)
        self._file_worker.start()

        # Обновляем UI
        self.start_processing_btn.setEnabled(False)
        self.start_processing_btn.setVisible(False)
        self.stop_processing_btn.setEnabled(True)
        self.stop_processing_btn.setVisible(True)
        self.drop_zone.setEnabled(False)

    def _on_stop_processing(self) -> None:
        """Остановить обработку."""
        if self._file_queue:
            self._file_queue.cancel()

        self.stop_processing_btn.setEnabled(False)

    def _on_file_task_progress(self, task: FileTask) -> None:
        """Обновление прогресса задачи."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

    def _on_file_task_completed(self, task: FileTask) -> None:
        """Задача завершена."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

        if task.status == FileStatus.COMPLETED:
            self._last_completed_task = task
            # Если обрабатываем один файл — открываем отчёт автоматически
            if getattr(self, "_file_processing_batch_size", 0) == 1:
                self._auto_open_transcription(task)

    def _on_all_files_completed(self) -> None:
        """Все файлы обработаны."""
        self.start_processing_btn.setVisible(True)
        self.stop_processing_btn.setEnabled(False)
        self.stop_processing_btn.setVisible(False)
        self.drop_zone.setEnabled(True)
        
        # Корректно обновляем состояние кнопок
        self._update_file_queue_ui()

        # Показываем уведомление
        completed = sum(1 for t in self._file_tasks if t.status == FileStatus.COMPLETED)
        total = len(self._file_tasks)

        if completed > 0:
            QMessageBox.information(
                self,
                self._t("processing_complete"),
                f"{self._t('files_processed')}: {completed}/{total}\n\n{self._output_dir}"
            )

            # Если файлов было несколько — открываем папку результатов
            if getattr(self, "_file_processing_batch_size", 0) > 1:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
            # Если файл был один и отчёт не открылся по какой-то причине — откроем хотя бы папку
            elif getattr(self, "_file_processing_batch_size", 0) == 1 and not self._last_completed_task:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _auto_open_transcription(self, task: FileTask) -> None:
        """Авто-открытие сгенерированного отчёта (HTML/PDF) для одного файла."""
        try:
            base_name = task.file_path.stem + "_transcription"
            html_path = self._output_dir / f"{base_name}.html"
            pdf_path = self._output_dir / f"{base_name}.pdf"

            fmt = getattr(self, "_file_output_format", "html")

            # При "both" открываем HTML (быстрее предпросмотр); при "pdf" — PDF если есть, иначе HTML.
            if fmt == "pdf":
                target = pdf_path if pdf_path.exists() else html_path
            elif fmt == "both":
                target = html_path if html_path.exists() else (pdf_path if pdf_path.exists() else html_path)
            else:
                target = html_path if html_path.exists() else pdf_path

            if target and target.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
        except Exception:
            # Не блокируем UI, если открыть не удалось
            pass

    def _add_file_widget(self, task: FileTask) -> None:
        """Добавить виджет файла в список."""
        widget = FileQueueItemWidget(task, translate_func=self._t)
        widget.remove_clicked.connect(self._on_remove_file_task)
        widget.open_clicked.connect(self._on_open_file_result)

        self._file_widgets[self._task_key(task.file_path)] = widget

        # Вставляем перед stretch
        idx = self._file_queue_layout.count() - 1
        self._file_queue_layout.insertWidget(idx, widget)

    def _on_remove_file_task(self, task: FileTask) -> None:
        """Удалить задачу из очереди."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.pop(key, None)
        if widget:
            widget.deleteLater()

        if task in self._file_tasks:
            self._file_tasks.remove(task)

        self._update_file_queue_ui()

    def _on_open_file_result(self, task: FileTask) -> None:
        """Открыть папку с результатом."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _update_file_queue_ui(self) -> None:
        """Обновить UI очереди."""
        has_files = len(self._file_tasks) > 0
        has_pending = any(t.status == FileStatus.PENDING for t in self._file_tasks)

        self._no_files_label.setVisible(not has_files)
        self.start_processing_btn.setEnabled(has_pending)

    def _rebuild_file_queue_ui(self) -> None:
        """Полностью перестроить UI очереди."""
        # Удаляем все виджеты
        for widget in self._file_widgets.values():
            widget.deleteLater()
        self._file_widgets.clear()

        # Добавляем заново
        for task in self._file_tasks:
            self._add_file_widget(task)

        self._update_file_queue_ui()

    def closeEvent(self, event) -> None:
        """Закрытие приложения или сворачивание в трей."""
        # Останавливаем обработку файлов если запущена
        if self._file_queue and self._file_queue.is_running:
            self._file_queue.cancel()

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
    # Устанавливаем обработчик crash'ей ДО создания QApplication
    from .crash_reporter import install_crash_handler, set_crash_dialog_callback
    from .ui.dialogs import show_crash_dialog

    install_crash_handler()
    set_crash_dialog_callback(show_crash_dialog)

    app = QApplication(sys.argv)
    app.setWindowIcon(create_app_icon(64))  # Иконка для всего приложения

    # Проверяем лицензию перед запуском
    license_manager = LicenseManager()
    has_access, info = license_manager.check_access()

    # Получаем язык из конфига для диалогов до создания MainWindow
    config = ConfigManager()
    ui_lang = config.config.get("ui_language", "ru")
    translate_func = lambda key: get_text(key, ui_lang)

    if not has_access:
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            # Показываем блокирующий диалог (нельзя закрыть)
            dialog = TrialExpiredDialog(license_manager, translate_func=translate_func)
            result = dialog.exec()
            # Если диалог закрылся без активации - выходим
            final_info = license_manager.get_license_info()
            if final_info.status != LicenseStatus.VALID:
                sys.exit(1)
        else:
            # Показываем обычный диалог активации
            dialog = LicenseActivationDialog(license_manager, translate_func=translate_func)
            result = dialog.exec()
            if dialog.should_block_app():
                sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
