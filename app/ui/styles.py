"""
Стили для UI MindType.

Apple System OS (1984-1991) Style для PyQt6.
Основано на system.css by @sakofchit.
Единый источник всех стилей приложения.

Улучшения v2:
- Интеграция с design tokens
- Улучшенная типографская иерархия
- Focus states для accessibility
- Унифицированные компоненты
"""

from pathlib import Path

# Import design tokens
from .tokens import (
    COLORS,
    TYPOGRAPHY,
    SPACING,
    BORDERS,
    RADII,
    SYSTEM7,
    FONT_FAMILY,
    FONT_FAMILY_MONO,
    get_color,
    get_spacing,
)

# === LEGACY COLORS (для обратной совместимости) ===
# Deprecated: используйте tokens.COLORS
LEGACY_COLORS = {
    "background": "#ffffff",
    "info_box": "#dddddd",
    "text": "#000000",
    "disabled": "#808080",
    "border": "#000000",
    "border_light": "#ffffff",
    "selection_bg": "#000000",
    "selection_fg": "#ffffff",
}

# Путь к иконкам
ICONS_DIR = Path(__file__).parent / "icons"


def get_icon_path(name: str) -> str:
    """Получить путь к иконке для QSS."""
    path = ICONS_DIR / name
    # Для QSS нужен forward slash
    return str(path).replace("\\", "/")


# =============================================================================
# MAIN STYLESHEET
# =============================================================================

