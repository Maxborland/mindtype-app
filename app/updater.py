"""
Система автоматических обновлений приложения.
Проверка, скачивание и установка обновлений.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Tuple
from enum import Enum


class UpdateStatus(Enum):
    """Статус проверки обновлений."""
    CHECKING = "checking"
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    DOWNLOADING = "downloading"
    READY = "ready"
    ERROR = "error"


@dataclass
class UpdateInfo:
    """Информация об обновлении."""
    available: bool
    version: Optional[str] = None
    current_version: Optional[str] = None
    download_url: Optional[str] = None
    sha256: Optional[str] = None
    release_notes: Optional[str] = None
    file_size: Optional[int] = None
    mandatory: bool = False
    published_at: Optional[datetime] = None
    error: Optional[str] = None


def _get_config():
    """Получить конфигурацию из env модуля."""
    try:
        from .env import (
            API_BASE_URL,
            API_TIMEOUT,
            APP_VERSION,
            PLATFORM,
            UPDATE_AUTO_CHECK,
            UPDATE_AUTO_DOWNLOAD,
        )
        return {
            "api_base_url": API_BASE_URL,
            "api_timeout": API_TIMEOUT,
            "app_version": APP_VERSION,
            "platform": PLATFORM,
            "auto_check": UPDATE_AUTO_CHECK,
            "auto_download": UPDATE_AUTO_DOWNLOAD,
        }
    except ImportError:
        return {
            "api_base_url": "http://localhost:3000",
            "api_timeout": 30,
            "app_version": "1.0.0",
            "platform": sys.platform,
            "auto_check": True,
            "auto_download": False,
        }


def _get_data_dir() -> Path:
    """Получить директорию для хранения обновлений."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

    updates_dir = base / "MindType" / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    return updates_dir


