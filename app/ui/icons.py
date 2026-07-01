"""
Иконки для UI MindType.

Генерация пиксельных иконок в стиле Classic Mac OS.
"""

from pathlib import Path

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen


# ===== B&W STATUS ICONS (Unicode) =====
# These are text-based status indicators for System 7 aesthetic

# ASCII-символы: пиксельный шрифт Pixellari не содержит ✓✗○◐▸ (рендерятся .notdef-box),
# поэтому используем безопасную латиницу/пунктуацию (как в ранних версиях — «[OK]»).
STATUS_OK = "OK"          # success
STATUS_ERROR = "X"        # error
STATUS_PENDING = "..."    # pending
STATUS_PROGRESS = ">"     # in-progress
STATUS_WARNING = "!"      # warning

# Status with brackets (Classic Mac style)
STATUS_OK_BRACKET = "[OK]"
STATUS_ERROR_BRACKET = "[X]"
STATUS_PENDING_BRACKET = "[...]"
STATUS_PROGRESS_BRACKET = "[>]"
STATUS_WARNING_BRACKET = "[!]"


# Единый маппинг статусов к иконкам (plain, bracket)
_STATUS_MAPPING = {
    'success': (STATUS_OK, STATUS_OK_BRACKET),
    'completed': (STATUS_OK, STATUS_OK_BRACKET),
    'ok': (STATUS_OK, STATUS_OK_BRACKET),
    'error': (STATUS_ERROR, STATUS_ERROR_BRACKET),
    'failed': (STATUS_ERROR, STATUS_ERROR_BRACKET),
    'pending': (STATUS_PENDING, STATUS_PENDING_BRACKET),
    'waiting': (STATUS_PENDING, STATUS_PENDING_BRACKET),
    'progress': (STATUS_PROGRESS, STATUS_PROGRESS_BRACKET),
    'processing': (STATUS_PROGRESS, STATUS_PROGRESS_BRACKET),
    'warning': (STATUS_WARNING, STATUS_WARNING_BRACKET),
    'trial': (STATUS_WARNING, STATUS_WARNING_BRACKET),
}


def get_status_icon(status: str, bracket: bool = False) -> str:
    """Get B&W status icon for a given status.

    Args:
        status: One of 'success', 'error', 'pending', 'progress', 'warning'
        bracket: If True, return icon in brackets

    Returns:
        Unicode character/string for the status
    """
    icons = _STATUS_MAPPING.get(status.lower(), (STATUS_PENDING, STATUS_PENDING_BRACKET))
    return icons[1] if bracket else icons[0]


def get_status_bracket(status: str) -> str:
    """Get B&W status icon in brackets for a given status.

    Args:
        status: One of 'success', 'error', 'pending', 'progress', 'warning'

    Returns:
        Status indicator in brackets
    """
    return get_status_icon(status, bracket=True)


# =============================================================================
# SYSTEM 7 TITLE BAR STRIPES
# =============================================================================

def create_stripes_pixmap(width: int = 4, height: int = 4) -> QPixmap:
    """Create System 7 title bar stripes pattern.

    Creates a tileable pattern with horizontal black stripes.
    Default is 4x4: 2px black stripe, 2px white gap.
    """
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(255, 255, 255))

    painter = QPainter(pixmap)
    painter.fillRect(0, 0, width, 2, QColor(0, 0, 0))
    painter.end()

    return pixmap


def save_stripes_pattern(filename: str = "stripes.png") -> str:
    """Save stripes pattern to file in icons directory.

    Returns the path to the saved file.
    """
    pixmap = create_stripes_pixmap()
    path = Path(__file__).parent / "icons" / filename
    pixmap.save(str(path))
    return str(path)


def create_stripes_pixmap_white(width: int = 4, height: int = 4) -> QPixmap:
    """Create System 7 title bar stripes pattern with white stripes on transparent.

    For use on dark backgrounds.
    """
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.fillRect(0, 0, width, 2, QColor(255, 255, 255))
    painter.end()

    return pixmap


def save_stripes_pattern_white(filename: str = "stripes_white.png") -> str:
    """Save white stripes pattern to file in icons directory.

    Returns the path to the saved file.
    """
    pixmap = create_stripes_pixmap_white()
    path = Path(__file__).parent / "icons" / filename
    pixmap.save(str(path))
    return str(path)


# =============================================================================
# PIXEL ART STATUS ICONS
# =============================================================================

