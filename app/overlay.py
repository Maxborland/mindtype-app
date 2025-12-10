"""
Classic Mac OS System 7 style overlay-виджет для отображения состояния записи.
Текстовый индикатор в ретро-стиле.
"""

from enum import Enum, auto
from typing import List, Optional
import math

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen, QBrush, QPixmap, QFont, QMouseEvent
from PyQt6.QtWidgets import QWidget, QApplication, QGraphicsOpacityEffect


class OverlayState(Enum):
    HIDDEN = auto()
    RECORDING = auto()
    PROCESSING = auto()
    SUCCESS = auto()
    ERROR = auto()


class OverlayWidget(QWidget):
    """Classic Mac OS style overlay с текстовым индикатором."""

    # Сигнал отмены транскрипции
    cancelled = pyqtSignal()

    POSITIONS = ["bottom-right", "bottom-left", "top-right", "top-left", "bottom-center", "top-center"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._state = OverlayState.HIDDEN
        self._corner = "bottom-center"
        self._margin = 20
        self._bg_opacity = 255
        self._gain = 3.0

        # Текущий уровень звука (0.0 - 1.0)
        self._current_level = 0.0
        self._target_level = 0.0

        # Для анимации
        self._anim_frame = 0

        # Кэш фона
        self._bg_pixmap: Optional[QPixmap] = None

        # Область кнопки отмены (для клика)
        self._cancel_btn_rect: Optional[QRectF] = None

        # Настройка окна - по умолчанию прозрачен для кликов
        self._base_flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setWindowFlags(self._base_flags | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Размеры: компактный Classic Mac стиль
        self._width = 160
        self._height = 44
        self.setFixedSize(self._width, self._height)

        # Эффект прозрачности для анимации
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Анимация появления/скрытия
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(100)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.Linear)

        # Таймер автоскрытия
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_overlay)

        # Таймер анимации
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._animate)
        self._anim_timer.start(100)  # 10 FPS - ретро частота

        # Инициализация кэша
        self._update_bg_cache()

    # === Настройки ===

    def set_corner(self, corner: str) -> None:
        if corner in self.POSITIONS:
            self._corner = corner
            self._update_position()

    def set_margin(self, margin: int) -> None:
        self._margin = max(0, min(200, margin))
        self._update_position()

    def set_wave_gain(self, gain: float) -> None:
        self._gain = max(1.0, min(10.0, gain))

    def set_bg_opacity(self, opacity: int) -> None:
        self._bg_opacity = max(0, min(255, opacity))
        self._update_bg_cache()
        self.update()

    def get_position(self) -> str:
        return self._corner

    def get_margin(self) -> int:
        return self._margin

    def get_wave_gain(self) -> float:
        return self._gain

    def get_bg_opacity(self) -> int:
        return self._bg_opacity

    # === Позиционирование ===

    def _update_position(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return

        geometry = screen.availableGeometry()

        if "center" in self._corner:
            x = geometry.left() + (geometry.width() - self._width) // 2
        elif "right" in self._corner:
            x = geometry.right() - self._width - self._margin
        else:
            x = geometry.left() + self._margin

        if "bottom" in self._corner:
            y = geometry.bottom() - self._height - self._margin
        else:
            y = geometry.top() + self._margin

        self.move(x, y)

    def resizeEvent(self, event) -> None:
        self._update_bg_cache()
        super().resizeEvent(event)

    def _update_bg_cache(self) -> None:
        """Пересоздать кэш фона в стиле Classic Mac OS."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return

        self._bg_pixmap = QPixmap(w, h)
        self._bg_pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(self._bg_pixmap)

        # Тень
        painter.fillRect(QRectF(4, 4, w - 4, h - 4), QColor(0, 0, 0, 80))

        # Белый фон
        painter.fillRect(QRectF(0, 0, w - 4, h - 4), QColor(255, 255, 255))

        # Чёрная рамка
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(1, 1, w - 6, h - 6))

        painter.end()

    # === Состояния ===

    def show_recording(self) -> None:
        self._hide_timer.stop()
        self._state = OverlayState.RECORDING
        self._levels = [0.0] * 16
        self._target_levels = [0.0] * 16
        self._update_position()
        self._show_animated()

    def show_processing(self) -> None:
        self._hide_timer.stop()
        self._state = OverlayState.PROCESSING
        self._pulse_phase = 0.0
        # Делаем окно кликабельным во время обработки
        self.setWindowFlags(self._base_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.show()  # Нужно показать снова после изменения флагов
        self.update()

    def show_success(self, auto_hide_ms: int = 1000) -> None:
        self._state = OverlayState.SUCCESS
        self._flash_alpha = 1.0
        self.update()
        if auto_hide_ms > 0:
            self._hide_timer.start(auto_hide_ms)

    def show_error(self, message: str = "Ошибка", auto_hide_ms: int = 1200) -> None:
        self._state = OverlayState.ERROR
        self._flash_alpha = 1.0
        self.update()
        if auto_hide_ms > 0:
            self._hide_timer.start(auto_hide_ms)

    def hide_overlay(self) -> None:
        self._fade_animation.stop()
        # Возвращаем прозрачность для кликов
        self.setWindowFlags(self._base_flags | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Отключаем предыдущие подключения перед новым
        try:
            self._fade_animation.finished.disconnect(self._on_hidden)
        except TypeError:
            pass
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.finished.connect(self._on_hidden)
        self._fade_animation.start()

    def _on_hidden(self) -> None:
        try:
            self._fade_animation.finished.disconnect(self._on_hidden)
        except TypeError:
            pass
        self.hide()
        self._state = OverlayState.HIDDEN

    def _show_animated(self) -> None:
        self.show()
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    # === Анимация ===

    def _animate(self) -> None:
        """Общий таймер анимации."""
        needs_update = False

        # Плавное изменение уровня
        if self._state == OverlayState.RECORDING:
            diff = self._target_level - self._current_level
            if abs(diff) > 0.01:
                self._current_level += diff * 0.5
                needs_update = True

        # Счётчик кадров для анимации
        self._anim_frame += 1
        if self._anim_frame > 100:
            self._anim_frame = 0

        if self._state in (OverlayState.RECORDING, OverlayState.PROCESSING):
            needs_update = True

        if needs_update:
            self.update()

    def update_waveform(self, levels: List[float]) -> None:
        if self._state != OverlayState.RECORDING:
            return

        # Берём последнее значение (текущая громкость)
        if levels:
            current_level = levels[-1]
        else:
            current_level = 0.0

        # Усиление + sqrt для тихих звуков
        self._target_level = min(1.0, math.sqrt(current_level) * self._gain)

    # === Отрисовка ===

    def paintEvent(self, event) -> None:
        if self._state == OverlayState.HIDDEN:
            return

        painter = QPainter(self)

        w = self.width()
        h = self.height()

        # Фон
        if self._bg_pixmap:
            painter.drawPixmap(0, 0, self._bg_pixmap)

        # Шрифт
        font = QFont("Courier New", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0))

        # Контент в зависимости от состояния
        if self._state == OverlayState.RECORDING:
            self._draw_recording(painter, w, h)
        elif self._state == OverlayState.PROCESSING:
            self._draw_processing(painter, w, h)
        elif self._state == OverlayState.SUCCESS:
            self._draw_success(painter, w, h)
        elif self._state == OverlayState.ERROR:
            self._draw_error(painter, w, h)

    def _draw_recording(self, painter: QPainter, w: int, h: int) -> None:
        """Текстовый индикатор записи."""
        # Заголовок с мигающей точкой
        dot = "●" if (self._anim_frame // 5) % 2 == 0 else "○"
        painter.drawText(8, 18, f"{dot} Recording")

        # Текстовый индикатор уровня [■■■■□□□□□□]
        bar_chars = 12
        filled = int(self._current_level * bar_chars)
        bar = "■" * filled + "□" * (bar_chars - filled)
        painter.drawText(8, 34, f"[{bar}]")

    def _draw_processing(self, painter: QPainter, w: int, h: int) -> None:
        """Анимированный текст обработки с кнопкой отмены."""
        # Анимированные точки
        dots_count = (self._anim_frame // 3) % 4
        dots = "." * dots_count
        spaces = " " * (3 - dots_count)
        painter.drawText(8, 18, f"Processing{dots}{spaces}")

        # Спиннер
        spinner = ["|", "/", "-", "\\"]
        idx = (self._anim_frame // 2) % 4
        painter.drawText(8, 34, f"  [{spinner[idx]}] Please wait")

        # Кнопка отмены [X] в правом верхнем углу
        btn_w, btn_h = 24, 20
        btn_x = w - btn_w - 10  # Учитываем тень
        btn_y = 6

        self._cancel_btn_rect = QRectF(btn_x, btn_y, btn_w, btn_h)

        # Рисуем кнопку
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRect(self._cancel_btn_rect)

        # Текст X
        painter.drawText(int(btn_x + 7), int(btn_y + 14), "X")

    def _draw_success(self, painter: QPainter, w: int, h: int) -> None:
        """Сообщение об успехе."""
        painter.drawText(8, 18, "[OK] Done!")
        painter.drawText(8, 34, "Text inserted")

    def _draw_error(self, painter: QPainter, w: int, h: int) -> None:
        """Сообщение об ошибке."""
        painter.drawText(8, 18, "[X] Error!")
        painter.drawText(8, 34, "Try again")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Обработка клика - отмена транскрипции."""
        if self._state == OverlayState.PROCESSING and self._cancel_btn_rect:
            pos = event.position()
            if self._cancel_btn_rect.contains(pos):
                self.cancelled.emit()
                return
        super().mousePressEvent(event)
