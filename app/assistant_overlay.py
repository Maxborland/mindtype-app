"""
Classic Mac OS System 7 style overlay для голосового ассистента.
Текстовый индикатор в ретро-стиле с поддержкой различных состояний.
"""

from enum import Enum, auto
from typing import List, Optional
import math

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QFont, QMouseEvent
from PyQt6.QtWidgets import QWidget, QApplication, QGraphicsOpacityEffect


class AssistantOverlayState(Enum):
    HIDDEN = auto()
    CALIBRATING = auto()    # Калибровка: ◐ Калибровка...
    LISTENING = auto()      # Запись: ● Слушаю... + [■■■□□]
    TRANSCRIBING = auto()   # Whisper: [/] Распознаю...
    THINKING = auto()       # LLM: Думаю...
    SPEAKING = auto()       # TTS: ♪ Говорю...
    WAITING = auto()        # Ожидание: ○ Жду ввод... 5с
    ERROR = auto()          # Ошибка: ! Ошибка


class AssistantOverlayWidget(QWidget):
    """Classic Mac OS style overlay для ассистента."""

    # Сигналы
    closed = pyqtSignal()
    stop_clicked = pyqtSignal()
    new_dialog_clicked = pyqtSignal()
    cancelled = pyqtSignal()
    send_clicked = pyqtSignal()  # Принудительная отправка аудио

    POSITIONS = ["bottom-right", "bottom-left", "top-right", "top-left", "bottom-center", "top-center"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._state = AssistantOverlayState.HIDDEN
        self._corner = "bottom-center"
        self._margin = 20
        self._gain = 3.0

        # Уровень микрофона
        self._current_level = 0.0
        self._target_level = 0.0

        # Анимация
        self._anim_frame = 0
        self._wait_seconds = 5

        # Кэш фона
        self._bg_pixmap: Optional[QPixmap] = None

        # Области кнопок
        self._cancel_btn_rect: Optional[QRectF] = None
        self._send_btn_rect: Optional[QRectF] = None

        # Текст сообщений
        self._last_user_text: str = ""
        self._last_assistant_text: str = ""

        # Настройка окна
        self._base_flags = (
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setWindowFlags(self._base_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Размеры (увеличены для отображения текста)
        self._width = 260
        self._height = 90
        self.setFixedSize(self._width, self._height)

        # Эффект прозрачности
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Анимация появления/скрытия
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_animation.setDuration(100)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.Linear)

        # Таймеры
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_overlay)

        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(1000)
        self._wait_timer.timeout.connect(self._update_wait_timer)

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
        self._width = self.width()
        self._height = self.height()
        self._update_bg_cache()
        super().resizeEvent(event)

    def _update_bg_cache(self) -> None:
        """Создать кэш фона в стиле Classic Mac OS."""
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

    def set_state(self, state: AssistantOverlayState) -> None:
        old_state = self._state
        self._state = state
        self._hide_timer.stop()
        self._wait_timer.stop()

        if state == AssistantOverlayState.HIDDEN:
            self.hide_overlay()
            return

        if state == AssistantOverlayState.WAITING:
            self._wait_seconds = 5
            self._wait_timer.start()

        if state == AssistantOverlayState.ERROR:
            self._hide_timer.start(3000)

        # Делаем окно кликабельным
        self.setWindowFlags(self._base_flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        if old_state == AssistantOverlayState.HIDDEN:
            self._update_position()
            self._show_animated()
        else:
            self.show()  # Нужно после изменения флагов
            self.update()

    def update_level(self, level: float) -> None:
        """Обновить уровень микрофона (0.0 - 1.0)."""
        self._target_level = min(1.0, math.sqrt(level) * self._gain)

    def append_message(self, role: str, content: str) -> None:
        """Добавить сообщение для отображения."""
        if role == "user":
            self._last_user_text = content
        elif role == "assistant":
            self._last_assistant_text = content
        self.update()

    def clear_messages(self) -> None:
        """Очистить сообщения."""
        self._last_user_text = ""
        self._last_assistant_text = ""
        self.update()

    def set_state_text(self, text: str) -> None:
        """Установить текст состояния (для совместимости, игнорируется)."""
        pass

    # === Анимация ===

    def _animate(self) -> None:
        """Общий таймер анимации."""
        needs_update = False

        # Плавное изменение уровня
        if self._state in (AssistantOverlayState.CALIBRATING, AssistantOverlayState.LISTENING):
            diff = self._target_level - self._current_level
            if abs(diff) > 0.01:
                self._current_level += diff * 0.5
                needs_update = True

        # Счётчик кадров
        self._anim_frame += 1
        if self._anim_frame > 100:
            self._anim_frame = 0

        if self._state in (AssistantOverlayState.CALIBRATING, AssistantOverlayState.LISTENING,
                          AssistantOverlayState.TRANSCRIBING, AssistantOverlayState.THINKING,
                          AssistantOverlayState.SPEAKING, AssistantOverlayState.WAITING):
            needs_update = True

        if needs_update:
            self.update()

    def _update_wait_timer(self) -> None:
        self._wait_seconds -= 1
        if self._wait_seconds <= 0:
            self._wait_timer.stop()
            self.hide_overlay()
        else:
            self.update()

    # === Отрисовка ===

    def paintEvent(self, event) -> None:
        if self._state == AssistantOverlayState.HIDDEN:
            return

        painter = QPainter(self)

        # Фон из кэша
        if self._bg_pixmap:
            painter.drawPixmap(0, 0, self._bg_pixmap)

        # Шрифт
        font = QFont("Courier New", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0))

        # Контент в зависимости от состояния
        if self._state == AssistantOverlayState.CALIBRATING:
            self._draw_calibrating(painter)
        elif self._state == AssistantOverlayState.LISTENING:
            self._draw_listening(painter)
        elif self._state == AssistantOverlayState.TRANSCRIBING:
            self._draw_transcribing(painter)
        elif self._state == AssistantOverlayState.THINKING:
            self._draw_thinking(painter)
        elif self._state == AssistantOverlayState.SPEAKING:
            self._draw_speaking(painter)
        elif self._state == AssistantOverlayState.WAITING:
            self._draw_waiting(painter)
        elif self._state == AssistantOverlayState.ERROR:
            self._draw_error(painter)

        # Текст сообщения (транскрипт или ответ)
        self._draw_message_text(painter)

    def _draw_calibrating(self, painter: QPainter) -> None:
        """Состояние калибровки микрофона."""
        # Вращающийся индикатор ◐ ◓ ◑ ◒
        spinner = ["◐", "◓", "◑", "◒"][(self._anim_frame // 2) % 4]
        painter.drawText(8, 20, f"{spinner} Калибровка...")

        # Индикатор уровня (показываем шум)
        bar_chars = 12
        filled = int(self._current_level * bar_chars)
        bar = "░" * filled + "·" * (bar_chars - filled)
        painter.drawText(8, 38, f"[{bar}]")

        self._draw_cancel_button(painter)

    def _draw_listening(self, painter: QPainter) -> None:
        """Состояние записи."""
        # Мигающая точка
        dot = "●" if (self._anim_frame // 5) % 2 == 0 else "○"
        painter.drawText(8, 20, f"{dot} Слушаю...")

        # Индикатор уровня [■■■■□□□□]
        bar_chars = 12
        filled = int(self._current_level * bar_chars)
        bar = "■" * filled + "□" * (bar_chars - filled)
        painter.drawText(8, 38, f"[{bar}]")

        # Кнопка отмены
        self._draw_cancel_button(painter)

    def _draw_transcribing(self, painter: QPainter) -> None:
        """Состояние распознавания."""
        spinner = ["|", "/", "-", "\\"][(self._anim_frame // 2) % 4]
        painter.drawText(8, 20, f"[{spinner}] Распознаю...")
        painter.drawText(8, 38, "    Whisper AI")

        self._draw_cancel_button(painter)

    def _draw_thinking(self, painter: QPainter) -> None:
        """Состояние генерации ответа."""
        dots = "." * ((self._anim_frame // 3) % 4)
        spaces = " " * (3 - len(dots))
        painter.drawText(8, 20, f"Думаю{dots}{spaces}")

        spinner = ["|", "/", "-", "\\"][(self._anim_frame // 2) % 4]
        painter.drawText(8, 38, f"  [{spinner}] LLM...")

        self._draw_cancel_button(painter)

    def _draw_speaking(self, painter: QPainter) -> None:
        """Состояние озвучивания."""
        notes = ["♪ ", " ♪", "♫ "][(self._anim_frame // 4) % 3]
        painter.drawText(8, 20, f"{notes}Говорю...")
        painter.drawText(8, 38, "    TTS")

        self._draw_cancel_button(painter)

    def _draw_waiting(self, painter: QPainter) -> None:
        """Состояние ожидания ввода."""
        painter.drawText(8, 20, f"○ Жду ввод...")
        painter.drawText(8, 38, f"    {self._wait_seconds} сек")

        self._draw_cancel_button(painter)

    def _draw_error(self, painter: QPainter) -> None:
        """Состояние ошибки."""
        painter.setPen(QColor(180, 0, 0))
        painter.drawText(8, 20, "[!] Ошибка")
        painter.drawText(8, 38, "    Повторите")

    def _draw_message_text(self, painter: QPainter) -> None:
        """Отобразить последнее сообщение (транскрипт или ответ)."""
        # Выбираем текст в зависимости от состояния
        text = ""
        prefix = ""

        if self._state in (AssistantOverlayState.TRANSCRIBING, AssistantOverlayState.THINKING):
            # Показываем транскрипт пользователя
            if self._last_user_text:
                text = self._last_user_text
                prefix = "Вы: "
        elif self._state in (AssistantOverlayState.SPEAKING, AssistantOverlayState.WAITING):
            # Показываем ответ ассистента
            if self._last_assistant_text:
                text = self._last_assistant_text
                prefix = "AI: "

        if not text:
            return

        # Мелкий шрифт для текста сообщения
        font = QFont("Courier New", 8)
        painter.setFont(font)
        painter.setPen(QColor(60, 60, 60))

        # Обрезаем текст если слишком длинный
        max_chars = 30
        display_text = prefix + text
        if len(display_text) > max_chars:
            display_text = display_text[:max_chars - 3] + "..."

        # Рисуем в нижней части оверлея
        painter.drawText(8, 70, display_text)

    def _draw_cancel_button(self, painter: QPainter) -> None:
        """Кнопки: [✓] отправить и [X] отменить."""
        w = self.width()
        btn_w, btn_h = 24, 20
        btn_y = 14

        # Кнопка отмены [X] справа
        cancel_x = w - btn_w - 10  # Учитываем тень
        self._cancel_btn_rect = QRectF(cancel_x, btn_y, btn_w, btn_h)

        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRect(self._cancel_btn_rect)
        painter.drawText(int(cancel_x + 7), int(btn_y + 14), "X")

        # Кнопка отправки [✓] только в режиме записи
        if self._state in (AssistantOverlayState.CALIBRATING, AssistantOverlayState.LISTENING):
            send_x = cancel_x - btn_w - 4
            self._send_btn_rect = QRectF(send_x, btn_y, btn_w, btn_h)

            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.setBrush(QBrush(QColor(220, 255, 220)))  # Зеленоватый фон
            painter.drawRect(self._send_btn_rect)
            painter.drawText(int(send_x + 7), int(btn_y + 14), "✓")
        else:
            self._send_btn_rect = None

    # === События ===

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Обработка клика."""
        pos = event.position()

        # Кнопка отправки [✓]
        if self._send_btn_rect and self._send_btn_rect.contains(pos):
            if self._state in (AssistantOverlayState.CALIBRATING, AssistantOverlayState.LISTENING):
                self.send_clicked.emit()
                return

        # Кнопка отмены [X]
        if self._cancel_btn_rect and self._cancel_btn_rect.contains(pos):
            if self._state in (AssistantOverlayState.CALIBRATING, AssistantOverlayState.LISTENING):
                self.cancelled.emit()
            else:
                self.stop_clicked.emit()
            return

        super().mousePressEvent(event)

    # === Показ/скрытие ===

    def show_overlay(self) -> None:
        self._update_position()
        self._show_animated()

    def _show_animated(self) -> None:
        self.show()
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def hide_overlay(self) -> None:
        self._fade_animation.stop()
        # Отключаем предыдущие подключения
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
        self._state = AssistantOverlayState.HIDDEN
