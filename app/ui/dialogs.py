"""
Диалоговые окна для UI MindType.
Стиль: Classic Mac OS System 7.
"""

from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QCheckBox,
)

from .styles import STYLESHEET
from .components import apply_system7_titlebar


# system.css стиль (Apple System OS 1984-1991)
# Только небольшие дополнения; кнопки/чекбоксы/шрифт берутся из центрального QSS
# (3D-бевели System-7, Segoe) — без локальных скруглённых кнопок и ChicagoFLF.
SYSTEM7_STYLE = """
QDialog {
    background-color: #ffffff;
}
QLabel {
    color: #000000;
    background: transparent;
}
QFrame#content {
    background-color: #ffffff;
    border: 1.5px solid #000000;
}
"""


class CrashReportDialog(QDialog):
    """
    Диалог отображения crash-репорта в стиле System 7.
    """

    def __init__(
        self,
        report_text: str,
        report_path: Path,
        exc_info: Optional[Tuple[type, BaseException, object]] = None,
        support_email: str = "help@mindtype.space",
        parent=None
    ):
        super().__init__(parent)

        self.report_text = report_text
        self.report_path = report_path
        self.exc_info = exc_info
        self.support_email = support_email

        self.setWindowTitle("MindType")
        self.setFixedSize(480, 348)  # +28 под полосатый title bar
        self.setModal(True)
        # Беспарентный top-level диалог не наследует STYLESHEET главного окна —
        # применяем центральный QSS (3D-кнопки/чекбоксы System-7) + локальные дополнения.
        self.setStyleSheet(STYLESHEET + SYSTEM7_STYLE)

        self._build_ui()
        apply_system7_titlebar(self, self.windowTitle())

    def _build_ui(self) -> None:
        """Построить UI в стиле System 7."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Основной контент
        content_frame = QFrame()
        content_frame.setObjectName("content")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(10)

        # Заголовок
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        # Иконка X в квадрате (классика)
        icon_frame = QFrame()
        icon_frame.setFixedSize(32, 32)
        icon_frame.setStyleSheet("""
            background-color: #000000;
            border: 2px solid #000000;
        """)
        icon_label = QLabel("X")
        icon_label.setStyleSheet("""
            color: #ffffff;
            font-size: 18px;
            font-weight: bold;
            background: transparent;
        """)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(icon_label)
        header_layout.addWidget(icon_frame)

        # Текст
        title = QLabel("Sorry, a system error occurred.")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        content_layout.addLayout(header_layout)

        # Разделитель
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #808080;")
        sep.setFixedHeight(1)
        content_layout.addWidget(sep)

        # Описание
        desc = QLabel("The application has encountered an error and will close.")
        desc.setStyleSheet("font-size: 11px;")
        desc.setWordWrap(True)
        content_layout.addWidget(desc)

        # Текст ошибки
        error_summary = self._get_error_summary()
        error_frame = QFrame()
        error_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffcc;
                border: 1px solid #808080;
            }
        """)
        error_layout = QVBoxLayout(error_frame)
        error_layout.setContentsMargins(8, 6, 8, 6)

        error_label = QLabel(error_summary)
        error_label.setStyleSheet("""
            font-family: "Consolas", "Courier New", monospace;
            font-size: 11px;
            color: #000000;
            background: transparent;
        """)
        error_label.setWordWrap(True)
        error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        error_layout.addWidget(error_label)
        content_layout.addWidget(error_frame)

        # Путь к файлу
        path_label = QLabel(f"Report: {self.report_path}")
        path_label.setStyleSheet("font-size: 10px; color: #444444;")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(path_label)

        # Checkbox
        self.send_checkbox = QCheckBox("Send anonymous report to developers")
        self.send_checkbox.setChecked(True)
        content_layout.addWidget(self.send_checkbox)

        content_layout.addStretch()
        layout.addWidget(content_frame, stretch=1)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)

        folder_btn = QPushButton("Open Folder")
        folder_btn.clicked.connect(self._open_folder)
        buttons_layout.addWidget(folder_btn)

        email_btn = QPushButton("Email")
        email_btn.clicked.connect(self._open_email)
        buttons_layout.addWidget(email_btn)

        buttons_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("primaryButton")
        self.close_btn.clicked.connect(self._send_and_close)
        buttons_layout.addWidget(self.close_btn)

        layout.addLayout(buttons_layout)

    def _get_error_summary(self) -> str:
        """Получить краткое описание ошибки."""
        lines = self.report_text.split('\n')

        # Ищем traceback
        for i, line in enumerate(lines):
            if "TRACEBACK" in line or "Traceback" in line:
                # Берём последние строки
                remaining = [l.strip() for l in lines[i:] if l.strip() and not l.startswith("=")]
                if remaining:
                    # Последние 2-3 строки обычно содержат суть ошибки
                    return "\n".join(remaining[-3:])

        # Fallback - ищем Error в строках
        for line in reversed(lines):
            if "Error" in line and line.strip():
                return line.strip()

        return "Unknown error"

    def _open_folder(self) -> None:
        """Открыть папку с репортом."""
        folder = self.report_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_email(self) -> None:
        """Открыть почтовый клиент."""
        import urllib.parse

        subject = "MindType Crash Report"
        body = f"Report file: {self.report_path}\n\nDescription:\n"

        subject_enc = urllib.parse.quote(subject)
        body_enc = urllib.parse.quote(body)

        mailto = f"mailto:{self.support_email}?subject={subject_enc}&body={body_enc}"
        QDesktopServices.openUrl(QUrl(mailto))

    def _send_and_close(self) -> None:
        """Отправить репорт и закрыть."""
        if self.send_checkbox.isChecked() and self.exc_info:
            try:
                from ..crash_reporter import send_crash_report_to_server
                exc_type, exc_value, exc_tb = self.exc_info
                send_crash_report_to_server(exc_type, exc_value, exc_tb)
            except Exception:
                pass  # Не блокируем закрытие при ошибке отправки

        self._close_app()

    def _close_app(self) -> None:
        """Закрыть приложение."""
        self.accept()
        import sys
        sys.exit(1)


def show_crash_dialog(
    report_text: str,
    report_path: Path,
    exc_info: Optional[Tuple[type, BaseException, object]] = None
) -> None:
    """
    Показать диалог crash-репорта.
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        import sys
        app = QApplication(sys.argv)

    dialog = CrashReportDialog(report_text, report_path, exc_info=exc_info)
    dialog.exec()