# Apple System OS Style (system.css inspired) - Enhanced v2
STYLESHEET = f"""
/* ===== APPLE SYSTEM OS STYLE (1984-1991) - Enhanced v2 ===== */
/* Based on system.css by @sakofchit */
/* With improved typography, focus states, and accessibility */

/* === CSS VARIABLES (via tokens.py) === */
/*
    Surface: {COLORS['surface']['primary']}, {COLORS['surface']['secondary']}, {COLORS['surface']['tertiary']}
    Border: {COLORS['border']['default']}, {COLORS['border']['subtle']}
    Text: {COLORS['text']['primary']}, {COLORS['text']['secondary']}, {COLORS['text']['muted']}
*/

/* === BASE STYLES === */

QMainWindow, QWidget, QDialog {{
    background-color: {COLORS['surface']['primary']};
    color: {COLORS['text']['primary']};
    font-family: {FONT_FAMILY};
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

/* === TYPOGRAPHY HIERARCHY === */

QLabel {{
    color: {COLORS['text']['primary']};
    background: transparent;
}}

/* Display - 24px bold (экраны, большие заголовки) */
QLabel#displayTitle {{
    font-size: {TYPOGRAPHY['display']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    padding: {SPACING['sm']}px 0;
}}

/* Title - 18px bold (заголовки секций) */
QLabel#bigTitle, QLabel#title {{
    font-size: {TYPOGRAPHY['title']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    padding: {SPACING['xs']}px 0;
}}

/* Subtitle - 14px bold (подзаголовки, панели) */
QLabel#panelTitle, QLabel#subtitle {{
    font-size: {TYPOGRAPHY['subtitle']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    padding: {SPACING['xs']}px 0;
}}

/* Section title - 12px bold */
QLabel#sectionTitle {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    padding: 2px 0;
}}

/* Body muted - secondary text */
QLabel#muted, QLabel#hint {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    color: {COLORS['text']['muted']};
}}

/* Caption - 11px */
QLabel#caption {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['secondary']};
}}

/* Small - 10px */
QLabel#small {{
    font-size: {TYPOGRAPHY['small']['size']}px;
    color: {COLORS['text']['muted']};
}}

/* Warning text */
QLabel#warning {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    font-style: italic;
}}

/* === BUTTONS - SYSTEM 7 AUTHENTIC STYLE === */

QPushButton {{
    background-color: {COLORS['surface']['primary']};
    /* System 7 «приподнятая» кнопка: 1px рамка + утолщённые низ/право = тень. */
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 2px;
    border-right-width: 2px;
    border-radius: 0;
    padding: {SYSTEM7['button']['padding_y']}px {SYSTEM7['button']['padding_x']}px;
    color: {COLORS['text']['primary']};
    min-width: {SYSTEM7['button']['min_width']}px;
    min-height: {SYSTEM7['button']['min_height']}px;
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

QPushButton:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QPushButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
    /* «Вдавленная»: тень переезжает наверх/влево. */
    border: 1px solid {COLORS['border']['default']};
    border-top-width: 2px;
    border-left-width: 2px;
}}

QPushButton:checked {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

/* Focus: сохраняем 3D-бевель (чуть тяжелее), а не равномерную рамку */
QPushButton:focus {{
    border: 2px solid {COLORS['border']['default']};
    border-bottom-width: 3px;
    border-right-width: 3px;
}}

QPushButton:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    color: {COLORS['text']['disabled']};
    border-color: {COLORS['border']['muted']};
}}

/* Primary/Default button — тот же 3D-бевель, но тяжелее (3px тень) + bold */
QPushButton#primaryButton, QPushButton[default="true"] {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 3px;
    border-right-width: 3px;
    border-radius: 0;
    font-weight: bold;
}}

QPushButton#primaryButton:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QPushButton#primaryButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
    border: 1px solid {COLORS['border']['default']};
    border-top-width: 3px;
    border-left-width: 3px;
}}

QPushButton#primaryButton:focus {{
    border: 2px solid {COLORS['border']['default']};
    border-bottom-width: 3px;
    border-right-width: 3px;
}}

QPushButton#primaryButton:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    color: {COLORS['text']['disabled']};
    border-color: {COLORS['border']['muted']};
}}

/* Secondary button — тот же 3D-бевель, фон чуть серее */
QPushButton#secondaryButton {{
    background-color: {COLORS['surface']['secondary']};
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 2px;
    border-right-width: 2px;
}}

QPushButton#secondaryButton:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

/* Danger button — 3D-бевель + bold */
QPushButton#dangerButton {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 2px;
    border-right-width: 2px;
}}

QPushButton#dangerButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
    border: 1px solid {COLORS['border']['default']};
    border-top-width: 2px;
    border-left-width: 2px;
}}

/* Small button */
QPushButton#smallButton {{
    padding: 3px 10px;
    font-size: {TYPOGRAPHY['caption']['size']}px;
    min-width: 0;
    min-height: 18px;
    border-radius: {RADII['sm']};
}}

/* Icon button (no border) */
QPushButton#iconButton {{
    border: none;
    background: transparent;
    padding: {SPACING['xs']}px;
    min-width: 24px;
    min-height: 24px;
}}

QPushButton#iconButton:hover {{
    background-color: {COLORS['surface']['tertiary']};
    border-radius: {RADII['sm']};
}}

QPushButton#iconButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
}}

QPushButton#iconButton:focus {{
    border: 1px solid {COLORS['border']['default']};
}}

/* Ghost button - minimal styling */
QPushButton#ghostButton {{
    background: transparent;
    border: none;
    color: {COLORS['text']['secondary']};
}}

QPushButton#ghostButton:hover {{
    color: {COLORS['text']['primary']};
    text-decoration: underline;
}}

/* === TABS - SYSTEM 7 SHARP CORNERS === */

QTabWidget::pane {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    background-color: {COLORS['surface']['primary']};
    margin-top: -1px;
}}

QTabBar::tab {{
    background-color: {COLORS['surface']['tertiary']};
    color: {COLORS['text']['primary']};
    padding: {SPACING['sm']}px {SPACING['lg']}px;
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-bottom: none;
    border-top-left-radius: 0;
    border-top-right-radius: 0;
    margin-right: 2px;
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

QTabBar::tab:selected {{
    background-color: {COLORS['surface']['primary']};
    border-bottom: {BORDERS['default']} solid {COLORS['surface']['primary']};
    margin-bottom: -1px;
    font-weight: bold;
}}

QTabBar::tab:!selected {{
    margin-top: 2px;
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS['interactive']['hover']};
}}

QTabBar::tab:focus {{
    border-width: 2px;
}}

/* === COMBOBOX - SYSTEM.CSS STYLE === */

QComboBox {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
    padding: {SPACING['xs']}px {SPACING['xl']}px {SPACING['xs']}px {SPACING['sm']}px;
    color: {COLORS['text']['primary']};
    min-height: 20px;
}}

QComboBox:hover {{
    background-color: {COLORS['surface']['secondary']};
}}

QComboBox:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QComboBox::drop-down {{
    /* Отдельная «приподнятая» 3D-кнопка-стрелка (как в System 7) */
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    margin: 1px;
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 2px;
    border-right-width: 2px;
    background-color: {COLORS['surface']['primary']};
}}

QComboBox::drop-down:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QComboBox::down-arrow {{
    image: url({get_icon_path("dropdown.svg")});
    width: 10px;
    height: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    selection-background-color: {COLORS['interactive']['pressed']};
    selection-color: {COLORS['interactive']['pressed_text']};
    outline: none;
}}

QComboBox QAbstractItemView::item {{
    padding: {SPACING['xs']}px {SPACING['sm']}px;
    border: none;
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QComboBox:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    color: {COLORS['text']['disabled']};
    border-color: {COLORS['border']['muted']};
}}

/* === LINE EDIT - FOCUS INVERSION === */

QLineEdit {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px {SPACING['sm']}px;
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

QLineEdit:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QLineEdit:read-only {{
    background-color: {COLORS['surface']['tertiary']};
}}

QLineEdit:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    color: {COLORS['text']['disabled']};
    border-color: {COLORS['border']['muted']};
}}

QLineEdit::placeholder {{
    color: {COLORS['text']['muted']};
}}

/* === TEXT EDIT === */

QTextEdit {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    color: {COLORS['text']['primary']};
}}

QTextEdit:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

/* === PLAIN TEXT EDIT === */

QPlainTextEdit {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    color: {COLORS['text']['primary']};
    font-family: {FONT_FAMILY_MONO};
}}

QPlainTextEdit:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

/* === CHECKBOX - SYSTEM 7 X MARK STYLE === */

QCheckBox {{
    spacing: {SPACING['sm']}px;
    color: {COLORS['text']['primary']};
}}

QCheckBox::indicator {{
    width: {SYSTEM7['checkbox']['size']}px;
    height: {SYSTEM7['checkbox']['size']}px;
    border: {SYSTEM7['checkbox']['border']}px solid {COLORS['border']['default']};
    border-radius: 0;
    background-color: {COLORS['surface']['primary']};
}}

QCheckBox::indicator:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS['surface']['primary']};
    image: url({get_icon_path("checkbox_x.svg")});
}}

QCheckBox::indicator:focus {{
    border-width: 2px;
}}

QCheckBox::indicator:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    border-color: {COLORS['border']['muted']};
}}

QCheckBox::indicator:checked:disabled {{
    background-color: {COLORS['surface']['tertiary']};
}}

QCheckBox:disabled {{
    color: {COLORS['text']['disabled']};
}}

/* === RADIO BUTTON - SYSTEM 7 STYLE === */

QRadioButton {{
    spacing: {SPACING['sm']}px;
    color: {COLORS['text']['primary']};
}}

QRadioButton::indicator {{
    width: {SYSTEM7['radio']['size']}px;
    height: {SYSTEM7['radio']['size']}px;
    border: {SYSTEM7['radio']['border']}px solid {COLORS['border']['default']};
    border-radius: {SYSTEM7['radio']['size'] // 2}px;
    background-color: {COLORS['surface']['primary']};
}}

QRadioButton::indicator:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QRadioButton::indicator:checked {{
    background-color: {COLORS['surface']['primary']};
    border: 4px solid {COLORS['border']['default']};
}}

QRadioButton::indicator:focus {{
    border-width: 2px;
}}

QRadioButton::indicator:disabled {{
    background-color: {COLORS['surface']['tertiary']};
    border-color: {COLORS['border']['muted']};
}}

QRadioButton:disabled {{
    color: {COLORS['text']['disabled']};
}}

/* === SLIDER === */

QSlider::groove:horizontal {{
    background-color: {COLORS['surface']['secondary']};
    border: 1px solid {COLORS['border']['default']};
    height: 6px;
    border-radius: 0;
}}

QSlider::handle:horizontal {{
    /* Квадратный 3D-ползунок (как кнопки) вместо круглого */
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
    border-bottom-width: 2px;
    border-right-width: 2px;
    width: 12px;
    height: 18px;
    margin: -7px 0;
    border-radius: 0;
}}

QSlider::handle:horizontal:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QSlider::handle:horizontal:pressed {{
    background-color: {COLORS['interactive']['pressed']};
}}

QSlider::handle:horizontal:focus {{
    border-width: 2px;
}}

QSlider::sub-page:horizontal {{
    /* Заполненная часть — светло-серая (раньше была сплошная чёрная), не залив */
    background-color: {COLORS['surface']['tertiary']};
    border: 1px solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* === PROGRESS BAR === */

QProgressBar {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    height: 18px;
    text-align: center;
    color: {COLORS['text']['primary']};
    border-radius: 0;
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

QProgressBar::chunk {{
    background-color: {COLORS['border']['default']};
}}

/* === SCROLL AREA === */

QScrollArea {{
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    background-color: {COLORS['surface']['primary']};
}}

QScrollArea#noBorder {{
    border: none;
}}

QScrollBar:vertical {{
    background-color: {COLORS['surface']['primary']};
    width: 16px;
    border-left: {BORDERS['default']} solid {COLORS['border']['default']};
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['surface']['tertiary']};
    border: 1px solid {COLORS['border']['default']};
    min-height: 20px;
    border-radius: 0;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['border']['muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
    height: 16px;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background-color: {COLORS['surface']['secondary']};
}}

QScrollBar:horizontal {{
    background-color: {COLORS['surface']['primary']};
    height: 16px;
    border-top: {BORDERS['default']} solid {COLORS['border']['default']};
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS['surface']['tertiary']};
    border: 1px solid {COLORS['border']['default']};
    min-width: 20px;
    border-radius: 0;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['border']['muted']};
}}

/* === FRAMES & CARDS - SYSTEM 7 SHARP CORNERS === */

QFrame {{
    background-color: transparent;
}}

/* Window frame - solid black border */
QFrame#windowFrame {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* Basic card - System 7 sharp corners */
QFrame#card, QFrame#cardFrame {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* Elevated card - thicker border, sharp corners */
QFrame#cardElevated, QFrame#selectedCard {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* Interactive card */
QFrame#cardInteractive {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

QFrame#cardInteractive:hover {{
    background-color: {COLORS['surface']['secondary']};
}}

/* Info box - gray background */
QFrame#infoBox {{
    background-color: {COLORS['surface']['tertiary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* Surface card - subtle background */
QFrame#surfaceCard {{
    background-color: {COLORS['surface']['secondary']};
    border: {BORDERS['thin']} solid {COLORS['border']['subtle']};
    border-radius: 0;
}}

/* Settings card with title */
QFrame#settingsCard {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* === SYSTEM 7 3D EFFECTS === */

/* Raised effect - light top/left, dark bottom/right */
QFrame#raised {{
    background-color: {COLORS['surface']['primary']};
    border-top: 1px solid {COLORS['surface']['primary']};
    border-left: 1px solid {COLORS['surface']['primary']};
    border-bottom: 1px solid {COLORS['border']['default']};
    border-right: 1px solid {COLORS['border']['default']};
}}

/* Inset effect - dark top/left, light bottom/right */
QFrame#inset {{
    background-color: {COLORS['surface']['primary']};
    border-top: 1px solid {COLORS['border']['default']};
    border-left: 1px solid {COLORS['border']['default']};
    border-bottom: 1px solid {COLORS['surface']['primary']};
    border-right: 1px solid {COLORS['surface']['primary']};
}}

/* Horizontal line separator */
QFrame#hline {{
    background-color: {COLORS['border']['default']};
    max-height: 1px;
    min-height: 1px;
}}

/* Subtle horizontal line */
QFrame#hlineSubtle {{
    background-color: {COLORS['border']['subtle']};
    max-height: 1px;
    min-height: 1px;
}}

/* Vertical line separator */
QFrame#vline {{
    background-color: {COLORS['border']['default']};
    max-width: 1px;
    min-width: 1px;
}}

/* Title bar with stripes pattern */
QFrame#titleBar {{
    background-color: {COLORS['surface']['primary']};
    background-image: url({get_icon_path("stripes.png")});
    background-repeat: repeat;
    border-bottom: {BORDERS['default']} solid {COLORS['border']['default']};
    min-height: 22px;
    max-height: 22px;
}}

/* === SYSTEM 7 TITLE BAR === */

QFrame#system7TitleBar {{
    background-color: {COLORS['surface']['primary']};
    background-image: url({get_icon_path("stripes.png")});
    background-repeat: repeat-x;
    border: {SYSTEM7['checkbox']['border']}px solid {COLORS['border']['default']};
    border-bottom: {BORDERS['thick']} solid {COLORS['border']['default']};
    min-height: {SYSTEM7['title_bar']['height']}px;
    max-height: {SYSTEM7['title_bar']['height']}px;
}}

QLabel#system7TitleLabel {{
    background: {COLORS['surface']['primary']};
    padding: 0 {SPACING['sm']}px;
    font-weight: bold;
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

QPushButton#system7CloseButton {{
    background-color: {COLORS['surface']['primary']};
    border: {SYSTEM7['window_control']['border']}px solid {COLORS['border']['default']};
    border-radius: 0;
    min-width: {SYSTEM7['window_control']['size']}px;
    max-width: {SYSTEM7['window_control']['size']}px;
    min-height: {SYSTEM7['window_control']['size']}px;
    max-height: {SYSTEM7['window_control']['size']}px;
    padding: 0;
}}

QPushButton#system7CloseButton:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QPushButton#system7CloseButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
}}

/* System 7 Window frame */
QFrame#system7Window {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    border-radius: 0;
}}

QFrame#system7WindowContent {{
    background-color: {COLORS['surface']['primary']};
    border: none;
}}

/* === FRAMELESS APP WINDOW (главное окно) === */

QWidget#appWindowFrame {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QFrame#appTitleBar {{
    background-color: {COLORS['surface']['primary']};
    background-image: url({get_icon_path("stripes.png")});
    background-repeat: repeat-x;
    border: none;
    border-bottom: {BORDERS['default']} solid {COLORS['border']['default']};
}}

QPushButton#winMin, QPushButton#winMax, QPushButton#winClose {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    border-radius: 0;
    font-weight: bold;
    font-size: 11px;
    padding: 0;
}}

QPushButton#winMin:hover, QPushButton#winMax:hover, QPushButton#winClose:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QPushButton#winMin:pressed, QPushButton#winMax:pressed, QPushButton#winClose:pressed {{
    background-color: {COLORS['text']['primary']};
    color: {COLORS['text']['inverse']};
}}

/* System 7 Modal frame - double border effect */
QFrame#system7ModalOuter {{
    background-color: {COLORS['surface']['primary']};
    border: {SYSTEM7['modal']['outer_border']}px solid {COLORS['border']['default']};
    border-radius: 0;
}}

QFrame#system7ModalInner {{
    background-color: {COLORS['surface']['primary']};
    border: {SYSTEM7['modal']['inner_border']}px solid {COLORS['border']['default']};
    border-radius: 0;
}}

/* === GROUP BOX === */

QGroupBox {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    margin-top: {SPACING['md']}px;
    padding-top: {SPACING['sm']}px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 {SPACING['sm']}px;
    background-color: {COLORS['surface']['primary']};
}}

/* === SPLITTER === */

QSplitter::handle {{
    background-color: {COLORS['border']['default']};
    width: 1px;
}}

QSplitter::handle:hover {{
    background-color: {COLORS['border']['subtle']};
    width: 3px;
}}

/* === MENU === */

QMenu {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QMenu::item {{
    padding: {SPACING['xs']}px {SPACING['xl']}px {SPACING['xs']}px {SPACING['lg']}px;
}}

QMenu::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QMenu::separator {{
    height: 1px;
    background-color: {COLORS['border']['default']};
    margin: {SPACING['xs']}px 0;
}}

QMenu::indicator {{
    width: 12px;
    height: 12px;
    margin-left: {SPACING['xs']}px;
}}

/* === MENU BAR === */

QMenuBar {{
    background-color: {COLORS['surface']['primary']};
    border-bottom: {BORDERS['default']} solid {COLORS['border']['default']};
}}

QMenuBar::item {{
    padding: {SPACING['xs']}px {SPACING['md']}px;
    background: transparent;
}}

QMenuBar::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

/* === TOOLTIP === */

QToolTip {{
    background-color: {COLORS['surface']['primary']};
    color: {COLORS['text']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

/* === JOURNAL === */

QFrame#journalEntry {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thin']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    margin: 2px 0;
}}

QLabel#journalTime {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    font-weight: bold;
}}

QLabel#journalText {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

/* === STATUS INDICATORS - B&W ONLY === */

QLabel[status="success"] {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}

QLabel[status="error"] {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}

QLabel[status="pending"] {{
    color: {COLORS['text']['muted']};
}}

QLabel[status="progress"] {{
    color: {COLORS['text']['primary']};
}}

QLabel[status="warning"] {{
    color: {COLORS['text']['primary']};
    font-style: italic;
}}

/* File queue item status - B&W */
QLabel#fileStatus {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

QLabel#fileStatusPending {{
    color: {COLORS['text']['muted']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

QLabel#fileStatusProgress {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    font-weight: bold;
}}

QLabel#fileStatusComplete {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    font-weight: bold;
}}

QLabel#fileStatusError {{
    color: {COLORS['text']['primary']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    font-weight: bold;
}}

/* License status - B&W */
QLabel#licenseActive {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}

QLabel#licenseTrial {{
    color: {COLORS['text']['primary']};
}}

QLabel#licenseExpired {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}

/* === SPIN BOX === */

QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: 2px {SPACING['xs']}px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
    width: 16px;
}}

QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

QSpinBox::up-button:pressed, QSpinBox::down-button:pressed,
QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background-color: {COLORS['interactive']['pressed']};
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 6px solid {COLORS['border']['default']};
    width: 0;
    height: 0;
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {COLORS['border']['default']};
    width: 0;
    height: 0;
}}

/* === LIST WIDGET === */

QListWidget {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    outline: none;
}}

QListWidget::item {{
    padding: {SPACING['xs']}px;
}}

QListWidget::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QListWidget::item:hover:!selected {{
    background-color: {COLORS['interactive']['hover']};
}}

QListWidget::item:focus {{
    border: 1px solid {COLORS['border']['default']};
}}

/* === TABLE WIDGET === */

QTableWidget, QTableView {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    gridline-color: {COLORS['border']['default']};
    outline: none;
}}

QTableWidget::item, QTableView::item {{
    padding: {SPACING['xs']}px;
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QHeaderView::section {{
    background-color: {COLORS['surface']['tertiary']};
    border: 1px solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    font-weight: bold;
}}

QHeaderView::section:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

/* === TREE WIDGET === */

QTreeWidget, QTreeView {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    outline: none;
}}

QTreeWidget::item, QTreeView::item {{
    padding: 2px;
}}

QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QTreeWidget::branch {{
    background: transparent;
}}

/* === TOOLBAR === */

QToolBar {{
    background-color: {COLORS['surface']['primary']};
    border-bottom: {BORDERS['default']} solid {COLORS['border']['default']};
    spacing: {SPACING['xs']}px;
    padding: 2px;
}}

QToolBar::separator {{
    width: 1px;
    background-color: {COLORS['border']['default']};
    margin: {SPACING['xs']}px 2px;
}}

QToolButton {{
    background-color: transparent;
    border: {BORDERS['default']} solid transparent;
    border-radius: {RADII['sm']};
    padding: {SPACING['xs']}px;
}}

QToolButton:hover {{
    background-color: {COLORS['interactive']['hover']};
    border-color: {COLORS['border']['default']};
}}

QToolButton:pressed {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

QToolButton:checked {{
    background-color: {COLORS['surface']['tertiary']};
    border-color: {COLORS['border']['default']};
}}

QToolButton:focus {{
    border-color: {COLORS['border']['default']};
}}

/* === STATUS BAR === */

QStatusBar {{
    background-color: {COLORS['surface']['primary']};
    border-top: {BORDERS['default']} solid {COLORS['border']['default']};
    font-size: {TYPOGRAPHY['caption']['size']}px;
}}

QStatusBar::item {{
    border: none;
}}

/* === DIALOG === */

QDialog {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

/* Modal dialog - double effect using padding */
QDialog#modalDialog {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['accent']} solid {COLORS['border']['default']};
}}

/* === EMPTY STATE === */

QLabel#emptyState {{
    color: {COLORS['text']['muted']};
    font-size: {TYPOGRAPHY['subtitle']['size']}px;
    padding: {SPACING['xxl']}px;
}}

QLabel#emptyStateHint {{
    color: {COLORS['text']['muted']};
    font-size: {TYPOGRAPHY['body']['size']}px;
}}

/* === KEYBOARD SHORTCUT HINT === */

QLabel#shortcutHint {{
    color: {COLORS['text']['muted']};
    font-size: {TYPOGRAPHY['small']['size']}px;
    font-family: {FONT_FAMILY_MONO};
    background-color: {COLORS['surface']['secondary']};
    padding: 2px {SPACING['xs']}px;
    border: 1px solid {COLORS['border']['subtle']};
    border-radius: 2px;
}}

/* === ADDITIONAL TYPOGRAPHY VARIANTS === */

/* Body bold - 12px bold */
QLabel#bodyBold {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    background: transparent;
}}

/* Body - standard 12px */
QLabel#body {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    color: {COLORS['text']['primary']};
    background: transparent;
}}

/* Caption italic */
QLabel#captionItalic {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['secondary']};
    font-style: italic;
    background: transparent;
}}

/* Muted italic */
QLabel#mutedItalic {{
    color: {COLORS['text']['muted']};
    font-style: italic;
    background: transparent;
}}

/* Small bold - 10px bold */
QLabel#smallBold {{
    font-size: {TYPOGRAPHY['small']['size']}px;
    font-weight: bold;
    color: {COLORS['text']['primary']};
    background: transparent;
}}

/* Tiny muted - 9px muted (for dates, etc) */
QLabel#tinyMuted {{
    font-size: 9px;
    color: {COLORS['text']['muted']};
    background: transparent;
}}

/* Tiny secondary */
QLabel#tinySecondary {{
    font-size: 9px;
    color: {COLORS['text']['secondary']};
    background: transparent;
}}

/* Title bar label - white text for title bars */
QLabel#titleBarLabel {{
    color: {COLORS['text']['inverse']};
    font-weight: bold;
    font-size: {TYPOGRAPHY['small']['size']}px;
    background: transparent;
}}

/* === SCROLL AREAS === */

QScrollArea#scrollArea {{
    background-color: {COLORS['surface']['primary']};
    border: none;
}}

QWidget#scrollContent {{
    background-color: {COLORS['surface']['primary']};
}}

/* === CONTROL BAR === */

QFrame#controlBar {{
    background-color: {COLORS['surface']['primary']};
    border-top: 1px solid {COLORS['border']['subtle']};
}}

/* === MESSAGE BUBBLES === */

QFrame#userBubble {{
    background-color: {COLORS['surface']['tertiary']};
    border: 1px solid {COLORS['border']['default']};
}}

QFrame#assistantBubble {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
}}

/* === SMALL BUTTON === */

QPushButton#smallButton {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px {SPACING['sm']}px;
    font-size: {TYPOGRAPHY['small']['size']}px;
}}

QPushButton#smallButton:hover {{
    background-color: {COLORS['interactive']['hover']};
}}

/* === ICON LABELS === */

QLabel#iconLabel {{
    border: none;
    background: transparent;
}}

/* === CODE EDITOR === */

QTextEdit#codeEditor {{
    font-family: {FONT_FAMILY_MONO};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    border: 1px solid {COLORS['border']['subtle']};
    background-color: {COLORS['surface']['primary']};
}}

QTextEdit#codeEditor:focus {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

/* === MONO INPUT === */

QLineEdit#monoInput {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px {SPACING['sm']}px;
    background-color: {COLORS['surface']['primary']};
    font-family: {FONT_FAMILY_MONO};
}}

/* === WIDE COMBOBOX === */

QComboBox#wideCombo {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px {SPACING['sm']}px;
    background-color: {COLORS['surface']['primary']};
    min-width: 120px;
}}

QComboBox#wideCombo::drop-down {{
    border: none;
    border-left: {BORDERS['thick']} solid {COLORS['border']['default']};
    width: 20px;
}}

QComboBox#wideCombo QAbstractItemView {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    background-color: {COLORS['surface']['primary']};
    selection-background-color: {COLORS['interactive']['pressed']};
    selection-color: {COLORS['interactive']['pressed_text']};
}}

/* === COMPACT COMBOBOX === */

QComboBox#compactCombo {{
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    padding: 2px {SPACING['xs']}px;
    background-color: {COLORS['surface']['primary']};
    min-width: 80px;
}}

/* === THINKING PANEL (Classic Mac OS style) === */

QFrame#thinkingFrame {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
}}

QFrame#thinkingHeader {{
    background-color: {COLORS['surface']['primary']};
    background-image: url({get_icon_path("stripes.png")});
    background-repeat: repeat-x;
    border: none;
    border-bottom: {BORDERS['default']} solid {COLORS['border']['default']};
}}

QLabel#thinkingTitle {{
    color: {COLORS['text']['primary']};
    font-weight: bold;
    font-size: {TYPOGRAPHY['caption']['size']}px;
    background: {COLORS['surface']['primary']};
    padding: 0 {SPACING['sm']}px;
}}

QPushButton#windowClose {{
    background-color: {COLORS['surface']['primary']};
    border: 1px solid {COLORS['border']['default']};
}}

QPushButton#windowClose:hover {{
    background-color: {COLORS['surface']['tertiary']};
}}

QTextEdit#thinkingOutput {{
    background-color: {COLORS['surface']['primary']};
    color: {COLORS['text']['primary']};
    border: none;
    border-top: 1px solid {COLORS['border']['muted']};
    font-family: {FONT_FAMILY_MONO};
    font-size: {TYPOGRAPHY['caption']['size']}px;
    padding: {SPACING['sm']}px;
}}

/* === WHITE BACKGROUND === */

QWidget#whiteBackground {{
    background-color: {COLORS['surface']['primary']};
}}

/* === BOLD CHECKBOX === */

QCheckBox#boldCheckbox {{
    font-weight: bold;
}}

/* === PLACEHOLDER LABEL === */

QLabel#placeholder {{
    color: {COLORS['text']['muted']};
    padding: {SPACING['xl']}px;
}}

/* === SYSTEM PROMPT EDIT === */

QTextEdit#systemPromptEdit {{
    background-color: {COLORS['surface']['primary']};
    border: {BORDERS['default']} solid {COLORS['border']['default']};
    padding: {SPACING['xs']}px;
    color: {COLORS['text']['primary']};
}}

QTextEdit#systemPromptEdit:focus {{
    background-color: {COLORS['interactive']['pressed']};
    color: {COLORS['interactive']['pressed_text']};
}}

/* === UPDATE STATUS LABELS === */

QLabel#updateStatusNeutral {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['primary']};
}}

QLabel#updateStatusSuccess {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}

QLabel#updateStatusError {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['primary']};
    font-weight: bold;
}}
"""

