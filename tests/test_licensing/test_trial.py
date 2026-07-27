"""
Тесты для модуля управления trial периодом.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.licensing.trial import (
    TrialManager,
    TRIAL_DURATION_DAYS,
    TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
    _get_machine_id,
    _sign_trial_data,
)


@pytest.fixture
def temp_trial_dir(tmp_path):
    """Временная директория для данных trial."""
    data_dir = tmp_path / "MindType"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def trial_manager(temp_trial_dir):
    """TrialManager с временной директорией."""
    with patch('app.licensing.trial._get_data_dir', return_value=temp_trial_dir):
        manager = TrialManager()
    return manager


class TestTrialManagerStartTrial:
    """Тесты для метода start_trial()."""

    def test_start_trial_first_time(self, trial_manager):
        """Тест первого запуска trial."""
        result = trial_manager.start_trial()
        assert result is True
        assert trial_manager.has_trial_started() is True

    def test_start_trial_already_started(self, trial_manager):
        """Тест повторного запуска trial."""
        trial_manager.start_trial()
        result = trial_manager.start_trial()
        assert result is False  # Уже запущен

    def test_start_trial_creates_file(self, trial_manager):
        """Тест создания файла trial."""
        trial_manager.start_trial()
        assert trial_manager._trial_file.exists()

    def test_start_trial_data_structure(self, trial_manager):
        """Тест структуры данных trial."""
        trial_manager.start_trial()

        with open(trial_manager._trial_file, "r") as f:
            data = json.load(f)

        assert "start_date" in data
        assert "machine_id" in data
        assert "duration_days" in data
        assert "transcription_seconds_used" in data
        assert "transcription_limit_seconds" in data


class TestTrialManagerIsActive:
    """Тесты для метода is_trial_active()."""

    def test_is_active_not_started(self, trial_manager):
        """Тест активности не начатого trial."""
        # Trial ещё не начат - возвращает True (можно начать)
        assert trial_manager.is_trial_active() is True

    def test_is_active_just_started(self, trial_manager):
        """Тест активности только что начатого trial."""
        trial_manager.start_trial()
        assert trial_manager.is_trial_active() is True

    def test_is_active_days_expired(self, trial_manager):
        """Тест неактивности после истечения дней."""
        # Создаём trial с датой начала в прошлом
        expired_date = (datetime.now() - timedelta(days=TRIAL_DURATION_DAYS + 1)).isoformat()
        trial_data = {
            "start_date": expired_date,
            "machine_id": _get_machine_id(),
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
            "last_activity": datetime.now().isoformat(),
        }
        # Добавляем подпись
        trial_data["_signature"] = _sign_trial_data(trial_data)

        with open(trial_manager._trial_file, "w") as f:
            json.dump(trial_data, f)

        trial_manager._load_trial_data()
        assert trial_manager.is_trial_active() is False

    def test_is_active_transcription_limit_reached(self, trial_manager):
        """Тест неактивности при достижении лимита транскрипции."""
        trial_manager.start_trial()
        # Используем весь лимит
        trial_manager.add_transcription_time(TRIAL_TRANSCRIPTION_LIMIT_SECONDS + 1)
        assert trial_manager.is_trial_active() is False


class TestTrialManagerTranscriptionTime:
    """Тесты для методов работы с временем транскрипции."""

    def test_add_transcription_time(self, trial_manager):
        """Тест добавления времени транскрипции."""
        trial_manager.start_trial()
        trial_manager.add_transcription_time(60)  # 1 минута

        assert trial_manager.get_remaining_transcription_seconds() == \
               TRIAL_TRANSCRIPTION_LIMIT_SECONDS - 60

    def test_add_transcription_time_multiple(self, trial_manager):
        """Тест накопления времени транскрипции."""
        trial_manager.start_trial()
        trial_manager.add_transcription_time(30)
        trial_manager.add_transcription_time(30)

        used_minutes = trial_manager.get_used_transcription_minutes()
        assert used_minutes == 1.0  # 60 секунд = 1 минута

    def test_trial_usage_is_idempotent_by_operation(self, trial_manager):
        trial_manager.start_trial()

        assert trial_manager.add_transcription_time(
            60,
            operation_id="operation-1",
        ) is True
        assert trial_manager.add_transcription_time(
            60,
            operation_id="operation-1",
        ) is False

        assert trial_manager.get_used_transcription_minutes() == 1.0

    def test_add_transcription_time_starts_trial(self, trial_manager):
        """Тест автоматического запуска trial при добавлении времени."""
        assert trial_manager.has_trial_started() is False
        trial_manager.add_transcription_time(10)
        assert trial_manager.has_trial_started() is True

    def test_remaining_transcription_not_started(self, trial_manager):
        """Тест оставшегося времени для не начатого trial."""
        remaining = trial_manager.get_remaining_transcription_seconds()
        assert remaining == TRIAL_TRANSCRIPTION_LIMIT_SECONDS

    def test_remaining_transcription_never_negative(self, trial_manager):
        """Тест что оставшееся время не отрицательное."""
        trial_manager.start_trial()
        trial_manager.add_transcription_time(TRIAL_TRANSCRIPTION_LIMIT_SECONDS + 1000)
        assert trial_manager.get_remaining_transcription_seconds() == 0


class TestTrialManagerRemainingDays:
    """Тесты для метода get_remaining_days()."""

    def test_remaining_days_not_started(self, trial_manager):
        """Тест оставшихся дней для не начатого trial."""
        days = trial_manager.get_remaining_days()
        assert days == TRIAL_DURATION_DAYS

    def test_remaining_days_just_started(self, trial_manager):
        """Тест оставшихся дней для только что начатого trial."""
        trial_manager.start_trial()
        days = trial_manager.get_remaining_days()
        # Должно быть около TRIAL_DURATION_DAYS (минус несколько часов)
        assert days >= TRIAL_DURATION_DAYS - 1

    def test_remaining_days_expired(self, trial_manager):
        """Тест оставшихся дней для истёкшего trial."""
        expired_date = (datetime.now() - timedelta(days=TRIAL_DURATION_DAYS + 1)).isoformat()
        trial_data = {
            "start_date": expired_date,
            "machine_id": _get_machine_id(),
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
            "last_activity": datetime.now().isoformat(),
        }
        trial_data["_signature"] = _sign_trial_data(trial_data)

        with open(trial_manager._trial_file, "w") as f:
            json.dump(trial_data, f)

        trial_manager._load_trial_data()
        assert trial_manager.get_remaining_days() == 0


class TestTrialManagerGetInfo:
    """Тесты для метода get_trial_info()."""

    def test_get_trial_info_not_started(self, trial_manager):
        """Тест информации о не начатом trial."""
        is_active, days, minutes, start_date = trial_manager.get_trial_info()

        assert is_active is True
        assert days == TRIAL_DURATION_DAYS
        assert minutes == TRIAL_TRANSCRIPTION_LIMIT_SECONDS / 60
        assert start_date is None

    def test_get_trial_info_started(self, trial_manager):
        """Тест информации о начатом trial."""
        trial_manager.start_trial()
        is_active, days, minutes, start_date = trial_manager.get_trial_info()

        assert is_active is True
        assert days >= TRIAL_DURATION_DAYS - 1
        assert minutes == TRIAL_TRANSCRIPTION_LIMIT_SECONDS / 60
        assert start_date is not None
        assert isinstance(start_date, datetime)


class TestTrialManagerReset:
    """Тесты для метода reset_trial()."""

    def test_reset_trial(self, trial_manager):
        """Тест сброса trial."""
        trial_manager.start_trial()
        assert trial_manager.has_trial_started() is True

        trial_manager.reset_trial()
        assert trial_manager.has_trial_started() is False

    def test_reset_trial_removes_file(self, trial_manager):
        """Тест удаления файла при сбросе."""
        trial_manager.start_trial()
        assert trial_manager._trial_file.exists()

        trial_manager.reset_trial()
        assert not trial_manager._trial_file.exists()


class TestTrialManagerMachineId:
    """Тесты для защиты machine_id."""

    def test_load_trial_different_machine_id(self, trial_manager):
        """Тест отклонения trial с другого машины."""
        trial_data = {
            "start_date": datetime.now().isoformat(),
            "machine_id": "different_machine_id_12345",  # Другой ID
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
            "last_activity": datetime.now().isoformat(),
        }
        trial_data["_signature"] = _sign_trial_data(trial_data)

        with open(trial_manager._trial_file, "w") as f:
            json.dump(trial_data, f)

        trial_manager._load_trial_data()
        # Trial данные должны быть отклонены
        assert trial_manager._trial_data is None


class TestTrialManagerTamperProtection:
    """Тесты для защиты от тамперинга."""

    def test_tampered_file_detected(self, trial_manager):
        """Тест обнаружения изменённого файла."""
        trial_manager.start_trial()

        # Читаем файл и меняем данные
        with open(trial_manager._trial_file, "r") as f:
            data = json.load(f)

        # Меняем start_date на будущее (попытка обхода)
        data["start_date"] = (datetime.now() + timedelta(days=30)).isoformat()

        # Сохраняем без обновления подписи
        with open(trial_manager._trial_file, "w") as f:
            json.dump(data, f)

        # Перезагружаем
        trial_manager._load_trial_data()

        # Trial должен быть помечен как tampered и неактивен
        assert trial_manager.is_trial_active() is False

    def test_missing_signature_detected(self, trial_manager):
        """Тест обнаружения отсутствующей подписи."""
        trial_data = {
            "start_date": datetime.now().isoformat(),
            "machine_id": _get_machine_id(),
            "duration_days": TRIAL_DURATION_DAYS,
            "transcription_seconds_used": 0,
            "transcription_limit_seconds": TRIAL_TRANSCRIPTION_LIMIT_SECONDS,
            "last_activity": datetime.now().isoformat(),
            # Нет _signature!
        }

        with open(trial_manager._trial_file, "w") as f:
            json.dump(trial_data, f)

        trial_manager._load_trial_data()

        # Trial должен быть помечен как tampered
        assert trial_manager.is_trial_active() is False

    def test_reset_trial_removes_marker(self, trial_manager):
        """Тест что reset_trial удаляет маркер."""
        trial_manager.start_trial()

        # Должен существовать маркер
        assert trial_manager._marker_file.exists()

        trial_manager.reset_trial()

        # Маркер должен быть удалён
        assert not trial_manager._marker_file.exists()

    def test_delete_trial_file_detected(self, trial_manager):
        """Тест обнаружения удаления trial.dat."""
        trial_manager.start_trial()
        marker_existed = trial_manager._marker_file.exists()

        # Удаляем trial.dat но оставляем маркер
        trial_manager._trial_file.unlink()

        # Перезагружаем менеджер
        with patch('app.licensing.trial._get_data_dir', return_value=trial_manager._data_dir):
            new_manager = TrialManager()

        if marker_existed:
            # Если маркер был, trial должен быть неактивен
            assert new_manager.is_trial_active() is False


class TestGetMachineId:
    """Тесты для функции _get_machine_id()."""

    def test_machine_id_is_string(self):
        """Тест что machine_id - строка."""
        machine_id = _get_machine_id()
        assert isinstance(machine_id, str)

    def test_machine_id_length(self):
        """Тест длины machine_id."""
        machine_id = _get_machine_id()
        assert len(machine_id) == 16

    def test_machine_id_deterministic(self):
        """Тест детерминированности machine_id."""
        id1 = _get_machine_id()
        id2 = _get_machine_id()
        assert id1 == id2

    def test_machine_id_hex_characters(self):
        """Тест что machine_id содержит только hex символы."""
        machine_id = _get_machine_id()
        assert all(c in "0123456789abcdef" for c in machine_id)
