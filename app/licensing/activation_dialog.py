"""
Диалог активации лицензии.
Показывает статус лицензии/trial и позволяет ввести ключ.
Поддерживает онлайн валидацию с обработкой ошибок.
"""

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFrame,
    QMessageBox,
    QProgressBar,
)
from PyQt6.QtGui import QFont

from .license_manager import LicenseManager, LicenseStatus, LicenseInfo, ValidationResult
from .key_validator import KeyValidator


class ActivationWorker(QThread):
    """Воркер для асинхронной активации лицензии."""
    finished = pyqtSignal(object, str, object)  # result, message, data

    def __init__(self, manager: LicenseManager, license_key: str):
        super().__init__()
        self._manager = manager
        self._license_key = license_key

    def run(self):
        result, message, data = self._manager.activate_online(self._license_key)
        self.finished.emit(result, message, data)


class DeactivationWorker(QThread):
    """Воркер для асинхронной деактивации лицензии."""
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, manager: LicenseManager):
        super().__init__()
        self._manager = manager

    def run(self):
        success, message = self._manager.deactivate_online()
        self.finished.emit(success, message)


class LicenseActivationDialog(QDialog):
    """Диалог активации лицензии."""

    license_activated = pyqtSignal()  # Сигнал успешной активации

    def __init__(self, license_manager: LicenseManager, translate_func=None, parent=None):
        super().__init__(parent)
        self._manager = license_manager
        self._t = translate_func or (lambda x: x)
        self._activation_worker = None
        self._deactivation_worker = None
        self._setup_ui()
        self._update_status()

    def set_translate_func(self, func):
        """Установить функцию перевода."""
        self._t = func
        self._update_texts()

    def _setup_ui(self):
        """Настроить UI в стиле Classic Mac OS."""
        self.setWindowTitle(self._t("license_activation"))
        self.setFixedSize(450, 380)
        self.setStyleSheet("""
            QDialog {
                background-color: #ffffff;
                color: #000000;
                font-family: "MS Sans Serif", "Geneva", "Arial", sans-serif;
            }
            QLabel {
                color: #000000;
                background: transparent;
            }
            QLabel#title {
                font-size: 16px;
                font-weight: bold;
            }
            QLabel#status {
                font-size: 12px;
                padding: 6px 10px;
                border: 2px solid #000000;
                background-color: #dddddd;
            }
            QLabel#statusActive {
                background-color: #dddddd;
            }
            QLabel#statusTrial {
                background-color: #dddddd;
            }
            QLabel#statusExpired {
                background-color: #dddddd;
            }
            QLabel#deviceInfo {
                font-size: 10px;
                color: #666666;
            }
            QLineEdit {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
                padding: 8px;
                font-size: 14px;
                font-family: monospace;
            }
            QLineEdit:focus {
                border-color: #000000;
            }
            QLineEdit:disabled {
                background-color: #eeeeee;
            }
            QPushButton {
                background-color: #dddddd;
                border: 2px solid;
                border-top-color: #ffffff;
                border-left-color: #ffffff;
                border-right-color: #000000;
                border-bottom-color: #000000;
                padding: 6px 16px;
                min-height: 20px;
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
            QPushButton#primary {
                font-weight: bold;
            }
            QPushButton#danger {
                color: #cc0000;
            }
            QFrame#separator {
                background-color: #000000;
                max-height: 1px;
            }
            QProgressBar {
                background-color: #ffffff;
                border: 2px solid;
                border-top-color: #808080;
                border-left-color: #808080;
                border-right-color: #ffffff;
                border-bottom-color: #ffffff;
                height: 16px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #000000;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Заголовок
        self._title_label = QLabel(self._t("license_activation"))
        self._title_label.setObjectName("title")
        layout.addWidget(self._title_label)

        # Статус лицензии
        self._status_frame = QFrame()
        status_layout = QVBoxLayout(self._status_frame)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        self._status_label = QLabel()
        self._status_label.setObjectName("status")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(self._status_label)

        self._status_details = QLabel()
        self._status_details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_details.setStyleSheet("font-size: 11px;")
        status_layout.addWidget(self._status_details)

        # Информация о плане (для активной лицензии)
        self._plan_info = QLabel()
        self._plan_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_info.setStyleSheet("font-size: 11px; font-weight: bold;")
        self._plan_info.setVisible(False)
        status_layout.addWidget(self._plan_info)

        layout.addWidget(self._status_frame)

        # Разделитель
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # Ввод ключа
        key_section = QVBoxLayout()
        key_section.setSpacing(8)

        self._key_label = QLabel(self._t("enter_license_key"))
        key_section.addWidget(self._key_label)

        self._key_input = QLineEdit()
        self._key_input.setPlaceholderText("XXXX-XXXX-XXXX-XXXX")
        self._key_input.setMaxLength(19)  # 16 символов + 3 дефиса
        self._key_input.textChanged.connect(self._on_key_changed)
        key_section.addWidget(self._key_input)

        layout.addLayout(key_section)

        # Прогресс-бар для активации
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminate
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Сообщение об ошибке/успехе
        self._message_label = QLabel()
        self._message_label.setStyleSheet("font-size: 11px;")
        self._message_label.setWordWrap(True)
        self._message_label.setVisible(False)
        layout.addWidget(self._message_label)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)

        self._continue_btn = QPushButton(self._t("continue_trial"))
        self._continue_btn.clicked.connect(self._on_continue)
        buttons_layout.addWidget(self._continue_btn)

        buttons_layout.addStretch()

        self._deactivate_btn = QPushButton(self._t("deactivate"))
        self._deactivate_btn.setObjectName("danger")
        self._deactivate_btn.clicked.connect(self._on_deactivate)
        self._deactivate_btn.setVisible(False)
        buttons_layout.addWidget(self._deactivate_btn)

        self._activate_btn = QPushButton(self._t("activate"))
        self._activate_btn.setObjectName("primary")
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate)
        buttons_layout.addWidget(self._activate_btn)

        layout.addLayout(buttons_layout)

        # Информация об устройстве
        self._device_info = QLabel()
        self._device_info.setObjectName("deviceInfo")
        self._device_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        device_id = self._manager.get_device_id()[:8]
        device_name = self._manager.get_device_name()
        self._device_info.setText(f"Device: {device_name} ({device_id}...)")
        layout.addWidget(self._device_info)

        layout.addStretch()

    def _update_texts(self):
        """Обновить тексты интерфейса."""
        self.setWindowTitle(self._t("license_activation"))
        self._title_label.setText(self._t("license_activation"))
        self._key_label.setText(self._t("enter_license_key"))
        self._continue_btn.setText(self._t("continue_trial"))
        self._activate_btn.setText(self._t("activate"))
        self._deactivate_btn.setText(self._t("deactivate"))
        self._update_status()

    def _update_status(self):
        """Обновить отображение статуса лицензии."""
        info = self._manager.get_license_info()

        if info.status == LicenseStatus.VALID:
            self._status_label.setText(f"✓ {self._t('license_active')}")
            self._status_label.setObjectName("statusActive")

            # Показываем детали плана
            details_parts = []
            if info.activation_date:
                date_str = info.activation_date.strftime("%d.%m.%Y")
                details_parts.append(f"{self._t('activation_date')}: {date_str}")

            self._status_details.setText(" | ".join(details_parts) if details_parts else "")

            # Информация о плане
            plan_text = []
            if info.plan:
                plan_text.append(f"Plan: {info.plan.capitalize()}")
            if info.max_devices > 1:
                plan_text.append(f"Devices: {info.activated_devices}/{info.max_devices}")
            if info.email:
                plan_text.append(info.email)

            if plan_text:
                self._plan_info.setText(" | ".join(plan_text))
                self._plan_info.setVisible(True)
            else:
                self._plan_info.setVisible(False)

            self._continue_btn.setText(self._t("close"))
            self._continue_btn.setVisible(True)
            self._deactivate_btn.setVisible(True)
            self._key_input.setEnabled(False)
            self._key_input.setText("")
            self._activate_btn.setVisible(False)

        elif info.status == LicenseStatus.TRIAL:
            self._status_label.setText(f"[!] {self._t('trial_mode')}")
            self._status_label.setObjectName("statusTrial")
            remaining_min = int(info.trial_remaining_minutes)
            self._status_details.setText(
                f"{self._t('trial_days_left')}: {info.trial_remaining_days} | "
                f"{self._t('trial_minutes_left')}: {remaining_min}"
            )
            self._plan_info.setVisible(False)
            self._continue_btn.setVisible(True)
            self._continue_btn.setText(self._t("continue_trial"))
            self._deactivate_btn.setVisible(False)
            self._key_input.setEnabled(True)
            self._activate_btn.setVisible(True)

        elif info.status == LicenseStatus.TRIAL_EXPIRED:
            self._status_label.setText(f"✗ {self._t('trial_expired')}")
            self._status_label.setObjectName("statusExpired")
            self._status_details.setText(self._t('trial_expired_message'))
            self._plan_info.setVisible(False)
            self._continue_btn.setVisible(False)
            self._deactivate_btn.setVisible(False)
            self._key_input.setEnabled(True)
            self._activate_btn.setVisible(True)

        # Обновляем стиль статуса
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _on_key_changed(self, text: str):
        """Обработчик изменения текста ключа."""
        # Автоформатирование с дефисами
        clean = text.upper().replace("-", "").replace(" ", "")
        clean = "".join(c for c in clean if c.isalnum())[:16]

        # Добавляем дефисы
        formatted = ""
        for i, c in enumerate(clean):
            if i > 0 and i % 4 == 0:
                formatted += "-"
            formatted += c

        # Обновляем поле без рекурсии
        if formatted != text:
            self._key_input.blockSignals(True)
            self._key_input.setText(formatted)
            self._key_input.blockSignals(False)

        # Проверяем валидность для включения кнопки
        is_valid = KeyValidator.validate(formatted)
        self._activate_btn.setEnabled(is_valid)

        # Сбрасываем сообщение
        self._message_label.setVisible(False)

    def _show_message(self, message: str, is_error: bool = False):
        """Показать сообщение пользователю."""
        self._message_label.setText(message)
        if is_error:
            self._message_label.setStyleSheet("font-size: 11px; color: #cc0000;")
        else:
            self._message_label.setStyleSheet("font-size: 11px; color: #006600;")
        self._message_label.setVisible(True)

    def _set_loading(self, loading: bool):
        """Установить состояние загрузки."""
        self._progress.setVisible(loading)
        self._key_input.setEnabled(not loading)
        self._activate_btn.setEnabled(not loading and KeyValidator.validate(self._key_input.text()))
        self._continue_btn.setEnabled(not loading)
        self._deactivate_btn.setEnabled(not loading)

    def _on_activate(self):
        """Обработчик кнопки активации."""
        key = self._key_input.text()

        self._set_loading(True)
        self._message_label.setVisible(False)

        # Запускаем асинхронную активацию
        self._activation_worker = ActivationWorker(self._manager, key)
        self._activation_worker.finished.connect(self._on_activation_finished)
        self._activation_worker.start()

    def _on_activation_finished(self, result: ValidationResult, message: str, data):
        """Обработчик завершения активации."""
        self._set_loading(False)

        if result == ValidationResult.SUCCESS:
            self._update_status()
            self.license_activated.emit()

            # Показываем сообщение об успехе
            QMessageBox.information(
                self,
                self._t("license_activation"),
                self._t("activation_success")
            )
            self.accept()
        else:
            # Показываем ошибку
            error_messages = {
                ValidationResult.INVALID_KEY: self._t("invalid_key"),
                ValidationResult.NOT_FOUND: self._t("license_not_found"),
                ValidationResult.EXPIRED: self._t("license_expired_error"),
                ValidationResult.DEACTIVATED: self._t("license_deactivated_error"),
                ValidationResult.DEVICE_LIMIT: self._t("device_limit_error"),
                ValidationResult.NETWORK_ERROR: self._t("network_error"),
                ValidationResult.RATE_LIMITED: self._t("rate_limited"),
                ValidationResult.SERVER_ERROR: self._t("server_error"),
            }
            error_text = error_messages.get(result, message)
            self._show_message(error_text, is_error=True)

    def _on_deactivate(self):
        """Обработчик кнопки деактивации."""
        # Подтверждение
        reply = QMessageBox.question(
            self,
            self._t("deactivate"),
            self._t("deactivate_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_loading(True)
        self._message_label.setVisible(False)

        # Запускаем асинхронную деактивацию
        self._deactivation_worker = DeactivationWorker(self._manager)
        self._deactivation_worker.finished.connect(self._on_deactivation_finished)
        self._deactivation_worker.start()

    def _on_deactivation_finished(self, success: bool, message: str):
        """Обработчик завершения деактивации."""
        self._set_loading(False)

        if success:
            self._update_status()
            self._show_message(self._t("deactivation_success"), is_error=False)
        else:
            if message == "network_error":
                self._show_message(self._t("network_error"), is_error=True)
            else:
                self._show_message(self._t("deactivation_failed"), is_error=True)

    def _on_continue(self):
        """Обработчик кнопки продолжения trial / закрытия."""
        info = self._manager.get_license_info()
        if info.is_active:
            self.accept()

    def should_block_app(self) -> bool:
        """Проверить, должно ли приложение быть заблокировано."""
        info = self._manager.get_license_info()
        return info.status == LicenseStatus.TRIAL_EXPIRED


class LicenseStatusWidget(QFrame):
    """
    Виджет статуса лицензии для отображения в настройках.
    Компактная версия для встраивания в интерфейс.
    """

    clicked = pyqtSignal()

    def __init__(self, license_manager: LicenseManager, translate_func=None, parent=None):
        super().__init__(parent)
        self._manager = license_manager
        self._t = translate_func or (lambda x: x)
        self._setup_ui()
        self._update_status()

    def set_translate_func(self, func):
        """Установить функцию перевода."""
        self._t = func
        self._update_status()

    def _setup_ui(self):
        """Настроить UI."""
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
            QFrame:hover {
                background-color: #dddddd;
            }
            QLabel {
                background: transparent;
            }
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Иконка статуса
        self._icon_label = QLabel()
        self._icon_label.setFixedWidth(24)
        layout.addWidget(self._icon_label)

        # Текст статуса
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-weight: bold;")
        text_layout.addWidget(self._status_label)

        self._details_label = QLabel()
        self._details_label.setStyleSheet("font-size: 11px;")
        text_layout.addWidget(self._details_label)

        layout.addLayout(text_layout, stretch=1)

    def _update_status(self):
        """Обновить отображение статуса."""
        info = self._manager.get_license_info()

        if info.status == LicenseStatus.VALID:
            self._icon_label.setText("[OK]")
            self._icon_label.setStyleSheet("font-weight: bold; color: #006600;")
            self._status_label.setText(self._t("license_active"))

            details = []
            if info.license_key:
                details.append(info.license_key[:9] + "...")
            if info.plan:
                details.append(info.plan.capitalize())
            self._details_label.setText(" | ".join(details) if details else "")

        elif info.status == LicenseStatus.TRIAL:
            self._icon_label.setText("[!]")
            self._icon_label.setStyleSheet("font-weight: bold; color: #cc6600;")
            self._status_label.setText(self._t("trial_mode"))
            remaining_min = int(info.trial_remaining_minutes)
            self._details_label.setText(
                f"{self._t('trial_days_left')}: {info.trial_remaining_days} | {remaining_min} min"
            )

        elif info.status == LicenseStatus.TRIAL_EXPIRED:
            self._icon_label.setText("[X]")
            self._icon_label.setStyleSheet("font-weight: bold; color: #cc0000;")
            self._status_label.setText(self._t("trial_expired"))
            self._details_label.setText(self._t("buy_license"))

    def mousePressEvent(self, event):
        """Обработчик клика."""
        self.clicked.emit()
        super().mousePressEvent(event)

    def refresh(self):
        """Обновить статус."""
        self._update_status()
