"""
Setup Wizard для первого запуска MindType.

System 7 Style - Classic Mac OS.

Шаги:
1. Выбор языка интерфейса
2. Выбор AI провайдера (MindType Cloud / свой API ключ)
3. Если MindType Cloud - выбор пакета кредитов
3b. Если свой ключ - ввод API ключа
4. Загрузка модели распознавания
5. Завершение
"""

import logging
from typing import Optional, Callable

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWidgets import (
    QWizard,
    QWizardPage,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QCheckBox,
    QButtonGroup,
    QPushButton,
    QLineEdit,
    QComboBox,
    QProgressBar,
    QFrame,
    QWidget,
    QGridLayout,
    QSizePolicy,
)
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap, QPainter, QColor, QPalette

from ..translations import UI_LANGUAGES, get_text
from ..config import ConfigManager

logger = logging.getLogger(__name__)


# ============================================================================
# SYSTEM.CSS STYLE CONSTANTS (Apple System OS 1984-1991)
# ============================================================================

# Colors
COLOR_BG = "#ffffff"
COLOR_GRAY = "#dddddd"
COLOR_DARK_GRAY = "#808080"
COLOR_BLACK = "#000000"

# System.css Master Stylesheet for Wizard
WIZARD_STYLESHEET = """
QWizard {
    background-color: #ffffff;
}

QWizardPage {
    background-color: #ffffff;
}

QWidget {
    background-color: #ffffff;
    color: #000000;
    font-family: "ChicagoFLF", "Chicago", "Geneva", "Segoe UI", "Arial", sans-serif;
    font-size: 12px;
}

QLabel {
    background-color: transparent;
    color: #000000;
}

/* Rounded buttons - system.css style */
QPushButton {
    background-color: #ffffff;
    border: 1.5px solid #000000;
    border-radius: 6px;
    padding: 6px 16px;
    color: #000000;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f0f0f0;
}

QPushButton:pressed {
    background-color: #000000;
    color: #ffffff;
}

QPushButton:disabled {
    background-color: #dddddd;
    color: #808080;
    border-color: #808080;
}

QRadioButton {
    spacing: 8px;
    color: #000000;
    background-color: transparent;
}

QRadioButton::indicator {
    width: 12px;
    height: 12px;
    border: 1.5px solid #000000;
    background-color: #ffffff;
    border-radius: 6px;
}

QRadioButton::indicator:hover {
    background-color: #f0f0f0;
}

QRadioButton::indicator:checked {
    background-color: #ffffff;
    border: 4px solid #000000;
}

QCheckBox {
    spacing: 8px;
    color: #000000;
    background-color: transparent;
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

QCheckBox:disabled {
    color: #808080;
}

/* Focus inversion - system.css style */
QLineEdit {
    background-color: #ffffff;
    border: 1.5px solid #000000;
    padding: 6px 8px;
    color: #000000;
}

QLineEdit:focus {
    background-color: #000000;
    color: #ffffff;
    selection-background-color: #ffffff;
    selection-color: #000000;
}

QComboBox {
    background-color: #ffffff;
    border: 1.5px solid #000000;
    padding: 4px 24px 4px 8px;
    color: #000000;
    min-height: 20px;
}

QComboBox:hover {
    background-color: #f8f8f8;
}

QComboBox:focus {
    background-color: #000000;
    color: #ffffff;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
    background-color: #ffffff;
    border-left: 1.5px solid #000000;
}

QComboBox::down-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #000000;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 2px solid #000000;
    selection-background-color: #000000;
    selection-color: #ffffff;
}

QProgressBar {
    background-color: #ffffff;
    border: 1.5px solid #000000;
    height: 18px;
    text-align: center;
    color: #000000;
}

QProgressBar::chunk {
    background-color: #000000;
}
"""

# Card frame styles - simple border (system.css style)
CARD_STYLE = """
QFrame {
    background-color: #ffffff;
    border: 1.5px solid #000000;
}
"""

CARD_SELECTED_STYLE = """
QFrame {
    background-color: #ffffff;
    border: 2px solid #000000;
}
"""

INFO_BOX_STYLE = """
QFrame {
    background-color: #dddddd;
    border: 1.5px solid #000000;
}
"""

# Primary button - thick border, rounded (system.css style)
PRIMARY_BUTTON_STYLE = """
QPushButton {
    background-color: #ffffff;
    border: 3px solid #000000;
    border-radius: 8px;
    font-weight: bold;
    padding: 8px 20px;
}
QPushButton:hover {
    background-color: #f0f0f0;
}
QPushButton:pressed {
    background-color: #000000;
    color: #ffffff;
}
QPushButton:disabled {
    background-color: #dddddd;
    color: #808080;
    border-color: #808080;
}
"""


# Wizard page IDs
PAGE_LANGUAGE = 0
PAGE_KEY_OR_DEMO = 1
PAGE_LICENSE_KEY = 2
PAGE_MODEL_DOWNLOAD = 3
PAGE_COMPLETION = 4


