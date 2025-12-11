"""
Integration тесты для взаимодействия с License API.
Тестируют полный цикл: активация -> ревалидация -> деактивация.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import urllib.request
import urllib.error

import pytest

from app.licensing.license_manager import (
    LicenseManager,
    LicenseStatus,
    ValidationResult,
    _sign_data,
)
from app.licensing.key_validator import generate_license_key


def mock_urlopen_response(json_data, status=200):
    """Helper для создания mock response."""
    response = Mock()
    response.read.return_value = json.dumps(json_data).encode('utf-8')
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


@pytest.fixture
def temp_data_dir(tmp_path):
    """Временная директория для данных."""
    data_dir = tmp_path / "MindType"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def license_manager(temp_data_dir):
    """LicenseManager с временной директорией."""
    with patch('app.licensing.license_manager._get_data_dir', return_value=temp_data_dir):
        with patch('app.licensing.trial._get_data_dir', return_value=temp_data_dir):
            manager = LicenseManager()
    return manager


class TestFullActivationCycle:
    """Тесты полного цикла активации лицензии."""

    def test_activation_to_deactivation_cycle(self, license_manager):
        """Тест полного цикла: активация -> проверка -> деактивация."""
        license_key = generate_license_key()

        # Шаг 1: Активация
        activation_response = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + "Z",
            "activatedDevices": 1,
            "maxDevices": 2,
            "message": "activation_success"
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.SUCCESS
        assert license_manager._license_data is not None

        # Шаг 2: Проверка статуса
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.VALID
        assert info.is_full_license is True
        assert info.plan == "personal"
        assert info.email == "test@example.com"

        # Шаг 3: Деактивация
        deactivation_response = {"success": True}

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(deactivation_response)):
            success, message = license_manager.deactivate_online()

        assert success is True
        assert license_manager._license_data is None

        # Шаг 4: Статус после деактивации - trial
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.TRIAL

    def test_activation_revalidation_cycle(self, license_manager, temp_data_dir):
        """Тест цикла: активация -> ревалидация."""
        license_key = generate_license_key()

        # Шаг 1: Активация
        activation_response = {
            "valid": True,
            "plan": "pro",
            "email": "pro@example.com",
            "expiresAt": None,  # Lifetime
            "activatedDevices": 1,
            "maxDevices": 3,
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result, _, _ = license_manager.activate_online(license_key)

        assert result == ValidationResult.SUCCESS

        # Шаг 2: Модифицируем дату валидации чтобы требовалась ревалидация
        # Нужно сохранить данные без подписи, потом добавить подпись
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        data_without_sig = {k: v for k, v in license_manager._license_data.items() if k != "_signature"}
        data_without_sig["validated_at"] = old_date
        signature = _sign_data(data_without_sig)
        data_without_sig["_signature"] = signature

        # Сохраняем напрямую в файл
        import json
        with open(license_manager._license_file, "w", encoding="utf-8") as f:
            json.dump(data_without_sig, f)

        # Перезагружаем
        license_manager._load_license()

        # Шаг 3: Проверяем что нужна ревалидация
        assert license_manager.needs_revalidation() is True

        # Шаг 4: Ревалидация
        revalidation_response = {
            "valid": True,
            "plan": "pro",
            "email": "pro@example.com",
            "expiresAt": None,
            "activatedDevices": 1,
            "maxDevices": 3,
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(revalidation_response)):
            result = license_manager.revalidate_if_needed()

        assert result == ValidationResult.SUCCESS
        assert license_manager.needs_revalidation() is False


class TestActivationErrorHandling:
    """Тесты обработки ошибок при активации."""

    def test_activation_license_not_found(self, license_manager):
        """Тест активации несуществующей лицензии."""
        license_key = generate_license_key()

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
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.NOT_FOUND
        assert license_manager._license_data is None  # Лицензия не сохранена

    def test_activation_device_limit_exceeded(self, license_manager):
        """Тест превышения лимита устройств."""
        license_key = generate_license_key()

        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "device_limit",
            "message": "Maximum devices (2) reached",
            "activatedDevices": 2,
            "maxDevices": 2
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.DEVICE_LIMIT

    def test_activation_expired_license(self, license_manager):
        """Тест истёкшей лицензии."""
        license_key = generate_license_key()

        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "expired",
            "message": "This license has expired"
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.EXPIRED

    def test_activation_deactivated_license(self, license_manager):
        """Тест деактивированной лицензии."""
        license_key = generate_license_key()

        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "deactivated",
            "message": "This license has been deactivated"
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.DEACTIVATED

    def test_activation_rate_limited(self, license_manager):
        """Тест rate limiting."""
        license_key = generate_license_key()

        error_response = Mock()
        error_response.read.return_value = json.dumps({
            "valid": False,
            "error": "rate_limit_exceeded",
            "message": "Too many requests"
        }).encode('utf-8')

        http_error = urllib.error.HTTPError(
            url="http://localhost:3000/api/license/validate",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=error_response
        )

        with patch('urllib.request.urlopen', side_effect=http_error):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.RATE_LIMITED


class TestNetworkErrorHandling:
    """Тесты обработки сетевых ошибок."""

    def test_activation_network_error(self, license_manager):
        """Тест ошибки сети при активации."""
        license_key = generate_license_key()

        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError("Connection refused")):
            result, message, data = license_manager.activate_online(license_key)

        assert result == ValidationResult.NETWORK_ERROR

    def test_deactivation_network_error(self, license_manager):
        """Тест ошибки сети при деактивации."""
        # Сначала создаём локальную лицензию
        license_manager._license_data = {
            "license_key": "TESTKEY1234567890",
            "device_id": license_manager.get_device_id(),
            "validated_at": datetime.now().isoformat(),
        }
        license_manager._save_license()

        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError("Connection refused")):
            success, message = license_manager.deactivate_online()

        assert success is False
        assert message == "network_error"


class TestOfflineMode:
    """Тесты оффлайн режима."""

    def test_offline_activation(self, license_manager):
        """Тест оффлайн активации."""
        license_key = generate_license_key()

        success, message = license_manager.activate(license_key, online=False)

        assert success is True
        assert license_manager._license_data is not None
        assert license_manager._license_data.get("offline_activation") is True

    def test_offline_with_cached_license(self, license_manager):
        """Тест работы с кэшированной лицензией без сети."""
        # Активируем онлайн
        activation_response = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + "Z",
            "activatedDevices": 1,
            "maxDevices": 2,
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result, _, _ = license_manager.activate_online(generate_license_key())

        assert result == ValidationResult.SUCCESS

        # Проверяем что кэшированная лицензия работает без сети
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.VALID
        assert info.is_active is True


class TestTrialWithLicenseInteraction:
    """Тесты взаимодействия trial и лицензии."""

    def test_trial_to_license_upgrade(self, license_manager):
        """Тест перехода с trial на полную лицензию."""
        # Запускаем trial
        has_access, info = license_manager.check_access()
        assert has_access is True
        assert info.status == LicenseStatus.TRIAL

        # Добавляем время транскрипции
        license_manager.add_transcription_time(60)

        # Активируем лицензию
        activation_response = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + "Z",
            "activatedDevices": 1,
            "maxDevices": 2,
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result, _, _ = license_manager.activate_online(generate_license_key())

        assert result == ValidationResult.SUCCESS

        # Проверяем что теперь полная лицензия
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.VALID
        assert info.is_full_license is True

    def test_deactivation_returns_to_trial(self, license_manager):
        """Тест возврата к trial после деактивации."""
        # Активируем лицензию
        activation_response = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + "Z",
            "activatedDevices": 1,
            "maxDevices": 2,
        }

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            license_manager.activate_online(generate_license_key())

        # Деактивируем
        deactivation_response = {"success": True}

        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(deactivation_response)):
            license_manager.deactivate_online()

        # Проверяем что вернулись к trial
        info = license_manager.get_license_info()
        assert info.status == LicenseStatus.TRIAL


class TestMultipleActivations:
    """Тесты множественных активаций."""

    def test_reactivation_same_key(self, license_manager):
        """Тест повторной активации того же ключа."""
        license_key = generate_license_key()

        activation_response = {
            "valid": True,
            "plan": "personal",
            "email": "test@example.com",
            "expiresAt": (datetime.now() + timedelta(days=365)).isoformat() + "Z",
            "activatedDevices": 1,
            "maxDevices": 2,
        }

        # Первая активация
        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result1, _, _ = license_manager.activate_online(license_key)

        assert result1 == ValidationResult.SUCCESS

        # Повторная активация того же ключа
        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response)):
            result2, _, _ = license_manager.activate_online(license_key)

        assert result2 == ValidationResult.SUCCESS

    def test_activation_different_key_replaces(self, license_manager):
        """Тест что новый ключ заменяет старый."""
        key1 = generate_license_key()
        key2 = generate_license_key()

        activation_response_1 = {
            "valid": True,
            "plan": "personal",
            "email": "user1@example.com",
            "activatedDevices": 1,
            "maxDevices": 2,
        }

        activation_response_2 = {
            "valid": True,
            "plan": "pro",
            "email": "user2@example.com",
            "activatedDevices": 1,
            "maxDevices": 3,
        }

        # Активация первого ключа
        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response_1)):
            license_manager.activate_online(key1)

        info1 = license_manager.get_license_info()
        assert info1.plan == "personal"

        # Активация второго ключа
        with patch('urllib.request.urlopen', return_value=mock_urlopen_response(activation_response_2)):
            license_manager.activate_online(key2)

        info2 = license_manager.get_license_info()
        assert info2.plan == "pro"
        assert info2.email == "user2@example.com"

