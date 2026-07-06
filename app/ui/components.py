"""
Переиспользуемые UI компоненты для MindType.

Унифицированные компоненты на основе дизайн-системы tokens.py.
Используют ObjectName для стилизации через глобальный STYLESHEET.

Использование:
    from .components import Card, Section, EmptyState, ShortcutHint
"""

from typing import Optional, Callable, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)

from .tokens import COLORS, SPACING, TYPOGRAPHY, SYSTEM7


# =============================================================================
# CARD COMPONENTS
# =============================================================================

class Card(QFrame):
    """Базовая карточка с вариантами стилей.

    Variants:
        - default: Белый фон, стандартная граница
        - elevated: Белый фон, толстая граница
        - interactive: С hover-эффектом
        - surface: Серый фон, тонкая граница
        - info: Серый фон (для информационных блоков)

    Usage:
        card = Card(variant="elevated")
        card.setLayout(QVBoxLayout())
    """

    clicked = pyqtSignal()

    def __init__(
        self,
        variant: str = "default",
        clickable: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._variant = variant
        self._clickable = clickable
        self._setup()

    def _setup(self) -> None:
        # Map variants to ObjectNames
        variant_map = {
            "default": "card",
            "elevated": "cardElevated",
            "interactive": "cardInteractive",
            "surface": "surfaceCard",
            "info": "infoBox",
        }
        self.setObjectName(variant_map.get(self._variant, "card"))

        if self._clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Section(QWidget):
    """Секция с заголовком и контентом.

    Usage:
        section = Section("Settings", subtitle="Configure your preferences")
        section.content_layout.addWidget(...)
    """

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACING["lg"])
        layout.setSpacing(SPACING["sm"])

        # Header
        header = QVBoxLayout()
        header.setSpacing(SPACING["xs"])

        # Title
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("panelTitle")
        header.addWidget(self._title_label)

        # Subtitle (optional)
        if self._subtitle:
            self._subtitle_label = QLabel(self._subtitle)
            self._subtitle_label.setObjectName("muted")
            header.addWidget(self._subtitle_label)

        layout.addLayout(header)

        # Separator
        separator = QFrame()
        separator.setObjectName("hlineSubtle")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # Content area
        self._content = QWidget()
        self.content_layout = QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(0, SPACING["sm"], 0, 0)
        self.content_layout.setSpacing(SPACING["sm"])
        layout.addWidget(self._content)

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        if hasattr(self, '_subtitle_label'):
            self._subtitle_label.setText(subtitle)