def create_card_frame(selected: bool = False) -> QFrame:
    """Create a system.css style card frame."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.Box)
    frame.setLineWidth(2)
    if selected:
        # Selected: thicker black border
        frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 2px solid #000000;
            }
        """)
    else:
        # Not selected: thin black border (system.css style)
        frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1.5px solid #000000;
            }
        """)
    return frame


def create_info_frame() -> QFrame:
    """Create a System 7 style info box (gray background)."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.Box)
    frame.setLineWidth(1)
    frame.setStyleSheet("""
        QFrame {
            background-color: #dddddd;
            border: 1px solid #000000;
        }
    """)
    return frame


def create_title_label(text: str) -> QLabel:
    """Create a big title label."""
    label = QLabel(text)
    label.setStyleSheet("font-size: 18px; font-weight: bold; color: #000000; background: transparent;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def create_subtitle_label(text: str) -> QLabel:
    """Create a subtitle label."""
    label = QLabel(text)
    label.setStyleSheet("font-size: 12px; color: #808080; background: transparent;")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def create_primary_button(text: str) -> QPushButton:
    """Create a primary button with thick border."""
    btn = QPushButton(text)
    btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
    return btn


class LanguagePage(QWizardPage):
    """Step 1: Choose UI language."""

    language_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 30, 40, 30)

        # Title
        self.title = create_title_label(self._t("setup_welcome_title"))
        layout.addWidget(self.title)

        self.subtitle = create_subtitle_label(self._t("setup_choose_language"))
        layout.addWidget(self.subtitle)

        layout.addSpacing(20)

        # Language selection in a frame
        lang_frame = create_card_frame()
        lang_layout = QVBoxLayout(lang_frame)
        lang_layout.setSpacing(12)
        lang_layout.setContentsMargins(20, 16, 20, 16)

        self.language_group = QButtonGroup(self)

        # Priority languages with flags
        priority_langs = [
            ("en", "🇺🇸  English"),
            ("ru", "🇷🇺  Русский"),
            ("es", "🇪🇸  Español"),
            ("de", "🇩🇪  Deutsch"),
            ("fr", "🇫🇷  Français"),
            ("zh", "🇨🇳  中文"),
        ]

        for lang_code, native_name in priority_langs:
            rb = QRadioButton(native_name)
            rb.setStyleSheet("font-size: 14px; background: transparent;")
            rb.setProperty("lang_code", lang_code)
            if lang_code == "en":
                rb.setChecked(True)
            rb.toggled.connect(self._on_language_toggled)
            self.language_group.addButton(rb)
            lang_layout.addWidget(rb)

        layout.addWidget(lang_frame)
        layout.addStretch()

    def _update_texts(self):
        self.title.setText(self._t("setup_welcome_title"))
        self.subtitle.setText(self._t("setup_choose_language"))

    def _on_language_toggled(self, checked: bool):
        if checked:
            lang = self.get_selected_language()
            self.language_changed.emit(lang)

    def get_selected_language(self) -> str:
        btn = self.language_group.checkedButton()
        if btn:
            return btn.property("lang_code")
        return "en"


