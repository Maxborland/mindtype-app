"""
Виджеты для UI MindType.

Этот модуль содержит виджеты истории транскрипций, журнала и другие UI компоненты.
"""

from datetime import datetime
from typing import List, Optional, Callable, Any

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
    QApplication,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QLinearGradient, QBrush


class TranscriptionEntry:
    """Запись истории транскрипции."""
    def __init__(self, text: str):
        self.time = datetime.now()
        self.text = text


class TranscriptionHistoryWidget(QWidget):
    """Виджет истории транскрипций с возможностью копирования."""

    def __init__(self, translate_func: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self._entries: List[TranscriptionEntry] = []
        self._max_entries = 20
        self._translate = translate_func or (lambda x: x)
        self._build_ui()

    def set_translate_func(self, func: Callable) -> None:
        """Установить функцию перевода."""
        self._translate = func
        self._update_labels()

    def _build_ui(self) -> None:
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

    def _update_labels(self) -> None:
        """Обновить все переводимые тексты."""
        self._title_label.setText(self._translate("history"))
        self._last_label.setText(self._translate("last_transcription"))
        self._copy_btn.setText(self._translate("copy"))
        if not self._entries:
            self._last_text.setText(self._translate("no_transcriptions"))

    def add_transcription(self, text: str) -> None:
        """Добавить новую транскрипцию."""
        if not text.strip():
            return

        entry = TranscriptionEntry(text)
        self._entries.insert(0, entry)

        # Ограничиваем количество
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[:self._max_entries]

        self._rebuild_history()

    def _rebuild_history(self) -> None:
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

    def _copy_last(self) -> None:
        """Копировать последнюю транскрипцию."""
        if self._entries:
            self._copy_text(self._entries[0].text)

    def _copy_text(self, text: str) -> None:
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
    def __init__(
        self,
        status: str,
        title_key: str,
        text: str = "",
        extra_key: str = "",
        is_translatable: bool = True
    ):
        self.time = datetime.now()
        self.status = status  # "success", "pending", "error"
        self.title_key = title_key  # Ключ перевода или готовый текст
        self.text = text
        self.extra_key = extra_key  # Ключ перевода или готовый текст для доп. инфо
        self.is_translatable = is_translatable  # Нужен ли перевод


class JournalWidget(QWidget):
    """Виджет журнала транскрипций."""

    def __init__(self, translate_func: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self._entries: List[JournalEntry] = []
        self._max_entries = 50
        self._translate = translate_func or (lambda x: x)
        self._build_ui()

    def set_translate_func(self, func: Callable) -> None:
        """Установить функцию перевода."""
        self._translate = func
        self._rebuild_ui()

    def _build_ui(self) -> None:
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

    def add_entry(
        self,
        status: str,
        title_key: str,
        text: str = "",
        extra_key: str = "",
        is_translatable: bool = True
    ) -> None:
        """Добавить запись в журнал."""
        entry = JournalEntry(status, title_key, text, extra_key, is_translatable)
        self._entries.insert(0, entry)

        # Ограничиваем количество записей
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[:self._max_entries]

        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
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

    def clear(self) -> None:
        """Очистить журнал."""
        self._entries = []
        self._rebuild_ui()


class AssistantDialogHistoryWidget(QWidget):
    """Виджет истории диалогов ассистента."""

    dialog_selected = pyqtSignal(object)  # Сигнал при выборе диалога (Dialog)
    continue_clicked = pyqtSignal(object)  # Сигнал при нажатии "Продолжить"
    delete_clicked = pyqtSignal(str)  # Сигнал при удалении (dialog_id)

    def __init__(self, translate_func: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self._translate = translate_func or (lambda x: x)
        self._dialogs: List[Any] = []  # List[Dialog]
        self._selected_dialog: Optional[Any] = None  # Optional[Dialog]
        self._build_ui()

    def set_translate_func(self, func: Callable) -> None:
        """Установить функцию перевода."""
        self._translate = func
        self._update_labels()

    def _build_ui(self) -> None:
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

    def _update_labels(self) -> None:
        """Обновить переводимые тексты."""
        self._title_label.setText(self._translate("assistant_dialogs"))
        self._preview_label.setText(self._translate("dialog_preview"))
        self._clear_all_btn.setText(self._translate("clear_all_dialogs"))
        self._continue_btn.setText(self._translate("continue_dialog"))
        self._delete_btn.setText(self._translate("delete_dialog"))
        if not self._selected_dialog:
            self._placeholder_label.setText(self._translate("select_dialog"))

    def refresh(self) -> None:
        """Обновить список диалогов из менеджера."""
        # Импортируем здесь чтобы избежать циклических импортов
        try:
            from ..dialog_history import get_dialog_history_manager
            history_manager = get_dialog_history_manager()
            self._dialogs = history_manager.get_all_dialogs()
        except ImportError:
            self._dialogs = []
        self._rebuild_dialog_list()

    def _rebuild_dialog_list(self) -> None:
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

    def _create_dialog_item(self, dialog: Any) -> QWidget:
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
            date_str = dialog.timestamp[:16] if hasattr(dialog, 'timestamp') else ""
        date_label = QLabel(date_str)
        date_label.setStyleSheet("color: #808080; font-size: 9px; background: transparent;")
        layout.addWidget(date_label)

        # Клик для выбора
        item.mousePressEvent = lambda e, d=dialog: self._on_dialog_selected(d)

        return item

    def _on_dialog_selected(self, dialog: Any) -> None:
        """Обработка выбора диалога."""
        self._selected_dialog = dialog
        self._continue_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        self._show_dialog_preview(dialog)
        self.dialog_selected.emit(dialog)

    def _show_dialog_preview(self, dialog: Any) -> None:
        """Показать предпросмотр диалога."""
        # Очищаем preview
        while self._preview_layout.count() > 0:
            item = self._preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # System prompt (если есть)
        if hasattr(dialog, 'system_prompt') and dialog.system_prompt:
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
        if hasattr(dialog, 'messages'):
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

    def _on_continue(self) -> None:
        """Продолжить выбранный диалог."""
        if self._selected_dialog:
            self.continue_clicked.emit(self._selected_dialog)

    def _on_delete(self) -> None:
        """Удалить выбранный диалог."""
        if self._selected_dialog:
            dialog_id = self._selected_dialog.id
            try:
                from ..dialog_history import get_dialog_history_manager
                history_manager = get_dialog_history_manager()
                history_manager.delete_dialog(dialog_id)
            except ImportError:
                pass

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

    def _on_clear_all(self) -> None:
        """Очистить всю историю."""
        try:
            from ..dialog_history import get_dialog_history_manager
            history_manager = get_dialog_history_manager()
            history_manager.clear_all()
        except ImportError:
            pass

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
