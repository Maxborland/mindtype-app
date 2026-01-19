"""
Стили для UI MindType.

Classic Mac OS System 7 Style для PyQt6.
"""

# Classic Mac OS System 7 Style
STYLESHEET = """
/* ===== CLASSIC MAC OS SYSTEM 7 STYLE ===== */

/* Основной фон и шрифты */
QMainWindow, QWidget {
    background-color: #ffffff;
    color: #000000;
    font-family: "MS Sans Serif", "Geneva", "Arial", sans-serif;
    font-size: 12px;
}

/* Заголовки панелей */
QLabel#panelTitle {
    font-size: 14px;
    font-weight: bold;
    color: #000000;
    padding: 4px 0;
}

/* Обычные метки */
QLabel {
    color: #000000;
    background: transparent;
}

/* Разделитель */
QSplitter::handle {
    background-color: #000000;
    width: 1px;
}

/* Вкладки - классический стиль */
QTabWidget::pane {
    border: 2px solid #000000;
    background-color: #ffffff;
    margin-top: -1px;
}

QTabBar::tab {
    background-color: #dddddd;
    color: #000000;
    padding: 6px 16px;
    border: 1px solid #000000;
    border-bottom: none;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom: 1px solid #ffffff;
    margin-bottom: -1px;
}

QTabBar::tab:!selected {
    margin-top: 2px;
}

/* ComboBox - классический выпадающий список */
QComboBox {
    background-color: #ffffff;
    border: 2px solid #000000;
    border-top-color: #000000;
    border-left-color: #000000;
    border-right-color: #808080;
    border-bottom-color: #808080;
    padding: 4px 8px;
    color: #000000;
    min-height: 18px;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
    background-color: #dddddd;
    border-left: 1px solid #000000;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #000000;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 2px solid #000000;
    selection-background-color: #000000;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 4px 8px;
    border: none;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #000000;
    color: #ffffff;
}

/* LineEdit - классическое текстовое поле */
QLineEdit {
    background-color: #ffffff;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    padding: 4px 6px;
    color: #000000;
}

QLineEdit:focus {
    border-color: #000000;
}

QLineEdit:read-only {
    background-color: #dddddd;
}

/* Slider - классический ползунок */
QSlider::groove:horizontal {
    background-color: #dddddd;
    border: 1px solid #000000;
    height: 8px;
}

QSlider::handle:horizontal {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    width: 12px;
    height: 18px;
    margin: -6px 0;
}

QSlider::sub-page:horizontal {
    background-color: #000000;
}

/* Кнопки - классический 3D стиль */
QPushButton {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    padding: 4px 12px;
    color: #000000;
    min-height: 18px;
}

QPushButton:hover {
    background-color: #eeeeee;
}

QPushButton:pressed {
    background-color: #cccccc;
    border-top-color: #000000;
    border-left-color: #000000;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
}

QPushButton:disabled {
    background-color: #dddddd;
    color: #808080;
}

QPushButton#downloadButton {
    background-color: #dddddd;
    font-weight: bold;
}

/* CheckBox - классический чекбокс */
QCheckBox {
    spacing: 8px;
    color: #000000;
}

QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    background-color: #ffffff;
}

QCheckBox::indicator:checked {
    background-color: #000000;
}

/* ProgressBar - классический прогресс-бар */
QProgressBar {
    background-color: #ffffff;
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    height: 16px;
    text-align: center;
    color: #000000;
}

QProgressBar::chunk {
    background-color: #000000;
}

/* ScrollArea и ScrollBar */
QScrollArea {
    border: 2px solid;
    border-top-color: #808080;
    border-left-color: #808080;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    background-color: #ffffff;
}

QScrollBar:vertical {
    background-color: #dddddd;
    width: 16px;
    border: 1px solid #000000;
}

QScrollBar::handle:vertical {
    background-color: #dddddd;
    border: 2px solid;
    border-top-color: #ffffff;
    border-left-color: #ffffff;
    border-right-color: #000000;
    border-bottom-color: #000000;
    min-height: 20px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    background-color: #dddddd;
    border: 1px solid #000000;
    height: 16px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background-color: #dddddd;
}

/* Журнал */
QFrame#journalEntry {
    background-color: #ffffff;
    border: 1px solid #000000;
    padding: 4px;
    margin: 2px 0;
}

QLabel#journalTime {
    color: #000000;
    font-size: 11px;
    font-weight: bold;
}

QLabel#journalText {
    color: #000000;
    font-size: 11px;
}

/* Предупреждения */
QLabel#warning {
    color: #000000;
    font-size: 11px;
    font-style: italic;
}

/* Группы (Frame) */
QFrame {
    background-color: transparent;
}

QFrame#settingsCard {
    background-color: #ffffff;
    border: 1px solid #000000;
}
"""

