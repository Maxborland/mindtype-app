# MindType - AI Speech-to-Text Desktop Application
# Copyright (c) 2024-2025 Butakov Maksim Vladimirovich. All rights reserved.
# Author: Butakov Maksim Vladimirovich <info@mindtype.space>
#
# This software is the confidential and proprietary information of the Author.

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Для корректного отображения иконки в панели задач Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MindType.App.1.0")

# === FEATURE FLAG: Голосовой ассистент ===
# Установить False для отключения ассистента из билда
ASSISTANT_FEATURE_ENABLED = False

# Смещение оверлея ассистента относительно основного оверлея по вертикали
ASSISTANT_OVERLAY_OFFSET = 50

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt, QRectF, QUrl, QSize
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QPen, QBrush, QDesktopServices, QDragEnterEvent, QDropEvent

from .audio import AudioRecorder
from .config import ConfigManager, DEFAULT_MODELS_DIR
from .accelerator import has_npu, detect_available_providers
from .file_transcriber import (
    FileTranscriptionQueue,
    FileTask,
    FileStatus,
    ALL_EXTENSIONS,
    is_supported_file,
)
from .hotkeys import HotkeyListener, HotkeyRecorder
from .inserter import insert_text, focus_manager
from .licensing import LicenseManager, LicenseStatus
from .licensing.activation_dialog import LicenseActivationDialog, LicenseStatusWidget, TrialExpiredDialog
from .ui.setup_wizard import SetupWizard
from .ui.credits_widget import CreditsBalanceWidget, CreditsRefreshWorker, CreditsHistoryDialog, CreditsHistoryWorker
from .ui.mode_manager import ModeManager, ModeToggleWidget
from .overlay import OverlayWidget
from .report_generator import ReportGenerator
from .transcriber import Transcriber
from .translations import (
    get_text,
    UI_LANGUAGES,
    WHISPER_LANGUAGES,
)
# Импорты ассистента (условные)
if ASSISTANT_FEATURE_ENABLED:
    from .assistant import VoiceAssistant, AssistantConfig, AssistantState, PERSONALITY_TEMPLATES
    from .assistant_overlay import AssistantOverlayWidget
    from .dialog_history import get_dialog_history_manager, Dialog
else:
    # Заглушки для типов
    VoiceAssistant = None  # type: ignore
    AssistantConfig = None  # type: ignore
    AssistantState = None  # type: ignore
    PERSONALITY_TEMPLATES = {}
    AssistantOverlayWidget = None  # type: ignore
    get_dialog_history_manager = None  # type: ignore
    Dialog = None  # type: ignore
from .tts import get_tts_engine, is_edge_tts_available, RUSSIAN_VOICES
from .wake_word import is_openwakeword_available, WakeWordDetector
from .updater import Updater, UpdateInfo

# Импорты из UI модуля
from .ui.styles import STYLESHEET
from .ui.tokens import COLORS, SPACING, TYPOGRAPHY
from .ui.icons import create_app_icon
from .ui.workers import (
    TranscribeWorker,
    ModelDownloadWorker,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    FileTranscriptionWorker,
)
from .ui.widgets import (
    TranscriptionEntry,
    TranscriptionHistoryWidget,
    JournalEntry,
    JournalWidget,
    AssistantDialogHistoryWidget,
    MicLevelWidget,
)
from .ui.file_widgets import (
    DropZoneWidget,
    FileQueueItemWidget,
)
from .ui.layouts import (
    FormRow,
    FormLayout,
    TwoColumnLayout,
    SectionBox,
    ScrollableContent,
    ActionBar,
)
from .ui.components import Separator, EmptyState


# Версия приложения (импортируется из version.py)
from .version import __version__ as APP_VERSION


# =============================================================================
# UI КОМПОНЕНТЫ
# Примечание: STYLESHEET, create_app_icon и воркеры вынесены в модуль app.ui
# =============================================================================


class PromptCustomizationDialog(QMainWindow):
    """Диалог настройки промптов для AI саммаризации."""

    def __init__(self, config_manager, translate_func=None, parent=None):
        super().__init__(parent)
        self._t = translate_func or (lambda x: x)
        self.config = config_manager

        self.setWindowTitle(self._t("customize_prompts"))
        self.setFixedSize(700, 550)

        # Загружаем пресеты
        from .summary_presets import PRESETS, get_preset_prompts, DEFAULT_PRESET
        self._presets = PRESETS
        self._get_preset_prompts = get_preset_prompts
        self._default_preset = DEFAULT_PRESET

        # Текущий пресет из конфига
        self._current_preset = self.config.config.get("summary_preset", DEFAULT_PRESET)
        if self._current_preset not in self._presets:
            self._current_preset = DEFAULT_PRESET

        self._build_ui()
        self._load_prompts()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        layout.setSpacing(SPACING["sm"])

        # Заголовок
        title = QLabel(self._t("prompt_settings"))
        title.setObjectName("panelTitle")
        layout.addWidget(title)

        # Выбор пресета
        preset_layout = QHBoxLayout()
        preset_label = QLabel(self._t("preset") + ":")
        preset_label.setObjectName("bodyBold")
        preset_layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(200)
        for preset_id, preset_data in self._presets.items():
            # Формат: "Название — описание" (переведённые)
            name = self._t(preset_data.get('name_key', preset_id))
            desc = self._t(preset_data.get('description_key', ''))
            display_text = f"{name} — {desc}"
            self.preset_combo.addItem(display_text, preset_id)
        # Устанавливаем текущий пресет
        for i in range(self.preset_combo.count()):
            if self.preset_combo.itemData(i) == self._current_preset:
                self.preset_combo.setCurrentIndex(i)
                break
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        # Табы для разных промптов (используют глобальный STYLESHEET)
        self.prompt_tabs = QTabWidget()

        # Создаём вкладки для каждого промпта
        self.prompt_editors = {}

        prompt_names = [
            ("system", self._t("prompt_system")),
            ("short", self._t("prompt_short")),
            ("extraction", self._t("prompt_extraction")),
            ("aggregation", self._t("prompt_aggregation")),
        ]

        from PyQt6.QtWidgets import QTextEdit

        for key, name in prompt_names:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])

            # Описание
            desc = QLabel(self._get_prompt_description(key))
            desc.setWordWrap(True)
            desc.setObjectName("caption")
            tab_layout.addWidget(desc)

            # Редактор (использует глобальный стиль QTextEdit)
            editor = QTextEdit()
            editor.setObjectName("codeEditor")
            tab_layout.addWidget(editor)

            # Кнопка сброса
            reset_btn = QPushButton(self._t("reset_to_default"))
            reset_btn.clicked.connect(lambda checked, k=key: self._reset_prompt(k))
            tab_layout.addWidget(reset_btn)

            self.prompt_editors[key] = editor
            self.prompt_tabs.addTab(tab, name)

        layout.addWidget(self.prompt_tabs)

        # Кнопки
        buttons_layout = QHBoxLayout()

        # Кнопка сброса всех промптов
        reset_all_btn = QPushButton(self._t("reset_all_prompts"))
        reset_all_btn.clicked.connect(self._reset_all_prompts)
        buttons_layout.addWidget(reset_all_btn)

        buttons_layout.addStretch()

        save_btn = QPushButton(self._t("save"))
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_prompts)
        buttons_layout.addWidget(save_btn)

        cancel_btn = QPushButton(self._t("cancel"))
        cancel_btn.clicked.connect(self.close)
        buttons_layout.addWidget(cancel_btn)

        layout.addLayout(buttons_layout)

        self.setCentralWidget(central)

    def _get_prompt_description(self, key: str) -> str:
        desc_keys = {
            "system": "prompt_desc_system",
            "short": "prompt_desc_short",
            "extraction": "prompt_desc_extraction",
            "aggregation": "prompt_desc_aggregation",
        }
        return self._t(desc_keys.get(key, ""))

    def _get_current_preset_prompts(self) -> dict:
        """Получить промпты текущего пресета."""
        return self._get_preset_prompts(self._current_preset)

    def _on_preset_changed(self, index: int):
        """Обработка смены пресета."""
        preset_id = self.preset_combo.itemData(index)
        if preset_id and preset_id != self._current_preset:
            self._current_preset = preset_id
            # Заполняем редакторы промптами из нового пресета
            preset_prompts = self._get_current_preset_prompts()
            for key, editor in self.prompt_editors.items():
                editor.setPlainText(preset_prompts.get(key, ""))

    def _load_prompts(self):
        """Загрузить промпты из конфига или использовать пресет."""
        saved = self.config.config.get("custom_prompts", {})
        preset_prompts = self._get_current_preset_prompts()

        for key, editor in self.prompt_editors.items():
            # Если есть сохранённый кастомный промпт — используем его, иначе из пресета
            text = saved.get(key, preset_prompts.get(key, ""))
            editor.setPlainText(text)

    def _reset_prompt(self, key: str):
        """Сбросить промпт к значению из текущего пресета."""
        preset_prompts = self._get_current_preset_prompts()
        if key in self.prompt_editors and key in preset_prompts:
            self.prompt_editors[key].setPlainText(preset_prompts[key])

    def _reset_all_prompts(self):
        """Сбросить все промпты к значениям текущего пресета."""
        preset_prompts = self._get_current_preset_prompts()
        for key, editor in self.prompt_editors.items():
            if key in preset_prompts:
                editor.setPlainText(preset_prompts[key])
        # Очищаем кастомные промпты в конфиге
        self.config.update(custom_prompts={}, summary_preset=self._current_preset)
        # Показываем сообщение
        preset_name = self._presets[self._current_preset]["name"]
        from PyQt6.QtWidgets import QMessageBox
        msg = self._t("prompts_reset_message").replace("{preset}", preset_name)
        QMessageBox.information(self, self._t("prompts_reset"), msg)

    def _save_prompts(self):
        """Сохранить промпты и пресет в конфиг."""
        preset_prompts = self._get_current_preset_prompts()
        custom_prompts = {}

        for key, editor in self.prompt_editors.items():
            text = editor.toPlainText().strip()
            # Сохраняем только если отличается от пресета
            if text and text != preset_prompts.get(key, ""):
                custom_prompts[key] = text

        self.config.update(custom_prompts=custom_prompts, summary_preset=self._current_preset)
        self.close()


