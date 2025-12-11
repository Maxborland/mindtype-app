"""
Общие fixtures для тестов MindType.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Добавляем путь к app для импорта модулей
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_dir():
    """Временная директория для тестов."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_data_dir(temp_dir):
    """Мок директории данных приложения."""
    data_dir = temp_dir / "MindType"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def sample_license_key():
    """Пример валидного лицензионного ключа."""
    return "ABCD-EFGH-JKMN-PQRS"


@pytest.fixture
def sample_device_id():
    """Пример ID устройства."""
    return "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"


@pytest.fixture
def mock_api_response_success():
    """Успешный ответ API валидации лицензии."""
    return {
        "valid": True,
        "plan": "personal",
        "email": "test@example.com",
        "expiresAt": "2025-12-31T23:59:59Z",
        "activatedDevices": 1,
        "maxDevices": 2,
        "message": "activation_success"
    }


@pytest.fixture
def mock_api_response_invalid():
    """Ответ API для невалидной лицензии."""
    return {
        "valid": False,
        "error": "not_found",
        "message": "License key not found"
    }


@pytest.fixture
def mock_api_response_device_limit():
    """Ответ API при превышении лимита устройств."""
    return {
        "valid": False,
        "error": "device_limit",
        "message": "Maximum devices reached",
        "activatedDevices": 2,
        "maxDevices": 2
    }


@pytest.fixture
def mock_license_data():
    """Данные закэшированной лицензии."""
    return {
        "license_key": "ABCDEFGHJKMNPQRS",
        "device_id": "test_device_123",
        "plan": "personal",
        "email": "test@example.com",
        "validated_at": "2024-01-01T12:00:00",
        "expires_at": "2025-12-31T23:59:59Z",
        "activated_devices": 1,
        "max_devices": 2
    }


@pytest.fixture
def mock_trial_data():
    """Данные trial периода."""
    return {
        "start_date": "2024-01-01T00:00:00",
        "transcription_seconds": 0.0
    }


# Мок для HTTP запросов
@pytest.fixture
def mock_urllib():
    """Мок для urllib.request."""
    with patch('urllib.request.urlopen') as mock:
        yield mock


# Мок для env модуля
@pytest.fixture
def mock_env():
    """Мок для переменных окружения."""
    env_mock = MagicMock()
    env_mock.API_BASE_URL = "http://localhost:3000"
    env_mock.API_TIMEOUT = 30
    env_mock.LICENSE_HMAC_SECRET = "test_secret_key"
    env_mock.LICENSE_REVALIDATION_INTERVAL = 604800
    env_mock.APP_VERSION = "1.0.0"
    return env_mock