class KeyOrDemoPage(QWizardPage):
    """Step 2: Choose between license key activation or demo mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 24, 30, 24)

        self.title = create_title_label(self._t("setup_key_or_demo_title"))
        layout.addWidget(self.title)

        self.desc = create_subtitle_label(self._t("setup_key_or_demo_description"))
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        layout.addSpacing(16)

        self.choice_group = QButtonGroup(self)

        # License key option
        self.key_frame = create_card_frame(selected=False)
        key_layout = QVBoxLayout(self.key_frame)
        key_layout.setSpacing(8)
        key_layout.setContentsMargins(16, 12, 16, 12)

        self.key_radio = QRadioButton(self._t("setup_option_license_key"))
        self.key_radio.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        self.key_radio.toggled.connect(self._update_card_styles)
        self.choice_group.addButton(self.key_radio, 0)
        key_layout.addWidget(self.key_radio)

        self.key_desc = QLabel(self._t("setup_option_license_key_desc"))
        self.key_desc.setStyleSheet("color: #808080; font-size: 11px; margin-left: 22px; background: transparent;")
        self.key_desc.setWordWrap(True)
        key_layout.addWidget(self.key_desc)

        layout.addWidget(self.key_frame)

        layout.addSpacing(8)

        # Demo option
        self.demo_frame = create_card_frame(selected=True)
        demo_layout = QVBoxLayout(self.demo_frame)
        demo_layout.setSpacing(8)
        demo_layout.setContentsMargins(16, 12, 16, 12)

        self.demo_radio = QRadioButton(self._t("setup_option_demo"))
        self.demo_radio.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        self.demo_radio.setChecked(True)
        self.demo_radio.toggled.connect(self._update_card_styles)
        self.choice_group.addButton(self.demo_radio, 1)
        demo_layout.addWidget(self.demo_radio)

        self.demo_desc = QLabel(self._t("setup_option_demo_desc"))
        self.demo_desc.setStyleSheet("color: #808080; font-size: 11px; margin-left: 22px; background: transparent;")
        self.demo_desc.setWordWrap(True)
        demo_layout.addWidget(self.demo_desc)

        layout.addWidget(self.demo_frame)

        layout.addStretch()
        self._update_texts()

    def _update_card_styles(self):
        selected_style = "QFrame { background-color: #ffffff; border: 2px solid #000000; }"
        normal_style = "QFrame { background-color: #ffffff; border: 1.5px solid #000000; }"
        if self.demo_radio.isChecked():
            self.demo_frame.setStyleSheet(selected_style)
            self.key_frame.setStyleSheet(normal_style)
        else:
            self.demo_frame.setStyleSheet(normal_style)
            self.key_frame.setStyleSheet(selected_style)

    def _update_texts(self):
        self.title.setText(self._t("setup_key_or_demo_title"))
        self.desc.setText(self._t("setup_key_or_demo_description"))
        self.key_radio.setText(self._t("setup_option_license_key"))
        self.key_desc.setText(self._t("setup_option_license_key_desc"))
        self.demo_radio.setText(self._t("setup_option_demo"))
        self.demo_desc.setText(self._t("setup_option_demo_desc"))

    def is_demo_selected(self) -> bool:
        return self.demo_radio.isChecked()


class LicenseKeyPage(QWizardPage):
    """Step 3 (optional): Activate MindType license key for MindType Cloud."""

    def __init__(self, license_manager, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._license_manager = license_manager
        self._activated = False
        self._activation_worker = None
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        from ..licensing.key_validator import KeyValidator
        from PyQt6.QtWidgets import QProgressBar
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 24, 30, 24)

        self.title = create_title_label(self._t("setup_license_key_title"))
        layout.addWidget(self.title)

        self.desc = create_subtitle_label(self._t("setup_license_key_description"))
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        layout.addSpacing(12)

        key_frame = create_card_frame()
        key_layout = QVBoxLayout(key_frame)
        key_layout.setContentsMargins(16, 12, 16, 12)
        key_layout.setSpacing(8)

        key_row = QHBoxLayout()
        self.key_label = QLabel(self._t("license_key") + ":")
        self.key_label.setStyleSheet("font-weight: bold; background: transparent;")
        key_row.addWidget(self.key_label)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("ABCD-EFGH-JKMN-PQRS")
        self.key_input.textChanged.connect(lambda _: self._update_buttons())
        key_row.addWidget(self.key_input, 1)
        key_layout.addLayout(key_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #808080; font-size: 11px; background: transparent;")
        key_layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        key_layout.addWidget(self.progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.activate_btn = create_primary_button(self._t("activate"))
        self.activate_btn.clicked.connect(self._on_activate_clicked)
        self.activate_btn.setEnabled(False)
        btn_row.addWidget(self.activate_btn)
        key_layout.addLayout(btn_row)

        layout.addWidget(key_frame)

        # Credits hint
        info_frame = create_info_frame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_layout.setSpacing(6)

        self.credits_hint = QLabel(self._t("setup_credits_hint"))
        self.credits_hint.setWordWrap(True)
        self.credits_hint.setStyleSheet("background: transparent;")
        info_layout.addWidget(self.credits_hint)

        self.buy_credits_btn = QPushButton(self._t("buy_credits"))
        self.buy_credits_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://mindtype.space/buy-credits")))
        info_layout.addWidget(self.buy_credits_btn)

        layout.addWidget(info_frame)

        layout.addStretch()
        self._update_texts()
        self._update_buttons()

    def _update_texts(self):
        self.title.setText(self._t("setup_license_key_title"))
        self.desc.setText(self._t("setup_license_key_description"))
        self.key_label.setText(self._t("license_key") + ":")
        self.activate_btn.setText(self._t("activate"))
        self.credits_hint.setText(self._t("setup_credits_hint"))
        self.buy_credits_btn.setText(self._t("buy_credits"))

    def _set_loading(self, loading: bool):
        from ..licensing.key_validator import KeyValidator

        self.progress.setVisible(loading)
        self.key_input.setEnabled(not loading and not self._activated)
        self.activate_btn.setEnabled(not loading and not self._activated and KeyValidator.validate(self.key_input.text()))

    def _update_buttons(self):
        from ..licensing.key_validator import KeyValidator
        if self._activated:
            self.activate_btn.setEnabled(False)
            return
        self.activate_btn.setEnabled(KeyValidator.validate(self.key_input.text()))

    def _on_activate_clicked(self):
        from ..licensing.activation_dialog import ActivationWorker

        key = self.key_input.text().strip()
        if not key:
            return

        self.status_label.setText(self._t("setup_activation_in_progress"))
        self._set_loading(True)

        self._activation_worker = ActivationWorker(self._license_manager, key)
        self._activation_worker.finished.connect(self._on_activation_finished)
        self._activation_worker.start()

    def _on_activation_finished(self, result, message: str, data):
        from ..licensing.license_manager import ValidationResult

        self._set_loading(False)

        if result == ValidationResult.SUCCESS:
            self._activated = True
            self.status_label.setStyleSheet("color: #000000; font-size: 11px; background: transparent;")
            self.status_label.setText("✓ " + self._t("activation_success"))
            self.completeChanged.emit()
            self._update_buttons()
            return

        # Error mapping (same semantics as activation dialog).
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
        self.status_label.setStyleSheet("color: #000000; font-size: 11px; background: transparent;")
        self.status_label.setText(error_text)
        self._update_buttons()

    def isComplete(self) -> bool:
        return self._activated


class ProviderChoicePage(QWizardPage):
    """Step 2: Choose AI provider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(30, 24, 30, 24)

        # Title
        self.title = create_title_label("AI Features Setup")
        layout.addWidget(self.title)

        self.desc = create_subtitle_label("MindType uses AI for summarization")
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        layout.addSpacing(16)

        # Provider selection
        self.provider_group = QButtonGroup(self)

        # MindType Cloud option - selected card
        self.cloud_frame = create_card_frame(selected=True)
        cloud_layout = QVBoxLayout(self.cloud_frame)
        cloud_layout.setSpacing(8)
        cloud_layout.setContentsMargins(16, 12, 16, 12)

        self.cloud_radio = QRadioButton("MindType Cloud (Recommended)")
        self.cloud_radio.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        self.cloud_radio.setChecked(True)
        self.cloud_radio.toggled.connect(self._update_card_styles)
        self.provider_group.addButton(self.cloud_radio, 0)
        cloud_layout.addWidget(self.cloud_radio)

        # Benefits as checkboxes (visual only, always checked)
        self.benefit1 = QCheckBox("No API keys needed")
        self.benefit1.setChecked(True)
        self.benefit1.setEnabled(False)
        self.benefit1.setStyleSheet("margin-left: 20px; background: transparent;")
        cloud_layout.addWidget(self.benefit1)

        self.benefit2 = QCheckBox("Pay only for what you use")
        self.benefit2.setChecked(True)
        self.benefit2.setEnabled(False)
        self.benefit2.setStyleSheet("margin-left: 20px; background: transparent;")
        cloud_layout.addWidget(self.benefit2)

        self.benefit3 = QCheckBox("Credits never expire")
        self.benefit3.setChecked(True)
        self.benefit3.setEnabled(False)
        self.benefit3.setStyleSheet("margin-left: 20px; background: transparent;")
        cloud_layout.addWidget(self.benefit3)

        layout.addWidget(self.cloud_frame)

        layout.addSpacing(8)

        # Own API key option
        self.own_frame = create_card_frame(selected=False)
        own_layout = QVBoxLayout(self.own_frame)
        own_layout.setSpacing(8)
        own_layout.setContentsMargins(16, 12, 16, 12)

        self.own_key_radio = QRadioButton("Use Own API Key (Free)")
        self.own_key_radio.setStyleSheet("font-size: 13px; background: transparent;")
        self.own_key_radio.toggled.connect(self._update_card_styles)
        self.provider_group.addButton(self.own_key_radio, 1)
        own_layout.addWidget(self.own_key_radio)

        self.own_desc = QLabel("Bring your own OpenAI, Anthropic, or other API key")
        self.own_desc.setStyleSheet("color: #808080; font-size: 11px; margin-left: 22px; background: transparent;")
        self.own_desc.setWordWrap(True)
        own_layout.addWidget(self.own_desc)

        layout.addWidget(self.own_frame)
        layout.addStretch()

        self._update_texts()

    def _update_card_styles(self):
        """Update card borders based on selection (system.css style)."""
        selected_style = "QFrame { background-color: #ffffff; border: 2px solid #000000; }"
        # Simple thin border for unselected cards (system.css style)
        normal_style = "QFrame { background-color: #ffffff; border: 1.5px solid #000000; }"
        if self.cloud_radio.isChecked():
            self.cloud_frame.setStyleSheet(selected_style)
            self.own_frame.setStyleSheet(normal_style)
        else:
            self.cloud_frame.setStyleSheet(normal_style)
            self.own_frame.setStyleSheet(selected_style)

    def _update_texts(self):
        self.title.setText(self._t("setup_ai_title"))
        self.desc.setText(self._t("setup_ai_description"))
        self.cloud_radio.setText(self._t("mindtype_cloud_recommended"))
        self.benefit1.setText(self._t("cloud_benefit_no_api_keys"))
        self.benefit2.setText(self._t("cloud_benefit_buy_credits"))
        self.benefit3.setText(self._t("cloud_benefit_never_expire"))
        self.own_key_radio.setText(self._t("own_api_key_free"))
        self.own_desc.setText(self._t("own_api_key_description"))

    def is_mindtype_cloud_selected(self) -> bool:
        return self.cloud_radio.isChecked()


