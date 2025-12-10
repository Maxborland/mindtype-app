"""
Управление trial периодом.
Trial длится 7 дней ИЛИ 15 минут транскрипции (что наступит раньше).
"""

import json
import os
import sys
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple


# Длительность trial периода
TRIAL_DURATION_DAYS = 7
TRIAL_TRANSCRIPTION_LIMIT_SECONDS = 15 * 60  # 15 минут в секундах


def _get_data_dir() -> Path:
    """Получить директорию для хранения данных приложения."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux и др.
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base / "MindType"


def _get_machine_id() -> str:
    """Получить уникальный идентификатор машины для защиты от переноса trial."""
    # Собираем информацию о системе
    info_parts = [
        sys.platform,
        os.getenv("COMPUTERNAME", ""),
        os.getenv("USERNAME", os.getenv("USER", "")),
    ]

    # На Windows добавляем Volume Serial Number
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volume_serial = ctypes.c_ulong()
            kernel32.GetVolumeInformationW(
                "C:\\", None, 0, ctypes.byref(volume_serial), None, None, None, 0
            )
            info_parts.append(str(volume_serial.value))
        except Exception:
            pass

    # Хешируем
    combined = "|".join(info_parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


class TrialManager:
    """Менеджер trial периода."""

    def __init__(self):
        self._data_dir = _get_data_dir()
        self._trial_file = self._data_dir / "trial.dat"
        self._trial_data: Optional[dict] = None
        self._load_trial_data()

    def _load_trial_data(self) -> None:
        """Загрузить данные о trial."""
        if not self._trial_file.exists():
            self._trial_data = None
            return

        try:
            with open(self._trial_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Проверяем machine_id
            if data.get("machine_id") != _get_machine_id():
                self._trial_data = None
                return

            self._trial_data = data
        except Exception:
            self._trial_data = None

    def _save_trial_data(self) -> None:
        """Сохранить данные о trial."""
        if self._trial_data is None:
            return

        self._data_dir.mkdir(parents=True, exist_ok=True)

        with open(self._trial_file, "w", encoding="utf-8") as f:
            json.dump(self._trial_data, f, indent=2)

    def start_trial(self) -> bool:
        """
        Начать trial период.

        Returns:
            True если trial успешно начат, False если уже был
        """
        if self._trial_data is not None:
            return False

        self._trial_data = {
            "start_date": datetime.now().isoformat(),
            "machine_id": _get_machine_id(),
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
        }
        self._save_trial_data()
        return True

    def is_trial_active(self) -> bool:
        """Проверить, активен ли trial период."""
        if self._trial_data is None:
            return True  # Trial ещё не начинался - можно начать

        # Проверяем дни
        if self.get_remaining_days() <= 0:
            return False

        # Проверяем лимит транскрипции
        if self.get_remaining_transcription_seconds() <= 0:
            return False

        return True

    def add_transcription_time(self, seconds: float) -> None:
        """Добавить использованное время транскрипции."""
        if self._trial_data is None:
            self.start_trial()

        current = self._trial_data.get("transcription_seconds_used", 0)
        self._trial_data["transcription_seconds_used"] = current + seconds
        self._save_trial_data()

    def get_remaining_transcription_seconds(self) -> float:
        """Получить оставшееся время транскрипции в секундах."""
        if self._trial_data is None:
            return TRIAL_TRANSCRIPTION_LIMIT_SECONDS

        limit = self._trial_data.get("transcription_limit_seconds", TRIAL_TRANSCRIPTION_LIMIT_SECONDS)
        used = self._trial_data.get("transcription_seconds_used", 0)
        return max(0, limit - used)

    def get_used_transcription_minutes(self) -> float:
        """Получить использованное время транскрипции в минутах."""
        if self._trial_data is None:
            return 0
        return self._trial_data.get("transcription_seconds_used", 0) / 60

    def get_remaining_days(self) -> int:
        """
        Получить количество оставшихся дней trial.

        Returns:
            Количество дней (0 если trial истёк или не начат)
        """
        if self._trial_data is None:
            return TRIAL_DURATION_DAYS  # Trial ещё не начат

        try:
            start_date = datetime.fromisoformat(self._trial_data["start_date"])
            duration = self._trial_data.get("duration_days", TRIAL_DURATION_DAYS)
            end_date = start_date + timedelta(days=duration)

            remaining = (end_date - datetime.now()).days
            return max(0, remaining)
        except Exception:
            return 0

    def get_trial_info(self) -> Tuple[bool, int, float, Optional[datetime]]:
        """
        Получить информацию о trial.

        Returns:
            Tuple (is_active, remaining_days, remaining_minutes, start_date)
        """
        if self._trial_data is None:
            return (True, TRIAL_DURATION_DAYS, TRIAL_TRANSCRIPTION_LIMIT_SECONDS / 60, None)

        try:
            start_date = datetime.fromisoformat(self._trial_data["start_date"])
        except Exception:
            start_date = None

        return (
            self.is_trial_active(),
            self.get_remaining_days(),
            self.get_remaining_transcription_seconds() / 60,
            start_date,
        )

    def has_trial_started(self) -> bool:
        """Проверить, был ли начат trial."""
        return self._trial_data is not None

    def reset_trial(self) -> None:
        """Сбросить trial (для тестирования)."""
        if self._trial_file.exists():
            self._trial_file.unlink()
        self._trial_data = None


# Для тестирования
if __name__ == "__main__":
    manager = TrialManager()

    print(f"Data directory: {manager._data_dir}")
    print(f"Trial file: {manager._trial_file}")
    print(f"Machine ID: {_get_machine_id()}")
    print()

    is_active, remaining, start_date = manager.get_trial_info()
    print(f"Trial started: {manager.has_trial_started()}")
    print(f"Trial active: {is_active}")
    print(f"Remaining days: {remaining}")
    print(f"Start date: {start_date}")

    if not manager.has_trial_started():
        print("\nStarting trial...")
        manager.start_trial()
        is_active, remaining, start_date = manager.get_trial_info()
        print(f"Trial active: {is_active}")
        print(f"Remaining days: {remaining}")
        print(f"Start date: {start_date}")



