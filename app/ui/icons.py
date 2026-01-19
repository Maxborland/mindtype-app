"""
Иконки для UI MindType.

Генерация пиксельных иконок в стиле Classic Mac OS.
"""

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor


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

