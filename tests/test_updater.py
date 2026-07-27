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


def signed_update_payload(
    version="1.2.0",
    release_notes="New features",
    minimum_supported_version="0.9.0",
    rollout_percentage=100,
):
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
        "minimum_supported_version": minimum_supported_version,
        "url": (
            f"https://releases.mindtype.space/"
            f"MindType-{version}-Setup.exe"
        ),
        "sha256": "a" * 64,
        "size": 53_000_000,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "rollout_percentage": rollout_percentage,
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

    def test_check_updates_does_not_fall_back_to_untrusted_source(self):
        """A network failure must not downgrade to stale unsigned metadata."""
        from app.updater import Updater

        call_count = [0]
        _, public_key = signed_update_payload(version="1.1.0")

        def mock_urlopen(request, timeout=None):
            call_count[0] += 1
            raise urllib.error.URLError("Connection refused")

        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="test-device",
        )

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            info = updater.check_for_updates()

        assert call_count[0] == 1
        assert info.available is False
        assert "Connection refused" in (info.error or "")

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

    def test_below_minimum_version_bypasses_staged_rollout(self):
        from app.updater import Updater

        mock_response = MagicMock()
        payload, public_key = signed_update_payload(
            version="1.2.0",
            minimum_supported_version="1.1.0",
            rollout_percentage=0,
        )
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="excluded-device",
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is True

    def test_supported_version_still_respects_staged_rollout(self):
        from app.updater import Updater

        mock_response = MagicMock()
        payload, public_key = signed_update_payload(
            version="1.2.0",
            minimum_supported_version="0.9.0",
            rollout_percentage=0,
        )
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(payload).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            rollout_device_id="excluded-device",
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is False

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

    def test_oversized_manifest_response_is_rejected(self):
        from app.updater import MAX_UPDATE_MANIFEST_BYTES, Updater

        _, public_key = signed_update_payload()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b"x" * (
            MAX_UPDATE_MANIFEST_BYTES + 1
        )
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
        )

        with patch(
            "urllib.request.urlopen",
            return_value=mock_response,
        ):
            info = updater.check_for_updates()

        assert info.available is False
        assert "too large" in (info.error or "")


class TestUpdaterDownloadValidation:
    """Тесты для валидации скачивания."""

    def test_download_requires_a_verified_manifest(self, tmp_path):
        from app.updater import AUTOMATIC_UPDATE_DISABLED_MESSAGE

        updater = trusted_updater(
            current_version="1.0.0",
            update_directory=tmp_path,
        )

        with patch(
            "app.updater.download_verified_installer"
        ) as download:
            result = updater.download_update()

        assert result == (
            False,
            None,
            AUTOMATIC_UPDATE_DISABLED_MESSAGE,
        )
        download.assert_not_called()

    def test_download_uses_only_the_verified_manifest(self, tmp_path):
        from app.update_manifest import verify_update_manifest
        from app.updater import Updater

        payload, public_key = signed_update_payload()
        manifest = verify_update_manifest(
            payload,
            public_key=public_key,
            expected_channel="stable",
            expected_platform="windows",
            expected_architecture="x86_64",
            expected_signer=UPDATE_SIGNER,
            allowed_hosts={"releases.mindtype.space"},
        )
        updater = Updater(
            current_version="1.0.0",
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
            update_directory=tmp_path,
        )
        updater.verified_manifest = manifest
        expected = tmp_path / "MindType-1.2.0-Setup.exe"
        callback = MagicMock()

        with patch(
            "app.updater.download_verified_installer",
            return_value=expected,
        ) as download:
            result = updater.download_update(callback)

        assert result == (True, expected, None)
        assert updater._temp_path == expected
        download.assert_called_once_with(
            manifest,
            expected,
            allowed_hosts=updater._allowed_download_hosts,
            progress_callback=callback,
        )


class TestUpdaterInstallation:
    """The installer is authenticated again immediately before execution."""

    def test_install_fails_closed_without_verified_manifest(self, tmp_path):
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")
        updater._temp_path = tmp_path / "MindType_Setup.exe"
        updater._temp_path.write_bytes(b"untrusted installer")

        with patch("subprocess.Popen") as popen:
            installed = updater.install_update()

        assert installed is False
        popen.assert_not_called()

    def test_install_reverifies_and_launches_without_shell(self, tmp_path):
        from app.update_manifest import verify_update_manifest
        from app.updater import Updater

        payload, public_key = signed_update_payload()
        manifest = verify_update_manifest(
            payload,
            public_key=public_key,
            expected_channel="stable",
            expected_platform="windows",
            expected_architecture="x86_64",
            expected_signer=UPDATE_SIGNER,
            allowed_hosts={"releases.mindtype.space"},
        )
        installer = tmp_path / "MindType-1.2.0-Setup.exe"
        installer.write_bytes(b"signed installer")
        updater = Updater(
            update_public_key=public_key,
            expected_signer=UPDATE_SIGNER,
        )
        updater.verified_manifest = manifest
        updater._temp_path = installer

        with (
            patch("app.updater.verify_downloaded_installer") as verify,
            patch("app.updater.subprocess.Popen") as popen,
        ):
            installed = updater.install_update()

        assert installed is True
        verify.assert_called_once_with(installer, manifest)
        args, kwargs = popen.call_args
        assert args[0] == [str(installer.resolve())]
        assert kwargs.get("shell", False) is False


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
        """Only endpoints serving the signed envelope belong in the trust chain."""
        from app.updater import PRIMARY_VERSION_URL, VERSION_URLS

        assert isinstance(VERSION_URLS, list)
        assert VERSION_URLS == [PRIMARY_VERSION_URL]

    def test_primary_url_is_own_api(self):
        """Основной URL должен быть своим API."""
        from app.updater import PRIMARY_VERSION_URL

        assert "mindtype" in PRIMARY_VERSION_URL.lower() or "localhost" in PRIMARY_VERSION_URL.lower()

    def test_broken_unsigned_github_fallback_is_not_configured(self):
        from app import updater

        assert not hasattr(updater, "FALLBACK_VERSION_URL")
        assert "raw.githubusercontent.com" not in "\n".join(updater.VERSION_URLS)
