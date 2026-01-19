"""
Миксин для голосового ассистента в MainWindow.

Содержит методы:
- _init_voice_assistant: инициализация ассистента
- _on_assistant_*: обработчики событий ассистента
- _load_assistant_settings: загрузка настроек ассистента
- _save_assistant_settings: сохранение настроек ассистента
"""

from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    pass  # Типы импортируются по необходимости


class AssistantMixin:
    """Миксин для функциональности голосового ассистента."""

    # Флаг доступности ассистента
    _assistant_enabled: bool = False
    _assistant: Optional[Any] = None  # VoiceAssistant
    _assistant_overlay: Optional[Any] = None  # AssistantOverlayWidget
    _current_dialog_id: Optional[str] = None

    def _init_voice_assistant(self) -> None:
        """Инициализировать голосового ассистента (если включен)."""
        # Проверяем флаг feature
        try:
            from ...main import ASSISTANT_FEATURE_ENABLED
            if not ASSISTANT_FEATURE_ENABLED:
                return
        except ImportError:
            return

        try:
            from ...assistant import VoiceAssistant, AssistantConfig, AssistantState
            from ...assistant_overlay import AssistantOverlayWidget
        except ImportError:
            return

        self._assistant_enabled = True

        # Загружаем настройки
        cfg = self.config.config

        assistant_config = AssistantConfig(
            openrouter_api_key=cfg.get("openrouter_api_key", ""),
            openrouter_model=cfg.get("openrouter_model", ""),
            personality=cfg.get("assistant_personality", "assistant"),
            tts_enabled=cfg.get("assistant_tts_enabled", True),
            tts_voice=cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural"),
            wake_word_enabled=cfg.get("assistant_wake_word_enabled", False),
            wake_word_phrase=cfg.get("assistant_wake_word_phrase", "hey_jarvis"),
            beep_enabled=cfg.get("assistant_beep_enabled", True),
        )

        self._assistant = VoiceAssistant(
            config=assistant_config,
            audio_recorder=self.audio,
            transcriber=self.transcriber,
            models_dir=self.models_dir,
        )

        # Создаём overlay для ассистента
        self._assistant_overlay = AssistantOverlayWidget()

        # Подключаем сигналы
        self._assistant.state_changed.connect(self._on_assistant_state_changed)
        self._assistant.transcription_ready.connect(self._on_assistant_transcription)
        self._assistant.response_ready.connect(self._on_assistant_response)
        self._assistant.response_chunk.connect(self._on_assistant_chunk)
        self._assistant.error_occurred.connect(self._on_assistant_error)
        self._assistant.waveform_updated.connect(self._assistant_overlay.update_waveform)

        # Подключаем кнопку отмены overlay
        self._assistant_overlay.cancel_clicked.connect(self._on_assistant_cancel)

    def _on_assistant_state_changed(self, state: Any) -> None:
        """Обработчик изменения состояния ассистента."""
        if not self._assistant_enabled:
            return

        try:
            from ...assistant import AssistantState
        except ImportError:
            return

        if state == AssistantState.LISTENING:
            self._assistant_overlay.show_listening()
        elif state == AssistantState.THINKING:
            self._assistant_overlay.show_thinking()
        elif state == AssistantState.SPEAKING:
            self._assistant_overlay.show_speaking()
        elif state == AssistantState.IDLE:
            self._assistant_overlay.hide()

    def _on_assistant_transcription(self, text: str) -> None:
        """Обработчик готовой транскрипции от ассистента."""
        if not self._assistant_enabled:
            return

        self._assistant_overlay.show_user_text(text)
        self._add_journal_entry("pending", "assistant_thinking", text=text[:50], is_translatable=True)

    def _on_assistant_response(self, text: str) -> None:
        """Обработчик готового ответа от ассистента."""
        if not self._assistant_enabled:
            return

        self._assistant_overlay.show_response(text)
        self._add_journal_entry("success", "assistant_response", text=text[:100], is_translatable=True)

        # Сохраняем диалог в историю
        self._save_current_dialog()

    def _on_assistant_chunk(self, chunk: str) -> None:
        """Обработчик частичного ответа (стриминг)."""
        if not self._assistant_enabled:
            return

        self._assistant_overlay.append_response_chunk(chunk)

    def _on_assistant_error(self, error: str) -> None:
        """Обработчик ошибки ассистента."""
        if not self._assistant_enabled:
            return

        self._assistant_overlay.show_error(error)
        self._add_journal_entry("error", "assistant_error", text=error, is_translatable=True)

    def _on_assistant_cancel(self) -> None:
        """Обработчик отмены ассистента."""
        if not self._assistant_enabled or not self._assistant:
            return

        self._assistant.cancel()
        self._assistant_overlay.hide()

    def _on_assistant_hotkey_press(self) -> None:
        """Обработчик нажатия хоткея ассистента."""
        if not self._assistant_enabled or not self._assistant:
            return

        # Проверяем лицензию
        from ...licensing import LicenseStatus
        info = self.license_manager.get_license_info()
        if info.status == LicenseStatus.TRIAL_EXPIRED:
            self._show_trial_expired_dialog()
            return

        # Запускаем/останавливаем ассистента
        try:
            from ...assistant import AssistantState
        except ImportError:
            return

        if self._assistant.state == AssistantState.IDLE:
            self._assistant.start_listening()
        else:
            self._assistant.stop()

    def _save_current_dialog(self) -> None:
        """Сохранить текущий диалог в историю."""
        if not self._assistant_enabled or not self._assistant:
            return

        try:
            from ...dialog_history import get_dialog_history_manager
            history_manager = get_dialog_history_manager()

            # Получаем историю из ассистента
            messages = self._assistant.get_messages()
            if not messages:
                return

            # Сохраняем или обновляем диалог
            if self._current_dialog_id:
                history_manager.update_dialog(self._current_dialog_id, messages)
            else:
                dialog = history_manager.create_dialog(
                    messages=messages,
                    system_prompt=self._assistant.config.system_prompt,
                )
                self._current_dialog_id = dialog.id
        except Exception:
            pass

    def _load_assistant_settings(self) -> None:
        """Загрузить настройки ассистента в UI."""
        if not self._assistant_enabled:
            return

        cfg = self.config.config

        # Загружаем настройки в соответствующие виджеты
        if hasattr(self, 'assistant_enable_check'):
            self.assistant_enable_check.setChecked(cfg.get("assistant_enabled", False))

        if hasattr(self, 'assistant_tts_check'):
            self.assistant_tts_check.setChecked(cfg.get("assistant_tts_enabled", True))

        if hasattr(self, 'assistant_use_wake_word_check'):
            self.assistant_use_wake_word_check.setChecked(cfg.get("assistant_wake_word_enabled", False))

        if hasattr(self, 'assistant_beep_check'):
            self.assistant_beep_check.setChecked(cfg.get("assistant_beep_enabled", True))

        # Загружаем выбор wake word
        if hasattr(self, 'assistant_wake_combo'):
            wake_phrase = cfg.get("assistant_wake_word_phrase", "hey_jarvis")
            idx = self.assistant_wake_combo.findData(wake_phrase)
            if idx >= 0:
                self.assistant_wake_combo.setCurrentIndex(idx)

        # Загружаем выбор голоса
        if hasattr(self, 'assistant_voice_combo'):
            voice = cfg.get("assistant_tts_voice", "ru-RU-DmitryNeural")
            idx = self.assistant_voice_combo.findData(voice)
            if idx >= 0:
                self.assistant_voice_combo.setCurrentIndex(idx)

        # Загружаем горячую клавишу
        if hasattr(self, 'assistant_hotkey_edit'):
            hotkey = cfg.get("assistant_hotkey", "ctrl+shift+a")
            self.assistant_hotkey_edit.setText(hotkey)

    def _save_assistant_settings(self) -> None:
        """Сохранить настройки ассистента из UI."""
        if not self._assistant_enabled:
            return

        updates = {}

        if hasattr(self, 'assistant_enable_check'):
            updates["assistant_enabled"] = self.assistant_enable_check.isChecked()

        if hasattr(self, 'assistant_tts_check'):
            updates["assistant_tts_enabled"] = self.assistant_tts_check.isChecked()

        if hasattr(self, 'assistant_use_wake_word_check'):
            updates["assistant_wake_word_enabled"] = self.assistant_use_wake_word_check.isChecked()

        if hasattr(self, 'assistant_beep_check'):
            updates["assistant_beep_enabled"] = self.assistant_beep_check.isChecked()

        if hasattr(self, 'assistant_wake_combo'):
            updates["assistant_wake_word_phrase"] = self.assistant_wake_combo.currentData()

        if hasattr(self, 'assistant_voice_combo'):
            updates["assistant_tts_voice"] = self.assistant_voice_combo.currentData()

        if hasattr(self, 'assistant_hotkey_edit'):
            updates["assistant_hotkey"] = self.assistant_hotkey_edit.text()

        self.config.update(**updates)

        # Обновляем конфиг ассистента
        if self._assistant:
            self._assistant.update_config(**updates)

    # Абстрактные методы, которые должны быть реализованы в MainWindow
    def _t(self, key: str) -> str:
        """Получить перевод строки."""
        raise NotImplementedError

    def _add_journal_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True) -> None:
        """Добавить запись в журнал."""
        raise NotImplementedError

    def _show_trial_expired_dialog(self) -> None:
        """Показать диалог истечения триала."""
        raise NotImplementedError