# =============================================================================
# ADDITIONAL STYLESHEETS
# =============================================================================

# Wizard-specific style additions
WIZARD_STYLESHEET = f"""
/* ===== WIZARD SPECIFIC STYLES ===== */

QWizard {{
    background-color: {COLORS['surface']['primary']};
}}

QWizardPage {{
    background-color: {COLORS['surface']['primary']};
}}

/* Wizard navigation buttons */
QWizard > QWidget > QPushButton {{
    min-width: 90px;
}}

/* Wizard title */
QWizard QLabel#wizardTitle {{
    font-size: {TYPOGRAPHY['title']['size']}px;
    font-weight: bold;
    padding-bottom: {SPACING['md']}px;
}}

/* Wizard subtitle */
QWizard QLabel#wizardSubtitle {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    color: {COLORS['text']['secondary']};
    padding-bottom: {SPACING['lg']}px;
}}
"""

# Overlay style
OVERLAY_STYLESHEET = f"""
/* Recording/Transcribing overlay */
QWidget#overlayWidget {{
    background-color: transparent;
}}

/* Recording indicator */
QWidget#recordingOverlay {{
    background-color: {COLORS['semantic']['recording_bg']};
    border: 2px solid {COLORS['semantic']['recording']};
}}
"""

# Dialog-specific styles
DIALOG_STYLESHEET = f"""
/* License dialogs */
QDialog#licenseDialog {{
    background-color: {COLORS['surface']['primary']};
}}

QDialog#licenseDialog QLabel#title {{
    font-size: {TYPOGRAPHY['title']['size']}px;
    font-weight: bold;
}}

QDialog#licenseDialog QLabel#status {{
    font-size: {TYPOGRAPHY['body']['size']}px;
    padding: {SPACING['sm']}px {SPACING['md']}px;
    border: {BORDERS['thick']} solid {COLORS['border']['default']};
    background-color: {COLORS['surface']['tertiary']};
}}

/* About dialog */
QDialog#aboutDialog QLabel#version {{
    font-size: {TYPOGRAPHY['caption']['size']}px;
    color: {COLORS['text']['muted']};
}}
"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_full_stylesheet() -> str:
    """Get the complete stylesheet for the application."""
    return STYLESHEET + WIZARD_STYLESHEET + OVERLAY_STYLESHEET + DIALOG_STYLESHEET


def get_card_style(variant: str = "default") -> str:
    """Get inline style for card variants.

    Variants: default, elevated, interactive, surface, info
    """
    styles = {
        "default": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['default']} solid {COLORS['border']['default']};",
        "elevated": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['thick']} solid {COLORS['border']['default']};",
        "interactive": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['default']} solid {COLORS['border']['default']};",
        "surface": f"background-color: {COLORS['surface']['secondary']}; border: {BORDERS['thin']} solid {COLORS['border']['subtle']};",
        "info": f"background-color: {COLORS['surface']['tertiary']}; border: {BORDERS['default']} solid {COLORS['border']['default']};",
    }
    return styles.get(variant, styles["default"])


def get_button_style(variant: str = "default") -> str:
    """Get inline style for button variants.

    Variants: default, primary, secondary, ghost, danger
    """
    styles = {
        "default": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['default']} solid {COLORS['border']['default']}; border-radius: {RADII['md']};",
        "primary": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['accent']} solid {COLORS['border']['default']}; border-radius: {RADII['lg']}; font-weight: bold;",
        "secondary": f"background-color: {COLORS['surface']['secondary']}; border: {BORDERS['thin']} solid {COLORS['border']['subtle']}; border-radius: {RADII['md']};",
        "ghost": f"background: transparent; border: none;",
        "danger": f"background-color: {COLORS['surface']['primary']}; border: {BORDERS['thick']} solid {COLORS['border']['default']}; border-radius: {RADII['md']}; font-weight: bold;",
    }
    return styles.get(variant, styles["default"])
