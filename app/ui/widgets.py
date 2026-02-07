"""
Виджеты для UI MindType.

Этот модуль содержит виджеты истории транскрипций, журнала и другие UI компоненты.
Рефакторинг: использует design tokens вместо inline стилей.
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
from PyQt6.QtGui import QColor, QPainter, QPainterPath

from .icons import STATUS_OK_BRACKET, STATUS_ERROR_BRACKET, STATUS_PENDING_BRACKET
from .tokens import COLORS, SPACING, TYPOGRAPHY, get_color


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
        self.setObjectName("historyWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["sm"])

        # Заголовок секции
        header = QHBoxLayout()
        self._title_label = QLabel(self._translate("history"))
        self._title_label.setObjectName("panelTitle")
        header.addWidget(self._title_label)
        header.addStretch()
        layout.addLayout(header)

        # Последняя транскрипция (крупная)
        last_section = QFrame()
        last_section.setObjectName("cardElevated")
        last_layout = QVBoxLayout(last_section)
        last_layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        last_layout.setSpacing(SPACING["xs"] + 2)

        last_header = QHBoxLayout()
        self._last_label = QLabel(self._translate("last_transcription"))
        self._last_label.setObjectName("caption")
        last_header.addWidget(self._last_label)
        last_header.addStretch()

        self._copy_btn = QPushButton(self._translate("copy"))
        self._copy_btn.setMinimumWidth(70)
        self._copy_btn.clicked.connect(self._copy_last)
        last_header.addWidget(self._copy_btn)

        last_layout.addLayout(last_header)

        self._last_text = QLabel(self._translate("no_transcriptions"))
        self._last_text.setObjectName("body")
        self._last_text.setWordWrap(True)
        self._last_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        last_layout.addWidget(self._last_text)

        layout.addWidget(last_section)

        # История (список)
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history_scroll.setObjectName("scrollArea")

        self._history_content = QWidget()
        self._history_content.setObjectName("scrollContent")
        self._history_layout = QVBoxLayout(self._history_content)
        self._history_layout.setContentsMargins(0, 0, SPACING["sm"], 0)
        self._history_layout.setSpacing(SPACING["xs"])
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
        widget.setObjectName("cardInteractive")
        widget.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(widget)
        layout.setContentsMargins(SPACING["xs"] + 2, SPACING["xs"], SPACING["xs"] + 2, SPACING["xs"])
        layout.setSpacing(SPACING["sm"])

        # Время
        time_label = QLabel(entry.time.strftime("%H:%M"))
        time_label.setObjectName("caption")
        time_label.setFixedWidth(40)
        layout.addWidget(time_label)

        # Текст (обрезаем если длинный)
        text = entry.text[:80] + "..." if len(entry.text) > 80 else entry.text
        text_label = QLabel(text)
        text_label.setObjectName("caption")
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
        self.setObjectName("journalWidget")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Скроллящаяся область
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("scrollArea")

        self._content = QWidget()
        self._content.setObjectName("scrollContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, SPACING["sm"], 0)
        self._content_layout.setSpacing(SPACING["sm"])
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
        widget.setObjectName("card")
        widget.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(widget)
        layout.setContentsMargins(SPACING["sm"], SPACING["xs"] + 2, SPACING["sm"], SPACING["xs"] + 2)
        layout.setSpacing(SPACING["sm"])

        # Время
        time_label = QLabel(entry.time.strftime("%H:%M:%S"))
        time_label.setObjectName("bodyBold")
        time_label.setFixedWidth(60)
        layout.addWidget(time_label)

        # Статус-индикатор (точка)
        status_dot = QLabel("*")
        status_dot.setObjectName("body")
        status_dot.setFixedWidth(16)
        layout.addWidget(status_dot)

        # Контент
        content_layout = QVBoxLayout()
        content_layout.setSpacing(2)

        # Заголовок со статусом (B&W icons)
        title_row = QHBoxLayout()

        status_label = QLabel()
        if entry.status == "success":
            status_label.setText(STATUS_OK_BRACKET)
            status_label.setObjectName("bodyBold")
        elif entry.status == "pending":
            status_label.setText(STATUS_PENDING_BRACKET)
            status_label.setObjectName("muted")
        else:
            status_label.setText(STATUS_ERROR_BRACKET)
            status_label.setObjectName("bodyBold")
        title_row.addWidget(status_label)

        # Переводим заголовок если нужно
        title_text = self._translate(entry.title_key) if entry.is_translatable else entry.title_key
        title_label = QLabel(title_text)
        title_label.setObjectName("bodyBold")
        title_row.addWidget(title_label)
        title_row.addStretch()

        content_layout.addLayout(title_row)

        # Текст (если есть)
        if entry.text:
            text_label = QLabel(entry.text[:100] + "..." if len(entry.text) > 100 else entry.text)
            text_label.setObjectName("body")
            text_label.setWordWrap(True)
            content_layout.addWidget(text_label)

        # Дополнительная информация (если есть)
        if entry.extra_key:
            # Переводим extra если нужно
            extra_text = self._translate(entry.extra_key) if entry.is_translatable else entry.extra_key
            extra_label = QLabel(extra_text)
            extra_label.setObjectName("captionItalic")
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
        self.setObjectName("assistantDialogWidget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["sm"])

        # === Левая панель: список диалогов ===
        left_panel = QFrame()
        left_panel.setObjectName("cardElevated")
        left_panel.setFixedWidth(200)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # Заголовок
        header = QFrame()
        header.setObjectName("titleBar")
        header.setFixedHeight(24)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING["sm"], 2, SPACING["sm"], 2)
        self._title_label = QLabel(self._translate("assistant_dialogs"))
        self._title_label.setObjectName("titleBarLabel")
        header_layout.addWidget(self._title_label)
        left_layout.addWidget(header)

        # Список диалогов
        self._dialog_scroll = QScrollArea()
        self._dialog_scroll.setWidgetResizable(True)
        self._dialog_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dialog_scroll.setObjectName("scrollArea")

        self._dialog_list = QWidget()
        self._dialog_list.setObjectName("scrollContent")
        self._dialog_list_layout = QVBoxLayout(self._dialog_list)
        self._dialog_list_layout.setContentsMargins(SPACING["xs"], SPACING["xs"], SPACING["xs"], SPACING["xs"])
        self._dialog_list_layout.setSpacing(SPACING["xs"])
        self._dialog_list_layout.addStretch()

        self._dialog_scroll.setWidget(self._dialog_list)
        left_layout.addWidget(self._dialog_scroll, stretch=1)

        # Кнопка "Очистить всё"
        self._clear_all_btn = QPushButton(self._translate("clear_all_dialogs"))
        self._clear_all_btn.setObjectName("smallButton")
        self._clear_all_btn.clicked.connect(self._on_clear_all)
        left_layout.addWidget(self._clear_all_btn)

        layout.addWidget(left_panel)

        # === Правая панель: просмотр диалога ===
        right_panel = QFrame()
        right_panel.setObjectName("cardElevated")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Заголовок
        preview_header = QFrame()
        preview_header.setObjectName("titleBar")
        preview_header.setFixedHeight(24)
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(SPACING["sm"], 2, SPACING["sm"], 2)
        self._preview_label = QLabel(self._translate("dialog_preview"))
        self._preview_label.setObjectName("titleBarLabel")
        preview_header_layout.addWidget(self._preview_label)
        right_layout.addWidget(preview_header)

        # Контент диалога
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_scroll.setObjectName("scrollArea")

        self._preview_content = QWidget()
        self._preview_content.setObjectName("scrollContent")
        self._preview_layout = QVBoxLayout(self._preview_content)
        self._preview_layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        self._preview_layout.setSpacing(SPACING["xs"] + 2)

        self._placeholder_label = QLabel(self._translate("select_dialog"))
        self._placeholder_label.setObjectName("mutedItalic")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._placeholder_label)
        self._preview_layout.addStretch()

        self._preview_scroll.setWidget(self._preview_content)
        right_layout.addWidget(self._preview_scroll, stretch=1)

        # Кнопки управления
        controls = QFrame()
        controls.setObjectName("controlBar")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(SPACING["sm"], SPACING["xs"] + 2, SPACING["sm"], SPACING["xs"] + 2)
        controls_layout.setSpacing(SPACING["sm"])

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
            no_dialogs.setObjectName("mutedItalic")
            no_dialogs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._dialog_list_layout.insertWidget(0, no_dialogs)
            return

        for dialog in self._dialogs:
            item = self._create_dialog_item(dialog)
            self._dialog_list_layout.insertWidget(self._dialog_list_layout.count() - 1, item)

    def _create_dialog_item(self, dialog: Any) -> QWidget:
        """Создать элемент списка диалогов."""
        item = QFrame()
        item.setObjectName("cardInteractive")
        item.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(item)
        layout.setContentsMargins(SPACING["xs"] + 2, SPACING["xs"], SPACING["xs"] + 2, SPACING["xs"])
        layout.setSpacing(2)

        # Заголовок (обрезанный)
        title = dialog.title or "Новый диалог"
        title_label = QLabel(title[:30] + "..." if len(title) > 30 else title)
        title_label.setObjectName("smallBold")
        layout.addWidget(title_label)

        # Дата
        try:
            dt = datetime.fromisoformat(dialog.timestamp)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = dialog.timestamp[:16] if hasattr(dialog, 'timestamp') else ""
        date_label = QLabel(date_str)
        date_label.setObjectName("tinyMuted")
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
            sys_frame.setObjectName("infoBox")
            sys_layout = QVBoxLayout(sys_frame)
            sys_layout.setContentsMargins(SPACING["xs"] + 2, SPACING["xs"], SPACING["xs"] + 2, SPACING["xs"])
            sys_label = QLabel("System: " + dialog.system_prompt[:100] + ("..." if len(dialog.system_prompt) > 100 else ""))
            sys_label.setWordWrap(True)
            sys_label.setObjectName("tinySecondary")
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
        bubble.setObjectName("userBubble" if role == "user" else "assistantBubble")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(SPACING["xs"] + 2, SPACING["xs"], SPACING["xs"] + 2, SPACING["xs"])

        label = QLabel(content[:200] + ("..." if len(content) > 200 else ""))
        label.setWordWrap(True)
        label.setObjectName("small")
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
            self._placeholder_label.setObjectName("mutedItalic")
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
        self._placeholder_label.setObjectName("mutedItalic")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_layout.addWidget(self._placeholder_label)
        self._preview_layout.addStretch()


class MicLevelWidget(QWidget):
    """Индикатор уровня микрофона в B&W стиле (system.css)."""

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

        # Фон - белый с чёрной рамкой (system.css style)
        painter.fillRect(0, 0, w, h, QColor(255, 255, 255))
        painter.setPen(QColor(0, 0, 0))
        painter.drawRect(0, 0, w - 1, h - 1)

        # Уровень - чёрная полоса (B&W style)
        level_width = max(0, int((w - 4) * self._level))
        if level_width > 0:
            painter.fillRect(2, 2, level_width, h - 4, QColor(0, 0, 0))

        # Индикатор пика (вертикальная линия) - чёрный на белом
        if self._peak > 0.05:
            peak_x = 2 + int((w - 4) * self._peak)
            # Рисуем пик только если он за пределами текущего уровня
            if peak_x > 2 + level_width:
                painter.setPen(QColor(0, 0, 0))
                painter.drawLine(peak_x, 2, peak_x, h - 3)
