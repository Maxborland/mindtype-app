"""
Тесты для модуля updater.

Тестирует:
- Проверку обновлений с fallback
- Сравнение версий
- Валидацию URL скачивания
"""

import json
import sys
import base64
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import urllib.error

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


UPDATE_SIGNER = "CN=MindType"


def signed_update_payload(version="1.2.0", release_notes="New features"):
    private_key = Ed25519PrivateKey.generate()
    public = private_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    )
    public_text = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
    manifest = {
        "schema_version": "1.0",
        "channel": "stable",
        "version": version,
        "platform": "windows",
        "architecture": "x86_64",
        "minimum_supported_version": "0.9.0",
        "url": (
            f"https://releases.mindtype.space/"
            f"MindType-{version}-Setup.exe"
        ),
        "sha256": "a" * 64,
        "size": 53_000_000,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "rollout_percentage": 100,
        "authenticode_signer": UPDATE_SIGNER,
        "release_notes": release_notes,
    }
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = base64.urlsafe_b64encode(
        private_key.sign(canonical)
    ).rstrip(b"=").decode("ascii")
    return {"manifest": manifest, "signature": signature}, public_text


def trusted_updater(**kwargs):
    from app.updater import Updater

    _payload, public_key = signed_update_payload()
    return Updater(
        update_public_key=public_key,
        expected_signer=UPDATE_SIGNER,
        rollout_device_id="test-device",
        **kwargs,
    )


