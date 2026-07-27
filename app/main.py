# MindType - AI Speech-to-Text Desktop Application
# Copyright (c) 2024-2025 Butakov Maksim Vladimirovich. All rights reserved.
# Author: Butakov Maksim Vladimirovich <info@mindtype.space>
#
# This software is the confidential and proprietary information of the Author.

import logging
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

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

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt, QRectF, QUrl, QSize, QEvent
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
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QPen, QBrush, QDesktopServices, QDragEnterEvent, QDropEvent

from .audio import AudioRecorder
from .audio_sources import (
    AudioSourceKind,
    MultiTrackAudioRecorder,
    SystemAudioRecorder,
)
from .config import ConfigManager, DEFAULT_MODELS_DIR, BUNDLED_MODELS_DIR
from .operation_coordinator import OperationCoordinator
from .operation_ack import acknowledge_completed_operation
from .operation_models import OperationStage, OperationStatus, utc_now
from .operation_store import OperationStore
from .spool import SpoolManager
from .accelerator import has_npu, detect_available_providers
from .file_transcriber import (
    FileTranscriptionQueue,
    FileTask,
    FileStatus,
    ALL_EXTENSIONS,
    is_supported_file,
    TranscribeOptions,
    SummaryOptions,
    PostProcessOptions,
)
from .media_io import (
    MediaDurationTooLong,
    enforce_media_duration_limit,
    get_file_duration,
)
from .hotkeys import HotkeyListener, HotkeyRecorder
from .inserter import insert_text_result, focus_manager
from .licensing import LicenseManager, LicenseStatus
from .licensing.activation_dialog import LicenseActivationDialog, LicenseStatusWidget, TrialExpiredDialog
from .ui.setup_wizard import SetupWizard
from .ui.credits_widget import CreditsBalanceWidget, CreditsRefreshWorker, CreditsHistoryDialog, CreditsHistoryWorker
from .overlay import OverlayWidget
from .exporters import CanonicalExporter
from .accessibility import (
    configure_accessibility,
    windows_high_contrast_enabled,
)
from .optional_features import local_diarization_available
from .transcriber import (
    Transcriber,
    available_transcriber_backends,
    select_available_backend,
)
from .dictation_state import DictationState
from .data_routes import canonical_processing_route, resolve_processing_route
from .translations import (
    get_text,
    UI_LANGUAGES,
    WHISPER_LANGUAGES,
)
# Импорты ассистента (условные). Heavy optional runtimes must not be imported
# by the base desktop when the feature is excluded.
if ASSISTANT_FEATURE_ENABLED:
    from .assistant import VoiceAssistant, AssistantConfig, AssistantState, PERSONALITY_TEMPLATES
    from .assistant_overlay import AssistantOverlayWidget
    from .dialog_history import get_dialog_history_manager, Dialog
    from .tts import get_tts_engine, is_edge_tts_available, RUSSIAN_VOICES
    from .wake_word import is_openwakeword_available, WakeWordDetector
else:
    # Заглушки для типов
    VoiceAssistant = None  # type: ignore
    AssistantConfig = None  # type: ignore
    AssistantState = None  # type: ignore
    PERSONALITY_TEMPLATES = {}
    AssistantOverlayWidget = None  # type: ignore
    get_dialog_history_manager = None  # type: ignore
    Dialog = None  # type: ignore
    RUSSIAN_VOICES = []
    WakeWordDetector = None  # type: ignore

    def is_edge_tts_available() -> bool:
        return False

    def is_openwakeword_available() -> bool:
        return False

    def get_tts_engine():
        raise RuntimeError("Voice assistant is not included in this build")

from .updater import Updater, UpdateInfo

