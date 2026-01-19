"""
Миксин для управления горячими клавишами в MainWindow.

Содержит методы:
- _init_hotkey: инициализация слушателя горячих клавиш
- _start_hotkey_recording: запись нового хоткея
- _on_hotkey_recorded: обработчик записанной комбинации
- _emit_hotkey_press/_emit_hotkey_release: эмиттеры сигналов
- _handle_hotkey_press/_handle_hotkey_release: обработчики нажатий
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ...hotkeys import HotkeyListener, HotkeyRecorder
    from ...audio import AudioRecorder
    from ...config import ConfigManager
    from ...licensing import LicenseManager


class HotkeysMixin:
    """Миксин для функциональности горячих клавиш."""

    # Атрибуты, которые должны быть определены в MainWindow
    config: "ConfigManager"
    audio: "AudioRecorder"
    license_manager: "LicenseManager"
    hotkey_listener: Optional["HotkeyListener"]
    hotkey_recorder: Optional["HotkeyRecorder"]
    hotkey_edit: object
    hotkey_record_btn: object
    overlay: object
    _recording_hotkey: bool
    _transcription_in_progress: bool
    _recording_start_time: Optional[datetime]

    def _init_hotkey(self) -> None:
        """Инициализировать слушатель горячих клавиш."""
        from ...hotkeys import HotkeyListener

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
        from ...hotkeys import HotkeyRecorder

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
        from ...hotkeys import HotkeyListener

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
        from ...crash_reporter import add_breadcrumb
        from ...licensing import LicenseStatus
        from ...inserter import focus_manager

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

    def _cancel_transcription(self) -> None:
        """Отменить текущую транскрипцию."""
        raise NotImplementedError

    def _stop_recording_with_auto_insert(self) -> None:
        """Остановить запись и вставить текст."""
        raise NotImplementedError

    def _selected_device_id(self) -> int:
        """Получить ID выбранного устройства."""
        raise NotImplementedError

    def _update_tray_icon(self, recording: bool = False) -> None:
        """Обновить иконку в трее."""
        raise NotImplementedError