class TestUpdaterVersionComparison:
    """Тесты для сравнения версий."""

    def test_newer_version_detected(self):
        """Новая версия должна определяться корректно."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")

        assert updater._is_newer("1.1.0", "1.0.0") is True
        assert updater._is_newer("2.0.0", "1.9.9") is True
        assert updater._is_newer("1.0.1", "1.0.0") is True

    def test_same_version_not_newer(self):
        """Одинаковые версии не должны считаться новее."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")

        assert updater._is_newer("1.0.0", "1.0.0") is False

    def test_older_version_not_newer(self):
        """Старая версия не должна считаться новее."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")

        assert updater._is_newer("0.9.0", "1.0.0") is False
        assert updater._is_newer("1.0.0", "1.0.1") is False

    def test_version_with_different_parts(self):
        """Версии с разным количеством частей."""
        from app.updater import Updater

        updater = Updater(current_version="1.0")

        assert updater._is_newer("1.0.1", "1.0") is True
        assert updater._is_newer("1.1", "1.0.0") is True


class TestUpdaterCheckForUpdates:
    """Тесты для check_for_updates."""

    def test_check_updates_primary_success(self):
        """Успешная проверка через основной URL."""
        from app.updater import Updater

        mock_response = MagicMock()
        mock_response.status = 200
        payload, public_key = signed_update_payload()
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="test-device",
        )

        with patch('urllib.request.urlopen', return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is True
        assert info.version == "1.2.0"
        assert info.error is None

    def test_check_updates_fallback_on_primary_failure(self):
        """Fallback на GitHub при недоступности основного сервера."""
        from app.updater import Updater

        call_count = [0]

        payload, public_key = signed_update_payload(
            version="1.1.0",
            release_notes="Fallback release",
        )

        def mock_urlopen(request, timeout=None):
            call_count[0] += 1
            url = request.full_url if hasattr(request, 'full_url') else str(request)

            # Первый вызов (primary) - ошибка
            if call_count[0] == 1:
                raise urllib.error.URLError("Connection refused")

            # Второй вызов (fallback) - успех
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = json.dumps(payload).encode(
                "utf-8"
            )
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="test-device",
        )

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            info = updater.check_for_updates()

        assert call_count[0] == 2  # Оба URL были опробованы
        assert info.available is True
        assert info.version == "1.1.0"
        assert info.error is None

    def test_check_updates_all_sources_fail(self):
        """Ошибка когда все источники недоступны."""
        from app.updater import Updater

        updater = trusted_updater(current_version="1.0.0")

        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Network error")
            info = updater.check_for_updates()

        assert info.available is False
        assert info.error is not None
        assert "Сетевая ошибка" in info.error or "Network" in info.error

    def test_check_updates_no_update_available(self):
        """Нет доступных обновлений."""
        from app.updater import Updater

        mock_response = MagicMock()
        mock_response.status = 200
        payload, public_key = signed_update_payload(
            version="1.0.0",
            release_notes="Current version",
        )
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="test-device",
        )

        with patch('urllib.request.urlopen', return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is False
        assert info.version == "1.0.0"
        assert info.error is None

    def test_missing_embedded_trust_root_does_not_touch_network(self):
        from app.updater import Updater

        updater = Updater(
            current_version="1.0.0",
            update_public_key="",
            expected_signer="",
        )

        with patch("urllib.request.urlopen") as urlopen:
            info = updater.check_for_updates()

        assert info.available is False
        assert "доверенного ключа" in info.error
        urlopen.assert_not_called()

    def test_tampered_manifest_is_not_shown_as_update(self):
        from app.updater import Updater

        payload, public_key = signed_update_payload()
        payload["manifest"]["release_notes"] = "Install malware"
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="test-device",
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is False
        assert "Недоверенный manifest" in info.error


class TestUpdaterDownloadValidation:
    """Тесты для валидации скачивания."""

    def test_download_is_disabled_before_any_network_or_file_access(self):
        """Отключённый updater не должен даже начинать загрузку."""
        from app.updater import AUTOMATIC_UPDATE_DISABLED_MESSAGE, Updater

        updater = Updater(current_version="1.0.0")
        updater.latest_info = {
            "version": "1.1.0",
            "platforms": {
                "windows": {
                    "url": "https://mindtype.space/MindType_Setup.exe",
                    "sha256": "a" * 64,
                }
            },
        }

        with (
            patch.object(updater, "get_download_info") as get_download_info,
            patch("urllib.request.urlretrieve") as urlretrieve,
        ):
            success, path, error = updater.download_update()

        assert (success, path, error) == (
            False,
            None,
            AUTOMATIC_UPDATE_DISABLED_MESSAGE,
        )
        get_download_info.assert_not_called()
        urlretrieve.assert_not_called()

class TestUpdaterInstallationDisabled:
    """Автоматический запуск установщика закрыт до появления корня доверия."""

    def test_install_is_disabled_without_process_or_exit(self, tmp_path):
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")
        updater._temp_path = tmp_path / "MindType_Setup.exe"
        updater._temp_path.write_bytes(b"untrusted installer")

        with (
            patch("subprocess.Popen") as popen,
            patch("sys.exit") as exit_app,
        ):
            installed = updater.install_update()

        assert installed is False
        popen.assert_not_called()
        exit_app.assert_not_called()


class TestUpdaterGetDownloadInfo:
    """Тесты для get_download_info."""

    def test_get_download_info_windows(self):
        """Получение URL для Windows."""
        from app.updater import Updater

        updater = Updater()
        updater.latest_info = {
            "platforms": {
                "windows": {
                    "url": "https://example.com/setup.exe",
                    "sha256": "abc123"
                }
            }
        }

        with patch('sys.platform', 'win32'):
            url, sha256 = updater.get_download_info()

        assert url == "https://example.com/setup.exe"
        assert sha256 == "abc123"

    def test_get_download_info_macos(self):
        """Получение URL для macOS."""
        from app.updater import Updater

        updater = Updater()
        updater.latest_info = {
            "platforms": {
                "macos": {
                    "url": "https://example.com/app.dmg",
                    "sha256": "def456"
                }
            }
        }

        with patch('sys.platform', 'darwin'):
            url, sha256 = updater.get_download_info()

        assert url == "https://example.com/app.dmg"
        assert sha256 == "def456"

    def test_get_download_info_linux(self):
        """Получение URL для Linux."""
        from app.updater import Updater

        updater = Updater()
        updater.latest_info = {
            "platforms": {
                "linux": {
                    "url": "https://example.com/app.AppImage",
                    "sha256": "ghi789"
                }
            }
        }

        with patch('sys.platform', 'linux'):
            url, sha256 = updater.get_download_info()

        assert url == "https://example.com/app.AppImage"
        assert sha256 == "ghi789"

    def test_get_download_info_no_data(self):
        """Возврат None когда нет данных."""
        from app.updater import Updater

        updater = Updater()
        updater.latest_info = None

        url, sha256 = updater.get_download_info()

        assert url is None
        assert sha256 is None


class TestUpdaterConstants:
    """Тесты для констант и конфигурации."""

    def test_version_urls_defined(self):
        """VERSION_URLS должен быть определён."""
        from app.updater import VERSION_URLS

        assert isinstance(VERSION_URLS, list)
        assert len(VERSION_URLS) >= 2  # Primary + fallback

    def test_primary_url_is_own_api(self):
        """Основной URL должен быть своим API."""
        from app.updater import PRIMARY_VERSION_URL

        assert "mindtype" in PRIMARY_VERSION_URL.lower() or "localhost" in PRIMARY_VERSION_URL.lower()

    def test_fallback_url_is_github(self):
        """Fallback URL должен быть GitHub."""
        from app.updater import FALLBACK_VERSION_URL

        assert "github" in FALLBACK_VERSION_URL.lower()
