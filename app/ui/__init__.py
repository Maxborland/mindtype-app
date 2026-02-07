"""
UI компоненты MindType.

Этот пакет содержит разделённые UI модули для улучшения maintainability.

Структура:
- tokens.py: Design tokens (colors, typography, spacing)
- styles.py: STYLESHEET для PyQt6 (использует tokens)
- components.py: Переиспользуемые компоненты (Card, Section, EmptyState)
- icons.py: create_app_icon и другие иконки
- workers.py: QThread классы для фоновых операций
- widgets.py: виджеты истории, журнала и индикаторы
- dialogs.py: диалоговые окна
- file_widgets.py: виджеты для работы с файлами (drag & drop, очередь)
- setup_wizard.py: мастер первого запуска
- credits_widget.py: виджет баланса кредитов MindType Cloud
- mode_manager.py: Simple/Advanced режимы

Design System v2:
- Централизованные токены в tokens.py
- Улучшенная типографская иерархия (24/18/14/12/11/10px)
- Focus states для accessibility
- Унифицированные компоненты
"""

# Design tokens
from .tokens import (
    COLORS,
    TYPOGRAPHY,
    SPACING,
    BORDERS,
    RADII,
    FONT_FAMILY,
    get_color,
    get_spacing,
)

# Styles
from .styles import STYLESHEET, get_full_stylesheet, get_card_style, get_button_style

# Icons (pixel art, Classic Mac style)
from .icons import (
    create_app_icon,
    create_mic_icon,
    create_settings_icon,
    create_folder_icon,
    create_document_icon,
    create_play_icon,
    create_stop_icon,
    create_pause_icon,
    create_copy_icon,
    create_trash_icon,
    create_refresh_icon,
    create_check_icon,
    create_close_icon,
    create_arrow_right_icon,
    create_arrow_down_icon,
    create_info_icon,
    create_warning_icon,
)

# Reusable components
from .components import (
    Card,
    Section,
    TitledCard,
    EmptyState,
    ShortcutHint,
    Separator,
    Spacer,
    ButtonGroup,
    StatusLabel,
    ToolbarButton,
    FormField,
)

# Layout components
from .layouts import (
    FormRow,
    FormLayout,
    TwoColumnLayout,
    SectionBox,
    ScrollableContent,
    TabHeader,
    ActionBar,
)
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
from .setup_wizard import SetupWizard
from .credits_widget import CreditsBalanceWidget, CreditsRefreshWorker
from .mode_manager import ModeManager, ModeToggleWidget, SIMPLE_MODE_SIZE, ADVANCED_MODE_SIZE

__all__ = [
    # Design Tokens
    "COLORS",
    "TYPOGRAPHY",
    "SPACING",
    "BORDERS",
    "RADII",
    "FONT_FAMILY",
    "get_color",
    "get_spacing",
    # Styles
    "STYLESHEET",
    "get_full_stylesheet",
    "get_card_style",
    "get_button_style",
    # Icons (pixel art)
    "create_app_icon",
    "create_mic_icon",
    "create_settings_icon",
    "create_folder_icon",
    "create_document_icon",
    "create_play_icon",
    "create_stop_icon",
    "create_pause_icon",
    "create_copy_icon",
    "create_trash_icon",
    "create_refresh_icon",
    "create_check_icon",
    "create_close_icon",
    "create_arrow_right_icon",
    "create_arrow_down_icon",
    "create_info_icon",
    "create_warning_icon",
    # Reusable Components
    "Card",
    "Section",
    "TitledCard",
    "EmptyState",
    "ShortcutHint",
    "Separator",
    "Spacer",
    "ButtonGroup",
    "StatusLabel",
    "ToolbarButton",
    "FormField",
    # Layout Components
    "FormRow",
    "FormLayout",
    "TwoColumnLayout",
    "SectionBox",
    "ScrollableContent",
    "TabHeader",
    "ActionBar",
    # Workers
    "TranscribeWorker",
    "ModelDownloadWorker",
    "UpdateCheckWorker",
    "UpdateDownloadWorker",
    "FileTranscriptionWorker",
    "CreditsRefreshWorker",
    # Data classes
    "TranscriptionEntry",
    "JournalEntry",
    # Widgets
    "TranscriptionHistoryWidget",
    "JournalWidget",
    "AssistantDialogHistoryWidget",
    "MicLevelWidget",
    "CreditsBalanceWidget",
    "ModeToggleWidget",
    # Mode manager
    "ModeManager",
    "SIMPLE_MODE_SIZE",
    "ADVANCED_MODE_SIZE",
    # Dialogs
    "CrashReportDialog",
    "show_crash_dialog",
    # File widgets
    "DropZoneWidget",
    "FileQueueItemWidget",
    # Setup wizard
    "SetupWizard",
]