class Updater:
    """
    Менеджер обновлений приложения.

    Функции:
    - Проверка наличия новых версий
    - Скачивание обновлений с проверкой SHA256
    - Запуск установщика и закрытие приложения
    """

    def __init__(self):
        self._config = _get_config()
        self._update_info: Optional[UpdateInfo] = None
        self._download_path: Optional[Path] = None
        self._status = UpdateStatus.NOT_AVAILABLE

    @property
    def status(self) -> UpdateStatus:
        """Текущий статус обновления."""
        return self._status

    @property
    def update_info(self) -> Optional[UpdateInfo]:
        """Информация о доступном обновлении."""
        return self._update_info

    @property
    def current_version(self) -> str:
        """Текущая версия приложения."""
        return self._config["app_version"]

    def check_for_updates(self) -> UpdateInfo:
        """
        Проверить наличие обновлений.

        Returns:
            UpdateInfo с информацией об обновлении
        """
        self._status = UpdateStatus.CHECKING

        config = self._config
        url = (
            f"{config['api_base_url'].rstrip('/')}/api/updates/latest"
            f"?platform={config['platform']}"
            f"&current_version={config['app_version']}"
        )

        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': f'MindType/{config["app_version"]}'},
                method='GET'
            )

            with urllib.request.urlopen(req, timeout=config['api_timeout']) as response:
                data = json.loads(response.read().decode('utf-8'))

            if data.get('available'):
                published_at = None
                if data.get('publishedAt'):
                    try:
                        published_at = datetime.fromisoformat(
                            data['publishedAt'].replace('Z', '+00:00')
                        )
                    except Exception:
                        pass

                self._update_info = UpdateInfo(
                    available=True,
                    version=data.get('version'),
                    current_version=data.get('currentVersion', config['app_version']),
                    download_url=data.get('downloadUrl'),
                    sha256=data.get('sha256'),
                    release_notes=data.get('releaseNotes'),
                    file_size=data.get('fileSize'),
                    mandatory=data.get('mandatory', False),
                    published_at=published_at,
                )
                self._status = UpdateStatus.AVAILABLE
            else:
                self._update_info = UpdateInfo(
                    available=False,
                    current_version=config['app_version'],
                )
                self._status = UpdateStatus.NOT_AVAILABLE

            return self._update_info

        except urllib.error.URLError as e:
            self._update_info = UpdateInfo(
                available=False,
                error="network_error",
            )
            self._status = UpdateStatus.ERROR
            return self._update_info

        except Exception as e:
            self._update_info = UpdateInfo(
                available=False,
                error=str(e),
            )
            self._status = UpdateStatus.ERROR
            return self._update_info

    def download_update(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Скачать обновление.

        Args:
            progress_callback: Функция (downloaded_bytes, total_bytes)

        Returns:
            Tuple (success, file_path, error_message)
        """
        if not self._update_info or not self._update_info.available:
            return False, None, "no_update_available"

        if not self._update_info.download_url:
            return False, None, "no_download_url"

        self._status = UpdateStatus.DOWNLOADING

        try:
            # Определяем имя файла
            url = self._update_info.download_url
            filename = url.split('/')[-1]
            if not filename or '.' not in filename:
                # Если имя файла некорректное, генерируем своё
                ext = '.exe' if sys.platform == 'win32' else '.dmg' if sys.platform == 'darwin' else '.AppImage'
                filename = f"MindType-{self._update_info.version}{ext}"

            download_path = _get_data_dir() / filename

            # Скачиваем файл
            req = urllib.request.Request(
                url,
                headers={'User-Agent': f'MindType/{self._config["app_version"]}'},
            )

            with urllib.request.urlopen(req, timeout=300) as response:
                total_size = response.getheader('Content-Length')
                total_size = int(total_size) if total_size else self._update_info.file_size or 0

                downloaded = 0
                chunk_size = 8192

                with open(download_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback:
                            progress_callback(downloaded, total_size)

            # Проверяем SHA256
            if self._update_info.sha256:
                sha256_hash = hashlib.sha256()
                with open(download_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha256_hash.update(chunk)

                calculated_hash = sha256_hash.hexdigest()
                expected_hash = self._update_info.sha256.lower()

                if calculated_hash != expected_hash:
                    download_path.unlink(missing_ok=True)
                    self._status = UpdateStatus.ERROR
                    return False, None, "checksum_mismatch"

            self._download_path = download_path
            self._status = UpdateStatus.READY
            return True, download_path, None

        except urllib.error.URLError:
            self._status = UpdateStatus.ERROR
            return False, None, "network_error"

        except Exception as e:
            self._status = UpdateStatus.ERROR
            return False, None, str(e)

    def install_update(self) -> bool:
        """
        Запустить установщик и закрыть приложение.

        Returns:
            True если установщик запущен успешно
        """
        if not self._download_path or not self._download_path.exists():
            return False

        try:
            if sys.platform == 'win32':
                # Windows: запускаем установщик
                # Используем START для запуска в отдельном процессе
                os.startfile(str(self._download_path))

            elif sys.platform == 'darwin':
                # macOS: открываем DMG
                subprocess.Popen(['open', str(self._download_path)])

            else:
                # Linux: запускаем AppImage
                self._download_path.chmod(0o755)
                subprocess.Popen([str(self._download_path)])

            # Выходим из текущего приложения
            # Даём время на запуск установщика
            import time
            time.sleep(1)

            # Закрываем приложение
            sys.exit(0)

        except Exception as e:
            print(f"Error launching installer: {e}")
            return False

        return True

    def cleanup(self) -> None:
        """Очистить скачанные файлы."""
        if self._download_path and self._download_path.exists():
            try:
                self._download_path.unlink()
            except Exception:
                pass

        # Очищаем старые файлы обновлений
        updates_dir = _get_data_dir()
        try:
            for file in updates_dir.iterdir():
                if file.is_file():
                    try:
                        file.unlink()
                    except Exception:
                        pass
        except Exception:
            pass


# Глобальный экземпляр
_updater: Optional[Updater] = None


def get_updater() -> Updater:
    """Получить глобальный экземпляр Updater."""
    global _updater
    if _updater is None:
        _updater = Updater()
    return _updater


# Для тестирования
if __name__ == "__main__":
    print("=== MindType Updater Test ===\n")

    updater = Updater()
    print(f"Current version: {updater.current_version}")
    print(f"Checking for updates...")

    info = updater.check_for_updates()

    if info.error:
        print(f"Error: {info.error}")
    elif info.available:
        print(f"\nUpdate available!")
        print(f"  Version: {info.version}")
        print(f"  Download URL: {info.download_url}")
        print(f"  SHA256: {info.sha256}")
        print(f"  File size: {info.file_size} bytes")
        print(f"  Mandatory: {info.mandatory}")
        print(f"  Release notes: {info.release_notes}")
    else:
        print("\nNo updates available. You're on the latest version!")

