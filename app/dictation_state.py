"""
Состояние цикла диктовки (push-to-talk): запись → транскрипция → автовставка.

Раньше эти флаги были размазаны по `MainWindow` (4 поля, мутации в 6 методах, нигде
не видно всей машины). Здесь — единое место. Чистый объект без Qt: тестируется напрямую
и станет ядром будущего DictationController.

Примечание: флаг «перепривязки хоткея» (`_recording_hotkey`) сюда НЕ входит — это
отдельная UI-забота настроек, не часть диктовки.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class DictationState:
    transcribing: bool = False                       # идёт транскрипция
    auto_insert_pending: bool = False                # результат нужно вставить
    recording_start_time: Optional[datetime] = None  # для учёта trial-времени

    def begin_transcription(self, *, auto_insert: bool) -> None:
        """Переход запись → транскрипция."""
        self.transcribing = True
        self.auto_insert_pending = auto_insert

    def finish_transcription(self) -> None:
        """Транскрипция завершена (флаг автовставки трогают отдельно)."""
        self.transcribing = False

    def cancel(self) -> None:
        """Отмена: ни транскрипции, ни автовставки."""
        self.transcribing = False
        self.auto_insert_pending = False
