"""
Переиспользуемые layout-компоненты для MindType.

Этот модуль содержит:
- FormRow: строка формы (label + widget)
- FormLayout: вертикальный layout для форм с единой шириной лейблов
- TwoColumnLayout: двухколоночный layout для Settings
- SectionBox: секция в рамке с заголовком (GroupBox-style)

Использование:
    from .layouts import FormRow, FormLayout, TwoColumnLayout, SectionBox
"""

from typing import Optional, Callable, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QGroupBox,
    QScrollArea,
)

from .tokens import COLORS, SPACING, TYPOGRAPHY


# =============================================================================
# FORM COMPONENTS
# =============================================================================

class FormRow(QWidget):
    """Строка формы: label + widget с фиксированной шириной лейбла.

    Usage:
        row = FormRow("Audio Input", my_combobox)
        row = FormRow("Hotkey", hotkey_widget, label_width=160)
    """

    def __init__(
        self,
        label: str,
        widget: QWidget,
        label_width: int = 140,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._label_text = label
        self._widget = widget
        self._label_width = label_width
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["md"])

        # Label
        self._label = QLabel(self._label_text)
        self._label.setFixedWidth(self._label_width)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label)

        # Widget
        layout.addWidget(self._widget, stretch=1)

    @property
    def label(self) -> QLabel:
        """Доступ к лейблу для обновления текста."""
        return self._label

    @property
    def widget(self) -> QWidget:
        """Доступ к виджету."""
        return self._widget