class MainWindow(QMainWindow):
    hotkey_press_signal = pyqtSignal()
    hotkey_release_signal = pyqtSignal()
    hotkey_recorded_signal = pyqtSignal(str)
    waveform_signal = pyqtSignal(list)
    mic_level_signal = pyqtSignal(float)
    thinking_signal = pyqtSignal(str)  # Для AI thinking output
    # Сигналы ассистента (для thread-safe обновления UI)
    assistant_state_signal = pyqtSignal(object)  # AssistantState
    assistant_transcript_signal = pyqtSignal(str)
    assistant_response_signal = pyqtSignal(str)
    assistant_level_signal = pyqtSignal(float)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("MindType")
        self.setWindowIcon(create_app_icon(64))
        self.setMinimumSize(950, 750)
        self.resize(1000, 780)

        self.config = ConfigManager()
        self.audio = AudioRecorder()
        backend = self.config.config.get("transcriber_backend", "auto")
        self.transcriber = Transcriber(backend=backend)
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.hotkey_recorder: Optional[HotkeyRecorder] = None

        # Determine models directory
        exe_path = Path(sys.executable).resolve()
        exe_dir = exe_path.parent

        # Check if we're in Nuitka standalone dist (MindType.exe next to python.exe)
        is_nuitka_dist = (exe_dir / "MindType.exe").exists()
        is_compiled = getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__") or is_nuitka_dist

        if is_compiled:
            self.models_dir = exe_dir / "models"
        else:
            self.models_dir = Path(self.config.config.get("models_dir", str(DEFAULT_MODELS_DIR)))

        # Ensure models directory exists
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._transcribe_thread: Optional[TranscribeWorker] = None
        self._download_thread: Optional[ModelDownloadWorker] = None
        self.last_text: str = ""
        self._auto_insert_pending = False
        self._recording_hotkey = False
        self._recording_start_time = None  # Время начала записи для учёта trial
        self._really_quit = False  # Флаг для полного выхода
        self._transcription_in_progress = False  # Флаг активной транскрипции

        # Текущий язык интерфейса
        self._ui_lang = self.config.config.get("ui_language", "ru")

        # Система лицензирования
        self.license_manager = LicenseManager()

        # Инициализация UI элементов ассистента (будут созданы позже в _build_ui)
        self.assistant_enable_check = None

        # Система обновлений
        self.updater = Updater()
        self._update_check_worker: Optional[UpdateCheckWorker] = None
        self._update_download_worker: Optional[UpdateDownloadWorker] = None

        # Overlay виджет
        self.overlay = OverlayWidget()
        self._apply_overlay_settings()

        # Оверлей диалога ассистента (System 7 style)
        self.assistant_overlay = None
        if ASSISTANT_FEATURE_ENABLED:
            self.assistant_overlay = AssistantOverlayWidget()
            # Используем те же настройки позиции/отступа, что и у overlay транскрипции
            cfg = self.config.config
            self.assistant_overlay.set_corner(cfg.get("overlay_position", "bottom-center"))
            # Чуть выше, чтобы не пересекаться с основным overlay
            self.assistant_overlay.set_margin(int(cfg.get("overlay_margin", 20)) + ASSISTANT_OVERLAY_OFFSET)
            self.assistant_overlay.hide_overlay()
            # Сигналы от оверлея подключаются в _connect_assistant_signals()

        # Системный трей
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._setup_tray()

        # Голосовой ассистент
        self.voice_assistant = None
        self._assistant_hotkey_listener = None
        self._assistant_hotkey_recorder = None
        if ASSISTANT_FEATURE_ENABLED:
            self._init_voice_assistant()
            self._init_assistant_hotkey()

        # Инициализация переменных для вкладки файлов
        self._file_tasks: List[FileTask] = []
        # key = resolved Path to input file
        self._file_widgets: dict[Path, "FileQueueItemWidget"] = {}
        self._file_queue: Optional[FileTranscriptionQueue] = None
        self._file_worker: Optional[FileTranscriptionWorker] = None
        self._output_dir = Path.home() / "Documents" / "MindType Transcriptions"

        self._build_ui()
        self._connect_signals()
        self._load_initial_state()
        self._init_hotkey()
        self._setup_focus_manager()

        # Check if models exist, show download dialog if not
        QTimer.singleShot(500, self._check_models_on_startup)

    def _check_models_on_startup(self) -> None:
        """Check if setup is complete and models are available."""
        # Check if first-run setup was completed
        setup_completed = self.config.config.get("setup_completed", False)

        if not setup_completed:
            # Show full setup wizard for new users
            self._show_setup_wizard()
        elif not self._has_any_model():
            # Setup done but no models - show model download only
            self._show_first_run_dialog()

    def _show_setup_wizard(self) -> None:
        """Show the first-run setup wizard."""
        wizard = SetupWizard(self.config, self._t, self)

        # Connect model download signal - pass wizard directly via lambda
        wizard.model_page.download_requested.connect(
            lambda model_size: self._on_wizard_model_download(model_size, wizard)
        )

        if wizard.exec():
            # Wizard completed successfully
            logger.info("Setup wizard completed")

            # Refresh UI with new settings
            self._apply_config()

            # Initialize MindType Cloud provider if selected
            if self.config.config.get("use_mindtype_cloud", False):
                self._init_mindtype_cloud()
        else:
            logger.info("Setup wizard cancelled")

    def _on_wizard_model_download(self, model_size: str, wizard: "SetupWizard") -> None:
        """Handle model download request from wizard."""
        logger.info(f"Starting model download: {model_size}")

        # Start download using existing ModelDownloadWorker
        from .ui.workers import ModelDownloadWorker

        downloader = ModelDownloadWorker(self.transcriber, model_size, self.models_dir)
        downloader.progress.connect(
            lambda status, current, total: wizard.model_page.update_progress(
                int(current / max(total, 1) * 100) if total > 0 else 0,
                current / (1024 * 1024) if total > 0 else 0,
                total / (1024 * 1024) if total > 0 else 0,
            )
        )
        downloader.finished.connect(
            lambda path, err: wizard.model_page.download_finished(err == "")
        )
        downloader.start()
        self._download_worker = downloader  # Keep reference
        logger.info("Model download worker started")

    def _init_mindtype_cloud(self) -> None:
        """Initialize MindType Cloud provider."""
        try:
            from .llm.mindtype_cloud import MindTypeCloudProvider

            # Получить лицензионный ключ из LicenseManager
            license_info = self.license_manager.get_license_info()
            license_key = license_info.license_key or ""
            self._cloud_provider = MindTypeCloudProvider(license_key=license_key)

            # Update credits balance widget if exists
            if hasattr(self, '_credits_widget'):
                self._refresh_credits_balance()

            logger.info("MindType Cloud provider initialized")
        except Exception as e:
            logger.error(f"Failed to initialize MindType Cloud: {e}")

    def _refresh_credits_balance(self) -> None:
        """Refresh credits balance from server."""
        if not hasattr(self, '_cloud_provider') or not self._cloud_provider:
            return

        if not hasattr(self, '_credits_widget'):
            return

        self._credits_widget.set_loading(True)

        # Use background worker to avoid blocking UI
        worker = CreditsRefreshWorker(self._cloud_provider, self)
        worker.balance_fetched.connect(self._on_credits_fetched)
        worker.error_occurred.connect(self._on_credits_error)
        worker.start()
        self._credits_worker = worker  # Keep reference

    def _on_credits_fetched(self, credits: int) -> None:
        """Handle credits balance fetched."""
        if hasattr(self, '_credits_widget'):
            self._credits_widget.set_balance(credits)
            logger.info(f"Credits balance updated: {credits}")

    def _on_credits_error(self, error: str) -> None:
        """Handle credits fetch error."""
        if hasattr(self, '_credits_widget'):
            self._credits_widget.set_loading(False)
            logger.warning(f"Failed to fetch credits: {error}")

    def _on_credits_history_requested(self) -> None:
        """Загрузить и показать историю кредитов."""
        if not hasattr(self, '_cloud_provider') or not self._cloud_provider:
            return

        worker = CreditsHistoryWorker(self._cloud_provider, self)
        worker.history_fetched.connect(self._on_credits_history_fetched)
        worker.error_occurred.connect(
            lambda err: logger.warning(f"Failed to fetch credits history: {err}")
        )
        worker.start()
        self._history_worker = worker  # Keep reference

    def _on_credits_history_fetched(self, credits: int, history: list) -> None:
        """Показать диалог истории кредитов."""
        # Обновляем баланс
        if hasattr(self, '_credits_widget'):
            self._credits_widget.set_balance(credits)

        dialog = CreditsHistoryDialog(
            history=history,
            translate_func=self._t,
            parent=self,
        )
        dialog.exec()

    def _apply_config(self) -> None:
        """Apply configuration changes after setup wizard."""
        cfg = self.config.config

        # Update UI language
        ui_lang = cfg.get("ui_language", "ru")
        self._ui_lang = ui_lang
        idx = self.ui_lang_box.findData(ui_lang)
        if idx >= 0:
            self.ui_lang_box.setCurrentIndex(idx)

        # Update credits widget visibility based on llm_provider
        use_cloud = cfg.get("llm_provider", "") == "mindtype_cloud"
        if hasattr(self, '_credits_widget'):
            self._credits_widget.setVisible(use_cloud)

        # Initialize cloud provider if needed
        if use_cloud:
            self._init_mindtype_cloud()

        logger.info("Configuration applied from setup wizard")

    def _has_any_model(self) -> bool:
        """Check if at least one model is downloaded."""
        if not self.models_dir.exists():
            return False

        # Проверяем ggml-*.bin файлы в корне (whisper.cpp модели)
        for f in self.models_dir.iterdir():
            if f.is_file() and f.name.startswith("ggml-") and f.name.endswith(".bin"):
                return True

        # Проверяем подпапки с HuggingFace моделями
        for subdir in self.models_dir.iterdir():
            if not subdir.is_dir():
                continue

            # HuggingFace модели содержат config.json
            if (subdir / "config.json").exists():
                # Дополнительно проверяем наличие весов модели
                has_weights = (
                    (subdir / "model.bin").exists() or
                    (subdir / "model.safetensors").exists() or
                    (subdir / "pytorch_model.bin").exists() or
                    any(f.name.endswith(".safetensors") for f in subdir.iterdir() if f.is_file())
                )
                if has_weights:
                    return True
                # Если есть только config.json без весов - модель не полностью загружена
                # но config.json достаточно для определения что модель начала качаться
                # Для пользователя важнее не показывать диалог если модель есть
                # Проверим размер папки - если > 50MB, считаем что модель есть
                try:
                    total_size = sum(f.stat().st_size for f in subdir.rglob("*") if f.is_file())
                    if total_size > 50 * 1024 * 1024:  # 50 MB
                        return True
                except Exception:
                    pass

        return False

    def _show_first_run_dialog(self) -> None:
        """Show dialog to download model on first run."""
        from PyQt6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("first_run_title"))
        dialog.setFixedWidth(480)
        dialog.setModal(True)
        # Использует глобальный STYLESHEET

        layout = QVBoxLayout(dialog)
        layout.setSpacing(SPACING["md"])
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])

        # Welcome message
        welcome = QLabel(self._t("first_run_welcome"))
        welcome.setWordWrap(True)
        layout.addWidget(welcome)

        # Model selection
        model_label = QLabel(self._t("first_run_select_model"))
        model_label.setObjectName("bodyBold")
        layout.addWidget(model_label)

        # Dropdown for model selection
        self._first_run_model_combo = QComboBox()

        models_info = [
            ("tiny", "~75 MB", self._t("model_tiny_desc")),
            ("small", "~150 MB", self._t("model_small_desc")),
            ("medium", "~1.5 GB", self._t("model_medium_desc")),
            ("large-v3", "~3 GB", self._t("model_large_desc")),
        ]

        for model_id, size, desc in models_info:
            # Check if model is already downloaded
            model_path = self.models_dir / model_id
            is_downloaded = model_path.exists() and (model_path / "model.bin").exists()

            if is_downloaded:
                label = f"[OK] {model_id} ({size}) - {desc}"
            else:
                label = f"{model_id} ({size}) - {desc}"

            self._first_run_model_combo.addItem(label, model_id)

        layout.addWidget(self._first_run_model_combo)

        # Progress section (hidden initially)
        self._first_run_progress = QProgressBar()
        self._first_run_progress.setVisible(False)
        layout.addWidget(self._first_run_progress)

        self._first_run_status = QLabel("")
        self._first_run_status.setVisible(False)
        self._first_run_status.setWordWrap(True)
        layout.addWidget(self._first_run_status)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._first_run_download_btn = QPushButton(self._t("download_model"))
        self._first_run_download_btn.clicked.connect(lambda: self._start_first_run_download(dialog))
        btn_layout.addWidget(self._first_run_download_btn)

        self._first_run_skip_btn = QPushButton(self._t("skip"))
        self._first_run_skip_btn.clicked.connect(lambda: self._cancel_first_run_download(dialog))
        btn_layout.addWidget(self._first_run_skip_btn)

        layout.addLayout(btn_layout)

        dialog.exec()

        # Cancel download if still running when dialog closes
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()

    def _cancel_first_run_download(self, dialog) -> None:
        """Cancel download and close dialog."""
        if self._download_thread and self._download_thread.isRunning():
            self._download_thread.cancel()
        dialog.reject()

    def _populate_model_combo(self) -> None:
        """Populate model combo box with download status indicators."""
        self.model_box.clear()
        models = ["large-v3", "medium", "small", "tiny"]

        for name in models:
            # Check both formats: ggml-*.bin (whisper.cpp) and name/model.bin (ONNX)
            ggml_path = self.models_dir / f"ggml-{name}.bin"
            onnx_path = self.models_dir / name
            is_downloaded = (
                ggml_path.exists()
                or (onnx_path.exists() and (onnx_path / "model.bin").exists())
            )

            if is_downloaded:
                self.model_box.addItem(f"[OK] {name}", name)
            else:
                self.model_box.addItem(name, name)

    def _set_model_combo_value(self, model_name: str) -> None:
        """Set model combo box value by model name (data)."""
        for i in range(self.model_box.count()):
            if self.model_box.itemData(i) == model_name:
                self.model_box.setCurrentIndex(i)
                return
        # Fallback: try to find by text
        idx = self.model_box.findText(model_name)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)

    def _start_first_run_download(self, dialog) -> None:
        """Start downloading the selected model."""
        self._first_run_progress.setVisible(True)
        self._first_run_status.setVisible(True)
        self._first_run_download_btn.setEnabled(False)
        self._first_run_model_combo.setEnabled(False)
        self._first_run_skip_btn.setText(self._t("cancel"))

        selected_model = self._first_run_model_combo.currentData()

        worker = ModelDownloadWorker(
            self.transcriber, selected_model, self.models_dir
        )
        worker.progress.connect(self._on_first_run_progress)
        worker.finished.connect(lambda path, err: self._on_first_run_finished(dialog, path, err, selected_model))
        self._download_thread = worker
        worker.start()

    def _on_first_run_progress(self, status: str, current: int, total: int) -> None:
        self._first_run_progress.setValue(current)
        self._first_run_status.setText(status)

    def _on_first_run_finished(self, dialog, path: str, err: str, selected_model: str) -> None:
        if err == "cancelled":
            # Download was cancelled, just close dialog
            return
        elif err:
            self._first_run_status.setText(f"Error: {err}")
            self._first_run_download_btn.setEnabled(True)
            self._first_run_model_combo.setEnabled(True)
            self._first_run_skip_btn.setEnabled(True)
        else:
            # Update config with downloaded model and refresh combo
            self.config.update(model_size=selected_model)
            self._populate_model_combo()  # Refresh to show [OK]
            self._set_model_combo_value(selected_model)
            dialog.accept()

    def _init_voice_assistant(self) -> None:
        """Инициализировать голосового ассистента."""
        try:
            cfg = self.config.config

            # Создаем конфигурацию ассистента
            assistant_config = AssistantConfig(
                wake_word=cfg.get("assistant_wake_word", "hey_jarvis"),
                wake_word_threshold=cfg.get("assistant_wake_threshold", 0.5),
                beep_on_wake=cfg.get("assistant_beep_on_wake", True),
                tts_voice=cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural"),
                tts_rate=cfg.get("assistant_tts_rate", 0),
                tts_language=cfg.get("assistant_tts_language", "ru"),
                # Используем общие настройки OpenRouter
                openrouter_model=cfg.get("openrouter_model", "anthropic/claude-3-haiku"),
                openrouter_api_key=cfg.get("openrouter_api_key", ""),
                system_prompt=cfg.get("assistant_system_prompt", PERSONALITY_TEMPLATES["friendly"]["prompt"]),
                normalize_numbers=cfg.get("assistant_normalize_numbers", True),
                normalize_dates=cfg.get("assistant_normalize_dates", True),
                normalize_translit=cfg.get("assistant_normalize_translit", True),
                normalize_abbreviations=cfg.get("assistant_normalize_abbrev", True),
                microphone_device=self._get_current_mic_index(),
                recording_timeout=cfg.get("assistant_recording_timeout", 3.0),
                # Параметры модели транскрипции
                model_size=cfg.get("model_size", "large-v3"),
                compute_type=cfg.get("compute_type", "int8"),
                device=cfg.get("device", "auto"),
                models_dir=str(self.models_dir),
                beam_size=int(cfg.get("beam_size", 5)),
                vad_filter=False,  # Отключен для ассистента, команды короткие
            )

            # Создаем ассистента
            self.voice_assistant = VoiceAssistant(assistant_config)
            # Передаем transcriber
            self.voice_assistant.set_transcriber(self.transcriber)
            # Подключаем callbacks через сигналы (thread-safe)
            # Callback'и вызываются из фонового потока, поэтому emit'им сигналы
            self.voice_assistant.set_state_callback(lambda s: self.assistant_state_signal.emit(s))
            self.voice_assistant.set_transcript_callback(lambda t: self.assistant_transcript_signal.emit(t))
            self.voice_assistant.set_response_callback(lambda r: self.assistant_response_signal.emit(r))
            self.voice_assistant.set_level_callback(lambda l: self.assistant_level_signal.emit(l))

            # Запускаем если включен
            if cfg.get("assistant_enabled", False):
                self.voice_assistant.start()

        except Exception as e:
            logger.error(f"Ошибка инициализации голосового ассистента: {e}")
            self.voice_assistant = None

    def _on_assistant_state_changed(self, state) -> None:
        """Обновление оверлея ассистента при смене состояния."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return

        from .assistant_overlay import AssistantOverlayState

        # Не показываем, если ассистент выключен
        if not self.config.config.get("assistant_enabled", False):
            return

        # Маппинг состояний ассистента на состояния оверлея
        state_map = {
            AssistantState.IDLE: AssistantOverlayState.HIDDEN,
            AssistantState.CALIBRATING: AssistantOverlayState.CALIBRATING,
            AssistantState.LISTENING: AssistantOverlayState.LISTENING,
            AssistantState.TRANSCRIBING: AssistantOverlayState.TRANSCRIBING,
            AssistantState.PROCESSING: AssistantOverlayState.THINKING,
            AssistantState.SPEAKING: AssistantOverlayState.SPEAKING,
            AssistantState.WAITING: AssistantOverlayState.WAITING,
            AssistantState.ERROR: AssistantOverlayState.ERROR,
        }

        target_state = state_map.get(state, AssistantOverlayState.HIDDEN)
        self.assistant_overlay.set_state(target_state)

        # Логика автоскрытия для IDLE/ERROR переехала в AssistantOverlayWidget (через таймеры)
        # но мы можем оставить спец. обработку если нужно
        if state == AssistantState.ERROR:
            # Можно вывести сообщение об ошибке в лог или статусную строку
            pass

    def _on_assistant_transcript(self, text: str) -> None:
        """Добавить сообщение пользователя в оверлей."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return
        if not self.config.config.get("assistant_enabled", False):
            return
        self.assistant_overlay.append_message("user", text)

    def _on_assistant_response(self, text: str) -> None:
        """Добавить ответ ассистента в оверлей."""
        if not ASSISTANT_FEATURE_ENABLED or not self.assistant_overlay:
            return
        if not self.config.config.get("assistant_enabled", False):
            return
        self.assistant_overlay.append_message("assistant", text)

    def _on_assistant_overlay_stop(self) -> None:
        """Стоп из оверлея: прервать текущую операцию и начать слушать заново."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "interrupt"):
            self.voice_assistant.interrupt(start_listening=True)  # type: ignore[attr-defined]
        else:
            self.voice_assistant.stop()

    def _on_assistant_overlay_cancel(self) -> None:
        """Отмена из оверлея: просто остановить всё и уйти в IDLE."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "interrupt"):
            self.voice_assistant.interrupt(start_listening=False)  # type: ignore[attr-defined]
        else:
            self.voice_assistant.stop()
        if self.assistant_overlay:
            self.assistant_overlay.hide_overlay()

    def _on_assistant_overlay_send(self) -> None:
        """Принудительная отправка аудио на обработку."""
        if not self.voice_assistant:
            return
        if hasattr(self.voice_assistant, "force_send"):
            self.voice_assistant.force_send()  # type: ignore[attr-defined]

    def _on_assistant_overlay_new_dialog(self) -> None:
        """Новый диалог: очистить контекст и UI."""
        if self.assistant_overlay:
            self.assistant_overlay.clear_messages()
        if self.voice_assistant:
            self.voice_assistant.clear_history()

    def _on_assistant_overlay_closed(self) -> None:
        """Пользователь закрыл оверлей: остановить всё и скрыть."""
        if self.voice_assistant:
            if hasattr(self.voice_assistant, "interrupt"):
                self.voice_assistant.interrupt(start_listening=False)
            else:
                self.voice_assistant.stop()
        if self.assistant_overlay:
            self.assistant_overlay.hide_overlay()

    def _load_assistant_settings(self) -> None:
        """Загрузить настройки ассистента в UI."""
        # Проверяем, что UI ассистента уже создан
        if self.assistant_enable_check is None:
            return

        cfg = self.config.config

        # Включение
        self.assistant_enable_check.setChecked(cfg.get("assistant_enabled", False))

        # Hotkey
        self.assistant_hotkey_edit.setText(cfg.get("assistant_hotkey", "ctrl+shift+a"))

        # Wake word
        self.assistant_use_wake_word_check.setChecked(cfg.get("assistant_use_wake_word", True))
        wake_word = cfg.get("assistant_wake_word", "hey_jarvis")
        idx = self.assistant_wake_combo.findData(wake_word)
        if idx >= 0:
            self.assistant_wake_combo.setCurrentIndex(idx)
        self.assistant_beep_check.setChecked(cfg.get("assistant_beep_on_wake", True))

        # TTS
        tts_lang = cfg.get("assistant_tts_language", "ru")
        idx = self.assistant_tts_lang_combo.findData(tts_lang)
        if idx >= 0:
            self.assistant_tts_lang_combo.setCurrentIndex(idx)
        self._load_tts_voices(tts_lang)

        tts_voice = cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural")
        idx = self.assistant_voice_combo.findData(tts_voice)
        if idx >= 0:
            self.assistant_voice_combo.setCurrentIndex(idx)

        tts_rate = cfg.get("assistant_tts_rate", 0)
        self.assistant_speed_slider.setValue(tts_rate)
        self._update_speed_label(tts_rate)

        # Личность
        personality = cfg.get("assistant_personality", "friendly")
        idx = self.assistant_personality_combo.findData(personality)
        if idx >= 0:
            self.assistant_personality_combo.setCurrentIndex(idx)

        system_prompt = cfg.get("assistant_system_prompt", PERSONALITY_TEMPLATES["friendly"]["prompt"])
        self.assistant_system_prompt_edit.setText(system_prompt)

    def _load_tts_voices(self, language: str) -> None:
        """Загрузить голоса TTS для выбранного языка."""
        self.assistant_voice_combo.clear()

        if not is_edge_tts_available():
            self.assistant_voice_combo.addItem("Edge TTS не установлен", "")
            return

        try:
            tts_engine = get_tts_engine()
            # Получаем голоса для языка (первые 2 символа из locale)
            voices = tts_engine.get_voices(language)

            if not voices:
                self.assistant_voice_combo.addItem("Нет доступных голосов", "")
                return

            for voice in voices[:10]:  # Ограничим до 10 голосов
                self.assistant_voice_combo.addItem(voice.display_name, voice.short_name)

        except Exception as e:
            logger.error(f"Ошибка загрузки TTS голосов: {e}")
            self.assistant_voice_combo.addItem("Ошибка загрузки", "")

    def _update_speed_label(self, value: int) -> None:
        """Обновить метку скорости речи."""
        speed_factor = 1.0 + (value / 100.0)
        self.assistant_speed_label.setText(f"{speed_factor:.1f}x")

    def _connect_assistant_signals(self) -> None:
        """Подключить сигналы ассистента."""
        if not ASSISTANT_FEATURE_ENABLED:
            return

        # Проверяем, что UI создан
        if self.assistant_enable_check is None:
            return

        # Сигналы для thread-safe обновления UI из фоновых потоков
        self.assistant_state_signal.connect(self._on_assistant_state_changed)
        self.assistant_transcript_signal.connect(self._on_assistant_transcript)
        self.assistant_response_signal.connect(self._on_assistant_response)
        if self.assistant_overlay:
            self.assistant_level_signal.connect(self.assistant_overlay.update_level)

            # Сигналы от оверлея
            self.assistant_overlay.cancelled.connect(self._on_assistant_overlay_cancel)
            self.assistant_overlay.stop_clicked.connect(self._on_assistant_overlay_stop)
            self.assistant_overlay.new_dialog_clicked.connect(self._on_assistant_overlay_new_dialog)
            self.assistant_overlay.closed.connect(self._on_assistant_overlay_closed)
            self.assistant_overlay.send_clicked.connect(self._on_assistant_overlay_send)

        # Включение/выключение
        self.assistant_enable_check.toggled.connect(self._on_assistant_enable_toggle)

        # Hotkey
        self.assistant_hotkey_record_btn.clicked.connect(self._on_record_assistant_hotkey)

        # Wake word
        self.assistant_use_wake_word_check.toggled.connect(
            lambda v: self.config.update(assistant_use_wake_word=v)
        )
        self.assistant_wake_combo.currentIndexChanged.connect(
            lambda: self.config.update(assistant_wake_word=self.assistant_wake_combo.currentData())
        )
        self.assistant_beep_check.toggled.connect(
            lambda v: self.config.update(assistant_beep_on_wake=v)
        )

        # TTS
        self.assistant_tts_lang_combo.currentIndexChanged.connect(self._on_assistant_tts_lang_change)
        self.assistant_voice_combo.currentIndexChanged.connect(
            lambda: self.config.update(assistant_tts_voice=self.assistant_voice_combo.currentData())
        )
        self.assistant_speed_slider.valueChanged.connect(self._on_assistant_speed_change)
        self.assistant_test_voice_btn.clicked.connect(self._on_test_assistant_voice)

        # Нормализация - удалено, всегда включено

        # Личность
        self.assistant_personality_combo.currentIndexChanged.connect(self._on_assistant_personality_change)
        self.assistant_system_prompt_edit.textChanged.connect(self._on_assistant_prompt_change)

    def _on_assistant_enable_toggle(self, enabled: bool) -> None:
        """Обработка включения/выключения ассистента."""
        self.config.update(assistant_enabled=enabled)

        if self.voice_assistant:
            if enabled:
                if not is_openwakeword_available():
                    QMessageBox.warning(
                        self,
                        "openWakeWord не установлен",
                        "Для работы голосового ассистента необходимо установить openWakeWord:\n\npip install openwakeword"
                    )
                    self.assistant_enable_check.setChecked(False)
                    return

                if not is_edge_tts_available():
                    QMessageBox.warning(
                        self,
                        "edge-tts не установлен",
                        "Для работы голосового ассистента необходимо установить edge-tts:\n\npip install edge-tts"
                    )
                    self.assistant_enable_check.setChecked(False)
                    return

                self.voice_assistant.start()
            else:
                self.voice_assistant.stop()

    def _on_assistant_tts_lang_change(self) -> None:
        """Обработка смены языка TTS."""
        lang = self.assistant_tts_lang_combo.currentData()
        self.config.update(assistant_tts_language=lang)
        self._load_tts_voices(lang)

    def _on_assistant_speed_change(self, value: int) -> None:
        """Обработка изменения скорости речи."""
        self.config.update(assistant_tts_rate=value)
        self._update_speed_label(value)

    def _on_test_assistant_voice(self) -> None:
        """Тест голоса ассистента."""
        if not is_edge_tts_available():
            QMessageBox.warning(self, "Ошибка", "edge-tts не установлен")
            return

        voice = self.assistant_voice_combo.currentData()
        rate = self.assistant_speed_slider.value()

        try:
            tts = get_tts_engine()
            tts.set_voice(voice)
            tts.set_rate(rate)

            test_text = "Привет! Я твой голосовой ассистент."
            tts.speak(test_text, blocking=False)
        except Exception as e:
            logger.error(f"Ошибка теста голоса: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось протестировать голос:\n{e}")

    def _on_assistant_personality_change(self) -> None:
        """Обработка смены шаблона личности."""
        personality = self.assistant_personality_combo.currentData()
        self.config.update(assistant_personality=personality)

        if personality != "custom" and personality in PERSONALITY_TEMPLATES:
            prompt = PERSONALITY_TEMPLATES[personality]["prompt"]
            self.assistant_system_prompt_edit.setText(prompt)

    def _on_assistant_prompt_change(self) -> None:
        """Обработка изменения system prompt."""
        prompt = self.assistant_system_prompt_edit.toPlainText()
        self.config.update(assistant_system_prompt=prompt)

    def _on_record_assistant_hotkey(self) -> None:
        """Записать новые горячие клавиши для ассистента."""
        self.assistant_hotkey_record_btn.setEnabled(False)
        self.assistant_hotkey_edit.setText("Нажмите клавиши...")

        # Используем тот же рекордер что для основного hotkey
        def on_hotkey_recorded(combo: str) -> None:
            self.assistant_hotkey_edit.setText(combo)
            self.config.update(assistant_hotkey=combo)
            self.assistant_hotkey_record_btn.setEnabled(True)
            self._reinit_assistant_hotkey()

        self._assistant_hotkey_recorder = HotkeyRecorder(on_hotkey_recorded)
        self._assistant_hotkey_recorder.start()

    def _init_assistant_hotkey(self) -> None:
        """Инициализировать горячие клавиши ассистента."""
        hotkey_combo = self.config.config.get("assistant_hotkey", "ctrl+shift+a")
        if not hotkey_combo:
            return

        try:
            if hasattr(self, '_assistant_hotkey_listener') and self._assistant_hotkey_listener:
                self._assistant_hotkey_listener.stop()

            self._assistant_hotkey_listener = HotkeyListener(
                hotkey_combo,
                handler=self._on_assistant_hotkey_press,
            )
            self._assistant_hotkey_listener.start()
            logger.info(f"[Assistant] Горячие клавиши ассистента зарегистрированы: {hotkey_combo}")
        except Exception as e:
            logger.error(f"[Assistant] Ошибка регистрации горячих клавиш: {e}")

    def _reinit_assistant_hotkey(self) -> None:
        """Переинициализировать горячие клавиши ассистента."""
        self._init_assistant_hotkey()

    def _on_assistant_hotkey_press(self) -> None:
        """Обработка нажатия горячих клавиш ассистента."""
        logger.info("[Assistant] 🎹 Горячие клавиши нажаты! Активирую ассистента...")

        if not self.voice_assistant:
            logger.warning("[Assistant] Ассистент не инициализирован")
            return

        if not self.config.config.get("assistant_enabled", False):
            logger.warning("[Assistant] Ассистент отключён в настройках")
            return

        # Публичная активация: если ассистент говорит — прервёт и начнёт слушать
        if hasattr(self.voice_assistant, "activate"):
            self.voice_assistant.activate()
        else:
            # Fallback для старых версий
            if hasattr(self.voice_assistant, "_on_wake_word_detected"):
                self.voice_assistant._on_wake_word_detected()
            else:
                logger.error("[Assistant] Метод активации не найден")

    def _t(self, key: str) -> str:
        """Получить перевод для текущего языка."""
        return get_text(key, self._ui_lang)

    def _build_ui(self) -> None:
        # Применяем стиль Classic Mac OS
        self.setStyleSheet(STYLESHEET)

        # Главный контейнер
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        main_layout.setSpacing(SPACING["lg"])

        # Header bar с кредитами и переключателем режима
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 4)

        # Credits widget (показывается только для MindType Cloud)
        self._credits_widget = CreditsBalanceWidget(self._t, self)
        self._credits_widget.history_requested.connect(self._on_credits_history_requested)
        is_mindtype_cloud = self.config.config.get("llm_provider", "") == "mindtype_cloud"
        self._credits_widget.setVisible(is_mindtype_cloud)
        header_layout.addWidget(self._credits_widget)

        # Инициализировать MindType Cloud если выбран
        if is_mindtype_cloud:
            self._init_mindtype_cloud()

        header_layout.addStretch()

        # Mode toggle (Simple/Advanced)
        self._mode_manager = ModeManager(self, self.config, self._t)
        self._mode_toggle = ModeToggleWidget(self._mode_manager, self._t, self)
        header_layout.addWidget(self._mode_toggle)

        main_layout.addLayout(header_layout)

        # Вкладки - порядок: Основные, Саммари, Настройки
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), self._t("basic"))
        self.tabs.addTab(self._build_files_tab(), self._t("files_tab"))
        self.tabs.addTab(self._build_additional_tab(), self._t("additional"))
        main_layout.addWidget(self.tabs)

        # Журнал событий (внизу окна)
        main_layout.addWidget(self._build_journal_section())

        self.setCentralWidget(central)

    def _build_basic_tab(self) -> QWidget:
        """Построить вкладку основных настроек."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        tab_layout.setSpacing(SPACING["sm"])

        # Форма с полями
        form = FormLayout(label_width=140, spacing=SPACING["sm"])

        # Аудио вход
        self.mic_box = QComboBox()
        self._audio_input_row = form.add_row(self._t("audio_input"), self.mic_box)
        self.audio_input_label = self._audio_input_row.label

        # Хоткей
        hotkey_widget = QWidget()
        hotkey_layout = QHBoxLayout(hotkey_widget)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.setSpacing(SPACING["sm"])
        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setPlaceholderText("ctrl+alt+v")
        self.hotkey_edit.setReadOnly(True)
        self.hotkey_record_btn = QPushButton(self._t("record_hotkey"))
        hotkey_layout.addWidget(self.hotkey_edit)
        hotkey_layout.addWidget(self.hotkey_record_btn)
        self._hotkey_row = form.add_row(self._t("hotkey"), hotkey_widget)
        self.hotkey_label = self._hotkey_row.label

        # Язык транскрипции
        self.trans_lang_box = QComboBox()
        for code, name in WHISPER_LANGUAGES.items():
            display = f"{name} ({code.upper()})" if code != "auto" else name
            self.trans_lang_box.addItem(display, code)
        self._trans_lang_row = form.add_row(self._t("transcription_language"), self.trans_lang_box)
        self.trans_lang_label = self._trans_lang_row.label

        # Статус лицензии
        self.license_status_widget = LicenseStatusWidget(
            self.license_manager,
            translate_func=self._t
        )
        self.license_status_widget.clicked.connect(self._show_license_dialog)
        self._license_row = form.add_row(self._t("license_status"), self.license_status_widget)
        self.license_status_label = self._license_row.label

        # Добавляем форму в таб
        tab_layout.addWidget(form)
        tab_layout.addStretch()

        return tab

    def _build_additional_tab(self) -> QWidget:
        """Построить вкладку дополнительных настроек."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        # Скроллируемый контейнер
        scroll = ScrollableContent(horizontal_scroll=False)

        # === Секция AI Provider ===
        ai_section = SectionBox(self._t("ai_provider"), label_width=140)
        self.ai_section_label = ai_section  # Для совместимости

        # Выбор провайдера
        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(200)
        self.provider_combo.addItem("MindType Cloud", "mindtype_cloud")
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.addItem("Claude (Anthropic)", "anthropic")
        self.provider_combo.addItem("Gemini (Google)", "gemini")
        self.provider_combo.addItem("Ollama (Local)", "ollama")
        self.provider_combo.addItem("OpenRouter (Private)", "openrouter")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self._provider_row = ai_section.form.add_row(self._t("llm_provider"), self.provider_combo)
        self.provider_label = self._provider_row.label

        # API ключ
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setObjectName("monoInput")
        self._api_key_row = ai_section.form.add_row(self._t("api_key"), self.api_key_edit)
        self.api_key_label = self._api_key_row.label

        # Base URL (для Ollama)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("http://localhost:11434")
        self.base_url_edit.setObjectName("monoInput")
        self._base_url_row = ai_section.form.add_row(self._t("base_url"), self.base_url_edit)
        self.base_url_label = self._base_url_row.label

        # Выбор модели с поиском
        model_widget = QWidget()
        model_layout = QHBoxLayout(model_widget)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(SPACING["sm"])
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model_combo.lineEdit().setPlaceholderText(self._t("search_model"))
        self.model_combo.setObjectName("wideCombo")
        self.model_combo.addItem(self._t("select_model"), "")
        self.refresh_models_btn = QPushButton(self._t("refresh_models"))
        self.refresh_models_btn.setObjectName("smallButton")
        self.refresh_models_btn.clicked.connect(self._on_refresh_models)
        model_layout.addWidget(self.model_combo, stretch=1)
        model_layout.addWidget(self.refresh_models_btn)
        self._model_select_row = ai_section.form.add_row(self._t("openrouter_model"), model_widget)
        self.model_select_label = self._model_select_row.label

        # Reasoning mode
        reasoning_widget = QWidget()
        reasoning_layout = QHBoxLayout(reasoning_widget)
        reasoning_layout.setContentsMargins(0, 0, 0, 0)
        reasoning_layout.setSpacing(SPACING["sm"])
        self.reasoning_checkbox = QCheckBox(self._t("reasoning_mode"))
        self.reasoning_checkbox.setToolTip(self._t("reasoning_tooltip"))
        self.reasoning_checkbox.stateChanged.connect(self._on_reasoning_changed)
        self.effort_label = QLabel(self._t("reasoning_effort"))
        self.effort_combo = QComboBox()
        self.effort_combo.addItem(self._t("effort_low"), "low")
        self.effort_combo.addItem(self._t("effort_medium"), "medium")
        self.effort_combo.addItem(self._t("effort_high"), "high")
        self.effort_combo.setCurrentIndex(1)
        self.effort_combo.setObjectName("compactCombo")
        self.effort_combo.currentIndexChanged.connect(self._on_effort_changed)
        reasoning_layout.addWidget(self.reasoning_checkbox)
        reasoning_layout.addWidget(self.effort_label)
        reasoning_layout.addWidget(self.effort_combo)
        reasoning_layout.addStretch()
        ai_section.form.add_widget(reasoning_widget)

        # Загрузка сохранённых настроек провайдера
        cfg = self.config.config
        saved_provider = cfg.get("llm_provider", "openrouter")
        provider_idx = self.provider_combo.findData(saved_provider)
        if provider_idx >= 0:
            self.provider_combo.setCurrentIndex(provider_idx)
        self._load_provider_settings(saved_provider)
        self.reasoning_checkbox.setChecked(cfg.get("llm_reasoning_enabled", True))
        effort = cfg.get("llm_reasoning_effort", "medium")
        effort_idx = self.effort_combo.findData(effort)
        if effort_idx >= 0:
            self.effort_combo.setCurrentIndex(effort_idx)
        self.api_key_edit.textChanged.connect(self._on_api_key_changed)
        self.base_url_edit.textChanged.connect(self._on_base_url_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self._update_provider_fields()

        scroll.content_layout.addWidget(ai_section)

        # === Секция Performance ===
        perf_section = SectionBox(self._t("performance_section"), label_width=140)
        self.perf_section_label = perf_section

        # VAD Filter
        self.vad_toggle = QCheckBox()
        self.vad_toggle.setChecked(True)
        self._vad_row = perf_section.form.add_row(self._t("vad_filter"), self.vad_toggle)
        self.vad_label = self._vad_row.label

        # Размер луча
        beam_widget = QWidget()
        beam_layout = QHBoxLayout(beam_widget)
        beam_layout.setContentsMargins(0, 0, 0, 0)
        beam_layout.setSpacing(SPACING["sm"])
        self.beam_slider = QSlider(Qt.Orientation.Horizontal)
        self.beam_slider.setRange(1, 10)
        self.beam_slider.setValue(5)
        self.beam_value_label = QLabel("5")
        self.beam_value_label.setFixedWidth(30)
        beam_layout.addWidget(self.beam_slider)
        beam_layout.addWidget(self.beam_value_label)
        self._beam_row = perf_section.form.add_row(self._t("beam_size"), beam_widget)
        self.beam_label = self._beam_row.label

        # Квантование
        self.compute_box = QComboBox()
        for ct in ["auto", "int8", "int8_float16", "float16", "float32"]:
            self.compute_box.addItem(ct)
        self._quant_row = perf_section.form.add_row(self._t("quantization"), self.compute_box)
        self.quant_label = self._quant_row.label

        # Устройство
        self.accel_box = QComboBox()
        for mode in ["auto", "npu", "gpu", "cpu"]:
            self.accel_box.addItem(mode)
        self._accel_row = perf_section.form.add_row(self._t("device"), self.accel_box)
        self.accel_label = self._accel_row.label

        # Статус NPU
        if has_npu():
            npu_status = QLabel(f"[OK] {self._t('npu_detected')} ({detect_available_providers()[0]})")
            npu_status.setObjectName("smallBold")
            perf_section.form.add_widget(npu_status)

        # Бэкенд транскрипции
        self.backend_box = QComboBox()
        self.backend_box.addItem(self._t("backend_whispercpp"), "whisper_cpp")
        self.backend_box.addItem(self._t("backend_faster_whisper"), "faster_whisper")
        self.backend_box.addItem(self._t("backend_onnx"), "onnx")
        self._backend_row = perf_section.form.add_row(self._t("whisper_backend"), self.backend_box)
        self.backend_label = self._backend_row.label

        # Модель
        self.model_box = QComboBox()
        self._populate_model_combo()
        self._model_row = perf_section.form.add_row(self._t("model"), self.model_box)
        self.model_label = self._model_row.label

        # Предупреждение о distil
        self.distil_warning = QLabel(self._t("distil_en_only"))
        self.distil_warning.setObjectName("warning")
        perf_section.form.add_widget(self.distil_warning)

        # Кнопка скачивания модели
        self.download_btn = QPushButton(self._t("download_model"))
        self.download_btn.setObjectName("downloadButton")
        perf_section.form.add_widget(self.download_btn)

        # Прогресс скачивания
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.setTextVisible(True)
        perf_section.form.add_widget(self.download_progress)

        self.download_status_label = QLabel("")
        perf_section.form.add_widget(self.download_status_label)

        # Путь модели
        self.models_path_edit = QLineEdit()
        self.models_path_edit.setText(str(self.models_dir))
        self.models_path_edit.setReadOnly(True)
        self._model_path_row = perf_section.form.add_row(self._t("model_path"), self.models_path_edit)
        self.model_path_label = self._model_path_row.label

        scroll.content_layout.addWidget(perf_section)

        # === Секция Overlay ===
        overlay_section = SectionBox(self._t("overlay_section"), label_width=140)
        self.overlay_section_label = overlay_section

        # Позиция
        self.overlay_position_box = QComboBox()
        positions = [
            ("bottom-center", "bottom_center"),
            ("top-center", "top_center"),
            ("bottom-right", "bottom_right"),
            ("bottom-left", "bottom_left"),
            ("top-right", "top_right"),
            ("top-left", "top_left"),
        ]
        for key, text_key in positions:
            self.overlay_position_box.addItem(self._t(text_key), key)
        self._position_row = overlay_section.form.add_row(self._t("position"), self.overlay_position_box)
        self.position_label = self._position_row.label

        # Отступ
        margin_widget = QWidget()
        margin_layout = QHBoxLayout(margin_widget)
        margin_layout.setContentsMargins(0, 0, 0, 0)
        margin_layout.setSpacing(SPACING["sm"])
        self.overlay_margin_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_margin_slider.setRange(0, 100)
        self.overlay_margin_slider.setValue(20)
        self.overlay_margin_value = QLabel("20")
        self.overlay_margin_value.setFixedWidth(40)
        margin_layout.addWidget(self.overlay_margin_slider)
        margin_layout.addWidget(self.overlay_margin_value)
        self._margin_row = overlay_section.form.add_row(self._t("margin"), margin_widget)
        self.margin_label = self._margin_row.label

        # Усиление волны
        gain_widget = QWidget()
        gain_layout = QHBoxLayout(gain_widget)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.setSpacing(SPACING["sm"])
        self.overlay_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_gain_slider.setRange(10, 100)
        self.overlay_gain_slider.setValue(15)
        self.overlay_gain_value = QLabel("1.5")
        self.overlay_gain_value.setFixedWidth(40)
        gain_layout.addWidget(self.overlay_gain_slider)
        gain_layout.addWidget(self.overlay_gain_value)
        self._wave_gain_row = overlay_section.form.add_row(self._t("wave_gain"), gain_widget)
        self.wave_gain_label = self._wave_gain_row.label

        # Прозрачность
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(SPACING["sm"])
        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(50, 255)
        self.overlay_opacity_slider.setValue(230)
        self.overlay_preview_btn = QPushButton(self._t("preview"))
        opacity_layout.addWidget(self.overlay_opacity_slider)
        opacity_layout.addWidget(self.overlay_preview_btn)
        self._opacity_row = overlay_section.form.add_row(self._t("opacity"), opacity_widget)
        self.opacity_label = self._opacity_row.label

        scroll.content_layout.addWidget(overlay_section)

        # === Секция App ===
        app_section = SectionBox(self._t("app_section"), label_width=140)
        self.app_section_label = app_section

        # Язык интерфейса
        self.ui_lang_box = QComboBox()
        for code, name in UI_LANGUAGES.items():
            self.ui_lang_box.addItem(name, code)
        self._ui_lang_row = app_section.form.add_row(self._t("ui_language"), self.ui_lang_box)
        self.ui_lang_label = self._ui_lang_row.label

        # Версия и обновления
        update_widget = QWidget()
        update_layout = QHBoxLayout(update_widget)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.setSpacing(SPACING["sm"])

        # Получаем версию из env
        try:
            from .env import APP_VERSION
            current_ver = APP_VERSION
        except ImportError:
            current_ver = "1.0.0"

        self.update_version_label = QLabel(f"v{current_ver}")
        self.update_version_label.setObjectName("bodyBold")
        update_layout.addWidget(self.update_version_label)
        update_layout.addStretch()

        self.check_update_btn = QPushButton(self._t("check_updates"))
        self.check_update_btn.clicked.connect(self._check_for_updates)
        update_layout.addWidget(self.check_update_btn)

        self._update_row = app_section.form.add_row(self._t("current_version"), update_widget)
        self.update_label = self._update_row.label

        # Статус обновления (на всю ширину)
        self.update_status_label = QLabel("")
        self.update_status_label.setObjectName("caption")
        self.update_status_label.setVisible(False)
        app_section.form.add_widget(self.update_status_label)

        # Прогресс-бар обновления (на всю ширину)
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setVisible(False)
        app_section.form.add_widget(self.update_progress)

        # Кнопка поддержки
        self.support_btn = QPushButton("help@mindtype.space")
        self.support_btn.setObjectName("smallButton")
        self.support_btn.clicked.connect(self._on_contact_support)
        self._support_row = app_section.form.add_row(self._t("contact_support"), self.support_btn)
        self.support_label = self._support_row.label

        scroll.content_layout.addWidget(app_section)
        scroll.content_layout.addStretch()

        tab_layout.addWidget(scroll)
        return tab

    def _build_assistant_tab(self) -> QWidget:
        """Построить вкладку голосового ассистента (Classic Mac OS System 7 style)."""
        tab = QWidget()
        tab.setObjectName("whiteBackground")

        # Скролл для всего контента
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("noBorder")

        content = QWidget()
        content.setObjectName("whiteBackground")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACING["lg"], SPACING["xl"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["xl"])

        # Главный чекбокс включения ассистента
        self.assistant_enable_check = QCheckBox(self._t("assistant_enable"))
        self.assistant_enable_check.setObjectName("boldCheckbox")
        layout.addWidget(self.assistant_enable_check)

        # === Wake Word секция ===
        wake_group = QGroupBox(self._t("assistant_wake_word"))
        # QGroupBox стилизуется через глобальный STYLESHEET
        wake_layout = QGridLayout()
        wake_layout.setContentsMargins(SPACING["sm"], SPACING["md"], SPACING["sm"], SPACING["sm"])
        wake_layout.setSpacing(SPACING["sm"])
        wake_layout.setColumnStretch(1, 1)

        row = 0
        # Чекбокс "Использовать Wake Word"
        self.assistant_use_wake_word_check = QCheckBox(self._t("assistant_use_wake_word"))
        wake_layout.addWidget(self.assistant_use_wake_word_check, row, 0, 1, 2)
        row += 1

        # Фраза активации
        wake_phrase_label = QLabel(self._t("assistant_phrase") + ":")
        self.assistant_wake_combo = QComboBox()
        self.assistant_wake_combo.addItem("hey jarvis", "hey_jarvis")
        self.assistant_wake_combo.addItem("alexa", "alexa")
        self.assistant_wake_combo.addItem("hey mycroft", "hey_mycroft")
        wake_layout.addWidget(wake_phrase_label, row, 0)
        wake_layout.addWidget(self.assistant_wake_combo, row, 1)
        row += 1

        # Звуковой сигнал
        self.assistant_beep_check = QCheckBox(self._t("assistant_beep"))
        wake_layout.addWidget(self.assistant_beep_check, row, 0, 1, 2)
        row += 1

        wake_group.setLayout(wake_layout)
        layout.addWidget(wake_group)

        # === Горячие клавиши секция ===
        hotkey_group = QGroupBox(self._t("assistant_hotkey"))
        # QGroupBox стилизуется через глобальный STYLESHEET
        hotkey_layout = QGridLayout()
        hotkey_layout.setContentsMargins(SPACING["sm"], SPACING["md"], SPACING["sm"], SPACING["sm"])
        hotkey_layout.setSpacing(SPACING["sm"])
        hotkey_layout.setColumnStretch(1, 1)

        row = 0
        # Горячие клавиши
        hotkey_label = QLabel(self._t("assistant_hotkey_label"))
        self.assistant_hotkey_edit = QLineEdit()
        self.assistant_hotkey_edit.setReadOnly(True)
        self.assistant_hotkey_edit.setPlaceholderText("ctrl+shift+a")
        self.assistant_hotkey_record_btn = QPushButton(self._t("assistant_hotkey_record"))
        self.assistant_hotkey_record_btn.setFixedWidth(80)

        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.assistant_hotkey_edit)
        hotkey_row.addWidget(self.assistant_hotkey_record_btn)

        hotkey_layout.addWidget(hotkey_label, row, 0)
        hotkey_layout.addLayout(hotkey_row, row, 1)
        row += 1

        hotkey_group.setLayout(hotkey_layout)
        layout.addWidget(hotkey_group)

        # === Голос TTS секция ===
        voice_group = QGroupBox(self._t("assistant_voice"))
        # QGroupBox стилизуется через глобальный STYLESHEET
        voice_layout = QGridLayout()
        voice_layout.setContentsMargins(SPACING["sm"], SPACING["md"], SPACING["sm"], SPACING["sm"])
        voice_layout.setSpacing(SPACING["sm"])
        voice_layout.setColumnStretch(1, 1)

        row = 0
        # Язык голоса
        voice_lang_label = QLabel(self._t("assistant_tts_language") + ":")
        self.assistant_tts_lang_combo = QComboBox()
        # Популярные языки для TTS
        tts_languages = [
            ("ru", "Русский (ru-RU)"),
            ("en", "English (en-US)"),
            ("de", "Deutsch (de-DE)"),
            ("fr", "Français (fr-FR)"),
            ("es", "Español (es-ES)"),
            ("zh", "中文 (zh-CN)"),
            ("ja", "日本語 (ja-JP)"),
        ]
        for code, name in tts_languages:
            self.assistant_tts_lang_combo.addItem(name, code)
        voice_layout.addWidget(voice_lang_label, row, 0)
        voice_layout.addWidget(self.assistant_tts_lang_combo, row, 1)
        row += 1

        # Выбор голоса
        voice_label = QLabel(self._t("assistant_tts_voice") + ":")
        self.assistant_voice_combo = QComboBox()
        voice_layout.addWidget(voice_label, row, 0)
        voice_layout.addWidget(self.assistant_voice_combo, row, 1)
        row += 1

        # Скорость речи
        speed_label = QLabel(self._t("assistant_tts_speed") + ":")
        speed_row = QHBoxLayout()
        self.assistant_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.assistant_speed_slider.setRange(-50, 50)
        self.assistant_speed_slider.setValue(0)
        self.assistant_speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.assistant_speed_slider.setTickInterval(25)
        self.assistant_speed_label = QLabel("1.0x")
        self.assistant_speed_label.setFixedWidth(50)
        speed_row.addWidget(self.assistant_speed_slider)
        speed_row.addWidget(self.assistant_speed_label)
        voice_layout.addWidget(speed_label, row, 0)
        voice_layout.addLayout(speed_row, row, 1)
        row += 1

        # Кнопка теста голоса
        self.assistant_test_voice_btn = QPushButton(self._t("assistant_test_voice"))
        voice_layout.addWidget(self.assistant_test_voice_btn, row, 0, 1, 2)
        row += 1

        voice_group.setLayout(voice_layout)
        layout.addWidget(voice_group)

        # === Личность секция ===
        personality_group = QGroupBox(self._t("assistant_personality"))
        # QGroupBox стилизуется через глобальный STYLESHEET
        personality_layout = QVBoxLayout()
        personality_layout.setContentsMargins(SPACING["sm"], SPACING["md"], SPACING["sm"], SPACING["sm"])
        personality_layout.setSpacing(SPACING["sm"])

        # Шаблон личности
        template_label = QLabel(self._t("assistant_personality_template") + ":")
        self.assistant_personality_combo = QComboBox()
        self.assistant_personality_combo.addItem(self._t("assistant_personality_friendly"), "friendly")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_professional"), "professional")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_creative"), "creative")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_programmer"), "programmer")
        self.assistant_personality_combo.addItem(self._t("assistant_personality_custom"), "custom")
        template_row = QHBoxLayout()
        template_row.addWidget(template_label)
        template_row.addWidget(self.assistant_personality_combo, stretch=1)
        personality_layout.addLayout(template_row)

        # System Prompt
        prompt_label = QLabel(self._t("assistant_system_prompt") + ":")
        personality_layout.addWidget(prompt_label)

        from PyQt6.QtWidgets import QTextEdit
        self.assistant_system_prompt_edit = QTextEdit()
        self.assistant_system_prompt_edit.setMaximumHeight(80)
        self.assistant_system_prompt_edit.setObjectName("systemPromptEdit")
        personality_layout.addWidget(self.assistant_system_prompt_edit)

        personality_group.setLayout(personality_layout)
        layout.addWidget(personality_group)

        layout.addStretch()

        scroll.setWidget(content)

        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

        return tab

    def _build_files_tab(self) -> QWidget:
        """Построить вкладку транскрибции файлов."""
        tab = QWidget()
        tab.setObjectName("whiteBackground")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        # === Зона Drag & Drop ===
        self.drop_zone = DropZoneWidget(translate_func=self._t)
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.drop_zone.clicked.connect(self._on_select_files_clicked)
        self.drop_zone.setFixedHeight(140)
        layout.addWidget(self.drop_zone)

        # Включить суммаризацию (checkbox напрямую)
        self.enable_summary_checkbox = QCheckBox(self._t("enable_summary"))
        self.enable_summary_checkbox.setChecked(True)
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        layout.addWidget(self.enable_summary_checkbox)

        # Скрытые виджеты для совместимости (не отображаются в UI)
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        self.output_format_combo.setVisible(False)

        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setReadOnly(True)
        self.output_folder_edit.setText(str(self._output_dir))
        self.output_folder_edit.setVisible(False)

        self.browse_folder_btn = QPushButton(self._t("browse"))
        self.browse_folder_btn.clicked.connect(self._on_browse_output_folder)
        self.browse_folder_btn.setVisible(False)

        self.customize_prompts_btn = QPushButton(self._t("customize_prompts"))
        self.customize_prompts_btn.clicked.connect(self._on_customize_prompts)
        self.customize_prompts_btn.setVisible(False)

        # === Очередь файлов (секция) ===
        queue_section = QWidget()
        queue_layout = QVBoxLayout(queue_section)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(SPACING["xs"])

        # Заголовок с кнопкой Clear (над рамкой)
        queue_header = QHBoxLayout()
        self.queue_title_label = QLabel(self._t("processing_queue"))
        self.queue_title_label.setObjectName("sectionTitle")
        queue_header.addWidget(self.queue_title_label)
        queue_header.addStretch()
        self.clear_queue_btn = QPushButton(self._t("clear_queue"))
        self.clear_queue_btn.setObjectName("smallButton")
        self.clear_queue_btn.clicked.connect(self._on_clear_queue)
        queue_header.addWidget(self.clear_queue_btn)
        queue_layout.addLayout(queue_header)

        # Очередь в рамке (QFrame#card)
        queue_frame = QFrame()
        queue_frame.setObjectName("card")
        queue_frame_layout = QVBoxLayout(queue_frame)
        queue_frame_layout.setContentsMargins(0, 0, 0, 0)
        queue_frame_layout.setSpacing(0)

        # Список файлов
        self._file_queue_scroll = QScrollArea()
        self._file_queue_scroll.setWidgetResizable(True)
        self._file_queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._file_queue_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._file_queue_content = QWidget()
        self._file_queue_content.setObjectName("whiteBackground")
        self._file_queue_layout = QVBoxLayout(self._file_queue_content)
        self._file_queue_layout.setContentsMargins(SPACING["sm"], SPACING["sm"], SPACING["sm"], SPACING["sm"])
        self._file_queue_layout.setSpacing(SPACING["sm"])

        # Placeholder (EmptyState)
        self._no_files_label = QLabel(self._t("no_files_in_queue"))
        self._no_files_label.setObjectName("placeholder")
        self._no_files_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_queue_layout.addWidget(self._no_files_label)
        self._file_queue_layout.addStretch()

        self._file_queue_scroll.setWidget(self._file_queue_content)
        queue_frame_layout.addWidget(self._file_queue_scroll)
        queue_layout.addWidget(queue_frame)

        layout.addWidget(queue_section, stretch=1)

        # === Блок AI Thinking (Classic Mac OS style) ===
        self._thinking_frame = QFrame()
        self._thinking_frame.setObjectName("thinkingFrame")
        self._thinking_frame.setVisible(False)
        thinking_layout = QVBoxLayout(self._thinking_frame)
        thinking_layout.setContentsMargins(0, 0, 0, 0)
        thinking_layout.setSpacing(0)

        # Заголовок окна
        thinking_header_frame = QFrame()
        thinking_header_frame.setObjectName("thinkingHeader")
        thinking_header_frame.setFixedHeight(22)
        thinking_header = QHBoxLayout(thinking_header_frame)
        thinking_header.setContentsMargins(SPACING["sm"], 2, SPACING["xs"], 2)

        self._thinking_title = QLabel(self._t("ai_thinking"))
        self._thinking_title.setObjectName("thinkingTitle")
        thinking_header.addWidget(self._thinking_title)
        thinking_header.addStretch()

        close_thinking_btn = QPushButton()
        close_thinking_btn.setFixedSize(12, 12)
        close_thinking_btn.setObjectName("windowClose")
        close_thinking_btn.clicked.connect(lambda: self._thinking_frame.setVisible(False))
        thinking_header.addWidget(close_thinking_btn)
        thinking_layout.addWidget(thinking_header_frame)

        from PyQt6.QtWidgets import QTextEdit
        self._thinking_output = QTextEdit()
        self._thinking_output.setReadOnly(True)
        self._thinking_output.setMinimumHeight(100)
        self._thinking_output.setMaximumHeight(150)
        self._thinking_output.setObjectName("thinkingOutput")
        thinking_layout.addWidget(self._thinking_output)

        self._thinking_buffer = ""
        layout.addWidget(self._thinking_frame)

        # === Кнопки управления (ActionBar) ===
        action_bar = ActionBar(align="right", spacing=SPACING["sm"])
        self.start_processing_btn = action_bar.add_button(
            self._t("start_processing"),
            primary=True,
            callback=self._on_start_processing
        )
        self.start_processing_btn.setEnabled(False)

        self.stop_processing_btn = action_bar.add_button(
            self._t("stop_processing"),
            callback=self._on_stop_processing
        )
        self.stop_processing_btn.setEnabled(False)
        self.stop_processing_btn.setVisible(False)

        layout.addWidget(action_bar)

        return tab

    def _on_ui_language_changed(self, idx: int) -> None:
        """Сменить язык интерфейса."""
        code = self.ui_lang_box.currentData()
        if code and code != self._ui_lang:
            self._ui_lang = code
            self.config.update(ui_language=code)
            self._update_ui_texts()

    def _build_journal_section(self) -> QWidget:
        """Построить секцию журнала событий."""
        section = QWidget()
        section.setObjectName("whiteBackground")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, SPACING["md"], 0, 0)
        layout.setSpacing(SPACING["xs"])

        # Заголовок журнала с кнопкой Clear (над рамкой)
        journal_header = QHBoxLayout()
        self.journal_title = QLabel(self._t("journal"))
        self.journal_title.setObjectName("sectionTitle")
        journal_header.addWidget(self.journal_title)
        journal_header.addStretch()

        self.clear_journal_btn = QPushButton(self._t("clear_journal"))
        self.clear_journal_btn.setObjectName("smallButton")
        self.clear_journal_btn.clicked.connect(self._clear_journal)
        journal_header.addWidget(self.clear_journal_btn)
        layout.addLayout(journal_header)

        # Журнал в рамке (QFrame#card)
        journal_frame = QFrame()
        journal_frame.setObjectName("card")
        journal_frame_layout = QVBoxLayout(journal_frame)
        journal_frame_layout.setContentsMargins(0, 0, 0, 0)
        journal_frame_layout.setSpacing(0)

        self.journal = JournalWidget(translate_func=self._t)
        self.journal.setMaximumHeight(100)
        journal_frame_layout.addWidget(self.journal)

        layout.addWidget(journal_frame)

        return section

    def _build_history_tab(self) -> QWidget:
        """Построить вкладку истории и журнала."""
        tab = QWidget()
        tab.setObjectName("whiteBackground")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(SPACING["lg"], SPACING["xl"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["xl"])

        # === История транскрипций ===
        self.transcription_history = TranscriptionHistoryWidget(translate_func=self._t)
        layout.addWidget(self.transcription_history, stretch=2)

        # === История диалогов ассистента ===
        self.assistant_dialog_history = AssistantDialogHistoryWidget(translate_func=self._t)
        self.assistant_dialog_history.continue_clicked.connect(self._on_continue_dialog)
        self.assistant_dialog_history.delete_clicked.connect(self._on_dialog_deleted)
        layout.addWidget(self.assistant_dialog_history, stretch=3)

        # === Журнал ===
        journal_header = QHBoxLayout()
        self.journal_title = QLabel(self._t("journal"))
        self.journal_title.setObjectName("sectionTitle")
        journal_header.addWidget(self.journal_title)
        journal_header.addStretch()

        self.clear_journal_btn = QPushButton(self._t("clear_journal"))
        self.clear_journal_btn.clicked.connect(self._clear_journal)
        journal_header.addWidget(self.clear_journal_btn)
        layout.addLayout(journal_header)

        self.journal = JournalWidget(translate_func=self._t)
        layout.addWidget(self.journal, stretch=1)

        return tab

    def _clear_journal(self):
        """Очистить журнал событий."""
        self.journal.clear()

    def _on_continue_dialog(self, dialog: Dialog):
        """Продолжить диалог из истории."""
        if not ASSISTANT_FEATURE_ENABLED or not self.voice_assistant:
            return
        # Загружаем диалог в ассистента
        self.voice_assistant.load_dialog(dialog)
        # Показываем оверлей с историей
        if self.assistant_overlay:
            self.assistant_overlay.clear_messages()
            for msg in dialog.messages:
                self.assistant_overlay.append_message(msg.role, msg.content)
            self.assistant_overlay.set_state_text(self._t("ready"))
            self.assistant_overlay.show_overlay()
        logger.info(f"[Main] Продолжен диалог: {dialog.title}")

    def _on_dialog_deleted(self, dialog_id: str):
        """Диалог удалён из истории."""
        logger.info(f"[Main] Диалог удалён: {dialog_id}")

    def _connect_signals(self) -> None:
        self.download_btn.clicked.connect(self._toggle_download)

        # Push-to-Talk сигналы
        self.hotkey_press_signal.connect(self._handle_hotkey_press)
        self.hotkey_release_signal.connect(self._handle_hotkey_release)
        self.hotkey_recorded_signal.connect(self._on_hotkey_recorded)
        self.waveform_signal.connect(self._update_waveform)

        # Настройки
        self.ui_lang_box.currentIndexChanged.connect(self._on_ui_lang_change)
        self.trans_lang_box.currentIndexChanged.connect(self._on_trans_lang_change)
        self.model_box.currentIndexChanged.connect(self._on_model_change)
        self.compute_box.currentTextChanged.connect(lambda v: self.config.update(compute_type=v))
        self.accel_box.currentTextChanged.connect(lambda v: self.config.update(accelerator=v))
        self.backend_box.currentIndexChanged.connect(lambda i: self.config.update(transcriber_backend=self.backend_box.itemData(i)))
        self.mic_box.currentTextChanged.connect(self._on_mic_change)
        self.hotkey_record_btn.clicked.connect(self._start_hotkey_recording)

        # Дополнительные
        self.vad_toggle.toggled.connect(lambda v: self.config.update(vad_filter=v))
        self.beam_slider.valueChanged.connect(self._on_beam_change)

        # Overlay настройки
        self.overlay_position_box.currentIndexChanged.connect(self._on_overlay_position_change)
        self.overlay_margin_slider.valueChanged.connect(self._on_overlay_margin_change)
        self.overlay_gain_slider.valueChanged.connect(self._on_overlay_gain_change)
        self.overlay_opacity_slider.valueChanged.connect(self._on_overlay_opacity_change)
        self.overlay_preview_btn.clicked.connect(self._test_overlay)

        # Сигналы уровня микрофона
        self.mic_level_signal.connect(self._update_mic_level)

        # Сигнал AI thinking
        self.thinking_signal.connect(self._update_thinking_output)

        # Отмена транскрипции через overlay
        self.overlay.cancelled.connect(self._cancel_transcription)

        # Сигналы голосового ассистента
        self._connect_assistant_signals()

    def _load_initial_state(self) -> None:
        cfg = self.config.config

        # Язык интерфейса
        ui_lang = cfg.get("ui_language", "ru")
        idx = self.ui_lang_box.findData(ui_lang)
        if idx >= 0:
            self.ui_lang_box.setCurrentIndex(idx)

        # Язык транскрипции
        trans_lang = cfg.get("language", "ru")
        idx = self.trans_lang_box.findData(trans_lang)
        if idx >= 0:
            self.trans_lang_box.setCurrentIndex(idx)

        # Модель и устройства
        self._set_model_combo_value(cfg.get("model_size", "large-v3"))
        self.compute_box.setCurrentText(cfg.get("compute_type", "int8"))
        self.accel_box.setCurrentText(cfg.get("accelerator", "auto"))
        backend = cfg.get("transcriber_backend", "whisper_cpp")
        idx = self.backend_box.findData(backend)
        if idx >= 0:
            self.backend_box.setCurrentIndex(idx)

        # Хоткей
        hotkey = cfg.get("hotkey", "ctrl+alt+v")
        self.hotkey_edit.setText(hotkey)

        # Дополнительные
        self.vad_toggle.setChecked(bool(cfg.get("vad_filter", True)))
        beam = int(cfg.get("beam_size", 5))
        self.beam_slider.setValue(beam)
        self.beam_value_label.setText(str(beam))

        # Микрофоны
        self._load_mics()
        mic = cfg.get("microphone")
        if mic:
            idx = self.mic_box.findText(mic)
            if idx >= 0:
                self.mic_box.setCurrentIndex(idx)

        # Overlay настройки
        position = cfg.get("overlay_position", "bottom-center")
        pos_idx = self.overlay_position_box.findData(position)
        if pos_idx >= 0:
            self.overlay_position_box.setCurrentIndex(pos_idx)

        margin = int(cfg.get("overlay_margin", 20))
        self.overlay_margin_slider.setValue(margin)
        self.overlay_margin_value.setText(str(margin))

        gain = float(cfg.get("overlay_wave_gain", 1.5))
        self.overlay_gain_slider.setValue(int(gain * 10))
        self.overlay_gain_value.setText(f"{gain:.1f}")

        opacity = int(cfg.get("overlay_opacity", 230))
        self.overlay_opacity_slider.setValue(opacity)

        self.config.update(models_dir=str(self.models_dir))

        # Загрузка настроек ассистента
        self._load_assistant_settings()

    def _load_mics(self) -> None:
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        for dev in self.audio.list_input_devices():
            self.mic_box.addItem(dev)
        self.mic_box.blockSignals(False)

    def _get_current_mic_index(self) -> Optional[int]:
        """Получить индекс текущего микрофона."""
        current_mic = self.config.config.get("microphone")
        if not current_mic:
            return None

        # Извлекаем номер из строки формата "0: Microphone Name"
        try:
            if ":" in current_mic:
                index_str = current_mic.split(":")[0].strip()
                return int(index_str)
        except (ValueError, IndexError):
            pass

        return None

    def _on_mic_change(self, value: str) -> None:
        self.config.update(microphone=value)
        # Обновляем описание микрофона в UI
        if hasattr(self, 'mic_desc_label'):
            mic_name = value.split(":")[1].strip() if ":" in value else value
            self.mic_desc_label.setText(mic_name)

    def _update_mic_level(self, level: float) -> None:
        """Обновить индикатор уровня микрофона (Qt thread)."""
        # Мониторинг микрофона убран из нового UI
        pass

    def _update_thinking_output(self, text: str) -> None:
        """Обновить блок AI thinking (Qt thread)."""
        if not hasattr(self, '_thinking_frame'):
            return

        # Показываем блок если скрыт
        if not self._thinking_frame.isVisible():
            self._thinking_frame.setVisible(True)
            self._thinking_output.clear()
            self._thinking_buffer = ""

        # Накапливаем текст в буфер
        self._thinking_buffer += text

        # Выводим только полные строки (или специальные маркеры)
        if "\n" in self._thinking_buffer or text.startswith("["):
            # Разбиваем на строки
            lines = self._thinking_buffer.split("\n")

            # Выводим все полные строки кроме последней (она может быть неполной)
            for line in lines[:-1]:
                if line.strip():
                    self._thinking_output.append(line)

            # Оставляем последнюю неполную строку в буфере
            self._thinking_buffer = lines[-1]

        # Прокручиваем вниз
        scrollbar = self._thinking_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_ui_lang_change(self, index: int) -> None:
        """Обработчик изменения языка интерфейса."""
        lang = self.ui_lang_box.itemData(index)
        if lang and lang != self._ui_lang:
            self._ui_lang = lang
            self.config.update(ui_language=lang)
            self._update_ui_texts()

    def _on_trans_lang_change(self, index: int) -> None:
        """Обработчик изменения языка транскрипции."""
        lang = self.trans_lang_box.itemData(index)
        if lang:
            self.config.update(language=lang)

    def _on_model_change(self, index: int) -> None:
        """Обработчик изменения модели."""
        model = self.model_box.itemData(index)
        if model:
            self.config.update(model_size=model)

    def _on_beam_change(self, value: int) -> None:
        """Обработчик изменения beam size."""
        self.beam_value_label.setText(str(value))
        self.config.update(beam_size=value)

    def _on_overlay_position_change(self, index: int) -> None:
        """Обработчик изменения позиции overlay."""
        position = self.overlay_position_box.itemData(index)
        self.config.update(overlay_position=position)
        self.overlay.set_corner(position)
        if self.assistant_overlay:
            self.assistant_overlay.set_corner(position)

    def _on_overlay_margin_change(self, value: int) -> None:
        """Обработчик изменения отступа overlay."""
        self.overlay_margin_value.setText(str(value))
        self.config.update(overlay_margin=value)
        self.overlay.set_margin(value)
        if self.assistant_overlay:
            self.assistant_overlay.set_margin(value + ASSISTANT_OVERLAY_OFFSET)

    def _on_overlay_gain_change(self, value: int) -> None:
        """Обработчик изменения усиления волн."""
        gain = value / 10.0
        self.overlay_gain_value.setText(f"{gain:.1f}")
        self.config.update(overlay_wave_gain=gain)
        self.overlay.set_wave_gain(gain)

    def _on_overlay_opacity_change(self, value: int) -> None:
        """Обработчик изменения прозрачности фона."""
        self.config.update(overlay_opacity=value)
        self.overlay.set_bg_opacity(value)

    def _test_overlay(self) -> None:
        """Показать превью overlay для теста настроек."""
        self.overlay.show_recording()
        import random
        test_levels = [random.uniform(0.1, 0.5) for _ in range(32)]
        self.overlay.update_waveform(test_levels)
        QTimer.singleShot(3000, self.overlay.hide_overlay)

    def _update_ui_texts(self) -> None:
        """Обновить все тексты интерфейса."""
        # Вкладки (порядок: Основные, Саммари, Настройки)
        self.tabs.setTabText(0, self._t("basic"))
        self.tabs.setTabText(1, self._t("files_tab"))
        self.tabs.setTabText(2, self._t("additional"))

        # Основная вкладка
        self.audio_input_label.setText(self._t("audio_input"))
        self.hotkey_label.setText(self._t("hotkey"))
        self.hotkey_record_btn.setText(self._t("record_hotkey"))
        self.ui_lang_label.setText(self._t("ui_language"))
        self.trans_lang_label.setText(self._t("transcription_language"))
        self.license_status_label.setText(self._t("license_status"))

        # Дополнительная вкладка - модель и устройство
        self.model_label.setText(self._t("model"))
        self.distil_warning.setText(self._t("distil_en_only"))
        self.quant_label.setText(self._t("quantization"))
        self.accel_label.setText(self._t("device"))
        self.download_btn.setText(self._t("download_model"))

        # Дополнительная вкладка
        self.perf_section_label.setTitle(self._t("performance_section"))
        self.vad_label.setText(self._t("vad_filter"))
        self.beam_label.setText(self._t("beam_size"))
        self.model_path_label.setText(self._t("model_path"))

        self.overlay_section_label.setTitle(self._t("overlay_section"))
        self.app_section_label.setTitle(self._t("app_section"))
        self.position_label.setText(self._t("position"))
        self.margin_label.setText(self._t("margin"))
        self.wave_gain_label.setText(self._t("wave_gain"))
        self.opacity_label.setText(self._t("opacity"))
        self.overlay_preview_btn.setText(self._t("preview"))

        # Обновляем позиции в комбобоксе
        current_pos = self.overlay_position_box.currentData()
        self.overlay_position_box.clear()
        positions = [
            ("bottom-center", "bottom_center"),
            ("top-center", "top_center"),
            ("bottom-right", "bottom_right"),
            ("bottom-left", "bottom_left"),
            ("top-right", "top_right"),
            ("top-left", "top_left"),
        ]
        for key, text_key in positions:
            self.overlay_position_box.addItem(self._t(text_key), key)
        idx = self.overlay_position_box.findData(current_pos)
        if idx >= 0:
            self.overlay_position_box.setCurrentIndex(idx)

        # Вкладка файлов
        self.drop_zone.set_translate_func(self._t)
        self.browse_folder_btn.setText(self._t("browse"))
        self.queue_title_label.setText(self._t("processing_queue"))
        self.clear_queue_btn.setText(self._t("clear_queue"))
        self.start_processing_btn.setText(self._t("start_processing"))
        self.stop_processing_btn.setText(self._t("stop_processing"))
        self._no_files_label.setText(self._t("no_files_in_queue"))

        # Обновляем формат комбобокса
        current_format = self.output_format_combo.currentData()
        self.output_format_combo.clear()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        idx = self.output_format_combo.findData(current_format)
        if idx >= 0:
            self.output_format_combo.setCurrentIndex(idx)

        # AI саммари
        self.enable_summary_checkbox.setText(self._t("enable_summary"))
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        self.customize_prompts_btn.setText(self._t("customize_prompts"))
        if hasattr(self, "_thinking_title"):
            self._thinking_title.setText(self._t("ai_thinking"))

        # Обновляем виджеты файлов
        for widget in self._file_widgets.values():
            widget.set_translate_func(self._t)

        # История транскрипций (если вкладка включена)
        if hasattr(self, 'transcription_history'):
            self.transcription_history.set_translate_func(self._t)

        # История диалогов ассистента (если вкладка включена)
        if hasattr(self, 'assistant_dialog_history'):
            self.assistant_dialog_history.set_translate_func(self._t)

        # Журнал
        self.journal_title.setText(self._t("journal"))
        self.clear_journal_btn.setText(self._t("clear_journal"))
        self.journal.set_translate_func(self._t)

        # Системный трей
        self._update_tray_menu_texts()

        # Лицензия
        self.license_status_widget.set_translate_func(self._t)

        # Обновления
        self.update_label.setText(self._t("current_version"))
        self.check_update_btn.setText(self._t("check_updates"))

        # Поддержка
        self.support_label.setText(self._t("contact_support"))

    def _setup_focus_manager(self) -> None:
        """Настроить менеджер фокуса с handle нашего окна."""
        hwnd = int(self.winId())
        focus_manager.set_our_window(hwnd)
        self._add_journal_entry("success", "ready", is_translatable=True)

    def _setup_tray(self) -> None:
        """Настроить системный трей."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(create_app_icon(64, recording=False))
        self.tray_icon.setToolTip("MindType")

        # Контекстное меню
        tray_menu = QMenu()

        # Показать окно
        self.tray_show_action = QAction(self._t("show_window"), self)
        self.tray_show_action.triggered.connect(self._tray_show_window)
        tray_menu.addAction(self.tray_show_action)

        # Начать запись
        self.tray_record_action = QAction(self._t("start_recording"), self)
        self.tray_record_action.triggered.connect(self._tray_start_recording)
        tray_menu.addAction(self.tray_record_action)

        tray_menu.addSeparator()

        # Выход
        self.tray_exit_action = QAction(self._t("exit"), self)
        self.tray_exit_action.triggered.connect(self._tray_exit)
        tray_menu.addAction(self.tray_exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Обработчик активации иконки в трее."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_show_window(self) -> None:
        """Показать главное окно."""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_start_recording(self) -> None:
        """Начать запись из трея."""
        if not self.audio.recording:
            focus_manager.save_current_window()
            self._start_recording_with_overlay()

    def _tray_exit(self) -> None:
        """Полностью закрыть приложение."""
        self._really_quit = True
        self.close()

    def _update_tray_icon(self, recording: bool) -> None:
        """Обновить иконку в трее."""
        if self.tray_icon:
            self.tray_icon.setIcon(create_app_icon(64, recording=recording))

    def _update_tray_menu_texts(self) -> None:
        """Обновить тексты меню трея."""
        if self.tray_icon:
            self.tray_show_action.setText(self._t("show_window"))
            self.tray_record_action.setText(self._t("start_recording"))
            self.tray_exit_action.setText(self._t("exit"))

    def _apply_overlay_settings(self) -> None:
        """Применить настройки overlay из конфига."""
        cfg = self.config.config
        self.overlay.set_corner(cfg.get("overlay_position", "bottom-center"))
        self.overlay.set_margin(int(cfg.get("overlay_margin", 20)))
        self.overlay.set_wave_gain(float(cfg.get("overlay_wave_gain", 1.5)))
        self.overlay.set_bg_opacity(int(cfg.get("overlay_opacity", 230)))

    def _init_hotkey(self) -> None:
        combo = self.config.config.get("hotkey", "ctrl+alt+v")
        self.hotkey_listener = HotkeyListener(
            combo,
            on_press=self._emit_hotkey_press,
            on_release=self._emit_hotkey_release,
            push_to_talk=True,
        )
        try:
            self.hotkey_listener.start()
            self._add_journal_entry("success", "hotkey_activated", extra_key="push_to_talk", is_translatable=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)

    def _start_hotkey_recording(self) -> None:
        """Начать запись нового хоткея."""
        if self._recording_hotkey:
            return

        if self.hotkey_listener:
            self.hotkey_listener.stop()

        self._recording_hotkey = True

        # Обновляем UI для индикации записи
        self.hotkey_edit.setText(self._t("press_combination"))
        self.hotkey_record_btn.setEnabled(False)

        def on_recorded(combo: str) -> None:
            self.hotkey_recorded_signal.emit(combo)

        self.hotkey_recorder = HotkeyRecorder(on_recorded)
        self.hotkey_recorder.start()

    def _on_hotkey_recorded(self, combo: str) -> None:
        """Обработчик записанного хоткея (Qt thread)."""
        self._recording_hotkey = False

        # Восстанавливаем UI
        self.hotkey_record_btn.setEnabled(True)

        if self.hotkey_recorder:
            self.hotkey_recorder.stop()
            self.hotkey_recorder = None

        # Обновляем хоткей
        self.hotkey_edit.setText(combo)

        self.config.update(hotkey=combo)

        self.hotkey_listener = HotkeyListener(
            combo,
            on_press=self._emit_hotkey_press,
            on_release=self._emit_hotkey_release,
            push_to_talk=True,
        )
        try:
            self.hotkey_listener.start()
            self._add_journal_entry("success", "hotkey_set", extra_key=combo, is_translatable=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)

    def _emit_hotkey_press(self) -> None:
        """Вызывается из keyboard thread при нажатии хоткея."""
        if not self._recording_hotkey:
            self.hotkey_press_signal.emit()

    def _emit_hotkey_release(self) -> None:
        """Вызывается из keyboard thread при отпускании хоткея."""
        if not self._recording_hotkey:
            self.hotkey_release_signal.emit()

    def _handle_hotkey_press(self) -> None:
        """Обработчик нажатия хоткея (Qt thread)."""
        from .crash_reporter import add_breadcrumb
        add_breadcrumb("Hotkey pressed - starting recording")

        # Проверяем лицензию перед записью
        info = self.license_manager.get_license_info()
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            # Показываем блокирующий диалог
            self._show_trial_expired_dialog()
            return

        # Если идёт транскрипция - отменяем её
        if self._transcription_in_progress:
            self._cancel_transcription()
            return

        if not self.audio.recording:
            focus_manager.save_current_window()
            self._add_journal_entry(
                "pending",
                "transcribing",
                extra_key=f"{focus_manager.saved_window_title}",
                is_translatable=True
            )
            self._start_recording_with_overlay()

    def _handle_hotkey_release(self) -> None:
        """Обработчик отпускания хоткея (Qt thread)."""
        if self.audio.recording:
            self._stop_recording_with_auto_insert()

    def _start_recording_with_overlay(self) -> None:
        """Начать запись с показом overlay."""
        if self.audio.recording:
            return
        try:
            device_id = self._selected_device_id()

            def on_level(levels: List[float]) -> None:
                self.waveform_signal.emit(levels)

            self.audio.start(device=device_id, level_callback=on_level)
            self._recording_start_time = datetime.now()  # Запоминаем время начала
            self.overlay.show_recording()
            self._update_tray_icon(recording=True)
        except Exception as exc:
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)
            self.overlay.show_error(self._t("error"))

    def _stop_recording_with_auto_insert(self) -> None:
        """Остановить запись и включить автовставку."""
        if not self.audio.recording:
            return

        self._auto_insert_pending = True
        self._transcription_in_progress = True  # Начинаем транскрипцию
        path = self.audio.stop()

        # Учитываем время записи для trial
        if hasattr(self, '_recording_start_time') and self._recording_start_time:
            duration = (datetime.now() - self._recording_start_time).total_seconds()
            self.license_manager.add_transcription_time(duration)
            self._recording_start_time = None

        self.overlay.show_processing()

        if not path:
            self._add_journal_entry("error", "error", text="no_audio", is_translatable=True)
            self.overlay.show_error(self._t("error"))
            self._auto_insert_pending = False
            return

        self._run_transcription(path)

    def _update_waveform(self, levels: List[float]) -> None:
        """Обновить waveform в overlay (Qt thread)."""
        self.overlay.update_waveform(levels)

    def _run_transcription(self, audio_path: Path) -> None:
        cfg = self.config.config
        worker = TranscribeWorker(
            self.transcriber,
            audio_path,
            model_size=cfg.get("model_size", "large-v3"),
            compute_type=cfg.get("compute_type", "int8"),
            device=cfg.get("device", "auto"),
            cpu_threads=int(cfg.get("cpu_threads", 4)),
            num_workers=int(cfg.get("num_workers", 1)),
            language=cfg.get("language", "ru"),
            beam_size=int(cfg.get("beam_size", 5)),
            vad_filter=bool(cfg.get("vad_filter", True)),
            models_dir=self.models_dir,
        )
        worker.progress.connect(self._on_transcribe_progress)
        worker.status_update.connect(self._on_transcribe_status)
        worker.finished.connect(self._on_transcribed)
        worker.finished.connect(lambda *_: audio_path.unlink(missing_ok=True))
        self._transcribe_thread = worker
        worker.start()

    def _on_transcribe_status(self, status: str) -> None:
        # status приходит как ключ перевода (loading_model, transcribing)
        self._add_journal_entry("pending", status, is_translatable=True)

    def _on_transcribe_progress(self, text: str, lang: str, prob: float) -> None:
        pass  # Прогресс отображается в overlay

    def _on_transcribed(self, text: str, lang: str, prob: float, err: str) -> None:
        from .crash_reporter import add_breadcrumb
        add_breadcrumb(f"Transcription completed: {'error' if err else 'success'}")

        self._update_tray_icon(recording=False)
        self._transcription_in_progress = False  # Транскрипция завершена

        if err:
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            self.overlay.show_error(self._t("error"))
            self._auto_insert_pending = False
            return

        self.last_text = text

        # Добавляем в историю транскрипций (если вкладка История включена)
        if text and hasattr(self, 'transcription_history'):
            self.transcription_history.add_transcription(text)

        # Обновляем последнюю запись в журнале
        self._add_journal_entry(
            "success" if text else "pending",
            "transcription" if text else "transcribing",
            is_translatable=True
        )

        if self._auto_insert_pending and text:
            self._auto_insert_pending = False
            QTimer.singleShot(150, lambda: self._do_auto_insert(text))
        else:
            self.overlay.show_success()

    def _do_auto_insert(self, text: str) -> None:
        """Автовставка после транскрипции с восстановлением фокуса."""
        if not text:
            self.overlay.show_success()
            return

        ok = insert_text(text)
        if ok:
            self._add_journal_entry("success", "auto_insert_done", is_translatable=True)
            self.overlay.show_success()
        else:
            self._add_journal_entry("error", "error", text="insert_failed", is_translatable=True)
            self.overlay.show_error(self._t("error"))

    def _cancel_transcription(self) -> None:
        """Отменить текущую транскрипцию."""
        if not self._transcription_in_progress:
            return

        # Отменяем worker
        if self._transcribe_thread and self._transcribe_thread.isRunning():
            self._transcribe_thread.cancel()

        self._transcription_in_progress = False
        self._auto_insert_pending = False
        self._update_tray_icon(recording=False)

        # Показываем сообщение об отмене
        self._add_journal_entry("pending", "cancelled", is_translatable=True)
        self.overlay.hide_overlay()

    def _add_journal_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True) -> None:
        """Добавить запись в журнал."""
        self.journal.add_entry(status, title_key, text, extra_key, is_translatable)

    def _toggle_download(self) -> None:
        """Toggle between starting and canceling download."""
        if self._download_thread and self._download_thread.isRunning():
            # Cancel download
            self._download_thread.cancel()
            self.download_btn.setText(self._t("download_model"))
            self.download_btn.setEnabled(False)  # Disable until thread finishes
        else:
            # Start download
            self._download_model()

    def _download_model(self) -> None:
        model_size = self.model_box.currentData() or self.model_box.currentText().replace("[OK] ", "")
        self.download_btn.setText(self._t("cancel"))
        self.download_progress.setValue(0)
        self.download_status_label.setText("...")
        worker = ModelDownloadWorker(
            self.transcriber, model_size, self.models_dir
        )
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        self._download_thread = worker
        worker.start()
        self._add_journal_entry("pending", "downloading", extra_key=model_size, is_translatable=True)

    def _on_download_progress(self, status: str, current: int, total: int) -> None:
        if total > 0:
            pct = int(current / total * 100)
            self.download_progress.setValue(pct)
            cur_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.download_status_label.setText(f"{cur_mb:.0f} / {tot_mb:.0f} MB")
        else:
            self.download_progress.setValue(0)
            self.download_status_label.setText(status)

    def _on_download_finished(self, path: str, err: str) -> None:
        self.download_btn.setEnabled(True)
        self.download_btn.setText(self._t("download_model"))

        if err and err != "cancelled":
            self.download_progress.setValue(0)
            short_err = err if len(err) <= 80 else err[:77] + "..."
            self.download_status_label.setText(f"Error: {short_err}")
            self.download_status_label.setToolTip(err)
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            return
        if err == "cancelled":
            self.download_progress.setValue(0)
            self.download_status_label.setText(self._t("cancelled"))
            return
        self.download_progress.setValue(100)
        self.download_status_label.setText("[OK]")
        # Refresh model combo to show [OK] indicator
        current_model = self.model_box.currentData() or self.model_box.currentText().replace("[OK] ", "")
        self._populate_model_combo()
        self._set_model_combo_value(current_model)
        self._add_journal_entry("success", "model_ready", is_translatable=True)

    def _selected_device_id(self) -> Optional[int]:
        current = self.mic_box.currentText()
        if not current:
            return None
        try:
            idx_str = current.split(":")[0]
            return int(idx_str)
        except Exception:
            return None

    def _show_license_dialog(self) -> None:
        """Показать диалог активации лицензии."""
        info = self.license_manager.get_license_info()

        if info.status == LicenseStatus.TRIAL_EXPIRED:
            self._show_trial_expired_dialog()
        else:
            dialog = LicenseActivationDialog(
                self.license_manager,
                translate_func=self._t,
                parent=self
            )
            dialog.license_activated.connect(self._on_license_activated)
            dialog.exec()

    def _show_trial_expired_dialog(self) -> None:
        """Показать блокирующий диалог истёкшего trial."""
        dialog = TrialExpiredDialog(
            self.license_manager,
            translate_func=self._t,
            parent=self
        )
        dialog.license_activated.connect(self._on_license_activated)
        dialog.exec()

    def _on_license_activated(self) -> None:
        """Обработчик активации лицензии."""
        self.license_status_widget.refresh()
        self._add_journal_entry("success", "license_active", is_translatable=True)

    def _on_contact_support(self) -> None:
        """Открыть почтовый клиент для связи с поддержкой."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("mailto:help@mindtype.space"))

    def _check_for_updates(self) -> None:
        """Проверить наличие обновлений."""
        if self._update_check_worker and self._update_check_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("checking_updates"))
        self.update_status_label.setVisible(False)

        self._update_check_worker = UpdateCheckWorker(self.updater)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_check_worker.start()

        self._add_journal_entry("pending", "checking_updates", is_translatable=True)

    def _on_update_check_finished(self, info: UpdateInfo) -> None:
        """Обработчик завершения проверки обновлений."""
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText(self._t("check_updates"))

        if info.error:
            self.update_status_label.setText(self._t("network_error"))
            self.update_status_label.setObjectName("updateStatusError")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.update_status_label.setVisible(True)
            self._add_journal_entry("error", "update_error", text=info.error, is_translatable=True)
            return

        if info.available:
            self.update_status_label.setText(
                f"{self._t('update_available')}: v{info.version}"
            )
            self.update_status_label.setObjectName("updateStatusSuccess")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.update_status_label.setVisible(True)

            # Показываем кнопку обновления
            self.check_update_btn.setText(self._t("update_now"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._download_update)

            self._add_journal_entry("success", "update_available",
                                   extra_key=f"v{info.version}", is_translatable=True)

            # Показываем диалог с информацией
            if info.release_notes:
                QMessageBox.information(
                    self,
                    self._t("update_available"),
                    f"{self._t('update_version').replace('{version}', info.version)}\n\n"
                    f"{info.release_notes}"
                )
        else:
            self.update_status_label.setText(self._t("no_updates"))
            self.update_status_label.setObjectName("updateStatusNeutral")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.update_status_label.setVisible(True)
            self._add_journal_entry("success", "no_updates", is_translatable=True)

    def _download_update(self) -> None:
        """Скачать обновление."""
        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("downloading_update"))
        self.update_progress.setValue(0)
        self.update_progress.setVisible(True)

        self._update_download_worker = UpdateDownloadWorker(self.updater)
        self._update_download_worker.progress.connect(self._on_update_download_progress)
        self._update_download_worker.finished.connect(self._on_update_download_finished)
        self._update_download_worker.start()

        self._add_journal_entry("pending", "downloading_update", is_translatable=True)

    def _on_update_download_progress(self, downloaded: int, total: int) -> None:
        """Обработчик прогресса скачивания."""
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.update_progress.setValue(percent)

            # Показываем размер
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.update_status_label.setText(
                f"{self._t('downloading_update')} {downloaded_mb:.1f} / {total_mb:.1f} MB"
            )

    def _on_update_download_finished(self, success: bool, path: str, error: str) -> None:
        """Обработчик завершения скачивания."""
        self.update_progress.setVisible(False)
        self.check_update_btn.setEnabled(True)

        if success:
            self.update_status_label.setText(self._t("update_ready"))
            self.update_status_label.setObjectName("updateStatusSuccess")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.check_update_btn.setText(self._t("update_now"))

            # Предлагаем установить
            reply = QMessageBox.question(
                self,
                self._t("update_ready"),
                self._t("update_ready") + "\n\n" +
                "Приложение будет закрыто для установки обновления.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._add_journal_entry("success", "update_ready", is_translatable=True)
                self.updater.install_update()
        else:
            self.update_status_label.setText(f"{self._t('update_error')}: {error}")
            self.update_status_label.setObjectName("updateStatusError")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.check_update_btn.setText(self._t("check_updates"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._check_for_updates)
            self._add_journal_entry("error", "update_error", text=error, is_translatable=True)

    # === Обработчики вкладки "Файлы" ===

    def _task_key(self, path: Path) -> Path:
        """Нормализованный ключ для задач/виджетов (абсолютный путь)."""
        try:
            return path.resolve()
        except Exception:
            return path.absolute()

    def _on_files_dropped(self, files: list) -> None:
        """Обработчик drop файлов."""
        # Исключаем только файлы в процессе или ожидающие обработки
        processing_statuses = (FileStatus.PENDING, FileStatus.EXTRACTING, 
                               FileStatus.TRANSCRIBING, FileStatus.SUMMARIZING, 
                               FileStatus.GENERATING)
        existing = {
            self._task_key(t.file_path) for t in self._file_tasks
            if t.status in processing_statuses
        }
        for file_path in files:
            key = self._task_key(file_path)
            if key not in existing:
                # Удаляем старую завершённую задачу с тем же путём если есть
                self._file_tasks = [t for t in self._file_tasks 
                                    if self._task_key(t.file_path) != key]
                # Удаляем старый виджет
                old_widget = self._file_widgets.pop(key, None)
                if old_widget:
                    old_widget.deleteLater()
                # Создаём новую задачу
                task = FileTask(file_path=file_path)
                self._file_tasks.append(task)
                self._add_file_widget(task)
                existing.add(key)

        self._update_file_queue_ui()

    def _on_select_files_clicked(self) -> None:
        """Открыть диалог выбора файлов."""
        extensions = " ".join(f"*{ext}" for ext in ALL_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("select_files"),
            str(Path.home()),
            f"Media Files ({extensions})"
        )

        if files:
            self._on_files_dropped([Path(f) for f in files])

    def _on_browse_output_folder(self) -> None:
        """Открыть диалог выбора папки вывода."""
        folder = QFileDialog.getExistingDirectory(
            self,
            self._t("output_folder"),
            str(self._output_dir)
        )

        if folder:
            self._output_dir = Path(folder)
            self.output_folder_edit.setText(folder)

    def _on_reasoning_changed(self, state: int) -> None:
        """Обработать изменение reasoning mode."""
        is_enabled = state == 2  # Qt.CheckState.Checked
        self.effort_label.setEnabled(is_enabled)
        self.effort_combo.setEnabled(is_enabled)
        self.config.update(llm_reasoning_enabled=is_enabled)

    def _on_effort_changed(self, index: int) -> None:
        """Сохранить выбранный effort."""
        effort = self.effort_combo.currentData()
        if effort:
            self.config.update(llm_reasoning_effort=effort)

    def _on_provider_changed(self, index: int) -> None:
        """Обработать смену провайдера."""
        provider = self.provider_combo.currentData()
        if not provider:
            return

        # Сохраняем в конфиг
        self.config.update(llm_provider=provider)

        # Обновляем видимость полей
        self._update_provider_fields()

        # Загружаем настройки для нового провайдера
        self._load_provider_settings(provider)

        # Очищаем список моделей
        self.model_combo.clear()
        self.model_combo.addItem(self._t("select_model"), "")

    def _update_provider_fields(self) -> None:
        """Обновить видимость полей в зависимости от провайдера."""
        provider = self.provider_combo.currentData()

        # MindType Cloud не требует API ключа (использует лицензию)
        is_mindtype_cloud = provider == "mindtype_cloud"
        # Ollama не требует API ключа, но требует base_url
        is_ollama = provider == "ollama"

        # Скрыть API key для MindType Cloud и Ollama
        self.api_key_label.setVisible(not is_ollama and not is_mindtype_cloud)
        self.api_key_edit.setVisible(not is_ollama and not is_mindtype_cloud)
        self.base_url_label.setVisible(is_ollama)
        self.base_url_edit.setVisible(is_ollama)

        # Скрыть выбор модели для MindType Cloud (автовыбор)
        self.model_select_label.setVisible(not is_mindtype_cloud)
        self.model_combo.setVisible(not is_mindtype_cloud)
        self.refresh_models_btn.setVisible(not is_mindtype_cloud)

        # Скрыть reasoning для MindType Cloud (не поддерживается)
        self.reasoning_checkbox.setVisible(not is_mindtype_cloud)
        self.effort_label.setVisible(not is_mindtype_cloud)
        self.effort_combo.setVisible(not is_mindtype_cloud)

        # Показать/скрыть виджет кредитов
        if hasattr(self, '_credits_widget'):
            self._credits_widget.setVisible(is_mindtype_cloud)

        # Инициализировать MindType Cloud провайдер
        if is_mindtype_cloud:
            self._init_mindtype_cloud()
            self._refresh_credits_balance()

        # Обновляем placeholder для API ключа
        placeholders = {
            "openai": "sk-...",
            "anthropic": "sk-ant-...",
            "gemini": "AIza...",
            "openrouter": "sk-or-...",
        }
        self.api_key_edit.setPlaceholderText(placeholders.get(provider, ""))

    def _load_provider_settings(self, provider: str) -> None:
        """Загрузить настройки для провайдера."""
        cfg = self.config.config

        # MindType Cloud использует лицензионный ключ, не API ключ
        if provider == "mindtype_cloud":
            self.api_key_edit.setText("")
            return

        # API ключ
        key_field = f"{provider}_api_key"
        api_key = cfg.get(key_field, "")
        self.api_key_edit.setText(api_key)

        # Base URL (для Ollama)
        if provider == "ollama":
            base_url = cfg.get("ollama_base_url", "http://localhost:11434")
            self.base_url_edit.setText(base_url)

        # Модель
        model_field = f"{provider}_model"
        saved_model = cfg.get(model_field, "")
        if saved_model:
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")
            self.model_combo.addItem(saved_model, saved_model)
            self.model_combo.setCurrentIndex(1)

    def _on_api_key_changed(self, value: str) -> None:
        """Сохранить API ключ для текущего провайдера."""
        provider = self.provider_combo.currentData()
        if provider and provider not in ("ollama", "mindtype_cloud"):
            key_field = f"{provider}_api_key"
            self.config.update(**{key_field: value})

    def _on_base_url_changed(self, value: str) -> None:
        """Сохранить base URL для Ollama."""
        self.config.update(ollama_base_url=value)

    def _on_model_changed(self, value: str) -> None:
        """Сохранить выбранную модель."""
        provider = self.provider_combo.currentData()
        if provider:
            model_field = f"{provider}_model"
            # Получаем ID модели из data, а не текст
            model_id = self.model_combo.currentData()
            if model_id:
                self.config.update(**{model_field: model_id})

    def _on_refresh_models(self) -> None:
        """Загрузить список моделей для текущего провайдера."""
        provider = self.provider_combo.currentData()
        if not provider:
            return

        # Для Ollama не нужен API ключ
        if provider != "ollama":
            api_key = self.api_key_edit.text().strip()
            if not api_key:
                QMessageBox.warning(
                    self,
                    self._t("error"),
                    self._t("api_key_required")
                )
                return
        else:
            api_key = ""

        # Показываем индикатор загрузки
        self.refresh_models_btn.setEnabled(False)
        self.refresh_models_btn.setText(self._t("loading_models"))
        QApplication.processEvents()

        try:
            from .llm import get_provider_by_name, LLMAuthError, LLMError, LLMConnectionError
            from PyQt6.QtWidgets import QCompleter

            # Создаём провайдер
            base_url = self.base_url_edit.text().strip() if provider == "ollama" else ""
            llm_provider = get_provider_by_name(
                name=provider,
                api_key=api_key,
                base_url=base_url,
            )

            # Загружаем модели
            models = llm_provider.fetch_models(force_refresh=True)

            # Сохраняем модели
            self._llm_models = models

            # Очищаем и заполняем комбобокс
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")

            model_names = []
            for model in models:
                # Формируем отображаемое имя
                display = model.display_name
                self.model_combo.addItem(display, model.id)
                model_names.append(display)

            # Добавляем completer для поиска
            completer = QCompleter(model_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.model_combo.setCompleter(completer)

            # Восстанавливаем сохранённый выбор
            model_field = f"{provider}_model"
            saved_model = self.config.config.get(model_field, "")
            if saved_model:
                idx = self.model_combo.findData(saved_model)
                if idx >= 0:
                    self.model_combo.setCurrentIndex(idx)

        except LLMAuthError:
            QMessageBox.critical(
                self,
                self._t("error"),
                self._t("invalid_api_key")
            )
        except LLMConnectionError as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                f"{self._t('connection_error')}: {e}"
            )
        except LLMError as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                f"{self._t('api_error')}: {e}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self._t("error"),
                str(e)
            )
        finally:
            self.refresh_models_btn.setEnabled(True)
            self.refresh_models_btn.setText(self._t("refresh_models"))

    def _on_model_selected(self, index: int) -> None:
        """Сохранить выбранную модель."""
        model_id = self.model_combo.currentData()
        if model_id:
            self.config.update(openrouter_model=model_id)

    def _on_customize_prompts(self) -> None:
        """Открыть диалог настройки промптов."""
        dialog = PromptCustomizationDialog(self.config, translate_func=self._t, parent=self)
        dialog.show()

    def _on_clear_queue(self) -> None:
        """Очистить очередь файлов."""
        # Оставляем только файлы в процессе обработки
        self._file_tasks = [
            t for t in self._file_tasks
            if t.status in (FileStatus.EXTRACTING, FileStatus.TRANSCRIBING, 
                            FileStatus.SUMMARIZING, FileStatus.GENERATING)
        ]
        self._rebuild_file_queue_ui()

    def _check_cloud_credits_before_processing(self) -> bool:
        """
        Pre-flight проверка кредитов MindType Cloud перед обработкой.

        Returns:
            True если можно продолжить, False если кредитов нет или отменено.
        """
        if not hasattr(self, '_cloud_provider') or not self._cloud_provider:
            self._init_mindtype_cloud()

        if not hasattr(self, '_cloud_provider') or not self._cloud_provider:
            QMessageBox.warning(
                self,
                self._t("error"),
                self._t("cloud_not_initialized"),
            )
            return False

        try:
            info = self._cloud_provider.get_balance()
            credits = info.credits

            if credits <= 0:
                from .llm.mindtype_cloud import LLMNoCreditsError
                reply = QMessageBox.warning(
                    self,
                    self._t("no_credits_title"),
                    self._t("no_credits_message"),
                    QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Open:
                    from PyQt6.QtGui import QDesktopServices
                    QDesktopServices.openUrl(QUrl("https://mindtype.space/buy-credits"))
                return False

            # Обновляем виджет баланса
            if hasattr(self, '_credits_widget'):
                self._credits_widget.set_balance(credits)

            return True

        except Exception as e:
            logger.warning(f"Failed to check credits: {e}")
            # При ошибке сети — разрешаем продолжить (сервер проверит)
            return True

    def _on_start_processing(self) -> None:
        """Начать обработку файлов."""
        from .crash_reporter import add_breadcrumb

        if not self._file_tasks:
            return

        pending_tasks = [t for t in self._file_tasks if t.status == FileStatus.PENDING]
        if not pending_tasks:
            return

        add_breadcrumb(f"Starting file processing: {len(pending_tasks)} files")

        # Создаём директорию вывода
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Запоминаем параметры запуска, чтобы понимать, что авто-открывать
        self._file_processing_batch_size = len(pending_tasks)
        self._file_output_format = self.output_format_combo.currentData()
        self._last_completed_task: Optional[FileTask] = None

        # Создаём очередь
        cfg = self.config.config

        # Загружаем промпты из пресета и объединяем с кастомными
        from .summary_presets import get_preset_prompts
        preset_id = cfg.get("summary_preset", "pm")
        preset_prompts = get_preset_prompts(preset_id)
        custom_prompts_saved = cfg.get("custom_prompts", {})
        # Кастомные промпты перезаписывают промпты из пресета
        custom_prompts = {**preset_prompts, **custom_prompts_saved} if custom_prompts_saved else preset_prompts

        # Определяем провайдер суммаризации из настроек
        llm_provider = cfg.get("llm_provider", "openrouter")
        summary_api_key = ""
        summary_model = ""
        summary_base_url = ""
        summary_reasoning = True
        summary_reasoning_effort = cfg.get("llm_reasoning_effort", "medium")

        if llm_provider == "mindtype_cloud":
            # MindType Cloud: используем лицензионный ключ
            license_info = self.license_manager.get_license_info()
            summary_api_key = license_info.license_key or ""
            summary_model = "auto"
            summary_reasoning = False  # Cloud не поддерживает reasoning
        elif llm_provider == "ollama":
            summary_base_url = cfg.get("ollama_base_url", "http://localhost:11434")
            summary_model = cfg.get("ollama_model", "")
            summary_reasoning = bool(cfg.get("llm_reasoning_enabled", True))
        else:
            # OpenAI, Anthropic, Gemini, OpenRouter
            summary_api_key = cfg.get(f"{llm_provider}_api_key", "")
            summary_model = cfg.get(f"{llm_provider}_model", "")
            summary_reasoning = bool(cfg.get("llm_reasoning_enabled", True))
            summary_reasoning_effort = cfg.get("llm_reasoning_effort", "medium")

        # Pre-flight проверка кредитов для MindType Cloud
        enable_summary = self.enable_summary_checkbox.isChecked()
        if enable_summary and llm_provider == "mindtype_cloud":
            if not self._check_cloud_credits_before_processing():
                return

        self._file_queue = FileTranscriptionQueue(
            transcriber=self.transcriber,
            model_size=cfg.get("model_size", "large-v3"),
            compute_type=cfg.get("compute_type", "int8"),
            device=cfg.get("device", "auto"),
            language=cfg.get("language", "ru"),
            beam_size=int(cfg.get("beam_size", 5)),
            vad_filter=bool(cfg.get("vad_filter", True)),
            models_dir=self.models_dir,
            enable_summary=self.enable_summary_checkbox.isChecked(),
            on_thinking=lambda text: self.thinking_signal.emit(text),  # Всегда включен
            enable_thinking=True,  # Всегда включен
            custom_prompts=custom_prompts,
            # Универсальные настройки провайдера
            summary_provider=llm_provider,
            summary_api_key=summary_api_key,
            summary_model=summary_model,
            summary_base_url=summary_base_url,
            summary_reasoning=summary_reasoning,
            summary_reasoning_effort=summary_reasoning_effort,
            # Legacy OpenRouter (обратная совместимость)
            openrouter_api_key=cfg.get("openrouter_api_key", ""),
            openrouter_model=cfg.get("openrouter_model", ""),
            openrouter_reasoning=bool(cfg.get("openrouter_reasoning", cfg.get("llm_reasoning_enabled", True))),
            openrouter_reasoning_effort=cfg.get("openrouter_reasoning_effort", "medium"),
            # Постобработка (диаризация, пунктуация и т.д.)
            enable_postprocessing=cfg.get("enable_postprocessing", True),
            postprocessing_diarization=cfg.get("postprocessing_diarization", True),
            postprocessing_punctuation=cfg.get("postprocessing_punctuation", True),
            postprocessing_fillers=cfg.get("postprocessing_fillers", True),
            postprocessing_normalize=cfg.get("postprocessing_normalize", True),
            postprocessing_correct=cfg.get("postprocessing_correct", True),
        )

        # Добавляем файлы
        for task in pending_tasks:
            self._file_queue._tasks.append(task)
            self._file_queue._queue.put(task)

        # Создаём и запускаем воркер
        self._file_worker = FileTranscriptionWorker(
            queue=self._file_queue,
            output_dir=self._output_dir,
            output_format=self.output_format_combo.currentData(),
            ui_language=self._ui_lang,
        )
        self._file_worker.task_progress.connect(self._on_file_task_progress)
        self._file_worker.task_completed.connect(self._on_file_task_completed)
        self._file_worker.all_completed.connect(self._on_all_files_completed)
        self._file_worker.start()

        # Обновляем UI
        self.start_processing_btn.setEnabled(False)
        self.start_processing_btn.setVisible(False)
        self.stop_processing_btn.setEnabled(True)
        self.stop_processing_btn.setVisible(True)
        self.drop_zone.setEnabled(False)

    def _on_stop_processing(self) -> None:
        """Остановить обработку."""
        if self._file_queue:
            self._file_queue.cancel()

        self.stop_processing_btn.setEnabled(False)

    def _on_file_task_progress(self, task: FileTask) -> None:
        """Обновление прогресса задачи."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

    def _on_file_task_completed(self, task: FileTask) -> None:
        """Задача завершена."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

        if task.status == FileStatus.COMPLETED:
            self._last_completed_task = task
            # Если обрабатываем один файл — открываем отчёт автоматически
            if getattr(self, "_file_processing_batch_size", 0) == 1:
                self._auto_open_transcription(task)

    def _on_all_files_completed(self) -> None:
        """Все файлы обработаны."""
        self.start_processing_btn.setVisible(True)
        self.stop_processing_btn.setEnabled(False)
        self.stop_processing_btn.setVisible(False)
        self.drop_zone.setEnabled(True)
        
        # Корректно обновляем состояние кнопок
        self._update_file_queue_ui()

        # Показываем уведомление
        completed = sum(1 for t in self._file_tasks if t.status == FileStatus.COMPLETED)
        total = len(self._file_tasks)

        if completed > 0:
            QMessageBox.information(
                self,
                self._t("processing_complete"),
                f"{self._t('files_processed')}: {completed}/{total}\n\n{self._output_dir}"
            )

            # Если файлов было несколько — открываем папку результатов
            if getattr(self, "_file_processing_batch_size", 0) > 1:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
            # Если файл был один и отчёт не открылся по какой-то причине — откроем хотя бы папку
            elif getattr(self, "_file_processing_batch_size", 0) == 1 and not self._last_completed_task:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _auto_open_transcription(self, task: FileTask) -> None:
        """Авто-открытие сгенерированного отчёта (HTML/PDF) для одного файла."""
        try:
            base_name = task.file_path.stem + "_transcription"
            html_path = self._output_dir / f"{base_name}.html"
            pdf_path = self._output_dir / f"{base_name}.pdf"

            fmt = getattr(self, "_file_output_format", "html")

            # При "both" открываем HTML (быстрее предпросмотр); при "pdf" — PDF если есть, иначе HTML.
            if fmt == "pdf":
                target = pdf_path if pdf_path.exists() else html_path
            elif fmt == "both":
                target = html_path if html_path.exists() else (pdf_path if pdf_path.exists() else html_path)
            else:
                target = html_path if html_path.exists() else pdf_path

            if target and target.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
        except Exception:
            # Не блокируем UI, если открыть не удалось
            pass

    def _add_file_widget(self, task: FileTask) -> None:
        """Добавить виджет файла в список."""
        widget = FileQueueItemWidget(task, translate_func=self._t)
        widget.remove_clicked.connect(self._on_remove_file_task)
        widget.open_clicked.connect(self._on_open_file_result)

        self._file_widgets[self._task_key(task.file_path)] = widget

        # Вставляем перед stretch
        idx = self._file_queue_layout.count() - 1
        self._file_queue_layout.insertWidget(idx, widget)

    def _on_remove_file_task(self, task: FileTask) -> None:
        """Удалить задачу из очереди."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.pop(key, None)
        if widget:
            widget.deleteLater()

        if task in self._file_tasks:
            self._file_tasks.remove(task)

        self._update_file_queue_ui()

    def _on_open_file_result(self, task: FileTask) -> None:
        """Открыть папку с результатом."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _update_file_queue_ui(self) -> None:
        """Обновить UI очереди."""
        has_files = len(self._file_tasks) > 0
        has_pending = any(t.status == FileStatus.PENDING for t in self._file_tasks)

        self._no_files_label.setVisible(not has_files)
        self.start_processing_btn.setEnabled(has_pending)

    def _rebuild_file_queue_ui(self) -> None:
        """Полностью перестроить UI очереди."""
        # Удаляем все виджеты
        for widget in self._file_widgets.values():
            widget.deleteLater()
        self._file_widgets.clear()

        # Добавляем заново
        for task in self._file_tasks:
            self._add_file_widget(task)

        self._update_file_queue_ui()

    def closeEvent(self, event) -> None:
        """Закрытие приложения или сворачивание в трей."""
        # Останавливаем обработку файлов если запущена
        if self._file_queue and self._file_queue.is_running:
            self._file_queue.cancel()

        # Если трей доступен и не нажат Exit - сворачиваем в трей
        if self.tray_icon and not self._really_quit:
            event.ignore()
            self.hide()
            return

        # Полное закрытие — останавливаем все фоновые потоки и ресурсы
        self._cleanup_all()
        super().closeEvent(event)

    def _cleanup_all(self) -> None:
        """Остановить все фоновые потоки и освободить ресурсы."""
        # Hotkeys
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.hotkey_recorder:
            self.hotkey_recorder.stop()

        # Assistant hotkeys
        if hasattr(self, '_assistant_hotkey_listener') and self._assistant_hotkey_listener:
            self._assistant_hotkey_listener.stop()
        if hasattr(self, '_assistant_hotkey_recorder') and self._assistant_hotkey_recorder:
            self._assistant_hotkey_recorder.stop()

        # Voice assistant
        if ASSISTANT_FEATURE_ENABLED and self.voice_assistant:
            try:
                self.voice_assistant.stop()
            except Exception:
                pass

        # Останавливаем запись аудио если идёт
        if self.audio.recording:
            self.audio.stop()
        self.audio.stop_monitoring()

        # Останавливаем QThread воркеры
        for worker in [
            self._transcribe_thread,
            self._download_thread,
            self._file_worker,
            self._update_check_worker,
            self._update_download_worker,
            getattr(self, '_credits_worker', None),
            getattr(self, '_history_worker', None),
        ]:
            if worker and worker.isRunning():
                worker.quit()
                if not worker.wait(2000):  # 2 секунды на завершение
                    worker.terminate()
                    worker.wait(1000)

        # UI cleanup
        self.overlay.hide()
        if self.tray_icon:
            self.tray_icon.hide()

        # Принудительно завершаем Qt event loop
        app = QApplication.instance()
        if app:
            app.quit()


def main() -> None:
    # Устанавливаем обработчик crash'ей ДО создания QApplication
    from .crash_reporter import install_crash_handler, set_crash_dialog_callback
    from .ui.dialogs import show_crash_dialog

    install_crash_handler()
    set_crash_dialog_callback(show_crash_dialog)

    app = QApplication(sys.argv)
    app.setWindowIcon(create_app_icon(64))  # Иконка для всего приложения

    # Загружаем шрифты Chicago/Geneva для system.css стиля
    from PyQt6.QtGui import QFontDatabase
    fonts_dir = Path(__file__).parent / "ui" / "fonts"
    for font_file in ["ChicagoFLF.ttf", "FindersKeepers.ttf"]:
        font_path = fonts_dir / font_file
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                logger.debug(f"Loaded font: {font_file} -> {families}")
            else:
                logger.warning(f"Failed to load font: {font_file}")

    # Force light theme (System 7 style)
    app.setStyle("Fusion")
    from PyQt6.QtGui import QPalette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(221, 221, 221))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Button, QColor(221, 221, 221))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    # Проверяем лицензию перед запуском
    license_manager = LicenseManager()
    has_access, info = license_manager.check_access()

    # Получаем язык из конфига для диалогов до создания MainWindow
    config = ConfigManager()
    ui_lang = config.config.get("ui_language", "ru")
    translate_func = lambda key: get_text(key, ui_lang)

    if not has_access:
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            # Показываем блокирующий диалог (нельзя закрыть)
            dialog = TrialExpiredDialog(license_manager, translate_func=translate_func)
            result = dialog.exec()
            # Если диалог закрылся без активации - выходим
            final_info = license_manager.get_license_info()
            if final_info.status != LicenseStatus.VALID:
                sys.exit(1)
        else:
            # Показываем обычный диалог активации
            dialog = LicenseActivationDialog(license_manager, translate_func=translate_func)
            result = dialog.exec()
            if dialog.should_block_app():
                sys.exit(1)

    window = MainWindow()
    window.show()

    exit_code = app.exec()

    # Принудительное завершение если остались висящие non-daemon потоки
    import threading
    alive = [t for t in threading.enumerate()
             if t.is_alive() and not t.daemon and t is not threading.main_thread()]
    if alive:
        logger.warning(f"Forcing exit, {len(alive)} non-daemon threads still alive: "
                       f"{[t.name for t in alive]}")
        # os._exit не вызывает atexit/finally, поэтому удаляем lock файл вручную
        lock_path = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "MindType" / ".lock"
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
        os._exit(exit_code)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