def create_checkmark_pixmap(size: int = 12) -> QPixmap:
    """Create a pixel-art checkmark in System 7 style."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    pen = QPen(QColor(0, 0, 0))
    pen.setWidth(2)
    painter.setPen(pen)

    # Draw checkmark: small tick at bottom left, longer line going up-right
    s = size
    painter.drawLine(int(s * 0.15), int(s * 0.5), int(s * 0.35), int(s * 0.75))
    painter.drawLine(int(s * 0.35), int(s * 0.75), int(s * 0.85), int(s * 0.2))

    painter.end()
    return pixmap


def create_x_mark_pixmap(size: int = 12) -> QPixmap:
    """Create a pixel-art X mark in System 7 style."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    pen = QPen(QColor(0, 0, 0))
    pen.setWidth(2)
    painter.setPen(pen)

    # Draw X
    margin = int(size * 0.2)
    painter.drawLine(margin, margin, size - margin, size - margin)
    painter.drawLine(size - margin, margin, margin, size - margin)

    painter.end()
    return pixmap


def create_status_icon(status: str, size: int = 16) -> QIcon:
    """Create a QIcon for a given status.

    Args:
        status: One of 'success', 'error', 'pending', 'progress'
        size: Icon size in pixels

    Returns:
        QIcon with the status indicator
    """
    if status in ('success', 'completed', 'ok'):
        return QIcon(create_checkmark_pixmap(size))
    elif status in ('error', 'failed'):
        return QIcon(create_x_mark_pixmap(size))
    else:
        # For other statuses, return empty icon (use text instead)
        return QIcon()


# =============================================================================
# PIXEL ART ICONS - Classic Mac OS Style
# =============================================================================

def create_mic_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка микрофона."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    # Scale factor
    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Mic head (rounded top)
    px(6, 1, 4, 1)
    px(5, 2, 6, 1)
    px(5, 3, 6, 6)

    # Mic body lines
    px(5, 4, 6, 1)
    px(5, 6, 6, 1)

    # Bottom curve
    px(6, 9, 4, 1)

    # Stand arc
    px(4, 7, 1, 3)
    px(11, 7, 1, 3)
    px(5, 10, 1, 1)
    px(10, 10, 1, 1)
    px(6, 11, 4, 1)

    # Pole
    px(7, 11, 2, 3)

    # Base
    px(5, 14, 6, 1)

    painter.end()
    return QIcon(pixmap)


def create_settings_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка настроек (шестерёнка)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Gear teeth (8 teeth around)
    # Top
    px(7, 0, 2, 2)
    # Top-right
    px(11, 2, 2, 2)
    # Right
    px(14, 7, 2, 2)
    # Bottom-right
    px(11, 12, 2, 2)
    # Bottom
    px(7, 14, 2, 2)
    # Bottom-left
    px(3, 12, 2, 2)
    # Left
    px(0, 7, 2, 2)
    # Top-left
    px(3, 2, 2, 2)

    # Center ring (outer)
    px(5, 3, 6, 1)
    px(4, 4, 1, 1)
    px(11, 4, 1, 1)
    px(3, 5, 1, 6)
    px(12, 5, 1, 6)
    px(4, 11, 1, 1)
    px(11, 11, 1, 1)
    px(5, 12, 6, 1)

    # Center ring (inner - hole)
    px(6, 6, 4, 1)
    px(5, 7, 1, 2)
    px(10, 7, 1, 2)
    px(6, 9, 4, 1)

    painter.end()
    return QIcon(pixmap)


def create_folder_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка папки."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)
    white = QColor(255, 255, 255)

    s = size / 16

    def px(x, y, w=1, h=1, color=black):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), color)

    # Tab
    px(1, 2, 5, 2)

    # Main body outline
    px(0, 4, 16, 1)  # top
    px(0, 14, 16, 1)  # bottom
    px(0, 4, 1, 11)  # left
    px(15, 4, 1, 11)  # right

    # Fill inside white
    px(1, 5, 14, 9, white)

    # Lines inside (content representation)
    px(2, 7, 10, 1)
    px(2, 10, 7, 1)

    painter.end()
    return QIcon(pixmap)