class TitledCard(QFrame):
    """Карточка с заголовком в стиле System 7 (полоски в title bar).

    Usage:
        card = TitledCard("Options")
        card.content_layout.addWidget(...)
    """

    def __init__(
        self,
        title: str,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._title = title
        self.setObjectName("cardElevated")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar with stripes
        title_bar = QFrame()
        title_bar.setObjectName("titleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(SPACING["sm"], 0, SPACING["sm"], 0)

        title_label = QLabel(self._title)
        title_label.setObjectName("sectionTitle")
        title_label.setStyleSheet("background: transparent;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        layout.addWidget(title_bar)

        # Content
        self._content = QWidget()
        self.content_layout = QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(
            SPACING["md"], SPACING["md"],
            SPACING["md"], SPACING["md"]
        )
        self.content_layout.setSpacing(SPACING["sm"])
        layout.addWidget(self._content, stretch=1)


# =============================================================================
# EMPTY STATES
# =============================================================================

class EmptyState(QWidget):
    """Пустое состояние с иконкой, текстом и опциональным действием.

    Usage:
        empty = EmptyState(
            icon="📝",
            title="No transcriptions yet",
            hint="Press F2 or click Record to start",
            action_text="Start Recording",
            action_callback=self.start_recording
        )
    """

    action_clicked = pyqtSignal()

    def __init__(
        self,
        icon: str = "",
        title: str = "",
        hint: str = "",
        action_text: str = "",
        action_callback: Optional[Callable] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._icon = icon
        self._title = title
        self._hint = hint
        self._action_text = action_text
        self._action_callback = action_callback
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(SPACING["md"])
        layout.setContentsMargins(SPACING["xxl"], SPACING["xxl"], SPACING["xxl"], SPACING["xxl"])

        # Icon (can be emoji string or QIcon)
        if self._icon:
            icon_label = QLabel()
            if isinstance(self._icon, str):
                # Text/emoji icon
                icon_label.setText(self._icon)
                icon_label.setStyleSheet(f"font-size: 24px; background: transparent;")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(icon_label)

        # Title
        if self._title:
            title_label = QLabel(self._title)
            title_label.setObjectName("emptyState")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title_label)

        # Hint
        if self._hint:
            hint_label = QLabel(self._hint)
            hint_label.setObjectName("emptyStateHint")
            hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        # Action button
        if self._action_text:
            layout.addSpacing(SPACING["sm"])
            action_btn = QPushButton(self._action_text)
            action_btn.setObjectName("primaryButton")
            action_btn.clicked.connect(self._on_action)
            layout.addWidget(action_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_action(self) -> None:
        if self._action_callback:
            self._action_callback()
        self.action_clicked.emit()


# =============================================================================
# HELPER COMPONENTS
# =============================================================================

class ShortcutHint(QLabel):
    """Подсказка клавиатурного сочетания.

    Usage:
        hint = ShortcutHint("F2")
        hint = ShortcutHint("Ctrl+C")
    """

    def __init__(self, shortcut: str, parent: Optional[QWidget] = None):
        super().__init__(shortcut, parent)
        self.setObjectName("shortcutHint")


class Separator(QFrame):
    """Разделитель (горизонтальный или вертикальный).

    Usage:
        sep = Separator()  # horizontal
        sep = Separator(vertical=True)
        sep = Separator(subtle=True)
    """

    def __init__(
        self,
        vertical: bool = False,
        subtle: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        if vertical:
            self.setObjectName("vline")
            self.setFrameShape(QFrame.Shape.VLine)
        else:
            self.setObjectName("hlineSubtle" if subtle else "hline")
            self.setFrameShape(QFrame.Shape.HLine)


class Spacer(QWidget):
    """Гибкий спейсер для layouts.

    Usage:
        layout.addWidget(Spacer())  # Flexible
        layout.addWidget(Spacer(fixed=16))  # Fixed 16px
    """

    def __init__(
        self,
        fixed: Optional[int] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        if fixed is not None:
            self.setFixedHeight(fixed)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)


# =============================================================================
# BUTTON GROUP
# =============================================================================

class ButtonGroup(QWidget):
    """Группа кнопок с автоматическим выравниванием.

    Usage:
        group = ButtonGroup()
        group.add_button("Cancel")
        group.add_button("Save", primary=True)

        # Or with alignment
        group = ButtonGroup(align="right")
    """

    def __init__(
        self,
        align: str = "right",
        spacing: int = SPACING["sm"],
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._align = align
        self._buttons: List[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)

        if align in ("right", "center"):
            layout.addStretch()

        self._button_layout = layout

    def add_button(
        self,
        text: str,
        primary: bool = False,
        danger: bool = False,
        callback: Optional[Callable] = None
    ) -> QPushButton:
        """Add a button to the group."""
        btn = QPushButton(text)

        if primary:
            btn.setObjectName("primaryButton")
        elif danger:
            btn.setObjectName("dangerButton")

        if callback:
            btn.clicked.connect(callback)

        self._buttons.append(btn)

        # Insert before stretch if right-aligned
        if self._align == "right":
            self._button_layout.insertWidget(self._button_layout.count() - 1, btn)
        else:
            self._button_layout.addWidget(btn)

        if self._align == "left":
            # Add stretch at the end
            if len(self._buttons) == 1:
                self._button_layout.addStretch()

        return btn

    def get_button(self, index: int) -> Optional[QPushButton]:
        """Get button by index."""
        if 0 <= index < len(self._buttons):
            return self._buttons[index]
        return None


# =============================================================================
# STATUS INDICATORS
# =============================================================================

class StatusLabel(QLabel):
    """Лейбл с индикатором статуса.

    Usage:
        status = StatusLabel("Ready", status="success")
        status.set_status("error", "Connection failed")
    """

    STATUS_ICONS = {
        # ASCII: пиксельный Pixellari не имеет ✓✗▸ (рендерятся .notdef-box).
        "success": "[OK]",
        "error": "[X]",
        "pending": "[...]",
        "progress": "[>]",
        "warning": "[!]",
    }

    def __init__(
        self,
        text: str = "",
        status: str = "pending",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.set_status(status, text)

    def set_status(self, status: str, text: str = "") -> None:
        """Update status and text."""
        icon = self.STATUS_ICONS.get(status, "")
        display_text = f"{icon} {text}" if text else icon
        self.setText(display_text)
        self.setProperty("status", status)
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)


# =============================================================================
# TOOLBAR COMPONENTS
# =============================================================================

class ToolbarButton(QPushButton):
    """Кнопка для toolbar с иконкой и опциональным текстом.

    Usage:
        btn = ToolbarButton("🎤", "Record")
        btn = ToolbarButton("⚙️", tooltip="Settings")
    """

    def __init__(
        self,
        icon_text: str = "",
        label: str = "",
        tooltip: str = "",
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        if label:
            self.setText(f"{icon_text} {label}" if icon_text else label)
        else:
            self.setText(icon_text)
            self.setObjectName("iconButton")

        if tooltip:
            self.setToolTip(tooltip)


# =============================================================================
# FORM COMPONENTS
# =============================================================================

class FormField(QWidget):
    """Поле формы с лейблом.

    Usage:
        field = FormField("Username")
        field.content_layout.addWidget(QLineEdit())
    """

    def __init__(
        self,
        label: str,
        hint: str = "",
        required: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._build_ui(label, hint, required)

    def _build_ui(self, label: str, hint: str, required: bool) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, SPACING["sm"])
        layout.setSpacing(SPACING["xs"])

        # Label row
        label_row = QHBoxLayout()
        label_row.setSpacing(SPACING["xs"])

        label_text = f"{label}{'*' if required else ''}"
        label_widget = QLabel(label_text)
        label_widget.setObjectName("sectionTitle")
        label_row.addWidget(label_widget)

        if hint:
            hint_widget = QLabel(hint)
            hint_widget.setObjectName("muted")
            label_row.addWidget(hint_widget)

        label_row.addStretch()
        layout.addLayout(label_row)

        # Content area for the actual input
        self._content = QWidget()
        self.content_layout = QHBoxLayout(self._content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(SPACING["sm"])
        layout.addWidget(self._content)


# =============================================================================
# SYSTEM 7 COMPONENTS
# =============================================================================

class System7TitleBar(QFrame):
    """Title bar in System 7 style with horizontal stripes.

    Features:
        - Horizontal stripes pattern background
        - Close button (optional)
        - Centered title with white background

    Usage:
        title_bar = System7TitleBar("Window Title")
        title_bar.close_clicked.connect(self.close)
    """

    close_clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        show_close: bool = True,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._title = title
        self._show_close = show_close
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("system7TitleBar")
        self.setFixedHeight(SYSTEM7["title_bar"]["height"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(0)

        # Close button
        if self._show_close:
            close_btn = QPushButton()
            close_btn.setObjectName("system7CloseButton")
            close_btn.setFixedSize(
                SYSTEM7["window_control"]["size"],
                SYSTEM7["window_control"]["size"]
            )
            close_btn.clicked.connect(self.close_clicked.emit)
            layout.addWidget(close_btn)
            layout.addSpacing(4)

        # Left stripes area (stretch)
        layout.addStretch()

        # Title label (centered, with white background)
        self._title_label = QLabel(self._title)
        self._title_label.setObjectName("system7TitleLabel")
        layout.addWidget(self._title_label)

        # Right stripes area (stretch)
        layout.addStretch()

    def set_title(self, title: str) -> None:
        """Update the title text."""
        self._title = title
        self._title_label.setText(title)


class System7Window(QFrame):
    """Window frame in System 7 style with title bar.

    Features:
        - System 7 title bar with stripes and close button
        - Content area for child widgets
        - Sharp corners (no border-radius)

    Usage:
        window = System7Window("My Window")
        window.content_layout.addWidget(my_widget)
    """

    close_clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        show_close: bool = True,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._title = title
        self._show_close = show_close
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("system7Window")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        self.title_bar = System7TitleBar(self._title, self._show_close)
        self.title_bar.close_clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.title_bar)

        # Content area
        self._content = QFrame()
        self._content.setObjectName("system7WindowContent")
        self.content_layout = QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(
            SPACING["md"], SPACING["md"],
            SPACING["md"], SPACING["md"]
        )
        self.content_layout.setSpacing(SPACING["sm"])
        layout.addWidget(self._content, stretch=1)

    def set_title(self, title: str) -> None:
        """Update the window title."""
        self.title_bar.set_title(title)


class System7ModalFrame(QFrame):
    """Frame with double border for modal dialogs.

    Features:
        - Outer border (2px)
        - Inner border (3.5px)
        - Creates authentic System 7 modal appearance

    Usage:
        modal = System7ModalFrame()
        modal.content_layout.addWidget(my_content)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("system7ModalOuter")

        # Outer frame layout
        outer_layout = QVBoxLayout(self)
        outer_margin = int(SYSTEM7["modal"]["outer_border"])
        outer_layout.setContentsMargins(
            outer_margin, outer_margin,
            outer_margin, outer_margin
        )
        outer_layout.setSpacing(0)

        # Inner frame
        self._inner = QFrame()
        self._inner.setObjectName("system7ModalInner")
        outer_layout.addWidget(self._inner)

        # Content layout inside inner frame
        inner_margin = int(SYSTEM7["modal"]["inner_border"])
        self.content_layout = QVBoxLayout(self._inner)
        self.content_layout.setContentsMargins(
            SPACING["md"] + inner_margin,
            SPACING["md"] + inner_margin,
            SPACING["md"] + inner_margin,
            SPACING["md"] + inner_margin
        )
        self.content_layout.setSpacing(SPACING["sm"])


# =============================================================================
# FRAMELESS WINDOW CHROME (полосатый System-7 title bar для диалогов)
# =============================================================================

class _DialogTitleBar(QFrame):
    """Полосатый System-7 заголовок для frameless-диалогов: title + закрыть + drag."""

    def __init__(self, window: QWidget, title: str):
        super().__init__()
        self._win = window
        self._press = False
        self.setObjectName("appTitleBar")
        self.setFixedHeight(24)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)
        lbl = QLabel(title)
        lbl.setObjectName("system7TitleLabel")
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setObjectName("winClose")
        close_btn.setFixedSize(18, 16)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(window.close)
        lay.addWidget(close_btn)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press and (event.buttons() & Qt.MouseButton.LeftButton):
            self._press = False
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = False
        super().mouseReleaseEvent(event)


def titlebar_qss() -> str:
    """Минимальный QSS для полосатого title bar — для окон со своим setStyleSheet
    (например QWizard, где полный центральный STYLESHEET ломает ModernStyle-рендер)."""
    from .styles import get_icon_path
    stripes = get_icon_path("stripes.png")
    return f"""
    QWidget#appWindowFrame {{ background-color: #ffffff; border: 2px solid #000000; }}
    QFrame#appTitleBar {{
        background-color: #ffffff;
        background-image: url({stripes});
        background-repeat: repeat-x;
        border: none; border-bottom: 1px solid #000000;
    }}
    QLabel#system7TitleLabel {{ background-color: #ffffff; padding: 0 8px; font-weight: bold; }}
    QPushButton#winClose {{
        background-color: #ffffff; border: 1px solid #000000; border-radius: 0;
        font-weight: bold; font-size: 11px; padding: 0;
    }}
    QPushButton#winClose:hover {{ background-color: #dddddd; }}
    QPushButton#winClose:pressed {{ background-color: #000000; color: #ffffff; }}
    """


def apply_system7_titlebar(window: QWidget, title: str) -> None:
    """Сделать окно/диалог frameless с полосатым System-7 заголовком.

    QMainWindow → заголовок через setMenuWidget; прочие — оборачиваем
    существующий layout в content-виджет и добавляем bar сверху.
    """
    from PyQt6.QtWidgets import QMainWindow
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    bar = _DialogTitleBar(window, title)
    if isinstance(window, QMainWindow):
        window.setMenuWidget(bar)
        return
    old = window.layout()
    content = QWidget()
    if old is not None:
        content.setLayout(old)
    outer = QVBoxLayout()
    outer.setContentsMargins(2, 2, 2, 2)
    outer.setSpacing(0)
    outer.addWidget(bar)
    outer.addWidget(content, 1)
    window.setLayout(outer)
    window.setObjectName("appWindowFrame")