class FormLayout(QWidget):
    """Вертикальный layout для форм с единой шириной лейблов.

    Usage:
        form = FormLayout(label_width=140)
        form.add_row("Audio Input", my_combobox)
        form.add_row("Language", my_langbox)
        form.add_separator()
        form.add_row("Updates", update_widget)
    """

    def __init__(
        self,
        label_width: int = 140,
        spacing: int = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._label_width = label_width
        self._rows: List[Tuple[str, FormRow]] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(spacing if spacing is not None else SPACING["md"])

    def add_row(self, label: str, widget: QWidget) -> FormRow:
        """Добавить строку формы."""
        row = FormRow(label, widget, label_width=self._label_width)
        self._rows.append((label, row))
        self._layout.addWidget(row)
        return row

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """Добавить произвольный виджет (без лейбла)."""
        self._layout.addWidget(widget, stretch=stretch)

    def add_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        """Добавить произвольный layout."""
        self._layout.addLayout(layout)

    def add_separator(self, subtle: bool = True) -> QFrame:
        """Добавить горизонтальный разделитель."""
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("hlineSubtle" if subtle else "hline")
        self._layout.addWidget(separator)
        return separator

    def add_spacing(self, size: int = None) -> None:
        """Добавить вертикальный отступ."""
        self._layout.addSpacing(size if size is not None else SPACING["md"])

    def add_stretch(self, stretch: int = 1) -> None:
        """Добавить растягивающийся spacer."""
        self._layout.addStretch(stretch)

    def get_row(self, label: str) -> Optional[FormRow]:
        """Получить строку по лейблу."""
        for row_label, row in self._rows:
            if row_label == label:
                return row
        return None

    @property
    def layout(self) -> QVBoxLayout:
        """Доступ к внутреннему layout."""
        return self._layout


# =============================================================================
# MULTI-COLUMN LAYOUTS
# =============================================================================

class TwoColumnLayout(QWidget):
    """Двухколоночный layout для секций Settings.

    Usage:
        columns = TwoColumnLayout()
        columns.add_to_left(ai_section)
        columns.add_to_left(performance_section)
        columns.add_to_right(overlay_section)
        columns.add_to_right(app_section)
    """

    def __init__(
        self,
        spacing: int = None,
        column_spacing: int = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(column_spacing if column_spacing is not None else SPACING["xl"])

        # Левая колонка
        self._left_widget = QWidget()
        self._left_column = QVBoxLayout(self._left_widget)
        self._left_column.setContentsMargins(0, 0, 0, 0)
        self._left_column.setSpacing(spacing if spacing is not None else SPACING["xl"])
        main_layout.addWidget(self._left_widget, stretch=1)

        # Правая колонка
        self._right_widget = QWidget()
        self._right_column = QVBoxLayout(self._right_widget)
        self._right_column.setContentsMargins(0, 0, 0, 0)
        self._right_column.setSpacing(spacing if spacing is not None else SPACING["xl"])
        main_layout.addWidget(self._right_widget, stretch=1)

    def add_to_left(self, widget: QWidget, stretch: int = 0) -> None:
        """Добавить виджет в левую колонку."""
        self._left_column.addWidget(widget, stretch=stretch)

    def add_to_right(self, widget: QWidget, stretch: int = 0) -> None:
        """Добавить виджет в правую колонку."""
        self._right_column.addWidget(widget, stretch=stretch)

    def add_left_stretch(self, stretch: int = 1) -> None:
        """Добавить stretch в левую колонку."""
        self._left_column.addStretch(stretch)

    def add_right_stretch(self, stretch: int = 1) -> None:
        """Добавить stretch в правую колонку."""
        self._right_column.addStretch(stretch)

    @property
    def left_column(self) -> QVBoxLayout:
        """Доступ к левому layout."""
        return self._left_column

    @property
    def right_column(self) -> QVBoxLayout:
        """Доступ к правому layout."""
        return self._right_column


# =============================================================================
# SECTION COMPONENTS
# =============================================================================

class SectionBox(QGroupBox):
    """Секция в рамке с заголовком в стиле Classic Mac OS.

    Usage:
        section = SectionBox("AI Provider")
        section.form.add_row("Provider", provider_combo)
        section.form.add_row("API Key", api_key_edit)

    Или с кастомным content:
        section = SectionBox("Performance", use_form=False)
        section.content_layout.addWidget(...)
    """

    def __init__(
        self,
        title: str,
        use_form: bool = True,
        label_width: int = 120,
        parent: Optional[QWidget] = None
    ):
        super().__init__(title, parent)
        self._use_form = use_form
        self._label_width = label_width
        self._build_ui()

    def _build_ui(self) -> None:
        if self._use_form:
            # FormLayout внутри GroupBox
            self._form = FormLayout(label_width=self._label_width)
            inner_layout = QVBoxLayout(self)
            inner_layout.setContentsMargins(
                SPACING["sm"], SPACING["md"],
                SPACING["sm"], SPACING["sm"]
            )
            inner_layout.setSpacing(SPACING["sm"])
            inner_layout.addWidget(self._form)
        else:
            # Кастомный layout
            self._content_layout = QVBoxLayout(self)
            self._content_layout.setContentsMargins(
                SPACING["sm"], SPACING["md"],
                SPACING["sm"], SPACING["sm"]
            )
            self._content_layout.setSpacing(SPACING["sm"])

    @property
    def form(self) -> FormLayout:
        """Доступ к FormLayout (если use_form=True)."""
        if not self._use_form:
            raise AttributeError("SectionBox was created with use_form=False. Use content_layout instead.")
        return self._form

    @property
    def content_layout(self) -> QVBoxLayout:
        """Доступ к content layout (если use_form=False)."""
        if self._use_form:
            raise AttributeError("SectionBox was created with use_form=True. Use form instead.")
        return self._content_layout


# =============================================================================
# SCROLLABLE CONTENT
# =============================================================================

class ScrollableContent(QScrollArea):
    """Скроллируемый контейнер для контента.

    Usage:
        scroll = ScrollableContent()
        scroll.content_layout.addWidget(section1)
        scroll.content_layout.addWidget(section2)
    """

    def __init__(
        self,
        horizontal_scroll: bool = False,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWidgetResizable(True)
        if not horizontal_scroll:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("scrollArea")

        # Внутренний контент
        self._content = QWidget()
        self._content.setObjectName("scrollContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(
            SPACING["lg"], SPACING["xl"],
            SPACING["lg"], SPACING["lg"]
        )
        self._content_layout.setSpacing(SPACING["xl"])
        self.setWidget(self._content)

    @property
    def content_layout(self) -> QVBoxLayout:
        """Доступ к layout контента."""
        return self._content_layout

    @property
    def content_widget(self) -> QWidget:
        """Доступ к виджету контента."""
        return self._content


# =============================================================================
# HEADER/FOOTER COMPONENTS
# =============================================================================

class TabHeader(QWidget):
    """Header для таба с элементами слева и справа.

    Usage:
        header = TabHeader()
        header.add_left(credits_widget)
        header.add_right(mode_toggle)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, SPACING["md"])
        self._layout.setSpacing(SPACING["md"])

        # Левая часть
        self._left_layout = QHBoxLayout()
        self._left_layout.setSpacing(SPACING["sm"])
        self._layout.addLayout(self._left_layout)

        # Spacer
        self._layout.addStretch()

        # Правая часть
        self._right_layout = QHBoxLayout()
        self._right_layout.setSpacing(SPACING["sm"])
        self._layout.addLayout(self._right_layout)

    def add_left(self, widget: QWidget) -> None:
        """Добавить виджет слева."""
        self._left_layout.addWidget(widget)

    def add_right(self, widget: QWidget) -> None:
        """Добавить виджет справа."""
        self._right_layout.addWidget(widget)


class ActionBar(QWidget):
    """Панель с кнопками действий (обычно внизу).

    Usage:
        bar = ActionBar(align="right")
        bar.add_button("Cancel")
        bar.add_button("Save", primary=True)
    """

    def __init__(
        self,
        align: str = "right",
        spacing: int = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self._align = align
        self._buttons: List[QPushButton] = []

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, SPACING["md"], 0, 0)
        self._layout.setSpacing(spacing if spacing is not None else SPACING["sm"])

        if align in ("right", "center"):
            self._layout.addStretch()

    def add_button(
        self,
        text: str,
        primary: bool = False,
        danger: bool = False,
        callback: Optional[Callable] = None
    ) -> QPushButton:
        """Добавить кнопку."""
        btn = QPushButton(text)

        if primary:
            btn.setObjectName("primaryButton")
        elif danger:
            btn.setObjectName("dangerButton")

        if callback:
            btn.clicked.connect(callback)

        self._buttons.append(btn)

        # Добавляем перед stretch если right-aligned
        if self._align == "right":
            self._layout.insertWidget(self._layout.count() - 1, btn)
        else:
            self._layout.addWidget(btn)

            # Добавляем stretch в конец для left alignment
            if self._align == "left" and len(self._buttons) == 1:
                self._layout.addStretch()

        return btn

    def add_widget(self, widget: QWidget) -> None:
        """Добавить произвольный виджет."""
        if self._align == "right":
            self._layout.insertWidget(self._layout.count() - 1, widget)
        else:
            self._layout.addWidget(widget)

    def get_button(self, index: int) -> Optional[QPushButton]:
        """Получить кнопку по индексу."""
        if 0 <= index < len(self._buttons):
            return self._buttons[index]
        return None