def create_document_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка документа."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)
    white = QColor(255, 255, 255)

    s = size / 16

    def px(x, y, w=1, h=1, color=black):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), color)

    # Fill white
    px(2, 1, 10, 14, white)

    # Outline
    px(2, 0, 9, 1)  # top
    px(2, 15, 12, 1)  # bottom
    px(1, 1, 1, 14)  # left
    px(13, 4, 1, 11)  # right

    # Folded corner
    px(11, 0, 1, 1)
    px(12, 1, 1, 1)
    px(13, 2, 1, 1)
    px(11, 1, 1, 3)  # fold line

    # Text lines
    px(3, 5, 8, 1)
    px(3, 7, 8, 1)
    px(3, 9, 6, 1)
    px(3, 11, 8, 1)

    painter.end()
    return QIcon(pixmap)


def create_play_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка play (треугольник)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Triangle pointing right
    px(4, 2, 2, 12)
    px(6, 3, 2, 10)
    px(8, 4, 2, 8)
    px(10, 5, 2, 6)
    px(12, 6, 2, 4)

    painter.end()
    return QIcon(pixmap)


def create_stop_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка stop (квадрат)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Square
    px(3, 3, 10, 10)

    painter.end()
    return QIcon(pixmap)


def create_pause_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка pause (две полоски)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Two vertical bars
    px(4, 2, 3, 12)
    px(9, 2, 3, 12)

    painter.end()
    return QIcon(pixmap)


def create_copy_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка копирования (два документа)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)
    white = QColor(255, 255, 255)

    s = size / 16

    def px(x, y, w=1, h=1, color=black):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), color)

    # Back document
    px(4, 0, 8, 1)
    px(4, 11, 8, 1)
    px(3, 1, 1, 10)
    px(11, 1, 1, 10)
    px(4, 1, 7, 10, white)

    # Front document (offset)
    px(1, 4, 8, 1)
    px(1, 15, 8, 1)
    px(0, 5, 1, 10)
    px(8, 5, 1, 10)
    px(1, 5, 7, 10, white)

    # Lines on front
    px(2, 7, 5, 1)
    px(2, 9, 5, 1)
    px(2, 11, 4, 1)

    painter.end()
    return QIcon(pixmap)


def create_trash_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка корзины."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Lid
    px(5, 1, 6, 1)
    px(3, 2, 10, 1)
    px(7, 0, 2, 1)  # handle

    # Body outline
    px(4, 3, 1, 11)
    px(11, 3, 1, 11)
    px(5, 14, 6, 1)

    # Vertical lines inside
    px(6, 5, 1, 8)
    px(9, 5, 1, 8)

    painter.end()
    return QIcon(pixmap)


def create_refresh_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка обновления (круговая стрелка)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Circle arc (top half)
    px(6, 1, 4, 1)
    px(4, 2, 2, 1)
    px(10, 2, 2, 1)
    px(3, 3, 1, 2)
    px(12, 3, 1, 2)

    # Circle arc (bottom half)
    px(3, 11, 1, 2)
    px(12, 11, 1, 2)
    px(4, 13, 2, 1)
    px(10, 13, 2, 1)
    px(6, 14, 4, 1)

    # Arrow at top
    px(10, 0, 3, 1)
    px(11, 1, 2, 1)
    px(12, 2, 1, 1)

    # Arrow at bottom
    px(3, 13, 3, 1)
    px(3, 12, 2, 1)
    px(3, 11, 1, 1)

    painter.end()
    return QIcon(pixmap)


def create_check_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка галочки."""
    return QIcon(create_checkmark_pixmap(size))


def create_close_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка крестика."""
    return QIcon(create_x_mark_pixmap(size))


def create_arrow_right_icon(size: int = 16) -> QIcon:
    """Пиксельная стрелка вправо."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Arrow pointing right
    px(3, 7, 8, 2)  # shaft
    px(9, 4, 2, 2)  # head top
    px(10, 5, 2, 2)
    px(11, 6, 2, 2)
    px(11, 8, 2, 2)  # head bottom
    px(10, 9, 2, 2)
    px(9, 10, 2, 2)

    painter.end()
    return QIcon(pixmap)


def create_arrow_down_icon(size: int = 16) -> QIcon:
    """Пиксельная стрелка вниз."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Arrow pointing down
    px(7, 3, 2, 8)  # shaft
    px(4, 9, 2, 2)  # head left
    px(5, 10, 2, 2)
    px(6, 11, 2, 2)
    px(8, 11, 2, 2)  # head right
    px(9, 10, 2, 2)
    px(10, 9, 2, 2)

    painter.end()
    return QIcon(pixmap)