class CreditPackPage(QWizardPage):
    """Step 3: Choose credit pack."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self.selected_pack: Optional[str] = None
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        self.title = create_title_label("Choose Credit Pack")
        layout.addWidget(self.title)

        self.desc = create_subtitle_label("1 credit = 1 AI summary")
        layout.addWidget(self.desc)

        layout.addSpacing(16)

        # Credit packs in horizontal layout
        packs_layout = QHBoxLayout()
        packs_layout.setSpacing(12)

        self.pack_group = QButtonGroup(self)
        self.pack_frames = {}
        self.pack_radios = {}

        # Starter Pack
        starter_frame, starter_radio = self._create_pack_card(
            "starter", "Starter", "$19", "100", "$0.19/credit"
        )
        self.pack_frames["starter"] = starter_frame
        self.pack_radios["starter"] = starter_radio
        packs_layout.addWidget(starter_frame)

        # Pro Pack
        pro_frame, pro_radio = self._create_pack_card(
            "pro", "Pro", "$49", "300", "$0.16/credit"
        )
        self.pack_frames["pro"] = pro_frame
        self.pack_radios["pro"] = pro_radio
        packs_layout.addWidget(pro_frame)

        # Business Pack (best value, selected by default)
        business_frame, business_radio = self._create_pack_card(
            "business", "Business", "$99", "750", "$0.13/credit", is_best=True
        )
        self.pack_frames["business"] = business_frame
        self.pack_radios["business"] = business_radio
        business_radio.setChecked(True)
        packs_layout.addWidget(business_frame)

        layout.addLayout(packs_layout)

        layout.addSpacing(12)

        # Info box with benefits
        info_frame = create_info_frame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(6)

        self.info_check1 = QCheckBox("Credits never expire")
        self.info_check1.setChecked(True)
        self.info_check1.setEnabled(False)
        self.info_check1.setStyleSheet("background: transparent;")
        info_layout.addWidget(self.info_check1)

        self.info_check2 = QCheckBox("Buy more anytime")
        self.info_check2.setChecked(True)
        self.info_check2.setEnabled(False)
        self.info_check2.setStyleSheet("background: transparent;")
        info_layout.addWidget(self.info_check2)

        layout.addWidget(info_frame)

        layout.addStretch()
        self._update_texts()

    def _create_pack_card(
        self, pack_id: str, name: str, price: str, credits: str, per_credit: str,
        is_best: bool = False
    ) -> tuple:
        frame = create_card_frame(selected=is_best)
        frame.setMinimumWidth(120)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(frame)
        layout.setSpacing(4)
        layout.setContentsMargins(12, 10, 12, 10)

        # Radio at top
        radio = QRadioButton()
        radio.setStyleSheet("background: transparent;")
        radio.setProperty("pack_id", pack_id)
        radio.toggled.connect(lambda checked, pid=pack_id: self._on_pack_selected(pid, checked))
        self.pack_group.addButton(radio)
        layout.addWidget(radio, alignment=Qt.AlignmentFlag.AlignCenter)

        if is_best:
            best_label = QLabel("★ Best Value")
            best_label.setStyleSheet("font-weight: bold; font-size: 10px; color: #000000; background: transparent;")
            best_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(best_label)

        name_label = QLabel(name)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        price_label = QLabel(price)
        price_label.setStyleSheet("font-size: 18px; font-weight: bold; background: transparent;")
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(price_label)

        credits_label = QLabel(f"{credits} credits")
        credits_label.setStyleSheet("font-size: 11px; background: transparent;")
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credits_label)

        per_label = QLabel(per_credit)
        per_label.setStyleSheet("font-size: 10px; color: #808080; background: transparent;")
        per_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(per_label)

        return frame, radio

    def _on_pack_selected(self, pack_id: str, checked: bool):
        """Update card styles when pack is selected (system.css style)."""
        selected_style = "QFrame { background-color: #ffffff; border: 2px solid #000000; }"
        # Simple thin border for unselected cards (system.css style)
        normal_style = "QFrame { background-color: #ffffff; border: 1.5px solid #000000; }"
        if checked:
            for pid, frame in self.pack_frames.items():
                if pid == pack_id:
                    frame.setStyleSheet(selected_style)
                else:
                    frame.setStyleSheet(normal_style)

    def _update_texts(self):
        self.title.setText(self._t("choose_credit_pack"))
        self.desc.setText(self._t("one_credit_one_summary"))
        self.info_check1.setText(self._t("credits_never_expire"))
        self.info_check2.setText(self._t("credits_buy_anytime"))

    def get_selected_pack(self) -> Optional[str]:
        btn = self.pack_group.checkedButton()
        if btn:
            return btn.property("pack_id")
        return None


class ApiKeyPage(QWizardPage):
    """Step 3b: Enter own API key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 24, 30, 24)

        # Title
        self.title = create_title_label("Connect AI Provider")
        layout.addWidget(self.title)

        layout.addSpacing(12)

        # Provider selection in a frame
        provider_frame = create_card_frame()
        provider_layout = QVBoxLayout(provider_frame)
        provider_layout.setContentsMargins(16, 12, 16, 12)
        provider_layout.setSpacing(10)

        # Provider row
        provider_row = QHBoxLayout()
        self.provider_label = QLabel("Provider:")
        self.provider_label.setStyleSheet("font-weight: bold; background: transparent;")
        provider_row.addWidget(self.provider_label)

        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(180)
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.addItem("Claude (Anthropic)", "anthropic")
        self.provider_combo.addItem("Gemini (Google)", "gemini")
        self.provider_combo.addItem("OpenRouter", "openrouter")
        self.provider_combo.addItem("Ollama (Local)", "ollama")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo)
        provider_row.addStretch()
        provider_layout.addLayout(provider_row)

        # Recommendation
        self.recommendation = QLabel("OpenAI: Easy signup, pay-as-you-go, excellent quality.")
        self.recommendation.setWordWrap(True)
        self.recommendation.setStyleSheet("color: #808080; font-size: 11px; margin-top: 4px; background: transparent;")
        provider_layout.addWidget(self.recommendation)

        layout.addWidget(provider_frame)

        layout.addSpacing(8)

        # API Key input frame
        self.key_frame = create_card_frame()
        key_layout = QVBoxLayout(self.key_frame)
        key_layout.setContentsMargins(16, 12, 16, 12)
        key_layout.setSpacing(8)

        key_row = QHBoxLayout()
        self.key_label = QLabel("API Key:")
        self.key_label.setStyleSheet("font-weight: bold; background: transparent;")
        key_row.addWidget(self.key_label)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self.api_key_input, 1)
        key_layout.addLayout(key_row)

        layout.addWidget(self.key_frame)

        layout.addSpacing(8)

        # Help section
        help_frame = create_info_frame()
        help_layout = QVBoxLayout(help_frame)
        help_layout.setContentsMargins(12, 10, 12, 10)
        help_layout.setSpacing(6)

        self.help_title = QLabel("How to get an API key:")
        self.help_title.setStyleSheet("font-weight: bold; background: transparent;")
        help_layout.addWidget(self.help_title)

        self.steps_label = QLabel(
            "1. Sign up at provider website\n"
            "2. Go to API keys section\n"
            "3. Create new key\n"
            "4. Paste it here"
        )
        self.steps_label.setStyleSheet("font-size: 11px; color: #808080; background: transparent;")
        self.steps_label.setWordWrap(True)
        help_layout.addWidget(self.steps_label)

        self.open_provider_btn = QPushButton("Open Provider Website")
        self.open_provider_btn.clicked.connect(self._open_provider_website)
        help_layout.addWidget(self.open_provider_btn)

        layout.addWidget(help_frame)

        layout.addStretch()
        self._update_texts()
        self._on_provider_changed(0)

    def _update_texts(self):
        self.title.setText(self._t("connect_ai_provider"))
        self.provider_label.setText(self._t("provider") + ":")
        self.key_label.setText(self._t("api_key") + ":")
        self.help_title.setText(self._t("how_to_get_api_key"))
        self.open_provider_btn.setText(self._t("open_provider_website"))
        self.steps_label.setText(
            "1. " + self._t("api_key_step_login") + "\n"
            "2. " + self._t("api_key_step_navigate") + "\n"
            "3. " + self._t("api_key_step_create") + "\n"
            "4. " + self._t("api_key_step_paste")
        )

    def _on_provider_changed(self, index: int):
        provider = self.provider_combo.currentData()

        recommendations = {
            "openai": "OpenAI: Easy signup, pay-as-you-go, excellent quality.",
            "anthropic": "Claude by Anthropic: Great for long documents.",
            "gemini": "Google Gemini: Fast, good for multilingual content.",
            "openrouter": "OpenRouter: Access many models with one API key.",
            "ollama": "Ollama: Run models locally, no API key needed.",
        }
        self.recommendation.setText(recommendations.get(provider, ""))

        placeholders = {
            "openai": "sk-...",
            "anthropic": "sk-ant-...",
            "gemini": "AIza...",
            "openrouter": "sk-or-...",
            "ollama": "",
        }
        self.api_key_input.setPlaceholderText(placeholders.get(provider, ""))

        # Hide API key for Ollama
        is_ollama = provider == "ollama"
        self.key_frame.setVisible(not is_ollama)

    def _open_provider_website(self):
        provider = self.provider_combo.currentData()
        urls = {
            "openai": "https://platform.openai.com/api-keys",
            "anthropic": "https://console.anthropic.com/settings/keys",
            "gemini": "https://aistudio.google.com/app/apikey",
            "openrouter": "https://openrouter.ai/keys",
            "ollama": "https://ollama.ai/download",
        }
        url = urls.get(provider, "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def get_provider(self) -> str:
        return self.provider_combo.currentData()

    def get_api_key(self) -> str:
        return self.api_key_input.text().strip()


class ModelDownloadPage(QWizardPage):
    """Step 4: Download speech recognition model."""

    download_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._download_complete = False
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(30, 24, 30, 24)

        # Title
        self.title = create_title_label("Download Speech Model")
        layout.addWidget(self.title)

        self.desc = create_subtitle_label("MindType needs a model for speech recognition")
        self.desc.setWordWrap(True)
        layout.addWidget(self.desc)

        layout.addSpacing(12)

        # Model selection
        self.model_group = QButtonGroup(self)

        # Small model (recommended)
        self.small_frame = create_card_frame(selected=True)
        small_layout = QVBoxLayout(self.small_frame)
        small_layout.setSpacing(4)
        small_layout.setContentsMargins(16, 12, 16, 12)

        self.small_radio = QRadioButton("Whisper Small (Recommended)")
        self.small_radio.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent;")
        self.small_radio.setChecked(True)
        self.small_radio.toggled.connect(self._update_card_styles)
        self.model_group.addButton(self.small_radio, 0)
        small_layout.addWidget(self.small_radio)

        self.small_desc = QLabel("244 MB • Fast • Good quality")
        self.small_desc.setStyleSheet("color: #808080; margin-left: 22px; background: transparent;")
        small_layout.addWidget(self.small_desc)

        layout.addWidget(self.small_frame)

        # Large model
        self.large_frame = create_card_frame(selected=False)
        large_layout = QVBoxLayout(self.large_frame)
        large_layout.setSpacing(4)
        large_layout.setContentsMargins(16, 12, 16, 12)

        self.large_radio = QRadioButton("Whisper Large")
        self.large_radio.setStyleSheet("font-size: 13px; background: transparent;")
        self.large_radio.toggled.connect(self._update_card_styles)
        self.model_group.addButton(self.large_radio, 1)
        large_layout.addWidget(self.large_radio)

        self.large_desc = QLabel("1.5 GB • Slower • Best quality")
        self.large_desc.setStyleSheet("color: #808080; margin-left: 22px; background: transparent;")
        large_layout.addWidget(self.large_desc)

        layout.addWidget(self.large_frame)

        layout.addSpacing(12)

        # Progress section (in info box, hidden initially)
        self.progress_frame = create_info_frame()
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(12, 10, 12, 10)
        progress_layout.setSpacing(6)

        self.progress_label = QLabel("Downloading...")
        self.progress_label.setStyleSheet("background: transparent;")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)

        self.size_label = QLabel("0 MB / 244 MB")
        self.size_label.setStyleSheet("font-size: 11px; color: #808080; background: transparent;")
        progress_layout.addWidget(self.size_label)

        self.progress_frame.setVisible(False)
        layout.addWidget(self.progress_frame)

        # Download button (primary style with thick border)
        self.download_btn = create_primary_button("Download Model")
        self.download_btn.clicked.connect(self._start_download)
        layout.addWidget(self.download_btn)

        layout.addStretch()
        self._update_texts()

    def _update_card_styles(self):
        """Update card borders based on selection (system.css style)."""
        selected_style = "QFrame { background-color: #ffffff; border: 2px solid #000000; }"
        # Simple thin border for unselected cards (system.css style)
        normal_style = "QFrame { background-color: #ffffff; border: 1.5px solid #000000; }"
        if self.small_radio.isChecked():
            self.small_frame.setStyleSheet(selected_style)
            self.large_frame.setStyleSheet(normal_style)
        else:
            self.small_frame.setStyleSheet(normal_style)
            self.large_frame.setStyleSheet(selected_style)

    def _update_texts(self):
        self.title.setText(self._t("download_model_title"))
        self.desc.setText(self._t("download_model_description"))
        self.small_radio.setText(self._t("whisper_small_recommended"))
        self.large_radio.setText(self._t("whisper_large"))
        self.download_btn.setText(self._t("download_model"))

    def _start_download(self):
        model = "small" if self.small_radio.isChecked() else "large-v3"
        self.progress_frame.setVisible(True)
        self.download_btn.setEnabled(False)
        self.small_radio.setEnabled(False)
        self.large_radio.setEnabled(False)
        self.download_requested.emit(model)

    def update_progress(self, percent: int, downloaded_mb: float, total_mb: float):
        self.progress_bar.setValue(percent)
        self.size_label.setText(f"{downloaded_mb:.1f} MB / {total_mb:.1f} MB")

    def download_finished(self, success: bool, error: str = ""):
        if success:
            self._download_complete = True
            self.progress_label.setText("✓ " + self._t("download_complete"))
            self.download_btn.setText("✓ " + self._t("download_complete"))
            self.completeChanged.emit()
        else:
            self.download_btn.setEnabled(True)
            self.small_radio.setEnabled(True)
            self.large_radio.setEnabled(True)
            # Show a helpful error message instead of a generic failure label.
            if error:
                self.progress_label.setText(f"{self._t('download_failed')}: {error}")
            else:
                self.progress_label.setText(self._t("download_failed"))

    def isComplete(self) -> bool:
        return self._download_complete

    def get_selected_model(self) -> str:
        return "small" if self.small_radio.isChecked() else "large-v3"


