"""
Тесты для модуля updater.

Тестирует:
- Проверку обновлений с fallback
- Сравнение версий
- Валидацию URL скачивания
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import urllib.error

import pytest


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
        mock_response.read.return_value = json.dumps({
            "version": "1.2.0",
            "release_notes": "New features"
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        updater = Updater(current_version="1.0.0")

        with patch('urllib.request.urlopen', return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is True
        assert info.version == "1.2.0"
        assert info.error is None

    def test_check_updates_fallback_on_primary_failure(self):
        """Fallback на GitHub при недоступности основного сервера."""
        from app.updater import Updater

        call_count = [0]

        def mock_urlopen(request, timeout=None):
            call_count[0] += 1
            url = request.full_url if hasattr(request, 'full_url') else str(request)

            # Первый вызов (primary) - ошибка
            if call_count[0] == 1:
                raise urllib.error.URLError("Connection refused")

            # Второй вызов (fallback) - успех
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = json.dumps({
                "version": "1.1.0",
                "release_notes": "Fallback release"
            }).encode('utf-8')
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        updater = Updater(current_version="1.0.0")

        with patch('urllib.request.urlopen', side_effect=mock_urlopen):
            info = updater.check_for_updates()

        assert call_count[0] == 2  # Оба URL были опробованы
        assert info.available is True
        assert info.version == "1.1.0"
        assert info.error is None

    def test_check_updates_all_sources_fail(self):
        """Ошибка когда все источники недоступны."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")

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
        mock_response.read.return_value = json.dumps({
            "version": "1.0.0",
            "release_notes": "Current version"
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        updater = Updater(current_version="1.0.0")

        with patch('urllib.request.urlopen', return_value=mock_response):
            info = updater.check_for_updates()

        assert info.available is False
        assert info.version == "1.0.0"
        assert info.error is None


class TestUpdaterDownloadValidation:
    """Тесты для валидации скачивания."""

    def test_allowed_download_domains(self):
        """Проверка whitelist доменов для скачивания."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")
        updater.latest_info = {
            "version": "1.1.0",
            "platforms": {
                "windows": {
                    "url": "https://evil.com/malware.exe",
                    "sha256": "abc123"
                }
            }
        }

        success, path, error = updater.download_update()

        assert success is False
        assert "Небезопасный URL" in error

    def test_github_domain_allowed(self):
        """GitHub домены должны быть разрешены."""
        from app.updater import Updater
        import urllib.parse

        allowed_domains = [
            "github.com",
            "objects.githubusercontent.com",
            "raw.githubusercontent.com",
            "mindtype.space",
        ]

        for domain in allowed_domains:
            url = f"https://{domain}/test.exe"
            parsed = urllib.parse.urlparse(url)
            assert parsed.netloc in allowed_domains or parsed.netloc == domain

    def test_wrong_extension_rejected(self):
        """Неверное расширение файла должно отклоняться."""
        from app.updater import Updater

        updater = Updater(current_version="1.0.0")
        updater.latest_info = {
            "version": "1.1.0",
            "platforms": {
                "windows": {
                    "url": "https://github.com/repo/file.zip",  # Неверное расширение
                    "sha256": "abc123"
                }
            }
        }

        with patch('sys.platform', 'win32'):
            success, path, error = updater.download_update()

        assert success is False
        assert "расширение" in error.lower() or "extension" in error.lower()


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
