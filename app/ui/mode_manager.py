"""
Simple/Advanced Mode Manager для MindType.

Управляет переключением между режимами:
- Simple Mode: минимум настроек, авто-размер окна 600x500
- Advanced Mode: все настройки, авто-размер окна 700x650

Classic Mac OS System 7 Style.
"""

import logging
from typing import Callable, Optional, List, Any

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget,
    QCheckBox,
    QMainWindow,
)

logger = logging.getLogger(__name__)


# Размеры окна для разных режимов
SIMPLE_MODE_SIZE = QSize(640, 540)
ADVANCED_MODE_SIZE = QSize(720, 700)


class ModeManager:
    """
    Менеджер режимов Simple/Advanced.

    Управляет видимостью виджетов и размером окна
    в зависимости от выбранного режима.
    """

    def __init__(
        self,
        main_window: QMainWindow,
        config_manager: Any,
        translate_func: Optional[Callable] = None,
    ):
        """
        Args:
            main_window: Главное окно приложения
            config_manager: Менеджер конфигурации
            translate_func: Функция перевода
        """
        self.main_window = main_window
        self.config = config_manager
        self._t = translate_func or (lambda x: x)

        # Списки виджетов для каждого режима
        self._simple_only_widgets: List[QWidget] = []
        self._advanced_only_widgets: List[QWidget] = []

        # Текущий режим
        self._is_simple_mode = config_manager.config.get("simple_mode", True)

    @property
    def is_simple_mode(self) -> bool:
        """Проверить, активен ли Simple Mode."""
        return self._is_simple_mode

    def register_simple_only(self, widget: QWidget):
        """
        Зарегистрировать виджет, видимый только в Simple Mode.

        Args:
            widget: Виджет для регистрации
        """
        self._simple_only_widgets.append(widget)

    def register_advanced_only(self, widget: QWidget):
        """
        Зарегистрировать виджет, видимый только в Advanced Mode.

        Args:
            widget: Виджет для регистрации
        """
        self._advanced_only_widgets.append(widget)

    def set_mode(self, simple_mode: bool):
        """
        Установить режим работы.

        Args:
            simple_mode: True для Simple Mode, False для Advanced
        """
        self._is_simple_mode = simple_mode

        # Сохранить в конфиг
        self.config.update(simple_mode=simple_mode)

        # Обновить видимость виджетов
        self._update_widget_visibility()

        # Обновить размер окна
        self._update_window_size()

        logger.info(f"Mode changed to: {'Simple' if simple_mode else 'Advanced'}")

    def toggle_mode(self):
        """Переключить режим."""
        self.set_mode(not self._is_simple_mode)

    def _update_widget_visibility(self):
        """Обновить видимость виджетов в соответствии с режимом."""
        # Виджеты только для Simple Mode
        for widget in self._simple_only_widgets:
            widget.setVisible(self._is_simple_mode)

        # Виджеты только для Advanced Mode
        for widget in self._advanced_only_widgets:
            widget.setVisible(not self._is_simple_mode)

    def _update_window_size(self):
        """Обновить размер окна в соответствии с режимом."""
        if self._is_simple_mode:
            target_size = SIMPLE_MODE_SIZE
        else:
            target_size = ADVANCED_MODE_SIZE

        # Плавно изменить размер
        self.main_window.resize(target_size)

    def apply_current_mode(self):
        """Применить текущий режим (вызывать после создания UI)."""
        self._update_widget_visibility()
        self._update_window_size()


class ModeToggleWidget(QCheckBox):
    """
    Виджет переключения режимов Simple/Advanced.

    Отображается как чекбокс с надписью "Simple" в правом углу tab bar.
    """

    mode_changed = pyqtSignal(bool)  # True = Simple Mode

    def __init__(
        self,
        mode_manager: ModeManager,
        translate_func: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.mode_manager = mode_manager
        self._t = translate_func or (lambda x: x)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Настроить UI виджета."""
        self.setText(self._t("simple_mode"))
        self.setChecked(self.mode_manager.is_simple_mode)

        # Стиль в стиле system.css
        self.setStyleSheet("""
            QCheckBox {
                spacing: 6px;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 12px;
                height: 12px;
                border: 1.5px solid #000000;
                background-color: #ffffff;
            }
            QCheckBox::indicator:hover {
                background-color: #f0f0f0;
            }
            QCheckBox::indicator:checked {
                background-color: #000000;
            }
        """)

    def _connect_signals(self):
        """Подключить сигналы."""
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        """
        Обработчик переключения режима.

        Args:
            checked: True если включен Simple Mode
        """
        self.mode_manager.set_mode(checked)
        self.mode_changed.emit(checked)


# Конфигурация видимости виджетов для разных режимов
# Формат: (widget_name, visible_in_simple, visible_in_advanced)
MODE_VISIBILITY_CONFIG = {
    # Вкладка Transcribe
    "transcribe": {
        "microphone_combo": (True, True),
        "hotkey_button": (True, True),
        "language_combo": (True, True),
        "license_status": (True, True),
        "model_combo": (False, True),
        "quantization_combo": (False, True),
        "device_combo": (False, True),
    },
    # Вкладка Files
    "files": {
        "drop_zone": (True, True),
        "summary_checkbox": (True, True),
        "queue_widget": (True, True),
        "start_button": (True, True),
        "output_format": (False, True),
        "output_folder": (False, True),
        "customize_prompts": (False, True),
    },
    # Вкладка Settings
    "settings": {
        "provider_combo": (True, True),
        "api_key_input": (True, True),
        "model_combo": (False, True),
        "refresh_models": (False, True),
        "reasoning_checkbox": (False, True),
        "reasoning_effort": (False, True),
        "ui_language": (True, True),
        "version_label": (True, True),
        "check_updates": (True, True),
        # Performance секция
        "cpu_threads": (False, True),
        "num_workers": (False, True),
        "accelerator": (False, True),
        # Overlay секция
        "overlay_position": (False, True),
        "overlay_margin": (False, True),
        "overlay_wave_gain": (False, True),
        "overlay_opacity": (False, True),
    },
}