class CompletionPage(QWizardPage):
    """Step 5: Setup complete."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #ffffff;")
        self._t = lambda x: x
        self._build_ui()

    def set_translate_func(self, t: Callable):
        self._t = t
        self._update_texts()

    def _create_checkmark_pixmap(self) -> QPixmap:
        """Create a pixelated checkmark icon."""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(255, 255, 255))

        painter = QPainter(pixmap)
        black = QColor(0, 0, 0)

        # Draw a big checkmark using rectangles (pixelated style)
        # Left part of checkmark (going down-right)
        for i in range(5):
            painter.fillRect(8 + i*4, 28 + i*4, 6, 6, black)

        # Right part of checkmark (going up-right)
        for i in range(8):
            painter.fillRect(24 + i*4, 44 - i*4, 6, 6, black)

        painter.end()
        return pixmap

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Success checkmark icon (large)
        check_label = QLabel()
        check_label.setPixmap(self._create_checkmark_pixmap())
        check_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check_label.setStyleSheet("background: transparent;")
        layout.addWidget(check_label)

        # Title
        self.title = create_title_label("Setup Complete!")
        layout.addWidget(self.title)

        # Subtitle
        self.instructions = create_subtitle_label("MindType is ready to use")
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)

        layout.addSpacing(12)

        # Tip box (info frame)
        self.tip_frame = create_info_frame()
        tip_layout = QVBoxLayout(self.tip_frame)
        tip_layout.setContentsMargins(16, 12, 16, 12)
        tip_layout.setSpacing(6)

        self.mode_note = QLabel("")
        self.mode_note.setWordWrap(True)
        self.mode_note.setStyleSheet("font-weight: bold; background: transparent;")
        self.mode_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip_layout.addWidget(self.mode_note)

        self.tip = QLabel("Tip: Use Ctrl+Alt+V to start recording from any application")
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color: #808080; background: transparent;")
        tip_layout.addWidget(self.tip)

        layout.addWidget(self.tip_frame)
        layout.addStretch()
        self._update_texts()

    def _update_texts(self):
        self.title.setText(self._t("setup_complete"))
        self.instructions.setText(self._t("setup_complete_instructions"))
        self.tip.setText(self._t("setup_tip_tray"))
        # mode_note is set in initializePage() based on wizard choices

    def initializePage(self) -> None:
        """Update completion texts based on wizard flow (demo vs license key)."""
        super().initializePage()
        wiz = self.wizard()
        is_demo = bool(getattr(wiz, "demo_mode", False))
        use_cloud = bool(getattr(wiz, "use_mindtype_cloud", False))
        if is_demo or not use_cloud:
            self.mode_note.setText(self._t("setup_complete_demo_note"))
        else:
            self.mode_note.setText(self._t("setup_complete_cloud_note"))

    # Backward-compat shim (older code may call this).
    def set_credits_balance(self, credits: int):
        self.mode_note.setText(self._t("your_balance") + f": {credits} " + self._t("credits"))


class SetupWizard(QWizard):
    """First-run setup wizard."""

    def __init__(self, config: ConfigManager, translate_func: Callable, license_manager=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._t = translate_func
        self._current_lang = "en"

        # Store choices
        self.demo_mode = True
        self.use_mindtype_cloud = False
        if license_manager is None:
            from ..licensing.license_manager import LicenseManager
            self.license_manager = LicenseManager()
        else:
            self.license_manager = license_manager

        self._setup_ui()
        self._setup_pages()

    def _setup_ui(self):
        self.setWindowTitle(self._t("setup_window_title"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(520, 500)

        # Apply System 7 stylesheet
        self.setStyleSheet(WIZARD_STYLESHEET)

        # Configure buttons
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        self._update_wizard_texts()

        # Style Next and Finish buttons as primary (thick black border)
        next_btn = self.button(QWizard.WizardButton.NextButton)
        if next_btn:
            next_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)

        finish_btn = self.button(QWizard.WizardButton.FinishButton)
        if finish_btn:
            finish_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)

    def _setup_pages(self):
        self.language_page = LanguagePage(self)
        self.language_page.language_changed.connect(self._on_language_changed)
        self.setPage(PAGE_LANGUAGE, self.language_page)

        self.key_or_demo_page = KeyOrDemoPage(self)
        self.setPage(PAGE_KEY_OR_DEMO, self.key_or_demo_page)

        self.license_key_page = LicenseKeyPage(self.license_manager, self)
        self.setPage(PAGE_LICENSE_KEY, self.license_key_page)

        self.model_page = ModelDownloadPage(self)
        self.setPage(PAGE_MODEL_DOWNLOAD, self.model_page)

        self.completion_page = CompletionPage(self)
        self.setPage(PAGE_COMPLETION, self.completion_page)

        # Set initial translations
        self._update_all_translations()

    def _on_language_changed(self, lang_code: str):
        """Update translations when language changes."""
        self._current_lang = lang_code
        self._t = lambda key: get_text(key, lang_code)
        self._update_all_translations()

    def _update_all_translations(self):
        """Update translations on all pages."""
        self.language_page.set_translate_func(self._t)
        self.key_or_demo_page.set_translate_func(self._t)
        self.license_key_page.set_translate_func(self._t)
        self.model_page.set_translate_func(self._t)
        self.completion_page.set_translate_func(self._t)
        self._update_wizard_texts()

    def _update_wizard_texts(self):
        self.setWindowTitle(self._t("setup_window_title"))
        self.setButtonText(QWizard.WizardButton.BackButton, self._t("wizard_back"))
        self.setButtonText(QWizard.WizardButton.NextButton, self._t("wizard_next"))
        self.setButtonText(QWizard.WizardButton.FinishButton, self._t("wizard_finish"))

    def nextId(self) -> int:
        current = self.currentId()

        if current == PAGE_LANGUAGE:
            return PAGE_KEY_OR_DEMO

        if current == PAGE_KEY_OR_DEMO:
            self.demo_mode = self.key_or_demo_page.is_demo_selected()
            self.use_mindtype_cloud = not self.demo_mode
            if self.demo_mode:
                return PAGE_MODEL_DOWNLOAD
            return PAGE_LICENSE_KEY

        if current == PAGE_LICENSE_KEY:
            return PAGE_MODEL_DOWNLOAD

        if current == PAGE_MODEL_DOWNLOAD:
            return PAGE_COMPLETION

        return -1

    def accept(self):
        """Save settings and close wizard."""
        ui_language = self.language_page.get_selected_language()

        self.config.update(
            setup_completed=True,
            ui_language=ui_language,
            use_mindtype_cloud=self.use_mindtype_cloud,
        )

        # Demo mode: do not touch AI summary provider/settings. User can configure later in Settings.
        if self.use_mindtype_cloud:
            self.config.update(llm_provider="mindtype_cloud")

        model = self.model_page.get_selected_model()
        self.config.update(model_size=model)

        logger.info(
            f"Setup wizard completed: language={ui_language}, "
            f"demo={self.demo_mode}, cloud={self.use_mindtype_cloud}"
        )
        super().accept()
