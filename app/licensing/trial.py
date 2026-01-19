"""
Управление trial периодом.
Trial длится 7 дней ИЛИ 15 минут транскрипции (что наступит раньше).

Защита от обхода:
- HMAC подпись данных (защита от редактирования)
- Привязка к hardware fingerprint
- Защита от перевода системных часов
"""

import hmac
import json
import os
import platform
import sys
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger("mindtype.trial")

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


def _get_trial_secret() -> str:
    """Получить секрет для подписи trial данных."""
    try:
        from ..env import LICENSE_HMAC_SECRET
        return LICENSE_HMAC_SECRET + "_trial"
    except ImportError:
        # Fallback: генерируем machine-based secret
        info = [platform.node(), platform.machine(), platform.processor()]
        # Соль генерируется из характеристик машины для уникальности
        salt = hashlib.md5(("|".join(info) + "trl").encode()).hexdigest()[:16]
        combined = "|".join(info) + "|" + salt
        return hashlib.sha256(combined.encode()).hexdigest()


def _get_machine_id() -> str:
    """
    Получить уникальный идентификатор машины для защиты от переноса trial.

    Используем более надёжный fingerprint чем просто USERNAME/COMPUTERNAME.
    """
    info_parts = [
        sys.platform,
        platform.node(),
        platform.machine(),
        platform.processor(),
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

        # Добавляем MAC адрес
        try:
            import uuid
            mac = uuid.getnode()
            info_parts.append(str(mac))
        except Exception:
            pass

    # На macOS добавляем hardware UUID
    elif sys.platform == "darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType"],
                capture_output=True, text=True
            )
            for line in result.stdout.split("\n"):
                if "Hardware UUID" in line:
                    info_parts.append(line.split(":")[1].strip())
                    break
        except Exception:
            pass

    # На Linux добавляем machine-id
    else:
        try:
            with open("/etc/machine-id", "r") as f:
                info_parts.append(f.read().strip())
        except Exception:
            pass

    # Хешируем
    combined = "|".join(info_parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _sign_trial_data(data: dict) -> str:
    """Создать HMAC подпись для trial данных."""
    secret = _get_trial_secret()
    # Создаём копию без подписи
    data_copy = {k: v for k, v in data.items() if k != "_signature"}
    data_str = json.dumps(data_copy, sort_keys=True, separators=(',', ':'))
    signature = hmac.new(
        secret.encode(),
        data_str.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def _verify_trial_signature(data: dict, signature: str) -> bool:
    """Проверить HMAC подпись trial данных."""
    expected = _sign_trial_data(data)
    return hmac.compare_digest(expected, signature)


class TrialManager:
    """
    Менеджер trial периода с защитой от обхода.

    Защита включает:
    - HMAC подпись данных (защита от редактирования файла)
    - Привязка к hardware fingerprint (защита от копирования между машинами)
    - Отслеживание "последней активности" (защита от перевода часов назад)
    - Запоминание факта использования trial (защита от удаления файла)
    """

    def __init__(self):
        self._data_dir = _get_data_dir()
        self._trial_file = self._data_dir / "trial.dat"
        self._marker_file = self._data_dir / ".trial_marker"  # Скрытый маркер
        self._trial_data: Optional[dict] = None
        self._load_trial_data()

    def _load_trial_data(self) -> None:
        """Загрузить данные о trial с проверкой подписи."""
        if not self._trial_file.exists():
            # Проверяем маркер - если он есть, значит trial уже использовался
            if self._marker_file.exists():
                try:
                    with open(self._marker_file, "r") as f:
                        marker_data = json.load(f)

                    # Проверяем подпись маркера
                    signature = marker_data.pop("_signature", None)
                    if signature and _verify_trial_signature(marker_data, signature):
                        if marker_data.get("machine_id") == _get_machine_id():
                            # Маркер валиден - trial был использован и удалён
                            # Создаём истёкший trial
                            logger.warning("Trial marker found - trial was already used")
                            self._trial_data = {
                                "start_date": marker_data.get("start_date"),
                                "machine_id": _get_machine_id(),
                                "duration_days": 0,  # Истёк
                                "transcription_seconds_used": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
                                "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
                                "_expired_by_deletion": True,
                            }
                            return
                except Exception as e:
                    logger.debug(f"Error reading trial marker: {e}")

            self._trial_data = None
            return

        try:
            with open(self._trial_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Проверяем подпись
            signature = data.pop("_signature", None)
            if not signature or not _verify_trial_signature(data, signature):
                logger.warning("Trial data signature invalid - file was tampered!")
                # Файл был изменён вручную - считаем trial истёкшим
                self._trial_data = {
                    "start_date": datetime.now().isoformat(),
                    "machine_id": _get_machine_id(),
                    "duration_days": 0,
                    "transcription_seconds_used": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
                    "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
                    "_tampered": True,
                }
                return

            # Проверяем machine_id
            if data.get("machine_id") != _get_machine_id():
                logger.warning("Trial machine_id mismatch - file was copied from another machine!")
                self._trial_data = None
                return

            # Защита от перевода часов назад
            last_activity = data.get("last_activity")
            if last_activity:
                try:
                    last_activity_dt = datetime.fromisoformat(last_activity)
                    now = datetime.now()
                    # Если текущее время меньше последней активности более чем на 1 час
                    # значит часы были переведены назад
                    if now < last_activity_dt - timedelta(hours=1):
                        logger.warning("System clock was moved backwards - trial expired!")
                        data["duration_days"] = 0
                        data["_clock_tampered"] = True
                except Exception:
                    pass

            self._trial_data = data

            # Обновляем last_activity
            self._trial_data["last_activity"] = datetime.now().isoformat()
            self._save_trial_data()

        except Exception as e:
            logger.error(f"Error loading trial data: {e}")
            self._trial_data = None

    def _save_trial_data(self) -> None:
        """Сохранить данные о trial с подписью."""
        if self._trial_data is None:
            return

        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Обновляем last_activity
        self._trial_data["last_activity"] = datetime.now().isoformat()

        # Создаём копию для сохранения с подписью
        data_to_save = self._trial_data.copy()
        # Удаляем внутренние флаги перед подписью
        for key in list(data_to_save.keys()):
            if key.startswith("_"):
                del data_to_save[key]

        data_to_save["_signature"] = _sign_trial_data(data_to_save)

        with open(self._trial_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)

        # Также сохраняем скрытый маркер (защита от удаления trial.dat)
        self._save_marker()

    def _save_marker(self) -> None:
        """Сохранить скрытый маркер о том, что trial был использован."""
        marker_data = {
            "machine_id": _get_machine_id(),
            "start_date": self._trial_data.get("start_date"),
            "created_at": datetime.now().isoformat(),
        }
        marker_data["_signature"] = _sign_trial_data(marker_data)

        try:
            with open(self._marker_file, "w", encoding="utf-8") as f:
                json.dump(marker_data, f)

            # На Windows делаем файл скрытым
            if sys.platform == "win32":
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetFileAttributesW(
                        str(self._marker_file), 0x02  # FILE_ATTRIBUTE_HIDDEN
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Error saving trial marker: {e}")

    def start_trial(self) -> bool:
        """
        Начать trial период.

        Returns:
            True если trial успешно начат, False если уже был
        """
        if self._trial_data is not None:
            return False

        # Проверяем маркер - может trial уже использовался
        if self._marker_file.exists():
            try:
                with open(self._marker_file, "r") as f:
                    marker_data = json.load(f)
                signature = marker_data.pop("_signature", None)
                if signature and _verify_trial_signature(marker_data, signature):
                    if marker_data.get("machine_id") == _get_machine_id():
                        logger.warning("Cannot start trial - already used on this machine")
                        return False
            except Exception:
                pass

        self._trial_data = {
            "start_date": datetime.now().isoformat(),
            "machine_id": _get_machine_id(),
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
            "last_activity": datetime.now().isoformat(),
        }
        self._save_trial_data()
        return True

    def is_trial_active(self) -> bool:
        """Проверить, активен ли trial период."""
        if self._trial_data is None:
            # Проверяем маркер - если есть, trial уже использовался
            if self._marker_file.exists():
                return False
            return True  # Trial ещё не начинался - можно начать

        # Проверяем флаги тамперинга
        if self._trial_data.get("_tampered") or self._trial_data.get("_clock_tampered"):
            return False

        if self._trial_data.get("_expired_by_deletion"):
            return False

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
        """
        Сбросить trial (ТОЛЬКО для тестирования!).

        В production этот метод не должен быть доступен пользователю.
        Проверяем frozen (PyInstaller) и __compiled__ (Nuitka) атрибуты.
        """
        # Block reset_trial in production builds (PyInstaller, Nuitka, etc.)
        if getattr(sys, 'frozen', False) or hasattr(sys, '__compiled__'):
            logger.warning("reset_trial called in production build - ignoring")
            return

        if self._trial_file.exists():
            self._trial_file.unlink()
        if self._marker_file.exists():
            self._marker_file.unlink()
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



