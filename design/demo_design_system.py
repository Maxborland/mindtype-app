#!/usr/bin/env python3
"""
Демонстрация обновлённой дизайн-системы MindType v2.

Запуск:
    python design/demo_design_system.py

Показывает:
- Типографскую иерархию (24/18/14/12/11/10px)
- Варианты кнопок (primary, secondary, ghost, danger)
- Карточки (default, elevated, interactive, surface, info)
- Компоненты (EmptyState, Section, StatusLabel, ButtonGroup)
- Focus states для accessibility
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTabWidget,
    QScrollArea,
    QFrame,
    QCheckBox,
    QComboBox,
    QSlider,
    QProgressBar,
)
from PyQt6.QtCore import Qt

from app.ui import (
    STYLESHEET,
    COLORS,
    TYPOGRAPHY,
    SPACING,
    Card,
    Section,
    TitledCard,
    EmptyState,
    ShortcutHint,
    Separator,
    Spacer,
    ButtonGroup,
    StatusLabel,
    FormField,
    # Pixel icons
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
    create_info_icon,
    create_warning_icon,
)


class DesignSystemDemo(QMainWindow):
    """Демонстрационное окно дизайн-системы."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MindType Design System v2")
        self.setMinimumSize(900, 700)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        # Header
        header = QLabel("MindType Design System v2")
        header.setObjectName("displayTitle")
        layout.addWidget(header)

        subtitle = QLabel("Apple System OS (1984-1991) Style • Enhanced with tokens & components")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        layout.addWidget(Separator(subtle=True))
        layout.addWidget(Spacer(fixed=16))

        # Tabs
        tabs = QTabWidget()
        tabs.addTab(self._create_typography_tab(), "Typography")
        tabs.addTab(self._create_buttons_tab(), "Buttons")
        tabs.addTab(self._create_icons_tab(), "Icons")
        tabs.addTab(self._create_cards_tab(), "Cards")
        tabs.addTab(self._create_components_tab(), "Components")
        tabs.addTab(self._create_forms_tab(), "Forms")
        tabs.addTab(self._create_colors_tab(), "Colors")
        layout.addWidget(tabs, stretch=1)

    def _create_typography_tab(self) -> QWidget:
        """Tab с типографикой."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["lg"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Typography samples
        samples = [
            ("displayTitle", "Display Title", f"{TYPOGRAPHY['display']['size']}px bold"),
            ("bigTitle", "Big Title / Title", f"{TYPOGRAPHY['title']['size']}px bold"),
            ("panelTitle", "Panel Title / Subtitle", f"{TYPOGRAPHY['subtitle']['size']}px bold"),
            ("sectionTitle", "Section Title", f"{TYPOGRAPHY['body']['size']}px bold"),
            (None, "Body Text - The quick brown fox jumps over the lazy dog", f"{TYPOGRAPHY['body']['size']}px"),
            ("muted", "Muted text for hints and secondary information", f"{TYPOGRAPHY['body']['size']}px muted"),
            ("caption", "Caption text for small annotations", f"{TYPOGRAPHY['caption']['size']}px"),
            ("small", "Small text for legal or auxiliary info", f"{TYPOGRAPHY['small']['size']}px"),
        ]

        for obj_name, text, desc in samples:
            row = QHBoxLayout()

            label = QLabel(text)
            if obj_name:
                label.setObjectName(obj_name)
            row.addWidget(label, stretch=1)

            size_label = QLabel(desc)
            size_label.setObjectName("caption")
            size_label.setFixedWidth(120)
            row.addWidget(size_label)

            layout.addLayout(row)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_buttons_tab(self) -> QWidget:
        """Tab с кнопками."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["xl"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Section: Button Variants
        section = Section("Button Variants", "Different button styles for different contexts")
        layout.addWidget(section)

        variants = [
            ("Default", None, "Standard button"),
            ("Primary", "primaryButton", "Main action, thick border"),
            ("Secondary", "secondaryButton", "Alternative action"),
            ("Danger", "dangerButton", "Destructive action"),
            ("Small", "smallButton", "Compact variant"),
            ("Icon", "iconButton", "Icon-only button"),
            ("Ghost", "ghostButton", "Minimal styling"),
        ]

        for name, obj_name, desc in variants:
            row = QHBoxLayout()

            btn = QPushButton(name if obj_name != "iconButton" else "⚙️")
            if obj_name:
                btn.setObjectName(obj_name)
            row.addWidget(btn)

            desc_label = QLabel(desc)
            desc_label.setObjectName("muted")
            row.addWidget(desc_label, stretch=1)

            section.content_layout.addLayout(row)

        # Section: Button States
        section2 = Section("Button States", "Focus states for keyboard accessibility")
        layout.addWidget(section2)

        states_row = QHBoxLayout()
        for state_name in ["Normal", "Hover", "Focus (Tab)", "Disabled"]:
            btn = QPushButton(state_name)
            if state_name == "Disabled":
                btn.setEnabled(False)
            states_row.addWidget(btn)
        section2.content_layout.addLayout(states_row)

        hint = QLabel("Tab through buttons to see focus states")
        hint.setObjectName("caption")
        section2.content_layout.addWidget(hint)

        # Section: ButtonGroup
        section3 = Section("ButtonGroup Component", "Aligned button groups")
        layout.addWidget(section3)

        group = ButtonGroup(align="right")
        group.add_button("Cancel")
        group.add_button("Save", primary=True)
        section3.content_layout.addWidget(group)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_icons_tab(self) -> QWidget:
        """Tab с пиксельными иконками."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["xl"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Section: Pixel Icons
        section = Section("Pixel Art Icons", "Classic Mac OS style, 16x16px")
        layout.addWidget(section)

        # Icons grid
        icons = [
            ("Microphone", create_mic_icon),
            ("Settings", create_settings_icon),
            ("Folder", create_folder_icon),
            ("Document", create_document_icon),
            ("Play", create_play_icon),
            ("Stop", create_stop_icon),
            ("Pause", create_pause_icon),
            ("Copy", create_copy_icon),
            ("Trash", create_trash_icon),
            ("Refresh", create_refresh_icon),
            ("Check", create_check_icon),
            ("Close", create_close_icon),
            ("Info", create_info_icon),
            ("Warning", create_warning_icon),
        ]

        grid = QHBoxLayout()
        grid.setSpacing(SPACING["lg"])

        for name, icon_fn in icons:
            item = QVBoxLayout()
            item.setSpacing(SPACING["xs"])
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Icon button
            btn = QPushButton()
            btn.setIcon(icon_fn(16))
            btn.setFixedSize(32, 32)
            btn.setObjectName("iconButton")
            item.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

            # Label
            label = QLabel(name)
            label.setObjectName("small")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.addWidget(label)

            grid.addLayout(item)

        grid.addStretch()
        section.content_layout.addLayout(grid)

        # Section: Icons at different sizes
        section2 = Section("Icon Sizes", "Scalable pixel art")
        layout.addWidget(section2)

        sizes_row = QHBoxLayout()
        sizes_row.setSpacing(SPACING["xl"])

        for size in [12, 16, 20, 24, 32]:
            item = QVBoxLayout()
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn = QPushButton()
            btn.setIcon(create_mic_icon(size))
            btn.setFixedSize(size + 12, size + 12)
            btn.setObjectName("iconButton")
            item.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

            label = QLabel(f"{size}px")
            label.setObjectName("caption")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.addWidget(label)

            sizes_row.addLayout(item)

        sizes_row.addStretch()
        section2.content_layout.addLayout(sizes_row)

        # Section: Icon buttons
        section3 = Section("Icon Buttons", "Using pixel icons in UI")
        layout.addWidget(section3)

        btns_row = QHBoxLayout()
        btns_row.setSpacing(SPACING["sm"])

        # Play/Pause/Stop group
        for icon_fn, tooltip in [(create_play_icon, "Play"), (create_pause_icon, "Pause"), (create_stop_icon, "Stop")]:
            btn = QPushButton()
            btn.setIcon(icon_fn(16))
            btn.setToolTip(tooltip)
            btn.setFixedSize(28, 28)
            btn.setObjectName("iconButton")
            btns_row.addWidget(btn)

        btns_row.addWidget(Separator(vertical=True))

        # Action buttons with text
        for icon_fn, text in [(create_copy_icon, "Copy"), (create_trash_icon, "Delete"), (create_refresh_icon, "Refresh")]:
            btn = QPushButton(text)
            btn.setIcon(icon_fn(16))
            btns_row.addWidget(btn)

        btns_row.addStretch()
        section3.content_layout.addLayout(btns_row)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_cards_tab(self) -> QWidget:
        """Tab с карточками."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["xl"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Card variants
        section = Section("Card Variants", "Different card styles using ObjectName")
        layout.addWidget(section)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(SPACING["md"])

        variants = [
            ("default", "Default\n1.5px border"),
            ("elevated", "Elevated\n2px border"),
            ("interactive", "Interactive\nHover effect"),
            ("surface", "Surface\nGray bg"),
            ("info", "Info\nGray bg, dark border"),
        ]

        for variant, text in variants:
            card = Card(variant=variant)
            card.setFixedSize(140, 100)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
            label = QLabel(text)
            label.setObjectName("caption")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(label)
            cards_row.addWidget(card)

        section.content_layout.addLayout(cards_row)

        # TitledCard
        section2 = Section("TitledCard", "Card with System 7 striped title bar")
        layout.addWidget(section2)

        titled = TitledCard("Options")
        titled.setFixedHeight(150)
        titled.content_layout.addWidget(QLabel("Content inside titled card"))
        titled.content_layout.addWidget(QCheckBox("Enable feature"))
        titled.content_layout.addStretch()
        section2.content_layout.addWidget(titled)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_components_tab(self) -> QWidget:
        """Tab с компонентами."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["xl"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # EmptyState
        section = Section("EmptyState", "For lists and areas with no content")
        layout.addWidget(section)

        empty = EmptyState(
            icon="",  # No emoji
            title="No transcriptions yet",
            hint="Press F2 or click Record to start",
            action_text="Start Recording"
        )
        empty.setStyleSheet(f"background-color: {COLORS['surface']['secondary']}; border: 1px dashed {COLORS['border']['subtle']};")
        section.content_layout.addWidget(empty)

        # StatusLabel
        section2 = Section("StatusLabel", "Status indicators with B&W icons")
        layout.addWidget(section2)

        statuses_row = QHBoxLayout()
        for status in ["success", "error", "pending", "progress", "warning"]:
            label = StatusLabel(status.capitalize(), status=status)
            statuses_row.addWidget(label)
        statuses_row.addStretch()
        section2.content_layout.addLayout(statuses_row)

        # ShortcutHint
        section3 = Section("ShortcutHint", "Keyboard shortcut badges")
        layout.addWidget(section3)

        hints_row = QHBoxLayout()
        hints_row.setSpacing(SPACING["sm"])
        for shortcut in ["F2", "Ctrl+C", "Esc", "Enter"]:
            hints_row.addWidget(ShortcutHint(shortcut))
        hints_row.addStretch()
        section3.content_layout.addLayout(hints_row)

        # Separator
        section4 = Section("Separator", "Horizontal and vertical dividers")
        layout.addWidget(section4)

        section4.content_layout.addWidget(QLabel("Default separator:"))
        section4.content_layout.addWidget(Separator())
        section4.content_layout.addWidget(QLabel("Subtle separator:"))
        section4.content_layout.addWidget(Separator(subtle=True))

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_forms_tab(self) -> QWidget:
        """Tab с формами."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["xl"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Form inputs
        section = Section("Form Inputs", "Focus inversion for Classic Mac feel")
        layout.addWidget(section)

        # LineEdit
        field1 = FormField("Username", required=True)
        edit = QLineEdit()
        edit.setPlaceholderText("Enter username...")
        field1.content_layout.addWidget(edit)
        section.content_layout.addWidget(field1)

        # ComboBox
        field2 = FormField("Language", hint="Select recognition language")
        combo = QComboBox()
        combo.addItems(["English", "Russian", "German", "French"])
        field2.content_layout.addWidget(combo)
        section.content_layout.addWidget(field2)

        # Checkbox
        section.content_layout.addWidget(QCheckBox("Enable auto-save"))
        section.content_layout.addWidget(QCheckBox("Show notifications"))

        # Slider
        section2 = Section("Slider & Progress", "Range inputs")
        layout.addWidget(section2)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(60)
        section2.content_layout.addWidget(slider)

        progress = QProgressBar()
        progress.setValue(75)
        section2.content_layout.addWidget(progress)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_colors_tab(self) -> QWidget:
        """Tab с цветами."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("noBorder")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(SPACING["lg"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Color palette
        for category, colors in COLORS.items():
            section = Section(category.replace("_", " ").title())
            layout.addWidget(section)

            row = QHBoxLayout()
            row.setSpacing(SPACING["sm"])

            for name, hex_color in colors.items():
                swatch = QFrame()
                swatch.setFixedSize(60, 60)
                swatch.setStyleSheet(f"""
                    background-color: {hex_color};
                    border: 1px solid #000000;
                """)

                swatch_layout = QVBoxLayout(swatch)
                swatch_layout.setContentsMargins(4, 4, 4, 4)
                swatch_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)

                # Determine text color based on brightness
                text_color = "#ffffff" if hex_color in ["#000000", "#606060"] else "#000000"
                label = QLabel(name)
                label.setStyleSheet(f"font-size: 8px; color: {text_color}; background: transparent;")
                swatch_layout.addWidget(label)

                row.addWidget(swatch)

            row.addStretch()
            section.content_layout.addLayout(row)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll


def main():
    app = QApplication(sys.argv)
    window = DesignSystemDemo()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