# Импорты из UI модуля
from .ui.styles import STYLESHEET
from .ui.tokens import COLORS, SPACING, TYPOGRAPHY
from .ui.icons import create_app_icon
from .ui.components import apply_system7_titlebar
from .ui.workers import (
    CloudCancellationWorker,
    OperationAcknowledgementWorker,
    CloudDictationWorker,
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
        self.setMinimumSize(740, 640)
        self.resize(900, 780)

        # Загружаем пресеты
        from .summary_presets import PRESETS, get_preset_prompts, DEFAULT_PRESET, PROMPT_KEYS
        self._presets = PRESETS
        self._get_preset_prompts = get_preset_prompts
        self._default_preset = DEFAULT_PRESET
        self._prompt_keys = PROMPT_KEYS

        # Пользовательские пресеты (рабочая копия). Отбрасываем повреждённые (не-dict)
        # записи из конфига, чтобы write-пути (save/rename) не падали на них.
        self._user_presets = {
            k: v for k, v in (self.config.config.get("user_presets", {}) or {}).items()
            if isinstance(v, dict)
        }

        # Текущий пресет из конфига (встроенный или пользовательский)
        self._current_preset = self.config.config.get("summary_preset", DEFAULT_PRESET)
        if self._current_preset not in self._presets and self._current_preset not in self._user_presets:
            self._current_preset = DEFAULT_PRESET

        self._build_ui()
        self._populate_preset_combo()
        self._load_editors(self._prompts_for(self._current_preset))

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
        self.preset_combo.setMinimumWidth(220)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        # CRUD-кнопки пользовательских пресетов
        crud_layout = QHBoxLayout()
        self.new_preset_btn = QPushButton(self._t("preset_new"))
        self.new_preset_btn.clicked.connect(self._on_new_preset)
        self.duplicate_preset_btn = QPushButton(self._t("preset_duplicate"))
        self.duplicate_preset_btn.clicked.connect(self._on_duplicate_preset)
        self.rename_preset_btn = QPushButton(self._t("preset_rename"))
        self.rename_preset_btn.clicked.connect(self._on_rename_preset)
        self.delete_preset_btn = QPushButton(self._t("preset_delete"))
        self.delete_preset_btn.setObjectName("dangerButton")
        self.delete_preset_btn.clicked.connect(self._on_delete_preset)
        for _b in (self.new_preset_btn, self.duplicate_preset_btn,
                   self.rename_preset_btn, self.delete_preset_btn):
            crud_layout.addWidget(_b)
        crud_layout.addStretch()
        layout.addLayout(crud_layout)

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
        apply_system7_titlebar(self, self._t("customize_prompts"))

    def _get_prompt_description(self, key: str) -> str:
        desc_keys = {
            "system": "prompt_desc_system",
            "short": "prompt_desc_short",
            "extraction": "prompt_desc_extraction",
            "aggregation": "prompt_desc_aggregation",
        }
        return self._t(desc_keys.get(key, ""))

    # ---- helpers --------------------------------------------------------
    def _preset_display_name(self, preset_id: str) -> str:
        """Отображаемое имя: user — как есть; встроенный — перевод name_key."""
        if preset_id in self._user_presets:
            data = self._user_presets[preset_id]
            return data.get("name", preset_id) if isinstance(data, dict) else preset_id
        p = self._presets.get(preset_id, {})
        return self._t(p.get("name_key", preset_id))

    def _prompts_for(self, preset_id: str) -> dict:
        """Промпты для редакторов: user → его набор; встроенный → пресет (+ сохранённые custom для активного)."""
        if preset_id in self._user_presets:
            return self._get_preset_prompts(preset_id, self._user_presets)
        base = self._get_preset_prompts(preset_id)
        saved = self.config.config.get("custom_prompts", {})
        active = self.config.config.get("summary_preset")
        if saved and preset_id == active:
            return {**base, **saved}
        return dict(base)

    def _load_editors(self, prompts: dict) -> None:
        for key, editor in self.prompt_editors.items():
            editor.setPlainText(prompts.get(key, ""))

    def _editor_prompts(self) -> dict:
        return {k: self.prompt_editors[k].toPlainText().strip() for k in self.prompt_editors}

    def _new_user_id(self) -> str:
        n = 1
        while f"user-{n}" in self._user_presets:
            n += 1
        return f"user-{n}"

    def _populate_preset_combo(self) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset_id, preset_data in self._presets.items():
            name = self._t(preset_data.get("name_key", preset_id))
            desc = self._t(preset_data.get("description_key", ""))
            self.preset_combo.addItem(f"{name} — {desc}", preset_id)
        for preset_id, data in self._user_presets.items():
            nm = data.get("name", preset_id) if isinstance(data, dict) else preset_id
            self.preset_combo.addItem(f"★ {nm}", preset_id)
        idx = self.preset_combo.findData(self._current_preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)
        is_user = self._current_preset in self._user_presets
        self.rename_preset_btn.setEnabled(is_user)
        self.delete_preset_btn.setEnabled(is_user)

    # ---- handlers -------------------------------------------------------
    def _on_preset_changed(self, index: int):
        preset_id = self.preset_combo.itemData(index)
        if not preset_id or preset_id == self._current_preset:
            return
        self._current_preset = preset_id
        self._load_editors(self._prompts_for(preset_id))
        is_user = preset_id in self._user_presets
        self.rename_preset_btn.setEnabled(is_user)
        self.delete_preset_btn.setEnabled(is_user)

    def _reset_prompt(self, key: str):
        """Сбросить один промпт к значению пресета."""
        prompts = self._get_preset_prompts(self._current_preset, self._user_presets)
        if key in self.prompt_editors and key in prompts:
            self.prompt_editors[key].setPlainText(prompts[key])

    def _reset_all_prompts(self):
        """Сбросить все промпты к значениям текущего пресета."""
        self._load_editors(self._get_preset_prompts(self._current_preset, self._user_presets))
        if self._current_preset not in self._user_presets:
            # для встроенного — заодно очищаем сохранённые кастомные правки
            self.config.update(custom_prompts={}, summary_preset=self._current_preset)
        from PyQt6.QtWidgets import QMessageBox
        name = self._preset_display_name(self._current_preset)
        msg = self._t("prompts_reset_message").replace("{preset}", name)
        QMessageBox.information(self, self._t("prompts_reset"), msg)

    def _save_prompts(self):
        """Сохранить промпты: user → полный набор; встроенный → diff в custom_prompts."""
        if self._current_preset in self._user_presets:
            self._user_presets[self._current_preset]["prompts"] = self._editor_prompts()
            self.config.update(
                user_presets=self._user_presets,
                summary_preset=self._current_preset,
                custom_prompts={},
            )
        else:
            preset_prompts = self._get_preset_prompts(self._current_preset)
            custom = {}
            for key, text in self._editor_prompts().items():
                if text and text != preset_prompts.get(key, ""):
                    custom[key] = text
            self.config.update(custom_prompts=custom, summary_preset=self._current_preset)
        self.close()

    def _on_new_preset(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, self._t("preset_new"), self._t("preset_name") + ":")
        if not ok or not name.strip():
            return
        pid = self._new_user_id()
        self._user_presets[pid] = {"name": name.strip(), "prompts": self._editor_prompts()}
        self._current_preset = pid
        self.config.update(user_presets=self._user_presets, summary_preset=pid, custom_prompts={})
        self._populate_preset_combo()
        self._load_editors(self._prompts_for(pid))

    def _on_duplicate_preset(self):
        prompts = self._editor_prompts()  # копируем то, что показано (учитывая правки в редакторах)
        base_name = self._preset_display_name(self._current_preset)
        pid = self._new_user_id()
        self._user_presets[pid] = {
            "name": f"{base_name} ({self._t('preset_copy_suffix')})",
            "prompts": {k: prompts.get(k, "") for k in self._prompt_keys},
        }
        self._current_preset = pid
        self.config.update(user_presets=self._user_presets, summary_preset=pid, custom_prompts={})
        self._populate_preset_combo()
        self._load_editors(self._prompts_for(pid))

    def _on_rename_preset(self):
        if self._current_preset not in self._user_presets:
            return
        from PyQt6.QtWidgets import QInputDialog
        cur = self._user_presets[self._current_preset].get("name", "")
        name, ok = QInputDialog.getText(self, self._t("preset_rename"), self._t("preset_name") + ":", text=cur)
        if not ok or not name.strip():
            return
        self._user_presets[self._current_preset]["name"] = name.strip()
        self.config.update(user_presets=self._user_presets)
        self._populate_preset_combo()

    def _on_delete_preset(self):
        if self._current_preset not in self._user_presets:
            return
        from PyQt6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self, self._t("preset_delete"), self._t("preset_delete_confirm")
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._user_presets.pop(self._current_preset, None)
        self._current_preset = self._default_preset
        self.config.update(user_presets=self._user_presets, summary_preset=self._default_preset)
        self._populate_preset_combo()
        self._load_editors(self._prompts_for(self._current_preset))


class AppTitleBar(QFrame):
    """Полосатый System-7 title bar для frameless главного окна.

    Перетаскивание/снап — через нативный startSystemMove (без ручного хит-теста).
    Кнопки: свернуть / развернуть-восстановить / закрыть.
    """

    def __init__(self, window: QMainWindow, title: str):
        super().__init__()
        self._win = window
        self._press_pos = None  # стартовая точка для drag (см. mouseMoveEvent)
        self.setObjectName("appTitleBar")
        self.setFixedHeight(24)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("system7TitleLabel")
        lay.addStretch()
        lay.addWidget(self._title_label)
        lay.addStretch()

        for glyph, slot, name in (
            ("–", self._win.showMinimized, "winMin"),
            ("☐", self._toggle_max, "winMax"),
            ("✕", self._win.close, "winClose"),
        ):
            btn = QPushButton(glyph)
            btn.setObjectName(name)
            btn.setFixedSize(18, 16)
            accessible_names = {
                "winMin": "Minimize window",
                "winMax": "Maximize or restore window",
                "winClose": "Close window",
            }
            btn.setAccessibleName(accessible_names[name])
            btn.setToolTip(accessible_names[name])
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
            if name == "winMax":
                self._max_btn = btn

    def set_title(self, title: str) -> None:
        self._title_label.setText(title)

    def _toggle_max(self) -> None:
        # Ручной maximize: showMaximized() на frameless-окне перекрывает таскбар,
        # поэтому разворачиваем в availableGeometry (рабочая область без таскбара).
        win = self._win
        if getattr(win, "_user_maximized", False):
            geom = getattr(win, "_restore_geometry", None)
            if geom is not None:
                win.setGeometry(geom)
            win._user_maximized = False
            self._max_btn.setText("☐")
        else:
            win._restore_geometry = win.geometry()
            screen = win.screen() or QApplication.primaryScreen()
            win.setGeometry(screen.availableGeometry())
            win._user_maximized = True
            self._max_btn.setText("❐")

    def mousePressEvent(self, event) -> None:
        # НЕ запускаем startSystemMove на press — иначе нативный move-loop съедает
        # double-click (maximize). Запоминаем точку, тащим только при реальном движении.
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._press_pos = None
            handle = self._win.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._press_pos = None
        self._toggle_max()
        super().mouseDoubleClickEvent(event)


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
        self._high_contrast = windows_high_contrast_enabled()
        # Native chrome is required for the Windows High Contrast contract.
        if not self._high_contrast:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(980, 520)
        self.resize(1060, 600)

        self.config = ConfigManager()
        self._operation_coordinator: Optional[OperationCoordinator] = None
        try:
            operation_store = OperationStore(
                self.config.config_dir / "cloud_jobs.sqlite3"
            )
            self._operation_coordinator = OperationCoordinator(
                store=operation_store,
                spool=SpoolManager(self.config.config_dir / "spool"),
            )
        except Exception:
            logger.exception("Could not initialize durable operation coordinator")
        self.audio = AudioRecorder()
        self.system_audio = SystemAudioRecorder()
        self.audio_session = MultiTrackAudioRecorder(
            microphone=self.audio,
            system=self.system_audio,
        )
        saved_backend = self.config.config.get("transcriber_backend", "whisper_cpp")
        backend = select_available_backend(saved_backend)
        if backend != saved_backend:
            logger.warning(
                "Configured transcription backend %s is unavailable; using %s",
                saved_backend,
                backend,
            )
            self.config.update(transcriber_backend=backend)
        self._transcriber_backend = backend
        self.transcriber = self._build_transcriber(backend)
        self.hotkey_listener: Optional[HotkeyListener] = None
        self.hotkey_recorder: Optional[HotkeyRecorder] = None

        # Determine models directory (must be writable for model downloads).
        desired_models_dir = Path(self.config.config.get("models_dir", str(DEFAULT_MODELS_DIR)))

        def _is_writable_dir(path: Path) -> bool:
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return True
            except Exception:
                try:
                    (path / ".write_probe").unlink(missing_ok=True)
                except Exception:
                    pass
                return False

        if not _is_writable_dir(desired_models_dir):
            # Fallback to a safe per-user location (e.g. %APPDATA%\\MindType\\models on Windows).
            fallback_models_dir = Path(DEFAULT_MODELS_DIR)
            if _is_writable_dir(fallback_models_dir):
                logger.warning(
                    f"Configured models_dir is not writable: {desired_models_dir}. "
                    f"Falling back to: {fallback_models_dir}"
                )
                self.models_dir = fallback_models_dir
                self.config.update(models_dir=str(self.models_dir))
            else:
                # Worst-case: keep the configured dir, but downloads may fail.
                logger.error(
                    f"Neither configured models_dir nor fallback is writable. "
                    f"Configured: {desired_models_dir}, fallback: {fallback_models_dir}"
                )
                self.models_dir = desired_models_dir
        else:
            self.models_dir = desired_models_dir
        self._transcribe_thread: Optional[QThread] = None
        self._cancellation_workers: set[QThread] = set()
        self._acknowledgement_workers: set[QThread] = set()
        self._download_thread: Optional[ModelDownloadWorker] = None
        self.last_text: str = ""
        self._dictation = DictationState()  # машина состояний диктовки (запись→транскрипция→вставка)
        self._dictation_operation_ids: dict[int, str] = {}
        self._dictation_durations_ms: dict[int, int] = {}
        self._retryable_dictation_ids: list[str] = []
        self._audio_finalize_retry_token: Optional[int] = None
        self._recording_hotkey = False  # отдельная забота: идёт перепривязка хоткея в настройках
        self._really_quit = False  # Флаг для полного выхода
        self._preserve_cloud_jobs_on_shutdown = False

        # Текущий язык интерфейса
        self._ui_lang = self.config.config.get("ui_language", "ru")

        # Система лицензирования
        self.license_manager = LicenseManager()
        self._cloud_session_manager = None
        self._cloud_client = None
        self._cloud_executor = None
        try:
            from .env import API_BASE_URL
            from .licensing.session import (
                CloudSessionManager,
                KeyringRefreshTokenStore,
                LicenseSessionClient,
            )

            lease_store = (
                self.license_manager.get_entitlement_lease_store()
            )
            if lease_store is not None:
                self._cloud_session_manager = CloudSessionManager(
                    client=LicenseSessionClient(API_BASE_URL),
                    lease_store=lease_store,
                    install_lease=(
                        self.license_manager.install_entitlement_lease
                    ),
                    refresh_store=KeyringRefreshTokenStore(),
                    device_id=self.license_manager.get_device_id(),
                )
                self.license_manager.add_deactivation_cleanup(
                    self._cloud_session_manager.clear
                )
                self.license_manager.set_cloud_deactivator(
                    self._cloud_session_manager.deactivate_remote
                )
        except Exception:
            logger.exception("MindType Cloud session boundary is unavailable")
        self.license_manager.revalidate_if_needed_async()
        self._license_revalidation_timer = QTimer(self)
        self._license_revalidation_timer.timeout.connect(
            self.license_manager.revalidate_if_needed_async
        )
        self._license_revalidation_timer.start(60 * 60 * 1000)

        # Инициализация UI элементов ассистента (будут созданы позже в _build_ui)
        self.assistant_enable_check = None

        # Система обновлений
        self.updater = Updater(
            rollout_device_id=self.license_manager.get_device_id(),
        )
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
        configure_accessibility(self)
        self._connect_signals()
        self._load_initial_state()
        self._restore_durable_operations()
        self._spool_cleanup_timer = QTimer(self)
        self._spool_cleanup_timer.setInterval(24 * 60 * 60 * 1000)
        self._spool_cleanup_timer.timeout.connect(self._cleanup_expired_spool)
        self._spool_cleanup_timer.start()
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
        elif (
            not self.config.config.get("use_mindtype_cloud", False)
            and not self._has_any_model()
        ):
            # Setup done but no models - show model download only
            self._show_first_run_dialog()

    def _show_setup_wizard(self) -> None:
        """Show the first-run setup wizard."""
        wizard = SetupWizard(self.config, self._t, self.license_manager, self)

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
            lambda path, err: wizard.model_page.download_finished(err == "", err)
        )
        downloader.start()
        self._download_worker = downloader  # Keep reference
        logger.info("Model download worker started")

    def _init_mindtype_cloud(self) -> None:
        """Initialize MindType Cloud provider."""
        try:
            if self._cloud_session_manager is None:
                raise RuntimeError(
                    "MindType Cloud session boundary is unavailable"
                )
            from .llm import configure_mindtype_cloud_session
            from .llm.mindtype_cloud import MindTypeCloudProvider

            configure_mindtype_cloud_session(
                self._cloud_session_manager.access_token,
                self._refresh_mindtype_cloud_session,
            )
            self._cloud_provider = MindTypeCloudProvider(
                access_token=self._cloud_session_manager.access_token,
                refresh_access_token=self._refresh_mindtype_cloud_session,
            )
            if self._operation_coordinator is None:
                raise RuntimeError(
                    "Durable operation storage is unavailable"
                )
            from .env import API_BASE_URL
            from .providers.mindtype_cloud import (
                MindTypeCloudClient,
                MindTypeCloudExecutor,
            )

            self._cloud_client = MindTypeCloudClient(
                API_BASE_URL,
                access_token=self._cloud_session_manager.access_token,
                refresh_access_token=self._refresh_mindtype_cloud_session,
            )
            self._cloud_executor = MindTypeCloudExecutor(
                client=self._cloud_client,
                coordinator=self._operation_coordinator,
            )

            # Update credits balance widget if exists
            if hasattr(self, '_credits_widget'):
                self._refresh_credits_balance()

            logger.info("MindType Cloud provider initialized")
        except Exception as e:
            logger.error(f"Failed to initialize MindType Cloud: {e}")

    def _refresh_mindtype_cloud_session(self) -> None:
        """Refresh or create a short-lived session without persisting access."""
        if self._cloud_session_manager is None:
            raise RuntimeError(
                "MindType Cloud session boundary is unavailable"
            )
        from .licensing.session import LicenseSessionError

        try:
            self._cloud_session_manager.refresh_access_token()
            return
        except LicenseSessionError as error:
            if error.code != "AUTH_REQUIRED":
                if error.authoritative:
                    self.license_manager.clear_authoritative_cache()
                raise

        license_info = self.license_manager.get_license_info()
        license_key = license_info.license_key or ""
        if not license_key:
            raise LicenseSessionError(
                "AUTH_REQUIRED",
                "MindType Cloud requires an activated license",
                retryable=False,
                authoritative=True,
            )
        try:
            self._cloud_session_manager.activate(
                license_key=license_key,
                desktop_version=APP_VERSION,
                platform="win32",
            )
        except LicenseSessionError as error:
            if error.authoritative:
                self.license_manager.clear_authoritative_cache()
            raise

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

        # Cloud work requires a fresh explicit opt-in in this session.
        if hasattr(self, "enable_summary_checkbox") and self.enable_summary_checkbox:
            self.enable_summary_checkbox.setChecked(False)
            self._update_data_route_disclosure()

        logger.info("Configuration applied from setup wizard")

    def _has_any_model(self) -> bool:
        """Check if at least one model is available (downloaded or bundled)."""
        search_roots: List[Path] = []
        try:
            search_roots.append(self.models_dir)
        except Exception:
            pass
        try:
            if BUNDLED_MODELS_DIR not in search_roots:
                search_roots.append(BUNDLED_MODELS_DIR)
        except Exception:
            pass

        for root in search_roots:
            if not root.exists():
                continue

            # GGML whisper.cpp models (ggml-*.bin) in root.
            for f in root.iterdir():
                if f.is_file() and f.name.startswith("ggml-") and f.name.endswith(".bin"):
                    return True

            # HuggingFace-style model dirs (legacy/other backends).
            for subdir in root.iterdir():
                if not subdir.is_dir():
                    continue

                if (subdir / "config.json").exists():
                    has_weights = (
                        (subdir / "model.bin").exists()
                        or (subdir / "model.safetensors").exists()
                        or (subdir / "pytorch_model.bin").exists()
                        or any(
                            f.name.endswith(".safetensors")
                            for f in subdir.iterdir()
                            if f.is_file()
                        )
                    )
                    if has_weights:
                        return True

                    # If config exists but weights are incomplete, consider the model present
                    # if the directory is already reasonably large (download likely in progress).
                    try:
                        total_size = sum(
                            f.stat().st_size for f in subdir.rglob("*") if f.is_file()
                        )
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
            ggml_bundled_path = BUNDLED_MODELS_DIR / f"ggml-{name}.bin"
            onnx_path = self.models_dir / name
            onnx_bundled_path = BUNDLED_MODELS_DIR / name
            is_downloaded = (
                ggml_path.exists()
                or ggml_bundled_path.exists()
                or (onnx_path.exists() and (onnx_path / "model.bin").exists())
                or (onnx_bundled_path.exists() and (onnx_bundled_path / "model.bin").exists())
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
        if not self._high_contrast:
            self.setStyleSheet(STYLESHEET)

        # Главный контейнер: рамка окна (frameless) = полосатый title bar + контент.
        central = QWidget()
        central.setObjectName("appWindowFrame")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title_bar = None
        if not self._high_contrast:
            self._title_bar = AppTitleBar(self, "MindType")
            outer.addWidget(self._title_bar)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        main_layout.setSpacing(SPACING["lg"])
        outer.addWidget(content, stretch=1)

        # Вкладки - порядок: Основные, Саммари, Настройки
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), self._t("basic"))
        self.tabs.addTab(self._build_files_tab(), self._t("files_tab"))
        self.tabs.addTab(self._build_additional_tab(), self._t("additional"))

        # Угол таб-бара: кредиты (нужны только для MindType Cloud) + кнопка журнала.
        # ponytail: simple/advanced режим удалён (мёртвый — ничего не скрывал); журнал вынесен в окно.
        self._credits_widget = CreditsBalanceWidget(self._t, self)
        self._credits_widget.history_requested.connect(self._on_credits_history_requested)
        is_mindtype_cloud = self.config.config.get("llm_provider", "") == "mindtype_cloud"
        self._credits_widget.setVisible(is_mindtype_cloud)

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, SPACING["sm"], 0)
        corner_layout.setSpacing(SPACING["sm"])
        corner_layout.addWidget(self._credits_widget)
        self.journal_btn = QPushButton(self._t("journal"))
        self.journal_btn.setObjectName("smallButton")
        self.journal_btn.clicked.connect(self._toggle_journal_window)
        corner_layout.addWidget(self.journal_btn)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        if is_mindtype_cloud:
            self._init_mindtype_cloud()

        main_layout.addWidget(self.tabs, stretch=1)

        # Ресайз frameless-окна: нативный QSizeGrip в правом-нижнем углу.
        # ponytail: только угловой grip; ресайз со всех краёв — если попросят.
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        grip_row.addWidget(QSizeGrip(content))
        main_layout.addLayout(grip_row)

        # Журнал событий — в отдельном окне, открывается кнопкой в углу таб-бара
        self._journal_window = self._build_journal_window()

        self.setCentralWidget(central)
        self._status_bar = self.statusBar()
        self._status_bar.setObjectName("accessibilityStatus")
        self._status_bar.setAccessibleName("MindType status")
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.showMessage(self._t("ready"))

    def _build_basic_tab(self) -> QWidget:
        """Построить вкладку основных настроек."""
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"])
        tab_layout.setSpacing(SPACING["sm"])

        # === Секция: Распознавание речи (единый стиль с вкладкой Настройки) ===
        rec_section = SectionBox(self._t("recognition_section"), label_width=140)
        self.recognition_section_label = rec_section

        self.audio_source_box = QComboBox()
        self.audio_source_box.addItem(
            self._t("microphone_only"),
            AudioSourceKind.MICROPHONE.value,
        )
        self.audio_source_box.addItem(
            self._t("system_audio_only"),
            AudioSourceKind.SYSTEM.value,
        )
        self.audio_source_box.addItem(
            self._t("microphone_and_system"),
            AudioSourceKind.MICROPHONE_SYSTEM.value,
        )
        self._audio_source_row = rec_section.form.add_row(
            self._t("audio_source"),
            self.audio_source_box,
        )

        # Аудио вход
        self.mic_box = QComboBox()
        self._audio_input_row = rec_section.form.add_row(
            self._t("audio_input"),
            self.mic_box,
        )
        self.audio_input_label = self._audio_input_row.label

        self.system_audio_box = QComboBox()
        self._system_audio_row = rec_section.form.add_row(
            self._t("system_audio_device"),
            self.system_audio_box,
        )
        self.system_audio_consent_toggle = QCheckBox(
            self._t("system_audio_consent")
        )
        rec_section.form.add_widget(self.system_audio_consent_toggle)
        self._system_audio_consent_row = self.system_audio_consent_toggle

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
        self._hotkey_row = rec_section.form.add_row(self._t("hotkey"), hotkey_widget)
        self.hotkey_label = self._hotkey_row.label

        # Язык транскрипции
        self.trans_lang_box = QComboBox()
        for code, name in WHISPER_LANGUAGES.items():
            display = f"{name} ({code.upper()})" if code != "auto" else name
            self.trans_lang_box.addItem(display, code)
        self._trans_lang_row = rec_section.form.add_row(self._t("transcription_language"), self.trans_lang_box)
        self.trans_lang_label = self._trans_lang_row.label

        self.dictation_route_label = QLabel()
        self.dictation_route_label.setWordWrap(True)
        rec_section.form.add_widget(self.dictation_route_label)
        self._update_data_route_disclosure()

        tab_layout.addWidget(rec_section)

        # === Секция: Статус лицензии ===
        lic_section = SectionBox(self._t("license_status"), label_width=140)
        self.license_section_label = lic_section
        self.license_status_widget = LicenseStatusWidget(
            self.license_manager,
            translate_func=self._t
        )
        self.license_status_widget.clicked.connect(self._show_license_dialog)
        lic_section.form.add_widget(self.license_status_widget)
        tab_layout.addWidget(lic_section)

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

        # Две колонки: слева — AI/Промпты/Overlay/App, справа — Производительность
        # (она самая высокая, поэтому идёт отдельной колонкой для баланса).
        _cols = QWidget()
        _cols_layout = QHBoxLayout(_cols)
        _cols_layout.setContentsMargins(0, 0, 0, 0)
        _cols_layout.setSpacing(SPACING["lg"])
        _left_col = QVBoxLayout()
        _left_col.setSpacing(SPACING["lg"])
        _right_col = QVBoxLayout()
        _right_col.setSpacing(SPACING["lg"])
        _cols_layout.addLayout(_left_col, 1)
        _cols_layout.addLayout(_right_col, 1)
        scroll.content_layout.addWidget(_cols)

        # === Секция AI Provider ===
        ai_section = SectionBox(self._t("ai_provider"), label_width=140)
        self.ai_section_label = ai_section  # Для совместимости

        # Выбор провайдера
        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(120)
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
        # Показывать начало имени модели (а не хвост) при выборе длинного значения
        self.model_combo.currentIndexChanged.connect(
            lambda: self.model_combo.lineEdit().setCursorPosition(0)
        )
        self.model_combo.addItem(self._t("select_model"), "")
        self.refresh_models_btn = QPushButton("↻")  # компактная иконка — больше места дропдауну
        self.refresh_models_btn.setObjectName("smallButton")
        self.refresh_models_btn.setFixedWidth(34)
        self.refresh_models_btn.setToolTip(self._t("refresh_models"))
        self.refresh_models_btn.clicked.connect(self._on_refresh_models)
        model_layout.addWidget(self.model_combo, stretch=1)
        model_layout.addWidget(self.refresh_models_btn)
        self._model_select_row = ai_section.form.add_row(self._t("openrouter_model"), model_widget)
        self.model_select_label = self._model_select_row.label

        # Reasoning mode — выравниваем по сетке формы: чекбокс занимает колонку
        # подписей (140px), combo встаёт ровно в колонку полей под остальными.
        reasoning_widget = QWidget()
        reasoning_layout = QHBoxLayout(reasoning_widget)
        reasoning_layout.setContentsMargins(0, 0, 0, 0)
        reasoning_layout.setSpacing(SPACING["md"])
        self.reasoning_checkbox = QCheckBox(self._t("reasoning_mode"))
        self.reasoning_checkbox.setToolTip(self._t("reasoning_tooltip"))
        self.reasoning_checkbox.setFixedWidth(140)
        self.reasoning_checkbox.stateChanged.connect(self._on_reasoning_changed)
        # «Глубина» как отдельная подпись убрана для компактности — смысл несёт сам combo
        # (Низкая/Средняя/Высокая) + tooltip.
        self.effort_combo = QComboBox()
        self.effort_combo.addItem(self._t("effort_low"), "low")
        self.effort_combo.addItem(self._t("effort_medium"), "medium")
        self.effort_combo.addItem(self._t("effort_high"), "high")
        self.effort_combo.setCurrentIndex(1)
        self.effort_combo.setObjectName("compactCombo")
        self.effort_combo.setToolTip(self._t("reasoning_effort"))
        self.effort_combo.currentIndexChanged.connect(self._on_effort_changed)
        reasoning_layout.addWidget(self.reasoning_checkbox)
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

        _left_col.addWidget(ai_section)

        # === Секция Промпты саммари ===
        prompts_section = SectionBox(self._t("summary_prompts_section"), label_width=140)
        self.prompts_section_label = prompts_section
        prompts_hint = QLabel(self._t("manage_presets_hint"))
        prompts_hint.setObjectName("tinyMuted")
        prompts_hint.setWordWrap(True)
        prompts_section.form.add_widget(prompts_hint)
        self.manage_presets_btn = QPushButton(self._t("manage_presets"))
        self.manage_presets_btn.clicked.connect(self._on_customize_prompts)
        prompts_section.form.add_widget(self.manage_presets_btn)
        _left_col.addWidget(prompts_section)

        # === Секция Performance ===
        perf_section = SectionBox(self._t("performance_section"), label_width=140)
        self.perf_section_label = perf_section

        # VAD Filter
        self.vad_toggle = QCheckBox()
        self.vad_toggle.setChecked(True)
        self._vad_row = perf_section.form.add_row(self._t("vad_filter"), self.vad_toggle)
        self.vad_label = self._vad_row.label

        self.auto_insert_toggle = QCheckBox()
        self.auto_insert_toggle.setChecked(True)
        self._auto_insert_row = perf_section.form.add_row(
            self._t("auto_insert"),
            self.auto_insert_toggle,
        )
        self.auto_insert_label = self._auto_insert_row.label

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
        available_backends = set(available_transcriber_backends())
        self.backend_box.addItem(self._t("backend_whispercpp"), "whisper_cpp")
        if "faster_whisper" in available_backends:
            self.backend_box.addItem(self._t("backend_faster_whisper"), "faster_whisper")
        if "onnx" in available_backends:
            self.backend_box.addItem(self._t("backend_onnx"), "onnx")
        self.backend_box.addItem(self._t("backend_openrouter"), "openrouter")
        self._backend_row = perf_section.form.add_row(self._t("whisper_backend"), self.backend_box)
        self.backend_label = self._backend_row.label

        # Модель транскрипции OpenRouter (динамический список, как для саммари)
        transcribe_model_widget = QWidget()
        transcribe_model_layout = QHBoxLayout(transcribe_model_widget)
        transcribe_model_layout.setContentsMargins(0, 0, 0, 0)
        transcribe_model_layout.setSpacing(SPACING["sm"])
        self.transcribe_model_combo = QComboBox()
        self.transcribe_model_combo.setEditable(True)
        self.transcribe_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.transcribe_model_combo.currentIndexChanged.connect(
            lambda: self.transcribe_model_combo.lineEdit().setCursorPosition(0)
        )
        self.transcribe_model_combo.addItem(self._t("select_model"), "")
        self.transcribe_refresh_btn = QPushButton("↻")  # компактная иконка
        self.transcribe_refresh_btn.setObjectName("smallButton")
        self.transcribe_refresh_btn.setFixedWidth(34)
        self.transcribe_refresh_btn.setToolTip(self._t("refresh_models"))
        transcribe_model_layout.addWidget(self.transcribe_model_combo, 1)
        transcribe_model_layout.addWidget(self.transcribe_refresh_btn)
        self._transcribe_model_row = perf_section.form.add_row(self._t("transcribe_model"), transcribe_model_widget)
        self.transcribe_model_label = self._transcribe_model_row.label

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

        # Источники загрузки моделей (опциональный override, если HF недоступен)
        sources_widget = QWidget()
        sources_layout = QVBoxLayout(sources_widget)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        sources_layout.setSpacing(SPACING["xs"])

        self.model_sources_edit = QPlainTextEdit()
        self.model_sources_edit.setFixedHeight(90)
        try:
            self.model_sources_edit.setPlaceholderText(
                "\n".join(
                    [
                        "https://cdn.mindtype.space/models/whispercpp",
                        "https://mindtype.space/models/whispercpp",
                        "https://hf-mirror.com/{repo_id}/resolve/main/{filename}",
                        "https://huggingface.co/{repo_id}/resolve/main/{filename}",
                    ]
                )
            )
        except Exception:
            pass
        sources_layout.addWidget(self.model_sources_edit)

        self.model_sources_hint = QLabel(self._t("model_download_sources_hint"))
        self.model_sources_hint.setObjectName("tinyMuted")
        self.model_sources_hint.setWordWrap(True)
        sources_layout.addWidget(self.model_sources_hint)

        sources_btns = QWidget()
        sources_btns_layout = QHBoxLayout(sources_btns)
        sources_btns_layout.setContentsMargins(0, 0, 0, 0)
        sources_btns_layout.setSpacing(SPACING["sm"])
        sources_btns_layout.addStretch()

        self.model_sources_save_btn = QPushButton(self._t("save"))
        self.model_sources_save_btn.clicked.connect(self._save_model_download_sources)
        sources_btns_layout.addWidget(self.model_sources_save_btn)

        self.model_sources_reset_btn = QPushButton(self._t("reset_to_default"))
        self.model_sources_reset_btn.clicked.connect(self._reset_model_download_sources)
        sources_btns_layout.addWidget(self.model_sources_reset_btn)

        sources_layout.addWidget(sources_btns)

        self._model_sources_row = perf_section.form.add_row(self._t("model_download_sources"), sources_widget)
        self.model_sources_label = self._model_sources_row.label

        _right_col.addWidget(perf_section)

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

        self.reduced_motion_toggle = QCheckBox(self._t("reduced_motion"))
        overlay_section.form.add_widget(self.reduced_motion_toggle)

        _left_col.addWidget(overlay_section)

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

        _right_col.addWidget(app_section)
        _left_col.addStretch()
        _right_col.addStretch()
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
        self.drop_zone.setFixedHeight(120)  # минимум под иконку + 3 строки текста (иначе форматы обрезаются)
        layout.addWidget(self.drop_zone)

        # Включить суммаризацию (checkbox напрямую)
        self.enable_summary_checkbox = QCheckBox(self._t("enable_summary"))
        # Every session starts without summarization until the user opts in.
        cfg = self.config.config
        self.enable_summary_checkbox.setChecked(False)
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        layout.addWidget(self.enable_summary_checkbox)

        # Формат отчёта (HTML / PDF / оба)
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(SPACING["sm"])
        self.output_format_label = QLabel(self._t("report_format"))
        format_row.addWidget(self.output_format_label)
        self.output_format_combo = QComboBox()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        saved_fmt = cfg.get("report_format", "both")
        _fmt_idx = self.output_format_combo.findData(saved_fmt)
        self.output_format_combo.setCurrentIndex(_fmt_idx if _fmt_idx >= 0 else self.output_format_combo.findData("both"))
        self.output_format_combo.currentIndexChanged.connect(
            lambda: self.config.update(report_format=self.output_format_combo.currentData())
        )
        format_row.addWidget(self.output_format_combo)
        format_row.addStretch()
        layout.addLayout(format_row)

        # Способ диаризации (определение спикеров)
        diar_row = QHBoxLayout()
        diar_row.setContentsMargins(0, 0, 0, 0)
        diar_row.setSpacing(SPACING["sm"])
        self.diarization_backend_label = QLabel(self._t("diarization_backend"))
        diar_row.addWidget(self.diarization_backend_label)
        self.diarization_backend_combo = QComboBox()
        self.diarization_backend_combo.addItem(self._t("diarization_backend_auto"), "auto")
        self.diarization_backend_combo.addItem(self._t("diarization_backend_openrouter"), "openrouter")
        self.diarization_backend_combo.addItem(self._t("diarization_backend_local"), "local")
        saved_diar = cfg.get("postprocessing_diarization_backend", "auto")
        _diar_idx = self.diarization_backend_combo.findData(saved_diar)
        self.diarization_backend_combo.setCurrentIndex(
            _diar_idx if _diar_idx >= 0 else self.diarization_backend_combo.findData("auto")
        )
        self._configure_local_diarization_option()
        self.diarization_backend_combo.setToolTip(self._t("diarization_backend_tooltip"))
        self.diarization_backend_combo.currentIndexChanged.connect(
            lambda: self.config.update(
                postprocessing_diarization_backend=self.diarization_backend_combo.currentData()
            )
        )
        diar_row.addWidget(self.diarization_backend_combo)
        diar_row.addStretch()
        layout.addLayout(diar_row)

        self.data_route_label = QLabel()
        self.data_route_label.setWordWrap(True)
        layout.addWidget(self.data_route_label)
        self.enable_summary_checkbox.toggled.connect(
            self._update_data_route_disclosure
        )
        self.diarization_backend_combo.currentIndexChanged.connect(
            self._update_data_route_disclosure
        )
        self._update_data_route_disclosure()

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

    def _build_journal_window(self) -> QWidget:
        """Журнал событий — отдельное окно (открывается кнопкой)."""
        win = QWidget(self)
        win.setWindowFlag(Qt.WindowType.Window)
        win.setObjectName("whiteBackground")
        win.setWindowTitle(self._t("journal"))
        win.resize(640, 380)
        layout = QVBoxLayout(win)
        layout.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        layout.setSpacing(SPACING["xs"])

        # Заголовок несёт сам title bar окна — внутри только кнопка очистки (справа)
        journal_header = QHBoxLayout()
        self.retry_dictation_btn = QPushButton(
            self._t("retry_recovered_dictation")
        )
        self.retry_dictation_btn.setObjectName("smallButton")
        self.retry_dictation_btn.setVisible(False)
        self.retry_dictation_btn.clicked.connect(
            self._retry_next_recovered_dictation
        )
        journal_header.addWidget(self.retry_dictation_btn)
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
        journal_frame_layout.addWidget(self.journal)

        layout.addWidget(journal_frame, stretch=1)

        apply_system7_titlebar(win, self._t("journal"))
        return win

    def _toggle_journal_window(self) -> None:
        """Показать/скрыть окно журнала."""
        if self._journal_window.isVisible():
            self._journal_window.hide()
        else:
            self._journal_window.show()
            self._journal_window.raise_()
            self._journal_window.activateWindow()

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
        self.backend_box.currentIndexChanged.connect(self._on_backend_change)
        self.transcribe_refresh_btn.clicked.connect(self._on_refresh_transcribe_models)
        self.transcribe_model_combo.currentIndexChanged.connect(self._on_transcribe_model_changed)
        self.audio_source_box.currentIndexChanged.connect(
            self._on_audio_source_change
        )
        self.mic_box.currentTextChanged.connect(self._on_mic_change)
        self.system_audio_box.currentIndexChanged.connect(
            self._on_system_audio_device_change
        )
        self.system_audio_consent_toggle.toggled.connect(
            lambda enabled: self.config.update(
                system_audio_consent=enabled
            )
        )
        self.hotkey_record_btn.clicked.connect(self._start_hotkey_recording)

        # Дополнительные
        self.vad_toggle.toggled.connect(lambda v: self.config.update(vad_filter=v))
        self.auto_insert_toggle.toggled.connect(
            lambda enabled: self.config.update(
                auto_insert_enabled=enabled
            )
        )
        self.beam_slider.valueChanged.connect(self._on_beam_change)

        # Overlay настройки
        self.overlay_position_box.currentIndexChanged.connect(self._on_overlay_position_change)
        self.overlay_margin_slider.valueChanged.connect(self._on_overlay_margin_change)
        self.overlay_gain_slider.valueChanged.connect(self._on_overlay_gain_change)
        self.overlay_opacity_slider.valueChanged.connect(self._on_overlay_opacity_change)
        self.overlay_preview_btn.clicked.connect(self._test_overlay)
        self.reduced_motion_toggle.toggled.connect(
            self._on_reduced_motion_change
        )

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

        # Предзаполнить выбранную STT-модель OpenRouter (до первого "Обновить")
        saved_transcribe_model = cfg.get("openrouter_transcribe_model", "")
        if saved_transcribe_model:
            self.transcribe_model_combo.clear()
            self.transcribe_model_combo.addItem(self._t("select_model"), "")
            self.transcribe_model_combo.addItem(saved_transcribe_model, saved_transcribe_model)
            self.transcribe_model_combo.setCurrentIndex(1)
        self._update_transcribe_ui_visibility()

        # Хоткей
        hotkey = cfg.get("hotkey", "ctrl+alt+v")
        self.hotkey_edit.setText(hotkey)

        # Дополнительные
        self.vad_toggle.setChecked(bool(cfg.get("vad_filter", True)))
        self.auto_insert_toggle.setChecked(
            bool(cfg.get("auto_insert_enabled", True))
        )
        beam = int(cfg.get("beam_size", 5))
        self.beam_slider.setValue(beam)
        self.beam_value_label.setText(str(beam))

        # Микрофоны
        self._load_mics()
        self._load_system_audio_devices()
        mic = cfg.get("microphone")
        if mic:
            idx = self.mic_box.findText(mic)
            if idx >= 0:
                self.mic_box.setCurrentIndex(idx)
        source = cfg.get("audio_source", AudioSourceKind.MICROPHONE.value)
        idx = self.audio_source_box.findData(source)
        self.audio_source_box.setCurrentIndex(idx if idx >= 0 else 0)
        system_device = cfg.get("system_audio_device")
        if system_device:
            idx = self.system_audio_box.findData(system_device)
            if idx >= 0:
                self.system_audio_box.setCurrentIndex(idx)
        self.system_audio_consent_toggle.setChecked(
            bool(cfg.get("system_audio_consent", False))
        )
        self._refresh_audio_source_controls()

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
        self.reduced_motion_toggle.setChecked(
            bool(cfg.get("reduced_motion", False))
        )

        self.config.update(models_dir=str(self.models_dir))

        # Model download sources override (empty = defaults).
        if hasattr(self, "model_sources_edit") and self.model_sources_edit:
            sources = cfg.get("model_download_sources", [])
            if isinstance(sources, str):
                # Support legacy/hand-edited config formats.
                sources = [s.strip() for s in sources.splitlines() if s.strip()]
            if not isinstance(sources, list):
                sources = []
            cleaned = [str(s).strip() for s in sources if str(s).strip()]
            self.model_sources_edit.setPlainText("\n".join(cleaned))

        # Загрузка настроек ассистента
        self._load_assistant_settings()

    def _load_mics(self) -> None:
        self.mic_box.blockSignals(True)
        self.mic_box.clear()
        for dev in self.audio.list_input_devices():
            self.mic_box.addItem(dev)
        self.mic_box.blockSignals(False)

    def _load_system_audio_devices(self) -> None:
        self.system_audio_box.blockSignals(True)
        self.system_audio_box.clear()
        try:
            for device in self.system_audio.list_devices():
                self.system_audio_box.addItem(device.name, device.device_id)
        except Exception:
            logger.exception("Could not enumerate Windows system-audio devices")
        self.system_audio_box.blockSignals(False)

    def _selected_audio_source(self) -> AudioSourceKind:
        value = self.audio_source_box.currentData()
        try:
            return AudioSourceKind(value)
        except (TypeError, ValueError):
            return AudioSourceKind.MICROPHONE

    def _on_audio_source_change(self, _index: int = -1) -> None:
        source = self._selected_audio_source()
        self.config.update(audio_source=source.value)
        self._refresh_audio_source_controls()

    def _on_system_audio_device_change(self, _index: int = -1) -> None:
        self.config.update(
            system_audio_device=self.system_audio_box.currentData()
        )

    def _refresh_audio_source_controls(self) -> None:
        source = self._selected_audio_source()
        uses_microphone = source in {
            AudioSourceKind.MICROPHONE,
            AudioSourceKind.MICROPHONE_SYSTEM,
        }
        uses_system = source in {
            AudioSourceKind.SYSTEM,
            AudioSourceKind.MICROPHONE_SYSTEM,
        }
        self._audio_input_row.setVisible(uses_microphone)
        self._system_audio_row.setVisible(uses_system)
        self._system_audio_consent_row.setVisible(uses_system)

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

    def _parse_model_download_sources(self, text: str) -> List[str]:
        raw = (text or "").strip()
        if not raw:
            return []

        parts: List[str]
        if "\n" not in raw and "," in raw:
            parts = raw.split(",")
        else:
            parts = raw.splitlines()

        out: List[str] = []
        for p in parts:
            s = str(p).strip()
            if not s:
                continue
            out.append(s)
        return out

    def _save_model_download_sources(self) -> None:
        """Save optional model download sources override and apply immediately."""
        if not hasattr(self, "model_sources_edit") or not self.model_sources_edit:
            return

        sources = self._parse_model_download_sources(self.model_sources_edit.toPlainText())
        self.config.update(model_download_sources=sources)
        try:
            self.transcriber.set_download_sources(sources)
        except Exception:
            pass

    def _reset_model_download_sources(self) -> None:
        """Reset model download sources override to built-in defaults."""
        if not hasattr(self, "model_sources_edit") or not self.model_sources_edit:
            return

        # Empty list means "use defaults" (see hint text in UI).
        self.model_sources_edit.setPlainText("")
        self._save_model_download_sources()

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

    def _on_reduced_motion_change(self, enabled: bool) -> None:
        self.config.update(reduced_motion=enabled)
        self.overlay.set_reduced_motion(enabled)

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
        self._audio_source_row.label.setText(self._t("audio_source"))
        self.audio_source_box.setItemText(0, self._t("microphone_only"))
        self.audio_source_box.setItemText(1, self._t("system_audio_only"))
        self.audio_source_box.setItemText(2, self._t("microphone_and_system"))
        self._system_audio_row.label.setText(
            self._t("system_audio_device")
        )
        self.system_audio_consent_toggle.setText(
            self._t("system_audio_consent")
        )
        self.hotkey_label.setText(self._t("hotkey"))
        self.hotkey_record_btn.setText(self._t("record_hotkey"))
        self.ui_lang_label.setText(self._t("ui_language"))
        self.trans_lang_label.setText(self._t("transcription_language"))
        if hasattr(self, "recognition_section_label"):
            self.recognition_section_label.setTitle(self._t("recognition_section"))
        if hasattr(self, "license_section_label"):
            self.license_section_label.setTitle(self._t("license_status"))

        # Дополнительная вкладка - модель и устройство
        self.model_label.setText(self._t("model"))
        self.distil_warning.setText(self._t("distil_en_only"))
        self.quant_label.setText(self._t("quantization"))
        self.accel_label.setText(self._t("device"))
        self.download_btn.setText(self._t("download_model"))
        if hasattr(self, "transcribe_model_label"):
            self.transcribe_model_label.setText(self._t("transcribe_model"))
        if hasattr(self, "transcribe_refresh_btn"):
            self.transcribe_refresh_btn.setToolTip(self._t("refresh_models"))
        if hasattr(self, "refresh_models_btn"):
            self.refresh_models_btn.setToolTip(self._t("refresh_models"))

        # Дополнительная вкладка
        self.perf_section_label.setTitle(self._t("performance_section"))
        self.vad_label.setText(self._t("vad_filter"))
        self.auto_insert_label.setText(self._t("auto_insert"))
        self.beam_label.setText(self._t("beam_size"))
        self.model_path_label.setText(self._t("model_path"))
        if hasattr(self, "model_sources_label"):
            self.model_sources_label.setText(self._t("model_download_sources"))
        if hasattr(self, "model_sources_hint"):
            self.model_sources_hint.setText(self._t("model_download_sources_hint"))
        if hasattr(self, "model_sources_save_btn"):
            self.model_sources_save_btn.setText(self._t("save"))
        if hasattr(self, "model_sources_reset_btn"):
            self.model_sources_reset_btn.setText(self._t("reset_to_default"))

        self.overlay_section_label.setTitle(self._t("overlay_section"))
        self.app_section_label.setTitle(self._t("app_section"))
        self.position_label.setText(self._t("position"))
        self.margin_label.setText(self._t("margin"))
        self.wave_gain_label.setText(self._t("wave_gain"))
        self.opacity_label.setText(self._t("opacity"))
        self.overlay_preview_btn.setText(self._t("preview"))
        self.reduced_motion_toggle.setText(self._t("reduced_motion"))

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
        if hasattr(self, "output_format_label"):
            self.output_format_label.setText(self._t("report_format"))
        current_format = self.output_format_combo.currentData()
        self.output_format_combo.blockSignals(True)
        self.output_format_combo.clear()
        self.output_format_combo.addItem(self._t("format_html"), "html")
        self.output_format_combo.addItem(self._t("format_pdf"), "pdf")
        self.output_format_combo.addItem(self._t("format_both"), "both")
        idx = self.output_format_combo.findData(current_format)
        if idx >= 0:
            self.output_format_combo.setCurrentIndex(idx)
        self.output_format_combo.blockSignals(False)

        # Способ диаризации
        if hasattr(self, "diarization_backend_label"):
            self.diarization_backend_label.setText(self._t("diarization_backend"))
            current_diar = self.diarization_backend_combo.currentData()
            self.diarization_backend_combo.blockSignals(True)
            self.diarization_backend_combo.clear()
            self.diarization_backend_combo.addItem(self._t("diarization_backend_auto"), "auto")
            self.diarization_backend_combo.addItem(self._t("diarization_backend_openrouter"), "openrouter")
            self.diarization_backend_combo.addItem(self._t("diarization_backend_local"), "local")
            diar_idx = self.diarization_backend_combo.findData(current_diar)
            if diar_idx >= 0:
                self.diarization_backend_combo.setCurrentIndex(diar_idx)
            self._configure_local_diarization_option()
            self.diarization_backend_combo.setToolTip(self._t("diarization_backend_tooltip"))
            self.diarization_backend_combo.blockSignals(False)

        # AI саммари
        self.enable_summary_checkbox.setText(self._t("enable_summary"))
        self.enable_summary_checkbox.setToolTip(self._t("enable_summary_tooltip"))
        self._update_data_route_disclosure()
        self.customize_prompts_btn.setText(self._t("customize_prompts"))
        if hasattr(self, "manage_presets_btn"):
            self.manage_presets_btn.setText(self._t("manage_presets"))
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
        self.clear_journal_btn.setText(self._t("clear_journal"))
        self.retry_dictation_btn.setText(
            self._t("retry_recovered_dictation")
        )
        self.journal.set_translate_func(self._t)
        if hasattr(self, "journal_btn"):
            self.journal_btn.setText(self._t("journal"))
        if hasattr(self, "_journal_window"):
            self._journal_window.setWindowTitle(self._t("journal"))

        # Системный трей
        self._update_tray_menu_texts()

        # Лицензия
        self.license_status_widget.set_translate_func(self._t)

        # Обновления
        self.update_label.setText(self._t("current_version"))
        self.check_update_btn.setText(self._t("check_updates"))

        # Поддержка
        self.support_label.setText(self._t("contact_support"))
        self._apply_overlay_accessible_texts()
        configure_accessibility(self)

    def _configure_local_diarization_option(self) -> None:
        index = self.diarization_backend_combo.findData("local")
        if index < 0:
            return
        if local_diarization_available():
            return
        self.diarization_backend_combo.setItemText(
            index,
            f"{self._t('diarization_backend_local')} "
            f"({self._t('optional_pack_required')})",
        )
        item = self.diarization_backend_combo.model().item(index)
        if item is not None:
            item.setEnabled(False)
        if self.diarization_backend_combo.currentData() == "local":
            self.diarization_backend_combo.setCurrentIndex(0)
            self.config.update(postprocessing_diarization_backend="auto")

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

        self.tray_repeat_insert_action = QAction(
            self._t("repeat_last_insert"),
            self,
        )
        self.tray_repeat_insert_action.setEnabled(bool(self.last_text))
        self.tray_repeat_insert_action.triggered.connect(
            self._repeat_last_insert
        )
        tray_menu.addAction(self.tray_repeat_insert_action)

        self.tray_retry_dictation_action = QAction(
            self._t("retry_recovered_dictation"),
            self,
        )
        self.tray_retry_dictation_action.setVisible(False)
        self.tray_retry_dictation_action.triggered.connect(
            self._retry_next_recovered_dictation
        )
        tray_menu.addAction(self.tray_retry_dictation_action)

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
        if not self.audio_session.recording:
            focus_manager.save_current_window()
            self._start_recording_with_overlay()

    def _tray_exit(self) -> None:
        """Полностью закрыть приложение."""
        self._really_quit = True
        self.close()

    def _repeat_last_insert(self) -> None:
        """Retry the last durable transcript against its captured target."""
        if not self.last_text:
            return
        result = insert_text_result(self.last_text)
        if result.success:
            self._add_journal_entry(
                "success",
                "auto_insert_done",
                is_translatable=True,
            )
            return
        failure = result.failure.value if result.failure else "unknown"
        self._add_journal_entry(
            "error",
            "insert_failed",
            text=failure,
            is_translatable=True,
        )

    def _update_tray_icon(self, recording: bool) -> None:
        """Обновить иконку в трее."""
        if self.tray_icon:
            self.tray_icon.setIcon(create_app_icon(64, recording=recording))

    def _update_tray_menu_texts(self) -> None:
        """Обновить тексты меню трея."""
        if self.tray_icon:
            self.tray_show_action.setText(self._t("show_window"))
            self.tray_record_action.setText(self._t("start_recording"))
            self.tray_repeat_insert_action.setText(
                self._t("repeat_last_insert")
            )
            self.tray_retry_dictation_action.setText(
                self._t("retry_recovered_dictation")
            )
            self.tray_exit_action.setText(self._t("exit"))

    def _apply_overlay_settings(self) -> None:
        """Применить настройки overlay из конфига."""
        cfg = self.config.config
        self.overlay.set_corner(cfg.get("overlay_position", "bottom-center"))
        self.overlay.set_margin(int(cfg.get("overlay_margin", 20)))
        self.overlay.set_wave_gain(float(cfg.get("overlay_wave_gain", 1.5)))
        self.overlay.set_bg_opacity(int(cfg.get("overlay_opacity", 230)))
        self.overlay.set_reduced_motion(bool(cfg.get("reduced_motion", False)))
        self._apply_overlay_accessible_texts()

    def _apply_overlay_accessible_texts(self) -> None:
        self.overlay.set_accessible_texts(
            recording=self._t("recording"),
            processing=self._t("transcribing"),
            success=self._t("success"),
            error=self._t("error"),
        )

    def _announce_status(self, message: str) -> None:
        if not message:
            return
        self._status_bar.setAccessibleDescription(message)
        self._status_bar.showMessage(message)

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

        # Один entitlement gate используется и для диктовки, и для файлов.
        has_access, info = self.license_manager.check_transcription_entitlement()
        if not has_access:
            self._show_trial_expired_dialog()
            return

        # Если идёт транскрипция - отменяем её
        if self._dictation.transcribing:
            self._cancel_transcription()
            return

        if not self.audio_session.recording:
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
        if self.audio_session.recording:
            self._stop_recording_with_auto_insert()

    def _start_recording_with_overlay(self) -> None:
        """Начать запись с показом overlay."""
        if self.audio_session.recording:
            return
        if self._operation_coordinator is None:
            self._add_journal_entry(
                "error",
                "error",
                text="Durable operation storage is unavailable.",
                is_translatable=False,
            )
            self.overlay.show_error(self._t("error"))
            return
        info = self.license_manager.get_license_info()
        quota_seconds = (
            max(0.0, info.trial_remaining_minutes * 60)
            if info.is_trial
            else None
        )
        started_at = time.monotonic()
        operation_token = self._dictation.begin_recording(
            started_at=started_at,
            max_duration_seconds=quota_seconds,
        )
        try:
            device_id = self._selected_device_id()

            def on_level(levels: List[float]) -> None:
                self.waveform_signal.emit(levels)

            source = self._selected_audio_source()
            if (
                source
                in {
                    AudioSourceKind.SYSTEM,
                    AudioSourceKind.MICROPHONE_SYSTEM,
                }
                and not self.system_audio_consent_toggle.isChecked()
            ):
                raise RuntimeError(
                    self._t("system_audio_consent_required")
                )
            self.audio_session.start(
                source,
                microphone_device=device_id,
                system_device=self.system_audio_box.currentData(),
                level_callback=on_level,
            )
            self.overlay.show_recording()
            self._announce_status(self._t("recording"))
            self._update_tray_icon(recording=True)
            if quota_seconds is not None:
                QTimer.singleShot(
                    max(1, int(quota_seconds * 1000)),
                    lambda token=operation_token: self._stop_at_trial_quota(token),
                )
        except Exception as exc:
            if self.audio_session.recording:
                MainWindow._schedule_failed_audio_start_cleanup(
                    self,
                    operation_token,
                )
            self._dictation.request_cancel(operation_token)
            self._dictation.mark_cancelled(operation_token)
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)
            self.overlay.show_error(self._t("error"))

    def _schedule_failed_audio_start_cleanup(
        self,
        operation_token: int,
    ) -> None:
        if getattr(self, "_audio_finalize_retry_token", None) == operation_token:
            return
        self._audio_finalize_retry_token = operation_token
        QTimer.singleShot(
            100,
            lambda token=operation_token: (
                MainWindow._retry_failed_audio_start_cleanup(self, token)
            ),
        )

    def _retry_failed_audio_start_cleanup(
        self,
        operation_token: int,
    ) -> None:
        if (
            getattr(self, "_audio_finalize_retry_token", None)
            != operation_token
        ):
            return
        self._audio_finalize_retry_token = None
        if (
            self._dictation.operation_token != operation_token
            or not self.audio_session.recording
        ):
            return
        try:
            capture = self.audio_session.stop()
            for track in capture.tracks:
                track.path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Could not finalize failed audio startup")
        if self.audio_session.recording:
            MainWindow._schedule_failed_audio_start_cleanup(
                self,
                operation_token,
            )

    def _stop_at_trial_quota(self, operation_token: int) -> None:
        """Остановить только ту запись, для которой истёк trial budget."""
        if self._dictation.recording_quota_reached(
            operation_token,
            now=time.monotonic(),
        ) and self.audio_session.recording:
            self._stop_recording_with_auto_insert()

    def _schedule_audio_finalization_retry(
        self,
        operation_token: int,
    ) -> None:
        if getattr(self, "_audio_finalize_retry_token", None) == operation_token:
            return
        self._audio_finalize_retry_token = operation_token
        QTimer.singleShot(
            100,
            lambda token=operation_token: MainWindow._retry_audio_finalization(
                self,
                token,
            ),
        )

    def _retry_audio_finalization(self, operation_token: int) -> None:
        if (
            getattr(self, "_audio_finalize_retry_token", None)
            != operation_token
        ):
            return
        self._audio_finalize_retry_token = None
        if (
            self._dictation.operation_token == operation_token
            and self.audio_session.recording
        ):
            MainWindow._stop_recording_with_auto_insert(self)

    def _stop_recording_with_auto_insert(self) -> None:
        """Остановить запись и включить автовставку."""
        if not self.audio_session.recording:
            return

        operation_token = self._dictation.operation_token
        auto_insert = bool(
            self.config.config.get("auto_insert_enabled", True)
        )

        try:
            capture = self.audio_session.stop()
        except Exception as exc:
            if (
                not self.audio_session.recording
                and self._dictation.begin_transcription(
                    operation_token,
                    auto_insert=auto_insert,
                )
            ):
                self._dictation.finish_transcription(
                    operation_token,
                    succeeded=False,
                )
            self._add_journal_entry("error", "error", text=str(exc), is_translatable=True)
            self.overlay.show_error(self._t("error"))
            return

        if not capture.tracks:
            if self.audio_session.recording:
                self.overlay.show_processing()
                MainWindow._schedule_audio_finalization_retry(
                    self,
                    operation_token,
                )
                return
            if self._dictation.begin_transcription(
                operation_token,
                auto_insert=auto_insert,
            ):
                self._dictation.finish_transcription(
                    operation_token,
                    succeeded=False,
                )
            self._add_journal_entry("error", "error", text="no_audio", is_translatable=True)
            self.overlay.show_error(self._t("error"))
            return

        if not self._dictation.begin_transcription(
            operation_token,
            auto_insert=auto_insert,
        ):
            return

        duration_seconds = 0.0
        # Учитываем время записи для trial
        if self._dictation.recording_started_at is not None:
            duration_seconds = (
                time.monotonic() - self._dictation.recording_started_at
            )
            self.license_manager.add_transcription_time(duration_seconds)
            self._dictation.recording_started_at = None

        self.overlay.show_processing()
        self._announce_status(self._t("transcribing"))

        if self._operation_coordinator is None:
            self._dictation.finish_transcription(
                operation_token,
                succeeded=False,
            )
            self._add_journal_entry(
                "error",
                "error",
                text="Durable operation storage is unavailable. Audio was preserved.",
                is_translatable=False,
            )
            self.overlay.show_error(self._t("error"))
            return

        cfg = self.config.config
        backend = cfg.get("transcriber_backend", "whisper_cpp")
        if cfg.get("use_mindtype_cloud", False):
            provider = "mindtype_cloud"
        elif backend == "openrouter":
            provider = "openrouter"
        else:
            provider = "local"
        model = (
            cfg.get("openrouter_transcribe_model") or "auto"
            if provider == "openrouter"
            else (
                "auto"
                if provider == "mindtype_cloud"
                else cfg.get("model_size", "large-v3")
            )
        )
        route = {
            "transcription": {
                "provider": provider,
                "model": str(model),
                **({"backend": backend} if provider == "local" else {}),
            }
        }
        try:
            operation = self._operation_coordinator.adopt_multitrack_dictation(
                capture,
                route=route,
            )
            if capture.interrupted:
                if (
                    operation.operation_id
                    not in self._retryable_dictation_ids
                ):
                    self._retryable_dictation_ids.append(
                        operation.operation_id
                    )
                self._update_recovered_dictation_actions()
                self._dictation.finish_transcription(
                    operation_token,
                    succeeded=False,
                )
                errors = "; ".join(
                    result.error
                    for result in capture.results
                    if result.error
                )
                self._add_journal_entry(
                    "error",
                    "error",
                    text=(
                        f"{errors or 'Audio capture interrupted'}. "
                        "Partial audio was preserved for recovery."
                    ),
                    is_translatable=False,
                )
                self.overlay.show_error(self._t("error"))
                return
            self._operation_coordinator.begin_attempt(
                operation.operation_id,
                stage=OperationStage.TRANSCRIBE,
            )
        except Exception as exc:
            logger.exception("Could not persist dictation before transcription")
            self._dictation.finish_transcription(
                operation_token,
                succeeded=False,
            )
            self._add_journal_entry(
                "error",
                "error",
                text=str(exc),
                is_translatable=False,
            )
            self.overlay.show_error(self._t("error"))
            return

        self._dictation_operation_ids[operation_token] = operation.operation_id
        self._dictation_durations_ms[operation_token] = max(
            0,
            int(duration_seconds * 1000),
        )
        self._run_transcription(operation.source_asset_path, operation_token)

    def _update_waveform(self, levels: List[float]) -> None:
        """Обновить waveform в overlay (Qt thread)."""
        self.overlay.update_waveform(levels)

    def _transcriber_for_operation(
        self,
        operation: Any,
    ) -> tuple["Transcriber", bool]:
        transcription_route = operation.route.get("transcription", {})
        provider = transcription_route.get("provider")
        if provider == "openrouter":
            backend = "openrouter"
        elif provider == "local":
            backend = str(
                transcription_route.get("backend") or "whisper_cpp"
            )
        else:
            raise RuntimeError(
                f"Unsupported durable transcription provider: {provider}"
            )
        if backend == self._transcriber_backend:
            return self.transcriber, False
        return self._build_transcriber(backend), True

    def _run_transcription(self, audio_path: Path, operation_token: int) -> None:
        cfg = self.config.config
        operation_id = self._dictation_operation_ids.get(operation_token)
        operation = (
            self._operation_coordinator.store.get(operation_id)
            if operation_id and self._operation_coordinator
            else None
        )
        cloud_route = bool(
            operation
            and operation.route.get("transcription", {}).get("provider")
            == "mindtype_cloud"
        )
        if cloud_route:
            self._init_mindtype_cloud()
            if self._cloud_executor is None or operation_id is None:
                self._on_transcribed(
                    operation_token,
                    "",
                    "",
                    0.0,
                    "MindType Cloud session could not be initialized.",
                )
                return
            worker = CloudDictationWorker(
                self._cloud_executor,
                operation_id,
                options={
                    "language": cfg.get("language", "ru"),
                    "word_timestamps": True,
                    "diarization": False,
                    "quality_profile": "fast",
                },
            )
        else:
            try:
                selected_transcriber, owns_transcriber = (
                    self._transcriber_for_operation(operation)
                    if operation is not None
                    else (self.transcriber, False)
                )
            except Exception as exc:
                self._on_transcribed(
                    operation_token,
                    "",
                    "",
                    0.0,
                    str(exc),
                )
                return
            transcription_route = (
                operation.route.get("transcription", {})
                if operation is not None
                else {}
            )
            worker = TranscribeWorker(
                selected_transcriber,
                audio_path,
                model_size=str(
                    transcription_route.get("model")
                    or cfg.get("model_size", "large-v3")
                ),
                compute_type=cfg.get("compute_type", "int8"),
                device=cfg.get("device", "auto"),
                cpu_threads=int(cfg.get("cpu_threads", 4)),
                num_workers=int(cfg.get("num_workers", 1)),
                language=cfg.get("language", "ru"),
                beam_size=int(cfg.get("beam_size", 5)),
                vad_filter=bool(cfg.get("vad_filter", True)),
                models_dir=self.models_dir,
            )
            if owns_transcriber:
                worker.finished.connect(
                    lambda *_: selected_transcriber.shutdown()
                )
                worker.cancelled.connect(selected_transcriber.shutdown)
        worker.progress.connect(
            lambda text, lang, prob: self._on_transcribe_progress(
                operation_token,
                text,
                lang,
                prob,
            )
        )
        worker.status_update.connect(
            lambda status: self._on_transcribe_status(operation_token, status)
        )
        worker.finished.connect(
            lambda text, lang, prob, err: self._on_transcribed(
                operation_token,
                text,
                lang,
                prob,
                err,
            )
        )
        worker.cancelled.connect(
            lambda: self._on_transcription_cancelled(operation_token)
        )
        if isinstance(worker, CloudDictationWorker):
            worker.cancellation_pending.connect(
                lambda error: self._on_transcription_cancellation_pending(
                    operation_token,
                    error,
                )
            )
        if operation_token not in self._dictation_operation_ids:
            worker.finished.connect(lambda *_: audio_path.unlink(missing_ok=True))
            worker.cancelled.connect(lambda: audio_path.unlink(missing_ok=True))
        self._transcribe_thread = worker
        worker.start()

    def _on_transcribe_status(self, operation_token: int, status: str) -> None:
        # status приходит как ключ перевода (loading_model, transcribing)
        if (
            operation_token != self._dictation.operation_token
            or not self._dictation.transcribing
        ):
            return
        self._add_journal_entry("pending", status, is_translatable=True)

    def _on_transcribe_progress(
        self,
        operation_token: int,
        text: str,
        lang: str,
        prob: float,
    ) -> None:
        if (
            operation_token != self._dictation.operation_token
            or not self._dictation.transcribing
        ):
            return
        pass  # Прогресс отображается в overlay

    def _on_transcribed(
        self,
        operation_token: int,
        text: str,
        lang: str,
        prob: float,
        err: str,
    ) -> None:
        from .crash_reporter import add_breadcrumb
        add_breadcrumb(f"Transcription completed: {'error' if err else 'success'}")

        if (
            operation_token != self._dictation.operation_token
            or not self._dictation.transcribing
        ):
            return

        operation_id = self._dictation_operation_ids.get(operation_token)
        if operation_id and self._operation_coordinator:
            try:
                if err:
                    self._operation_coordinator.mark_retryable(
                        operation_id,
                        error_code="TRANSCRIPTION_FAILED",
                    )
                else:
                    self._operation_coordinator.complete_dictation(
                        operation_id,
                        text=text,
                        language=lang,
                        confidence=max(0.0, min(1.0, float(prob))),
                        duration_ms=self._dictation_durations_ms.get(
                            operation_token,
                            0,
                        ),
                    )
            except Exception as exc:
                logger.exception("Could not persist canonical dictation result")
                try:
                    current = self._operation_coordinator.store.get(
                        operation_id
                    )
                    if current and current.status in {
                        OperationStatus.CREATED,
                        OperationStatus.RUNNING,
                        OperationStatus.RETRYABLE,
                    }:
                        self._operation_coordinator.mark_retryable(
                            operation_id,
                            error_code="CANONICAL_PERSIST_FAILED",
                        )
                except Exception:
                    logger.exception(
                        "Could not mark canonical persistence retryable"
                    )
                err = str(exc)

        if not self._dictation.finish_transcription(
            operation_token,
            succeeded=not err,
        ):
            return
        self._dictation_operation_ids.pop(operation_token, None)
        self._dictation_durations_ms.pop(operation_token, None)
        if operation_id and self._operation_coordinator:
            operation = self._operation_coordinator.store.get(operation_id)
            if operation and operation.status is OperationStatus.RETRYABLE:
                if operation_id not in self._retryable_dictation_ids:
                    self._retryable_dictation_ids.append(operation_id)
            else:
                self._retryable_dictation_ids = [
                    candidate
                    for candidate in self._retryable_dictation_ids
                    if candidate != operation_id
                ]
            self._update_recovered_dictation_actions()

        self._update_tray_icon(recording=False)

        if err:
            self._add_journal_entry("error", "error", text=err, is_translatable=True)
            self.overlay.show_error(self._t("error"))
            return

        self.last_text = text
        if self.tray_icon:
            self.tray_repeat_insert_action.setEnabled(bool(text))

        # Добавляем в историю транскрипций (если вкладка История включена)
        if text and hasattr(self, 'transcription_history'):
            self.transcription_history.add_transcription(text)

        # Обновляем последнюю запись в журнале
        self._add_journal_entry(
            "success" if text else "pending",
            "transcription" if text else "transcribing",
            is_translatable=True
        )

        if self._dictation.auto_insert_pending and text:
            QTimer.singleShot(
                150,
                lambda: self._do_auto_insert(
                    operation_token,
                    text,
                    operation_id,
                ),
            )
        else:
            self.overlay.show_success()
            if operation_id:
                try:
                    self._acknowledge_completed_operation(operation_id)
                except Exception:
                    logger.exception(
                        "Could not schedule delivered dictation acknowledgement"
                    )

    def _do_auto_insert(
        self,
        operation_token: int,
        text: str,
        operation_id: Optional[str] = None,
    ) -> None:
        """Автовставка после транскрипции с восстановлением фокуса."""
        if not text:
            self.overlay.show_success()
            return
        if not self._dictation.claim_auto_insert(operation_token):
            return

        result = insert_text_result(text)
        if result.success:
            self._add_journal_entry("success", "auto_insert_done", is_translatable=True)
            self.overlay.show_success()
        else:
            failure = result.failure.value if result.failure else "unknown"
            self._add_journal_entry(
                "error",
                "insert_failed",
                text=failure,
                is_translatable=True,
            )
            self.overlay.show_error(self._t("error"))
        if operation_id:
            try:
                self._acknowledge_completed_operation(operation_id)
            except Exception:
                logger.exception(
                    "Could not schedule delivered dictation acknowledgement"
                )

    def _cancel_transcription(self) -> None:
        """Отменить текущую транскрипцию."""
        if not self._dictation.transcribing:
            return

        operation_token = self._dictation.operation_token
        if not self._dictation.request_cancel(operation_token):
            return

        operation_id = self._dictation_operation_ids.get(operation_token)
        if operation_id and self._operation_coordinator:
            try:
                self._operation_coordinator.request_cancel(operation_id)
            except Exception:
                logger.exception("Could not persist dictation cancellation request")

        # Отменяем worker
        if self._transcribe_thread and self._transcribe_thread.isRunning():
            self._transcribe_thread.cancel()

        self._dictation.mark_cancelled(operation_token)
        self._update_tray_icon(recording=False)

        # Показываем сообщение об отмене
        self._add_journal_entry("pending", "cancelled", is_translatable=True)
        self.overlay.hide_overlay()

    def _on_transcription_cancelled(self, operation_token: int) -> None:
        """Finalize cancellation only for the operation that emitted it."""
        if operation_token == self._dictation.operation_token:
            self._dictation.request_cancel(operation_token)
            self._dictation.mark_cancelled(operation_token)
        operation_id = self._dictation_operation_ids.pop(operation_token, None)
        self._dictation_durations_ms.pop(operation_token, None)
        if operation_id and self._operation_coordinator:
            try:
                operation = self._operation_coordinator.store.get(operation_id)
                if operation and operation.status is OperationStatus.RUNNING:
                    self._operation_coordinator.request_cancel(operation_id)
                    operation = self._operation_coordinator.store.get(operation_id)
                if (
                    operation
                    and operation.status is OperationStatus.CANCEL_REQUESTED
                ):
                    self._operation_coordinator.finish_cancel(operation_id)
            except Exception:
                logger.exception("Could not persist worker cancellation")
            self._retryable_dictation_ids = [
                candidate
                for candidate in self._retryable_dictation_ids
                if candidate != operation_id
            ]
            self._update_recovered_dictation_actions()

    def _on_transcription_cancellation_pending(
        self,
        operation_token: int,
        error: str,
    ) -> None:
        """Keep remote cancellation durable when the server did not confirm it."""
        operation_id = self._dictation_operation_ids.pop(
            operation_token,
            None,
        )
        self._dictation_durations_ms.pop(operation_token, None)
        self._add_journal_entry(
            "error",
            "Cloud cancellation is pending",
            text=error,
            is_translatable=False,
        )
        if operation_id:
            self._retryable_dictation_ids = [
                candidate
                for candidate in self._retryable_dictation_ids
                if candidate != operation_id
            ]
            self._update_recovered_dictation_actions()
            QTimer.singleShot(
                60_000,
                lambda identifier=operation_id: (
                    self._retry_pending_cancellation(identifier)
                ),
            )

    def _add_journal_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True) -> None:
        """Добавить запись в журнал."""
        self.journal.add_entry(status, title_key, text, extra_key, is_translatable)
        title = self._t(title_key) if is_translatable else title_key
        detail = self._t(text) if is_translatable and text else text
        self._announce_status(
            f"{title}: {detail}" if detail and detail != text else (
                f"{title}: {text}" if text else title
            )
        )

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

            self._add_journal_entry("success", "update_available",
                                   extra_key=f"v{info.version}", is_translatable=True)

            details = self._t("update_version").replace("{version}", info.version)
            if info.release_notes:
                details += f"\n\n{info.release_notes}"
            reply = QMessageBox.question(
                self,
                self._t("update_available"),
                details,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_update()
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
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(
                self._prompt_install_downloaded_update
            )
            self._prompt_install_downloaded_update()
        else:
            self.update_status_label.setText(f"{self._t('update_error')}: {error}")
            self.update_status_label.setObjectName("updateStatusError")
            self.update_status_label.style().unpolish(self.update_status_label)
            self.update_status_label.style().polish(self.update_status_label)
            self.check_update_btn.setText(self._t("check_updates"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._check_for_updates)
            self._add_journal_entry("error", "update_error", text=error, is_translatable=True)

    def _prompt_install_downloaded_update(self) -> None:
        """Keep a verified deferred installer actionable without re-downloading."""
        from .updater import UpdateLaunchAfterCleanupError

        reply = QMessageBox.question(
            self,
            self._t("update_ready"),
            self._t("update_ready") + "\n\n"
            "Приложение будет закрыто для установки обновления.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._add_journal_entry(
            "success",
            "update_ready",
            is_translatable=True,
        )
        try:
            installed = self.updater.install_update(
                before_launch=self._prepare_for_update_install,
            )
        except UpdateLaunchAfterCleanupError:
            logger.critical(
                "Installer launch failed after application cleanup",
                exc_info=True,
            )
            return
        if installed:
            QApplication.quit()
            return
        QMessageBox.critical(
            self,
            self._t("update_error"),
            self._t("automatic_update_disabled"),
        )

    # === Обработчики вкладки "Файлы" ===

    def _task_key(self, path: Path) -> Path:
        """Нормализованный ключ для задач/виджетов (абсолютный путь)."""
        try:
            return path.resolve()
        except Exception:
            return path.absolute()

    def _select_file_processing_batch(
        self,
        pending_tasks: list[FileTask],
        requested_route: dict,
    ) -> tuple[list[FileTask], dict]:
        """Run durable cloud retries without mixing in a new route."""
        if self._operation_coordinator is None:
            return pending_tasks, requested_route
        durable_routes: list[dict] = []
        operations: dict[str, object] = {}
        for task in pending_tasks:
            operation = self._operation_coordinator.store.get(
                task.operation_id
            )
            if operation is None:
                continue
            operations[task.operation_id] = operation
            if operation.server_job_ids:
                durable_routes.append(operation.route)
        if not durable_routes:
            return pending_tasks, requested_route
        preserved_route = durable_routes[0]
        selected = [
            task
            for task in pending_tasks
            if (
                task.operation_id in operations
                and operations[task.operation_id].server_job_ids
                and operations[task.operation_id].route == preserved_route
            )
        ]
        return selected, preserved_route

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
        self._update_data_route_disclosure()

    def _update_provider_fields(self) -> None:
        """Обновить видимость полей в зависимости от провайдера (источник правды — реестр)."""
        from .llm import get_provider_descriptor
        provider = self.provider_combo.currentData()
        desc = get_provider_descriptor(provider)

        is_mindtype_cloud = provider == "mindtype_cloud"
        needs_key = desc.needs_api_key if desc else True
        needs_base_url = desc.needs_base_url if desc else False

        # API key / base URL — по реестру
        self.api_key_label.setVisible(needs_key)
        self.api_key_edit.setVisible(needs_key)
        self.base_url_label.setVisible(needs_base_url)
        self.base_url_edit.setVisible(needs_base_url)

        # MindType Cloud: авто-выбор модели, без reasoning, виджет кредитов
        self.model_select_label.setVisible(not is_mindtype_cloud)
        self.model_combo.setVisible(not is_mindtype_cloud)
        self.refresh_models_btn.setVisible(not is_mindtype_cloud)
        self.reasoning_checkbox.setVisible(not is_mindtype_cloud)
        self.effort_combo.setVisible(not is_mindtype_cloud)

        if hasattr(self, '_credits_widget'):
            self._credits_widget.setVisible(is_mindtype_cloud)
        if is_mindtype_cloud:
            self._init_mindtype_cloud()
            self._refresh_credits_balance()

        # Placeholder API-ключа — из реестра
        self.api_key_edit.setPlaceholderText(desc.key_placeholder if desc else "")

    def _load_provider_settings(self, provider: str) -> None:
        """Загрузить настройки для провайдера."""
        from .llm import get_provider_descriptor
        cfg = self.config.config
        desc = get_provider_descriptor(provider)

        # MindType Cloud использует лицензионный ключ, не API ключ
        if provider == "mindtype_cloud":
            self.api_key_edit.setText("")
            return

        # API ключ
        key_field = desc.api_key_field if desc else f"{provider}_api_key"
        self.api_key_edit.setText(cfg.get(key_field, ""))

        # Base URL (для провайдеров с base_url, напр. Ollama)
        if desc and desc.needs_base_url:
            self.base_url_edit.setText(cfg.get("ollama_base_url", "http://localhost:11434"))

        # Модель
        model_field = desc.model_field if desc else f"{provider}_model"
        saved_model = cfg.get(model_field, "")
        if saved_model:
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")
            self.model_combo.addItem(saved_model, saved_model)
            self.model_combo.setCurrentIndex(1)

    def _on_api_key_changed(self, value: str) -> None:
        """Сохранить API ключ для текущего провайдера."""
        from .llm import get_provider_descriptor
        desc = get_provider_descriptor(self.provider_combo.currentData())
        if desc and desc.needs_api_key:
            self.config.update(**{desc.api_key_field: value})

    def _on_base_url_changed(self, value: str) -> None:
        """Сохранить base URL для Ollama."""
        self.config.update(ollama_base_url=value)

    def _on_model_changed(self, value: str) -> None:
        """Сохранить выбранную модель."""
        from .llm import get_provider_descriptor
        desc = get_provider_descriptor(self.provider_combo.currentData())
        if not desc:
            return
        model_id = self.model_combo.currentData()  # ID модели из data, не текст
        if model_id:
            self.config.update(**{desc.model_field: model_id})

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
        self.refresh_models_btn.setText("…")
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

            # Очищаем и заполняем комбобокс (по алфавиту)
            self.model_combo.clear()
            self.model_combo.addItem(self._t("select_model"), "")

            model_names = []
            for model in sorted(models, key=lambda m: (m.display_name or m.id or "").lower()):
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
            self.refresh_models_btn.setText("↻")

    def _on_model_selected(self, index: int) -> None:
        """Сохранить выбранную модель."""
        model_id = self.model_combo.currentData()
        if model_id:
            self.config.update(openrouter_model=model_id)

    def _build_transcriber(self, backend: str) -> "Transcriber":
        """Создать транскрайбер и применить источники загрузки моделей (CDN/зеркала)."""
        transcriber = Transcriber(backend=backend)
        try:
            sources = self.config.config.get("model_download_sources", [])
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]
            if isinstance(sources, list):
                transcriber.set_download_sources(sources)
        except Exception:
            pass
        return transcriber

    def _on_backend_change(self, index: int) -> None:
        """Смена бэкенда транскрипции: пересоздать транскрайбер и переподключить зависимых."""
        backend = self.backend_box.itemData(index)
        if not backend:
            return
        # Уже активен (в т.ч. начальная установка из _load_initial_state) — не пересоздаём,
        # иначе на старте создался бы второй инстанс уже после захвата ассистентом (двойная
        # загрузка модели). Только синхронизируем конфиг и видимость UI.
        if backend == self._transcriber_backend:
            self.config.update(transcriber_backend=backend)
            self._update_transcribe_ui_visibility()
            self._update_data_route_disclosure()
            return
        # Строим новый ДО коммита конфига — при сбое конструкции состояние не разъезжается.
        try:
            new_transcriber = self._build_transcriber(backend)
        except Exception as e:
            QMessageBox.critical(self, self._t("error"), str(e))
            self.backend_box.blockSignals(True)
            i = self.backend_box.findData(self._transcriber_backend)
            if i >= 0:
                self.backend_box.setCurrentIndex(i)
            self.backend_box.blockSignals(False)
            self._update_transcribe_ui_visibility()
            return
        previous_transcriber = self.transcriber
        self.transcriber = new_transcriber
        self._transcriber_backend = backend
        try:
            previous_transcriber.shutdown()
        except Exception:
            logger.exception("Не удалось остановить предыдущий transcriber backend")
        self.config.update(transcriber_backend=backend)
        # Голосовой ассистент держит свою ссылку на транскрайбер — переподключаем,
        # иначе он продолжит работать на старом бэкенде до перезапуска.
        if self.voice_assistant is not None:
            try:
                self.voice_assistant.set_transcriber(self.transcriber)
            except Exception:
                pass
        self._update_transcribe_ui_visibility()
        self._update_data_route_disclosure()

    def _update_data_route_disclosure(self, *_args) -> None:
        """Показать эффективный маршрут данных до запуска обработки."""
        route = resolve_processing_route(
            self.config.config,
            summary_enabled=(
                self.enable_summary_checkbox.isChecked()
                if hasattr(self, "enable_summary_checkbox")
                else False
            ),
            diarization_backend=(
                self.diarization_backend_combo.currentData()
                if hasattr(self, "diarization_backend_combo")
                else "auto"
            ),
        )
        def display(value: str) -> str:
            return {
                "Local": self._t("route_local"),
                "Off": self._t("route_off"),
            }.get(value, value)
        if hasattr(self, "dictation_route_label"):
            self.dictation_route_label.setText(
                self._t("dictation_data_route").format(
                    audio=display(route.audio),
                )
            )
        if not hasattr(self, "data_route_label"):
            return
        self.data_route_label.setText(
            self._t("data_route_disclosure").format(
                audio=display(route.audio),
                diarization=display(route.diarization),
                summary=display(route.summary),
            )
        )

    def _update_transcribe_ui_visibility(self) -> None:
        """Показать STT-пикер для OpenRouter и спрятать whisper-специфичные элементы."""
        is_or = self.backend_box.currentData() == "openrouter"
        self._transcribe_model_row.setVisible(is_or)
        self._model_row.setVisible(not is_or)
        self.distil_warning.setVisible(not is_or)
        self.download_btn.setVisible(not is_or)
        self.download_progress.setVisible(not is_or)
        self.download_status_label.setVisible(not is_or)
        self._model_path_row.setVisible(not is_or)
        self._model_sources_row.setVisible(not is_or)

    def _on_transcribe_model_changed(self, index: int) -> None:
        """Сохранить выбранную STT-модель OpenRouter."""
        model_id = self.transcribe_model_combo.currentData()
        if model_id:
            self.config.update(openrouter_transcribe_model=model_id)

    def _on_refresh_transcribe_models(self) -> None:
        """Загрузить список STT-моделей OpenRouter (output_modalities=transcription)."""
        api_key = (self.config.config.get("openrouter_api_key") or "").strip()
        if not api_key:
            QMessageBox.warning(self, self._t("error"), self._t("api_key_required"))
            return

        self.transcribe_refresh_btn.setEnabled(False)
        self.transcribe_refresh_btn.setText("…")
        QApplication.processEvents()
        try:
            from .llm.openrouter import OpenRouterProvider
            from .llm import LLMAuthError, LLMError, LLMConnectionError
            from PyQt6.QtWidgets import QCompleter

            provider = OpenRouterProvider(api_key=api_key)
            models = provider.fetch_transcription_models()

            self.transcribe_model_combo.clear()
            self.transcribe_model_combo.addItem(self._t("select_model"), "")
            model_names = []
            for model in sorted(models, key=lambda m: (m.name or m.id or "").lower()):
                self.transcribe_model_combo.addItem(model.name, model.id)
                model_names.append(model.name)

            completer = QCompleter(model_names, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self.transcribe_model_combo.setCompleter(completer)

            saved = self.config.config.get("openrouter_transcribe_model", "")
            if saved:
                idx = self.transcribe_model_combo.findData(saved)
                if idx >= 0:
                    self.transcribe_model_combo.setCurrentIndex(idx)
        except LLMAuthError:
            QMessageBox.critical(self, self._t("error"), self._t("invalid_api_key"))
        except LLMConnectionError as e:
            QMessageBox.critical(self, self._t("error"), f"{self._t('connection_error')}: {e}")
        except LLMError as e:
            QMessageBox.critical(self, self._t("error"), f"{self._t('api_error')}: {e}")
        except Exception as e:
            QMessageBox.critical(self, self._t("error"), str(e))
        finally:
            self.transcribe_refresh_btn.setEnabled(True)
            self.transcribe_refresh_btn.setText("↻")

    def _on_customize_prompts(self) -> None:
        """Открыть диалог настройки промптов."""
        dialog = PromptCustomizationDialog(self.config, translate_func=self._t, parent=self)
        dialog.show()

    def _on_clear_queue(self) -> None:
        """Очистить очередь файлов."""
        # Оставляем только файлы в процессе обработки
        retained_statuses = (
            FileStatus.EXTRACTING,
            FileStatus.TRANSCRIBING,
            FileStatus.PROCESSING,
            FileStatus.SUMMARIZING,
            FileStatus.GENERATING,
        )
        retained_tasks = []
        for task in self._file_tasks:
            if task.status in retained_statuses:
                retained_tasks.append(task)
            elif not self._discard_cloud_task(task):
                retained_tasks.append(task)
        self._file_tasks = retained_tasks
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
        if self._operation_coordinator is None:
            QMessageBox.critical(
                self,
                self._t("error"),
                "Durable operation storage is unavailable. Files were not started.",
            )
            return

        cfg = self.config.config
        requested_summary = self.enable_summary_checkbox.isChecked()
        requested_processing_route = resolve_processing_route(
            cfg,
            summary_enabled=requested_summary,
            diarization_backend=cfg.get(
                "postprocessing_diarization_backend",
                "auto",
            ),
        )
        requested_route = canonical_processing_route(
            requested_processing_route,
            cfg,
        )
        pending_tasks, canonical_route = (
            self._select_file_processing_batch(
                pending_tasks,
                requested_route,
            )
        )
        if not pending_tasks:
            return
        transcription_provider = str(
            canonical_route.get("transcription", {}).get("provider")
            or "local"
        )
        summary_provider_id = str(
            canonical_route.get("summary", {}).get("provider") or ""
        )
        diarization_provider = str(
            canonical_route.get("diarization", {}).get("provider") or ""
        )
        enable_summary = bool(summary_provider_id)
        cloud_transcription = transcription_provider == "mindtype_cloud"

        estimated_seconds = 0.0
        for task in pending_tasks:
            try:
                duration_seconds = max(
                    0.0,
                    get_file_duration(task.file_path),
                )
                enforce_media_duration_limit(duration_seconds)
                estimated_seconds += duration_seconds
            except MediaDurationTooLong as exc:
                QMessageBox.warning(
                    self,
                    self._t("error"),
                    f"{task.file_name}: {exc}",
                )
                return
            except Exception as exc:
                logger.warning(
                    "Could not estimate duration for %s: %s",
                    task.file_path,
                    exc,
                )
        has_access, _ = self.license_manager.check_transcription_entitlement(
            required_seconds=estimated_seconds,
        )
        if not has_access:
            self._show_trial_expired_dialog()
            return

        add_breadcrumb(f"Starting file processing: {len(pending_tasks)} files")

        # Создаём директорию вывода
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Запоминаем параметры запуска, чтобы понимать, что авто-открывать
        self._file_processing_batch_size = len(pending_tasks)
        self._file_output_format = self.output_format_combo.currentData()
        self._last_completed_task: Optional[FileTask] = None

        # Загружаем промпты из пресета (встроенного или пользовательского) и объединяем с кастомными
        from .summary_presets import get_preset_prompts
        preset_id = cfg.get("summary_preset", "pm")
        user_presets = cfg.get("user_presets", {})
        preset_prompts = get_preset_prompts(preset_id, user_presets)
        custom_prompts_saved = cfg.get("custom_prompts", {})
        # Кастомные промпты перезаписывают промпты из пресета
        custom_prompts = {**preset_prompts, **custom_prompts_saved} if custom_prompts_saved else preset_prompts

        # Отображаемое имя пресета — попадает в отчёт рядом с саммари
        from .summary_presets import PRESETS as BUILTIN_PRESETS
        if preset_id in user_presets and isinstance(user_presets.get(preset_id), dict):
            preset_display_name = user_presets[preset_id].get("name", preset_id)
        else:
            preset_display_name = self._t(
                BUILTIN_PRESETS.get(preset_id, {}).get("name_key", preset_id)
            )

        # Определяем провайдер суммаризации из настроек
        llm_provider = (
            "ollama"
            if summary_provider_id == "local"
            else summary_provider_id
            or cfg.get("llm_provider", "openrouter")
        )
        summary_api_key = ""
        summary_model = ""
        summary_base_url = ""
        summary_reasoning = True
        summary_reasoning_effort = cfg.get("llm_reasoning_effort", "medium")

        if llm_provider == "mindtype_cloud":
            # MindType Cloud uses the configured in-memory cloud session.
            self._init_mindtype_cloud()
            summary_api_key = ""
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

        # Credit checks belong only to routes the current client can execute.
        if enable_summary and llm_provider == "mindtype_cloud":
            if not self._check_cloud_credits_before_processing():
                return

        if cloud_transcription:
            self._init_mindtype_cloud()
            if self._cloud_executor is None:
                QMessageBox.critical(
                    self,
                    self._t("error"),
                    "MindType Cloud session could not be initialized.",
                )
                return
            if (
                enable_summary
                and summary_provider_id != "mindtype_cloud"
            ):
                QMessageBox.warning(
                    self,
                    self._t("error"),
                    "Cloud transcription currently requires MindType Cloud "
                    "summary or summary disabled.",
                )
                return
        try:
            for task in pending_tasks:
                self._operation_coordinator.prepare_file_task(
                    task,
                    route=canonical_route,
                )
        except Exception as exc:
            logger.exception("Could not persist files before processing")
            QMessageBox.critical(self, self._t("error"), str(exc))
            return

        self._file_queue = FileTranscriptionQueue(
            transcriber=self.transcriber,
            transcribe=TranscribeOptions(
                model_size=cfg.get("model_size", "large-v3"),
                compute_type=cfg.get("compute_type", "int8"),
                device=cfg.get("device", "auto"),
                language=cfg.get("language", "ru"),
                beam_size=int(cfg.get("beam_size", 5)),
                vad_filter=bool(cfg.get("vad_filter", True)),
                models_dir=self.models_dir,
            ),
            summary=SummaryOptions(
                enable=enable_summary,
                enable_thinking=True,  # Всегда включен
                custom_prompts=custom_prompts,
                preset_name=preset_display_name,
                provider=llm_provider,
                api_key=summary_api_key,
                model=summary_model,
                base_url=summary_base_url,
                reasoning=summary_reasoning,
                reasoning_effort=summary_reasoning_effort,
                # Legacy OpenRouter (обратная совместимость)
                openrouter_api_key=cfg.get("openrouter_api_key", ""),
                openrouter_model=cfg.get("openrouter_model", ""),
                openrouter_reasoning=bool(cfg.get("openrouter_reasoning", cfg.get("llm_reasoning_enabled", True))),
                openrouter_reasoning_effort=cfg.get("openrouter_reasoning_effort", "medium"),
            ),
            postprocess=PostProcessOptions(
                enable=cfg.get("enable_postprocessing", True),
                diarization=cfg.get("postprocessing_diarization", True),
                punctuation=cfg.get("postprocessing_punctuation", True),
                fillers=cfg.get("postprocessing_fillers", True),
                normalize=cfg.get("postprocessing_normalize", True),
                correct=cfg.get("postprocessing_correct", True),
                diarization_backend=cfg.get("postprocessing_diarization_backend", "auto"),
                diarization_api_key=cfg.get("openrouter_api_key", ""),
                # Модель LLM-диаризации: своя, иначе модель саммари, иначе дешёвый дефолт
                diarization_model=(
                    cfg.get("openrouter_diarization_model", "")
                    or cfg.get("openrouter_model", "")
                    or "openai/gpt-4o-mini"
                ),
            ),
            on_thinking=lambda text: self.thinking_signal.emit(text),
            on_completed=self._on_file_task_completed,
            cloud_executor=(
                self._cloud_executor if cloud_transcription else None
            ),
            cloud_summary_executor=(
                self._cloud_executor
                if (
                    not cloud_transcription
                    and enable_summary
                    and summary_provider_id == "mindtype_cloud"
                )
                else None
            ),
            cloud_transcribe_options=(
                {
                    "language": cfg.get("language", "ru"),
                    "word_timestamps": True,
                    "diarization": diarization_provider
                    == "mindtype_cloud",
                    "quality_profile": "balanced",
                }
                if cloud_transcription
                else None
            ),
            cloud_summary_options=(
                {
                    "preset": preset_id,
                    "input_token_estimate": 0,
                    "max_output_tokens": 2_000,
                }
                if (
                    enable_summary
                    and summary_provider_id == "mindtype_cloud"
                )
                else None
            ),
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
            generate_reports=False,
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
        if self._operation_coordinator:
            try:
                self._operation_coordinator.sync_file_task(task)
            except Exception:
                logger.exception("Could not persist durable file progress")
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

    def _on_file_task_completed(self, task: FileTask) -> None:
        """Задача завершена."""
        if self._operation_coordinator:
            try:
                operation = self._operation_coordinator.sync_file_task(
                    task,
                    preserve_inflight=(
                        self._preserve_cloud_jobs_on_shutdown
                        and task.status is FileStatus.CANCELLED
                    ),
                )
                if task.status is FileStatus.COMPLETED:
                    if operation.canonical_result_path is None:
                        raise RuntimeError("Canonical file result was not saved")
                    MainWindow._record_file_trial_usage(
                        self,
                        task,
                        operation.operation_id,
                    )
                    task.output_files["json"] = operation.canonical_result_path
                    try:
                        canonical_payload = json.loads(
                            operation.canonical_result_path.read_text(
                                encoding="utf-8"
                            )
                        )
                        exported = CanonicalExporter().export_bundle(
                            canonical_payload,
                            self._output_dir,
                            idempotency_key=operation.operation_id,
                        )
                        task.output_files.update(
                            {
                                format_.value: path
                                for format_, path in exported.items()
                            }
                        )
                    except Exception as export_exc:
                        logger.exception(
                            "Canonical result was saved, but projections failed"
                        )
                        task.warning = (
                            f"{task.warning}\n" if task.warning else ""
                        ) + f"Export failed: {export_exc}"
                    else:
                        try:
                            self._acknowledge_completed_operation(
                                operation.operation_id
                            )
                        except Exception as acknowledgement_exc:
                            logger.exception(
                                "Canonical result was saved, but source cleanup failed"
                            )
                            task.warning = (
                                f"{task.warning}\n" if task.warning else ""
                            ) + f"Local cleanup failed: {acknowledgement_exc}"
            except Exception as exc:
                logger.exception("Could not persist durable file completion")
                task.status = FileStatus.ERROR
                task.error_message = str(exc)
                try:
                    operation = self._operation_coordinator.store.get(
                        task.operation_id
                    )
                    if (
                        operation is not None
                        and operation.status is OperationStatus.RUNNING
                    ):
                        self._operation_coordinator.mark_retryable(
                            task.operation_id,
                            error_code="CANONICAL_SAVE_FAILED",
                        )
                except Exception:
                    logger.exception("Could not mark failed canonical save retryable")
        key = self._task_key(task.file_path)
        widget = self._file_widgets.get(key)
        if widget:
            widget.update_status()

        if task.status == FileStatus.COMPLETED:
            self._last_completed_task = task
            # Если обрабатываем один файл — открываем отчёт автоматически
            if getattr(self, "_file_processing_batch_size", 0) == 1:
                self._auto_open_transcription(task)

    def _record_file_trial_usage(
        self,
        task: FileTask,
        operation_id: str,
        *,
        recovered_duration_seconds: Optional[float] = None,
    ) -> None:
        duration = recovered_duration_seconds
        if duration is None:
            if task.result is None:
                return
            duration = task.result.duration
        if not task.claim_trial_time_charge():
            return
        try:
            self.license_manager.add_transcription_time(
                duration,
                operation_id=operation_id,
            )
        except Exception:
            task.trial_time_charged = False
            raise

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
            html_path = task.output_files.get("html")
            pdf_path = task.output_files.get("pdf")

            fmt = getattr(self, "_file_output_format", "html")

            # При "both" открываем HTML (быстрее предпросмотр); при "pdf" — PDF если есть, иначе HTML.
            if fmt == "pdf":
                target = pdf_path if pdf_path and pdf_path.exists() else html_path
            elif fmt == "both":
                target = html_path if html_path and html_path.exists() else pdf_path
            else:
                target = html_path if html_path and html_path.exists() else pdf_path

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
        if not self._discard_cloud_task(task):
            return
        self._remove_file_task_from_queue(task)

    def _remove_file_task_from_queue(self, task: FileTask) -> None:
        """Удалить локальное представление завершённой отмены."""
        key = self._task_key(task.file_path)
        widget = self._file_widgets.pop(key, None)
        if widget:
            widget.deleteLater()

        if task in self._file_tasks:
            self._file_tasks.remove(task)

        self._update_file_queue_ui()

    def _discard_cloud_task(self, task: FileTask) -> bool:
        """Отменить durable-задачу; вернуть True, когда UI можно удалить."""
        operation = None
        if self._operation_coordinator:
            operation = self._operation_coordinator.store.get(
                task.operation_id
            )
        if (
            operation is not None
            and operation.server_job_ids
            and operation.status
            not in {
                OperationStatus.CANCELLED,
                OperationStatus.COMPLETED,
                OperationStatus.FAILED,
            }
        ):
            if operation.status is not OperationStatus.CANCEL_REQUESTED:
                self._operation_coordinator.request_cancel(
                    task.operation_id
                )
            task.cancellation_pending = True
            widget = self._file_widgets.get(
                self._task_key(task.file_path)
            )
            if widget:
                widget.update_status()
            self._retry_file_task_cancellation(task)
            return False

        task.status = FileStatus.CANCELLED
        if self._operation_coordinator:
            try:
                self._operation_coordinator.sync_file_task(task)
            except Exception:
                logger.exception("Could not cancel durable file operation")
        return True

    def _retry_file_task_cancellation(self, task: FileTask) -> None:
        """Отменить recovered cloud job до удаления его UI-записи."""
        if not task.cancellation_pending:
            return
        self._init_mindtype_cloud()
        if self._cloud_executor is None:
            self._on_file_task_cancellation_failed(
                task,
                task.operation_id,
                "MindType Cloud is unavailable",
            )
            return
        worker = CloudCancellationWorker(
            self._cloud_executor,
            task.operation_id,
        )
        self._cancellation_workers.add(worker)
        worker.resolved.connect(
            lambda _identifier, current=task: (
                self._on_file_task_cancellation_resolved(current)
            )
        )
        worker.failed.connect(
            lambda identifier, error, current=task: (
                self._on_file_task_cancellation_failed(
                    current,
                    identifier,
                    error,
                )
            )
        )
        worker.finished.connect(
            lambda current=worker: self._cancellation_workers.discard(
                current
            )
        )
        worker.start()

    def _on_file_task_cancellation_resolved(
        self,
        task: FileTask,
    ) -> None:
        task.cancellation_pending = False
        task.status = FileStatus.CANCELLED
        self._add_journal_entry(
            "success",
            "Cloud cancellation confirmed",
            text=task.operation_id,
            is_translatable=False,
        )
        self._remove_file_task_from_queue(task)

    def _on_file_task_cancellation_failed(
        self,
        task: FileTask,
        operation_id: str,
        error: str,
    ) -> None:
        self._add_journal_entry(
            "error",
            "Cloud cancellation is pending",
            text=f"{operation_id}: {error}",
            is_translatable=False,
        )
        if task in self._file_tasks and task.cancellation_pending:
            QTimer.singleShot(
                60_000,
                lambda current=task: (
                    self._retry_file_task_cancellation(current)
                ),
            )

    def _restore_durable_operations(self) -> None:
        """Restore pending file work without starting it or spending BYOK."""
        from .recovery import project_completed_operation

        durable_tasks: list[FileTask] = []
        durable_recovery = None
        if self._operation_coordinator is not None:
            try:
                durable_recovery = (
                    self._operation_coordinator.restore_startup()
                )
                durable_tasks = list(durable_recovery.retryable_files)
            except Exception:
                logger.exception("Could not recover durable file operations")

        existing_operation_ids = {
            task.operation_id
            for task in self._file_tasks
        }
        for task in durable_tasks:
            if task.operation_id in existing_operation_ids:
                continue
            self._file_tasks.append(task)
            self._add_file_widget(task)
            existing_operation_ids.add(task.operation_id)

        if durable_recovery is not None and self._operation_coordinator is not None:
            for operation in durable_recovery.completed_pending_ack:
                try:
                    projection = project_completed_operation(
                        operation,
                        output_dir=self._output_dir,
                    )
                    if projection.file_task is not None:
                        recovered_task = projection.file_task
                        MainWindow._record_file_trial_usage(
                            self,
                            recovered_task,
                            operation.operation_id,
                            recovered_duration_seconds=(
                                projection.file_duration_seconds
                            ),
                        )
                        if recovered_task.operation_id not in existing_operation_ids:
                            self._file_tasks.append(recovered_task)
                            self._add_file_widget(recovered_task)
                            existing_operation_ids.add(
                                recovered_task.operation_id
                            )
                        self._last_completed_task = recovered_task
                    elif projection.dictation_text:
                        self.last_text = projection.dictation_text
                        if self.tray_icon:
                            self.tray_repeat_insert_action.setEnabled(True)
                        if hasattr(self, "transcription_history"):
                            self.transcription_history.add_transcription(
                                projection.dictation_text
                            )
                    self._acknowledge_completed_operation(
                        operation.operation_id
                    )
                except Exception:
                    logger.exception(
                        "Could not project recovered completed operation %s",
                        operation.operation_id,
                    )

            for operation in durable_recovery.retryable_dictations:
                if (
                    operation.operation_id
                    not in self._retryable_dictation_ids
                ):
                    self._retryable_dictation_ids.append(
                        operation.operation_id
                    )
                self._add_journal_entry(
                    "error",
                    "Recovered dictation requires retry",
                    text=str(operation.source_asset_path),
                    is_translatable=False,
                )
            self._update_recovered_dictation_actions()
            for operation in durable_recovery.pending_cancellations:
                self._retry_pending_cancellation(operation.operation_id)
        self._update_file_queue_ui()

    def _update_recovered_dictation_actions(self) -> None:
        available = bool(self._retryable_dictation_ids)
        enabled = available and not self._dictation.transcribing
        if hasattr(self, "retry_dictation_btn"):
            self.retry_dictation_btn.setVisible(available)
            self.retry_dictation_btn.setEnabled(enabled)
        if hasattr(self, "tray_retry_dictation_action"):
            self.tray_retry_dictation_action.setVisible(available)
            self.tray_retry_dictation_action.setEnabled(enabled)

    def _retry_next_recovered_dictation(self) -> None:
        if (
            self._operation_coordinator is None
            or not self._retryable_dictation_ids
        ):
            self._update_recovered_dictation_actions()
            return
        has_access, _info = (
            self.license_manager.check_transcription_entitlement()
        )
        if not has_access:
            self._show_trial_expired_dialog()
            return
        if self.audio_session.recording or self._dictation.transcribing:
            self._add_journal_entry(
                "error",
                "error",
                text="Finish the active dictation before retrying recovery.",
                is_translatable=False,
            )
            return

        operation_id = self._retryable_dictation_ids[0]
        operation = self._operation_coordinator.store.get(operation_id)
        if (
            operation is None
            or operation.status is not OperationStatus.RETRYABLE
            or not operation.source_asset_path.is_file()
        ):
            self._retryable_dictation_ids.pop(0)
            self._update_recovered_dictation_actions()
            self._add_journal_entry(
                "error",
                "error",
                text="Recovered dictation audio is no longer available.",
                is_translatable=False,
            )
            return

        try:
            duration_ms = max(
                0,
                int(get_file_duration(operation.source_asset_path) * 1000),
            )
            self._operation_coordinator.begin_attempt(
                operation_id,
                stage=OperationStage.TRANSCRIBE,
            )
            operation_token = self._dictation.begin_recovery(
                auto_insert=False
            )
        except Exception as exc:
            logger.exception("Could not retry recovered dictation")
            self._add_journal_entry(
                "error",
                "error",
                text=str(exc),
                is_translatable=False,
            )
            return

        self._update_recovered_dictation_actions()
        self._dictation_operation_ids[operation_token] = operation_id
        self._dictation_durations_ms[operation_token] = duration_ms
        self.overlay.show_processing()
        self._announce_status(self._t("transcribing"))
        self._add_journal_entry(
            "pending",
            "transcribing",
            is_translatable=True,
        )
        self._run_transcription(
            operation.source_asset_path,
            operation_token,
        )

    def _retry_pending_cancellation(self, operation_id: str) -> None:
        """Retry a durable cloud cancellation without blocking the GUI."""
        if self._operation_coordinator is None:
            return
        operation = self._operation_coordinator.store.get(operation_id)
        if (
            operation is None
            or operation.status is not OperationStatus.CANCEL_REQUESTED
        ):
            return
        if not operation.server_job_ids:
            self._operation_coordinator.finish_cancel(operation_id)
            return
        self._init_mindtype_cloud()
        if self._cloud_executor is None:
            self._add_journal_entry(
                "error",
                "Cloud cancellation is pending",
                text=operation_id,
                is_translatable=False,
            )
            return
        worker = CloudCancellationWorker(
            self._cloud_executor,
            operation_id,
        )
        self._cancellation_workers.add(worker)
        worker.resolved.connect(
            lambda identifier: self._add_journal_entry(
                "success",
                "Cloud cancellation confirmed",
                text=identifier,
                is_translatable=False,
            )
        )
        worker.failed.connect(
            self._on_pending_cancellation_retry_failed
        )
        worker.finished.connect(
            lambda current=worker: self._cancellation_workers.discard(
                current
            )
        )
        worker.start()

    def _on_pending_cancellation_retry_failed(
        self,
        operation_id: str,
        error: str,
    ) -> None:
        self._add_journal_entry(
            "error",
            "Cloud cancellation is pending",
            text=f"{operation_id}: {error}",
            is_translatable=False,
        )
        QTimer.singleShot(
            60_000,
            lambda identifier=operation_id: (
                self._retry_pending_cancellation(identifier)
            ),
        )

    def _acknowledge_completed_operation(self, operation_id: str) -> None:
        """ACK remote artifacts before removing the durable local source."""
        if self._operation_coordinator is None:
            raise RuntimeError("Durable operation storage is unavailable")

        operation = self._operation_coordinator.store.get(operation_id)
        if operation is None:
            raise KeyError(operation_id)
        captured_executor = None
        if operation.server_job_ids:
            self._init_mindtype_cloud()
            captured_executor = self._cloud_executor

        worker = OperationAcknowledgementWorker(
            operation_id,
            lambda: acknowledge_completed_operation(
                self._operation_coordinator,
                operation_id,
                cloud_executor_factory=lambda: captured_executor,
            ),
        )
        self._acknowledgement_workers.add(worker)
        worker.failed.connect(
            lambda identifier, error: self._add_journal_entry(
                "error",
                "Result acknowledgement is pending",
                text=f"{identifier}: {error}",
                is_translatable=False,
            )
        )
        worker.finished.connect(
            lambda current=worker: self._acknowledgement_workers.discard(
                current
            )
        )
        worker.start()

    def _cleanup_expired_spool(self) -> None:
        if self._operation_coordinator is None:
            return
        try:
            self._operation_coordinator.cleanup_expired(now=utc_now())
        except Exception:
            logger.exception("Could not clean expired durable operation data")

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

    def changeEvent(self, event) -> None:
        """При сворачивании прячем и окно журнала (оно top-level и не следует за главным)."""
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if hasattr(self, "_journal_window"):
                self._journal_window.hide()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        """Закрытие приложения или сворачивание в трей."""
        # Если трей доступен и не нажат Exit - сворачиваем в трей
        if self.tray_icon and not self._really_quit:
            event.ignore()
            # Журнал — top-level окно, self.hide() его не прячет (Qt пропускает
            # дочерние окна) → прячем явно, иначе зависнет на экране сиротой.
            if hasattr(self, "_journal_window"):
                self._journal_window.hide()
            self.hide()
            return

        self._prepare_for_full_exit()
        super().closeEvent(event)

    def _prepare_for_update_install(self) -> None:
        """Release native binaries immediately before starting the installer."""
        self._really_quit = True
        self._prepare_for_full_exit()

    def _prepare_for_full_exit(self) -> None:
        """Preserve cloud jobs and stop every local runtime before exit."""
        self._preserve_cloud_jobs_on_shutdown = True
        local_file_worker_stopped = True
        if self._file_queue:
            stopped = self._file_queue.stop_for_shutdown()
            if (
                getattr(
                    self._file_queue,
                    "uses_local_transcriber",
                    True,
                )
                and stopped is False
            ):
                local_file_worker_stopped = False
        self._cleanup_all()
        if not local_file_worker_stopped:
            raise RuntimeError(
                "Local file transcription did not stop before shutdown"
            )

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
        if self.audio_session.recording:
            self.audio_session.stop()
        self.audio.stop_monitoring()
        try:
            self.transcriber.shutdown()
        except Exception:
            logger.exception("Не удалось остановить transcriber backend")
        if self._transcribe_thread and self._transcribe_thread.isRunning():
            preserve_cloud_dictation = (
                self._preserve_cloud_jobs_on_shutdown
                and isinstance(
                    self._transcribe_thread,
                    CloudDictationWorker,
                )
            )
            stop_worker = getattr(
                self._transcribe_thread,
                (
                    "stop_for_shutdown"
                    if preserve_cloud_dictation
                    else "cancel"
                ),
                None,
            )
            if callable(stop_worker):
                try:
                    stop_worker()
                except Exception:
                    logger.exception(
                        "Could not stop dictation worker"
                    )

        # Останавливаем QThread воркеры
        for worker in [
            self._transcribe_thread,
            self._download_thread,
            self._file_worker,
            self._update_check_worker,
            self._update_download_worker,
            getattr(self, '_credits_worker', None),
            getattr(self, '_history_worker', None),
            *list(self._cancellation_workers),
            *list(self._acknowledgement_workers),
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

    # Шрифты для System 7 стиля. Chicago (оригинальный шрифт Apple Macintosh,
    # версия с КИРИЛЛИЦЕЙ) — основной для всего UI: аутентично + русский/латиница
    # одним шрифтом. ChicagoFLF/FindersKeepers — латинский фолбэк/совместимость.
    from PyQt6.QtGui import QFontDatabase, QFont
    fonts_dir = Path(__file__).parent / "ui" / "fonts"
    for font_file in ["Chicago.ttf", "ChicagoFLF.ttf", "FindersKeepers.ttf"]:
        font_path = fonts_dir / font_file
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                logger.debug(f"Loaded font: {font_file} -> {families}")
            else:
                logger.warning(f"Failed to load font: {font_file}")

    # Единый шрифт приложения: чистый системный (Segoe UI), со сглаживанием.
    # System-7 «системность» держится на хроме (бевели/чекбоксы/полосатый title bar),
    # а не на ретро-шрифте (пиксельные/Chicago пользователю не зашли).
    _ui_font = QFont("Segoe UI")
    _ui_font.setPixelSize(13)
    app.setFont(_ui_font)

    if not windows_high_contrast_enabled():
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