def create_info_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка информации (i в круге)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Circle
    px(5, 0, 6, 1)
    px(3, 1, 2, 1)
    px(11, 1, 2, 1)
    px(2, 2, 1, 2)
    px(13, 2, 1, 2)
    px(1, 4, 1, 8)
    px(14, 4, 1, 8)
    px(2, 12, 1, 2)
    px(13, 12, 1, 2)
    px(3, 14, 2, 1)
    px(11, 14, 2, 1)
    px(5, 15, 6, 1)

    # Letter "i"
    px(7, 3, 2, 2)  # dot
    px(7, 6, 2, 6)  # stem

    painter.end()
    return QIcon(pixmap)


def create_warning_icon(size: int = 16) -> QIcon:
    """Пиксельная иконка предупреждения (! в треугольнике)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    black = QColor(0, 0, 0)

    s = size / 16

    def px(x, y, w=1, h=1):
        painter.fillRect(int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s)), black)

    # Triangle
    px(7, 1, 2, 1)
    px(6, 2, 4, 1)
    px(5, 3, 6, 1)
    px(4, 4, 8, 1)
    px(3, 5, 10, 1)
    px(2, 6, 12, 1)
    px(1, 7, 14, 1)
    px(0, 8, 16, 1)

    # Bottom edge
    px(0, 13, 16, 1)
    px(0, 9, 1, 4)
    px(15, 9, 1, 4)
    px(1, 12, 1, 1)
    px(14, 12, 1, 1)

    # Exclamation mark
    px(7, 4, 2, 5)  # line
    px(7, 10, 2, 2)  # dot

    painter.end()
    return QIcon(pixmap)


def create_app_icon(size: int = 64, recording: bool = False) -> QIcon:
    """Создать пиксельную иконку приложения в стиле Classic Mac OS."""
    base = 64  # Базовый размер пиксельной сетки
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))  # Прозрачный фон

    painter = QPainter(pixmap)
    px = size / base  # Размер одного "пикселя"

    black = QColor(255, 60, 60) if recording else QColor(0, 0, 0)
    white = QColor(255, 255, 255)

    def fill(x, y, w, h, color):
        painter.fillRect(int(x * px), int(y * px), max(1, int(w * px)), max(1, int(h * px)), color)

    # Белая заливка внутри рамки
    fill(6, 6, 52, 52, white)

    # Рамка окна
    fill(8, 2, 48, 2, black)   # верх
    fill(8, 60, 48, 2, black)  # низ
    fill(2, 8, 2, 48, black)   # лево
    fill(60, 8, 2, 48, black)  # право
    # Углы
    fill(4, 4, 4, 4, black)
    fill(56, 4, 4, 4, black)
    fill(4, 56, 4, 4, black)
    fill(56, 56, 4, 4, black)

    # Микрофон - верхняя дуга
    fill(18, 10, 2, 2, black)
    fill(20, 8, 8, 2, black)
    fill(28, 10, 2, 2, black)

    # Точки сверху
    fill(20, 12, 2, 2, black)
    fill(23, 11, 2, 2, black)
    fill(26, 12, 2, 2, black)

    # Бока микрофона
    fill(16, 12, 2, 22, black)
    fill(30, 12, 2, 22, black)

    # Горизонтальные линии
    fill(16, 16, 16, 2, black)
    fill(16, 20, 16, 2, black)
    fill(16, 24, 16, 2, black)
    fill(16, 28, 16, 2, black)
    fill(16, 32, 16, 2, black)

    # Нижняя дуга головы
    fill(18, 34, 2, 2, black)
    fill(20, 36, 8, 2, black)
    fill(28, 34, 2, 2, black)

    # Держатель (дуга)
    fill(12, 32, 2, 8, black)
    fill(34, 32, 2, 8, black)
    fill(14, 40, 2, 2, black)
    fill(32, 40, 2, 2, black)
    fill(16, 42, 4, 2, black)
    fill(28, 42, 4, 2, black)
    fill(20, 44, 8, 2, black)

    # Ножка
    fill(22, 44, 4, 6, black)

    # Подставка
    fill(16, 50, 16, 2, black)

    # Звуковые волны
    fill(42, 22, 4, 20, black)
    fill(48, 16, 4, 32, black)
    fill(54, 26, 4, 12, black)

    painter.end()
    return QIcon(pixmap)

