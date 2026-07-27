"""
Виджеты для работы с файлами в MindType.

Этот модуль содержит:
- DropZoneWidget: зона drag-and-drop для файлов
- FileQueueItemWidget: элемент очереди файлов

Рефакторинг: использует design tokens вместо inline стилей.
"""

from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
)
from PyQt6.QtGui import (
    QPixmap,
    QPainter,
    QColor,
    QIcon,
    QPen,
    QDragEnterEvent,
    QDropEvent,
)

from ..file_transcriber import (
    FileTask,
    FileStatus,
    ALL_EXTENSIONS,
    is_supported_file,
)
from .icons import STATUS_OK, STATUS_ERROR, STATUS_PENDING, STATUS_PROGRESS
from .tokens import COLORS, SPACING, TYPOGRAPHY


class DropZoneWidget(QFrame):
    """Зона drag-and-drop для файлов в стиле Classic Mac OS."""

    files_dropped = pyqtSignal(list)  # List[Path]
    clicked = pyqtSignal()

    def __init__(self, translate_func: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self._translate = translate_func or (lambda x: x)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self._build_ui()

    def set_translate_func(self, func: Callable) -> None:
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

    def _build_ui(self) -> None:
        self.setObjectName("cardInteractive")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING["xs"])

        # Пиксельная иконка папки
        icon_label = QLabel()
        icon_label.setPixmap(self._create_folder_icon())
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setObjectName("iconLabel")
        layout.addWidget(icon_label)

        # Основной текст
        self._main_label = QLabel(self._translate("drag_drop_files"))
        self._main_label.setObjectName("bodyBold")
        self._main_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._main_label)

        # Подсказка
        self._sub_label = QLabel(self._translate("or_click_to_select"))
        self._sub_label.setObjectName("caption")
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub_label)

        # Форматы
        self._formats_label = QLabel(self._translate("supported_formats"))
        self._formats_label.setObjectName("small")
        self._formats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formats_label.setWordWrap(True)
        layout.addWidget(self._formats_label)

    def _update_texts(self) -> None:
        self._main_label.setText(self._translate("drag_drop_files"))
        self._sub_label.setText(self._translate("or_click_to_select"))
        self._formats_label.setText(self._translate("supported_formats"))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Проверяем, есть ли поддерживаемые файлы
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if is_supported_file(path):
                    event.acceptProposedAction()
                    self.setObjectName("cardElevated")
                    # Force style refresh
                    self.style().unpolish(self)
                    self.style().polish(self)
                    return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setObjectName("cardInteractive")
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setObjectName("cardInteractive")
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)

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

    def __init__(self, task: FileTask, translate_func: Optional[Callable] = None, parent=None):
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

    def set_translate_func(self, func: Callable) -> None:
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

    def _build_ui(self) -> None:
        self.setObjectName("card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING["sm"], SPACING["xs"] + 2, SPACING["sm"], SPACING["xs"] + 2)
        layout.setSpacing(SPACING["sm"])

        # Иконка типа файла (пиксельная)
        icon_label = QLabel()
        icon_label.setPixmap(self._create_file_icon(self.task.is_video))
        icon_label.setFixedWidth(24)
        icon_label.setObjectName("iconLabel")
        layout.addWidget(icon_label)

        # Информация о файле
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        # Имя файла
        self._name_label = QLabel(self.task.file_name)
        self._name_label.setObjectName("bodyBold")
        info_layout.addWidget(self._name_label)

        # Статус
        self._status_label = QLabel("")
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
        self._action_btn.setObjectName("iconButton")
        self._action_btn.setText("")
        self._action_btn.setIconSize(QSize(12, 12))
        self._action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_btn)

    def _on_action_clicked(self) -> None:
        if self.task.status == FileStatus.COMPLETED:
            self.open_clicked.emit(self.task)
        elif self.task.status in (FileStatus.PENDING, FileStatus.ERROR, FileStatus.CANCELLED):
            self.remove_clicked.emit(self.task)

    def update_status(self) -> None:
        """Обновить отображение статуса (B&W theme)."""
        # Status map: (translation_key, status_icon, objectName)
        # Using ObjectName for styling instead of inline styles
        status_map = {
            FileStatus.PENDING: ("status_pending", STATUS_PENDING, "fileStatusPending"),
            FileStatus.EXTRACTING: ("status_extracting", STATUS_PROGRESS, "fileStatusProgress"),
            FileStatus.TRANSCRIBING: ("status_transcribing", STATUS_PROGRESS, "fileStatusProgress"),
            FileStatus.SUMMARIZING: ("status_summarizing", STATUS_PROGRESS, "fileStatusProgress"),
            FileStatus.GENERATING: ("status_generating", STATUS_PROGRESS, "fileStatusProgress"),
            FileStatus.COMPLETED: ("status_completed", STATUS_OK, "fileStatusComplete"),
            FileStatus.ERROR: ("status_error", STATUS_ERROR, "fileStatusError"),
            FileStatus.CANCELLED: ("status_cancelled", STATUS_PENDING, "fileStatusPending"),
        }

        key, icon, object_name = status_map.get(
            self.task.status,
            ("status_pending", STATUS_PENDING, "fileStatusPending")
        )
        status_text = f"{icon} {self._translate(key)}"

        if self.task.status == FileStatus.ERROR and self.task.error_message:
            status_text += f": {self.task.error_message[:50]}"

        self._status_label.setText(status_text)
        self._status_label.setObjectName(object_name)
        # Force style refresh
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        # Прогресс
        self._progress.setValue(self.task.progress)

        # Кнопка
        if self.task.status == FileStatus.COMPLETED:
            self._action_btn.setIcon(self._open_icon)
            self._action_btn.setToolTip(self._translate("open_folder"))
        else:
            self._action_btn.setIcon(self._close_icon)
            self._action_btn.setToolTip(self._translate("remove_from_queue"))
        self._action_btn.setEnabled(not self.task.cancellation_pending)

        # Прогресс-бар visibility
        self._progress.setVisible(self.task.status in (
            FileStatus.EXTRACTING,
            FileStatus.TRANSCRIBING,
            FileStatus.SUMMARIZING,
            FileStatus.GENERATING,
            FileStatus.PENDING,
        ))
