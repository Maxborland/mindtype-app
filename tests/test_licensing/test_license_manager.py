"""
Тесты для модуля управления лицензиями.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import urllib.request
import urllib.error
from io import BytesIO

import pytest

from app.licensing.license_manager import (
    LicenseManager,
    LicenseStatus,
    ValidationResult,
    LicenseInfo,
    _get_device_id,
    _get_device_name,
    _sign_data,
    _verify_signature,
)
from app.licensing.trial import TRIAL_TRANSCRIPTION_LIMIT_SECONDS


@pytest.fixture
def temp_license_dir(tmp_path):
    """Временная директория для данных лицензии."""
    data_dir = tmp_path / "MindType"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def license_manager(temp_license_dir):
    """LicenseManager с временной директорией."""
    with patch('app.licensing.license_manager._get_data_dir', return_value=temp_license_dir):
        with patch('app.licensing.trial._get_data_dir', return_value=temp_license_dir):
            manager = LicenseManager()
    return manager


@pytest.fixture
def valid_license_key():
    """Валидный лицензионный ключ."""
    from app.licensing.key_validator import generate_license_key
    return generate_license_key()


class TestDeviceIdentification:
    """Тесты для функций идентификации устройства."""

    def test_get_device_id_is_string(self):
        """Тест что device_id - строка."""
        device_id = _get_device_id()
        assert isinstance(device_id, str)

    def test_get_device_id_length(self):
        """Тест длины device_id."""
        device_id = _get_device_id()
        assert len(device_id) == 32

    def test_get_device_id_deterministic(self):
        """Тест детерминированности device_id."""
        id1 = _get_device_id()
        id2 = _get_device_id()
        assert id1 == id2

    def test_get_device_name_is_string(self):
        """Тест что device_name - строка."""
        name = _get_device_name()
        assert isinstance(name, str)

    def test_get_device_name_contains_os(self):
        """Тест что device_name содержит название ОС."""
        name = _get_device_name()
        assert "Windows" in name or "Linux" in name or "Darwin" in name


class TestHmacSignature:
    """Тесты для HMAC подписи."""

    def test_sign_data_returns_string(self):
        """Тест что подпись - строка."""
        data = {"key": "value"}
        signature = _sign_data(data)
        assert isinstance(signature, str)

    def test_sign_data_deterministic(self):
        """Тест детерминированности подписи."""
        data = {"key": "value", "number": 123}
        sig1 = _sign_data(data)
        sig2 = _sign_data(data)
        assert sig1 == sig2

    def test_sign_data_different_data(self):
        """Тест разных подписей для разных данных."""
        data1 = {"key": "value1"}
        data2 = {"key": "value2"}
        assert _sign_data(data1) != _sign_data(data2)

    def test_verify_signature_valid(self):
        """Тест верификации валидной подписи."""
        data = {"key": "value", "test": 123}
        signature = _sign_data(data)
        assert _verify_signature(data, signature) is True

    def test_verify_signature_invalid(self):
        """Тест верификации невалидной подписи."""
        data = {"key": "value"}
        assert _verify_signature(data, "invalid_signature") is False

    def test_verify_signature_tampered_data(self):
        """Тест верификации с изменёнными данными."""
        data = {"key": "value"}
        signature = _sign_data(data)
        data["key"] = "modified"
        assert _verify_signature(data, signature) is False


class TestLicenseManagerInit:
    """Тесты для инициализации LicenseManager."""

    def test_init_creates_data_dir(self, temp_license_dir):
        """Тест создания директории данных."""
        with patch('app.licensing.license_manager._get_data_dir', return_value=temp_license_dir):
            with patch('app.licensing.trial._get_data_dir', return_value=temp_license_dir):
                manager = LicenseManager()
        assert temp_license_dir.exists()

    def test_init_no_license(self, license_manager):
        """Тест инициализации без лицензии."""
        info = license_manager.get_license_info()
        # Должен быть trial статус (не начат)
        assert info.status == LicenseStatus.TRIAL

    def test_malformed_license_cache_is_deleted(self, temp_license_dir):
        """Повреждённый cache не должен переживать fail-closed загрузку."""
        license_file = temp_license_dir / "license.dat"
        license_file.write_text("{not-json", encoding="utf-8")

        with patch('app.licensing.license_manager._get_data_dir', return_value=temp_license_dir):
            with patch('app.licensing.trial._get_data_dir', return_value=temp_license_dir):
                manager = LicenseManager()

        assert manager._license_data is None
        assert not license_file.exists()


class TestLicenseManagerGetInfo:
    """Тесты для метода get_license_info()."""

    def test_get_info_trial_status(self, license_manager):
        """Тест получения информации о trial."""
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.TRIAL
        assert info.is_active is True
        assert info.is_trial is True
        assert info.is_full_license is False

    def test_get_info_with_cached_license(self, license_manager):
        """Тест получения информации о закэшированной лицензии."""
        # Создаём кэш лицензии
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "plan": "personal",
            "email": "test@example.com",
            "validated_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=365)).isoformat(),
            "activated_devices": 1,
            "max_devices": 2,
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()
        info = license_manager.get_license_info()

        assert info.status == LicenseStatus.VALID
        assert info.is_active is True
        assert info.is_full_license is True
        assert info.plan == "personal"
        assert info.email == "test@example.com"


def mock_urlopen_response(json_data, status=200):
    """Helper для создания mock response."""
    response = Mock()
    response.read.return_value = json.dumps(json_data).encode('utf-8')
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class TestLicenseManagerActivation:
    """Тесты для активации лицензии."""

    def test_activate_online_success(self, license_manager, valid_license_key):
        """Тест успешной онлайн активации."""
        response_data = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": "2025-12-31T23:59:59Z",
            "activatedDevices": 1,
            "maxDevices": 2,
            "message": "activation_success"
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(response_data)):
            result, message, data = license_manager.activate_online(valid_license_key)

        assert result == ValidationResult.SUCCESS
        assert data is not None
        assert data["valid"] is True

    def test_activate_online_not_found(self, license_manager, valid_license_key):
        """Тест активации несуществующего ключа."""
        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "not_found",
            "message": "License key not found"
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(valid_license_key)

        assert result == ValidationResult.NOT_FOUND

    def test_activate_online_device_limit(self, license_manager, valid_license_key):
        """Тест активации при превышении лимита устройств."""
        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "device_limit",
            "message": "Maximum devices reached"
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(valid_license_key)

        assert result == ValidationResult.DEVICE_LIMIT

    def test_activate_online_invalid_format(self, license_manager):
        """Тест активации с невалидным форматом ключа."""
        result, message, data = license_manager.activate_online("invalid")

        assert result == ValidationResult.INVALID_KEY
        assert data is None

    def test_activate_online_network_error(self, license_manager, valid_license_key):
        """Тест активации при ошибке сети."""
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError("Connection refused")):
            result, message, data = license_manager.activate_online(valid_license_key)

        assert result == ValidationResult.NETWORK_ERROR


class TestLicenseManagerDeactivation:
    """Тесты для деактивации лицензии."""

    def test_deactivate_no_license(self, license_manager):
        """Тест деактивации без лицензии."""
        success, message = license_manager.deactivate_online()
        assert success is False
        assert message == "no_license"

    def test_deactivate_online_success(self, license_manager):
        """Тест успешной деактивации."""
        # Сначала создаём кэшированную лицензию
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "plan": "personal",
            "validated_at": datetime.now().isoformat(),
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response({"success": True})):
            success, message = license_manager.deactivate_online()

        assert success is True
        assert license_manager._license_data is None


class TestLicenseManagerRevalidation:
    """Тесты для ревалидации лицензии."""

    def test_needs_revalidation_no_license(self, license_manager):
        """Тест проверки необходимости ревалидации без лицензии."""
        assert license_manager.needs_revalidation() is False

    def test_needs_revalidation_fresh_license(self, license_manager):
        """Тест свежей лицензии не требует ревалидации."""
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "validated_at": datetime.now().isoformat(),
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()

        assert license_manager.needs_revalidation() is False

    def test_needs_revalidation_old_license(self, license_manager):
        """Тест старой лицензии требует ревалидации."""
        # Дата валидации 8 дней назад (интервал по умолчанию 7 дней)
        old_date = (datetime.now() - timedelta(days=8)).isoformat()
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "validated_at": old_date,
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()

        assert license_manager.needs_revalidation() is True

    @pytest.mark.parametrize(
        "result",
        [
            ValidationResult.NOT_FOUND,
            ValidationResult.DEACTIVATED,
            ValidationResult.EXPIRED,
        ],
    )
    def test_authoritative_negative_clears_cached_license(
        self, license_manager, result
    ):
        license_manager._license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "validated_at": (datetime.now() - timedelta(days=8)).isoformat(),
        }
        license_manager._save_license()

        with patch.object(
            license_manager,
            "activate_online",
            return_value=(result, result.value, None),
        ):
            actual = license_manager.revalidate_if_needed()

        assert actual == result
        assert license_manager._license_data is None
        assert not license_manager._license_file.exists()

    def test_network_failure_keeps_cached_license(self, license_manager):
        license_manager._license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "validated_at": (datetime.now() - timedelta(days=8)).isoformat(),
        }
        license_manager._save_license()

        with patch.object(
            license_manager,
            "activate_online",
            return_value=(ValidationResult.NETWORK_ERROR, "network_error", None),
        ):
            actual = license_manager.revalidate_if_needed()

        assert actual == ValidationResult.NETWORK_ERROR
        assert license_manager._license_data is not None
        assert license_manager._license_file.exists()


class TestLicenseManagerCheckAccess:
    """Тесты для метода check_access()."""

    def test_check_access_starts_trial(self, license_manager):
        """Тест автоматического запуска trial при проверке доступа."""
        has_access, info = license_manager.check_access()

        assert has_access is True
        assert info.status == LicenseStatus.TRIAL
        assert license_manager._trial_manager.has_trial_started() is True

    def test_check_access_with_license(self, license_manager):
        """Тест доступа с полной лицензией."""
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "plan": "personal",
            "validated_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(days=365)).isoformat(),
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()

        has_access, info = license_manager.check_access()

        assert has_access is True
        assert info.status == LicenseStatus.VALID

    def test_transcription_entitlement_rejects_batch_over_trial_quota(
        self, license_manager
    ):
        license_manager.check_access()

        has_access, info = license_manager.check_transcription_entitlement(
            required_seconds=TRIAL_TRANSCRIPTION_LIMIT_SECONDS + 1
        )

        assert has_access is False
        assert info.status == LicenseStatus.TRIAL

    def test_transcription_entitlement_accepts_batch_within_trial_quota(
        self, license_manager
    ):
        license_manager.check_access()

        has_access, info = license_manager.check_transcription_entitlement(
            required_seconds=1
        )

        assert has_access is True
        assert info.status == LicenseStatus.TRIAL


class TestLicenseManagerTrialTime:
    """Тесты для учёта времени транскрипции в trial."""

    def test_add_transcription_time_trial(self, license_manager):
        """Тест добавления времени транскрипции в trial."""
        license_manager.check_access()  # Запуск trial
        license_manager.add_transcription_time(60)

        info = license_manager.get_license_info()
        # Оставшееся время должно уменьшиться
        assert info.trial_remaining_minutes < 15

    def test_add_transcription_time_full_license(self, license_manager):
        """Тест что время транскрипции не учитывается для полной лицензии."""
        license_data = {
            "license_key": "ABCDEFGHJKMNPQRS",
            "device_id": license_manager.get_device_id(),
            "plan": "personal",
            "validated_at": datetime.now().isoformat(),
        }
        license_data["_signature"] = _sign_data(license_data)

        license_manager._data_dir.mkdir(parents=True, exist_ok=True)
        with open(license_manager._license_file, "w") as f:
            json.dump(license_data, f)

        license_manager._load_license()

        # Для полной лицензии время не должно учитываться
        license_manager.add_transcription_time(1000)
        # Проверяем что trial менеджер не затронут
        info = license_manager.get_license_info()
        assert info.is_full_license is True


class TestLicenseInfo:
    """Тесты для класса LicenseInfo."""

    def test_is_active_valid(self):
        """Тест is_active для валидной лицензии."""
        info = LicenseInfo(status=LicenseStatus.VALID)
        assert info.is_active is True

    def test_is_active_trial(self):
        """Тест is_active для trial."""
        info = LicenseInfo(status=LicenseStatus.TRIAL)
        assert info.is_active is True

    def test_is_active_expired(self):
        """Тест is_active для истёкшего trial."""
        info = LicenseInfo(status=LicenseStatus.TRIAL_EXPIRED)
        assert info.is_active is False

    def test_is_trial_true(self):
        """Тест is_trial для trial."""
        info = LicenseInfo(status=LicenseStatus.TRIAL)
        assert info.is_trial is True

    def test_is_trial_false(self):
        """Тест is_trial для полной лицензии."""
        info = LicenseInfo(status=LicenseStatus.VALID)
        assert info.is_trial is False

    def test_is_full_license(self):
        """Тест is_full_license."""
        info = LicenseInfo(status=LicenseStatus.VALID)
        assert info.is_full_license is True

        info = LicenseInfo(status=LicenseStatus.TRIAL)
        assert info.is_full_license is False
