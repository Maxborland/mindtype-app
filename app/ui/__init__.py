"""
UI компоненты MindType.

Этот пакет содержит разделённые UI модули для улучшения maintainability.

Структура:
- styles.py: STYLESHEET для PyQt6
- icons.py: create_app_icon и другие иконки
- workers.py: QThread классы для фоновых операций
- widgets.py: виджеты истории, журнала и индикаторы
- dialogs.py: диалоговые окна
- file_widgets.py: виджеты для работы с файлами (drag & drop, очередь)
"""

from .styles import STYLESHEET
from .icons import create_app_icon
from .workers import (
    TranscribeWorker,
    ModelDownloadWorker,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    FileTranscriptionWorker,
)
from .widgets import (
    TranscriptionEntry,
    TranscriptionHistoryWidget,
    JournalEntry,
    JournalWidget,
    AssistantDialogHistoryWidget,
    MicLevelWidget,
)
from .dialogs import (
    CrashReportDialog,
    show_crash_dialog,
)
from .file_widgets import (
    DropZoneWidget,
    FileQueueItemWidget,
)

__all__ = [
    # Styles
    "STYLESHEET",
    # Icons
    "create_app_icon",
    # Workers
    "TranscribeWorker",
    "ModelDownloadWorker",
    "UpdateCheckWorker",
    "UpdateDownloadWorker",
    "FileTranscriptionWorker",
    # Data classes
    "TranscriptionEntry",
    "JournalEntry",
    # Widgets
    "TranscriptionHistoryWidget",
    "JournalWidget",
    "AssistantDialogHistoryWidget",
    "MicLevelWidget",
    # Dialogs
    "CrashReportDialog",
    "show_crash_dialog",
    # File widgets
    "DropZoneWidget",
    "FileQueueItemWidget",
]
