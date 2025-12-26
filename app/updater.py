import os
import sys
import json
import logging
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable
from enum import Enum, auto
from .version import __version__, __channel__

logger = logging.getLogger("mindtype.updater")

# URL репозитория на GitHub
GITHUB_REPO = "wispr-flow-clone/mindtype"
VERSION_FILE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"

class UpdateStatus(Enum):
    IDLE = auto()
    CHECKING = auto()
    AVAILABLE = auto()
    DOWNLOADING = auto()
    READY = auto()
    ERROR = auto()

class UpdateInfo:
    """Информация об обновлении."""
    def __init__(self):
        self.available: bool = False
        self.version: str = ""
        self.release_notes: str = ""
        self.error: Optional[str] = None

class Updater:
    """
    Класс для управления процессом обновления приложения.
    """
    def __init__(self, current_version: str = __version__, channel: str = __channel__):
        self.current_version = current_version
        self.channel = channel
        self.latest_info: Optional[Dict[str, Any]] = None
        self._temp_path: Optional[Path] = None

    def check_for_updates(self) -> UpdateInfo:
        """
        Проверяет наличие обновлений на GitHub.
        """
        info = UpdateInfo()
        try:
            logger.info(f"Проверка обновлений на {VERSION_FILE_URL}...")
            # Добавляем случайный параметр чтобы избежать кэширования на CDN GitHub
            url = f"{VERSION_FILE_URL}?t={os.urandom(4).hex()}"

            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status != 200:
                    info.error = f"Ошибка сервера: {response.status}"
                    return info

                data = json.loads(response.read().decode('utf-8'))
                self.latest_info = data

                latest_version = data.get("version")
                if not latest_version:
                    info.error = "Неверный формат version.json"
                    return info

                info.version = latest_version
                info.release_notes = data.get("release_notes", "")

                if self._is_newer(latest_version, self.current_version):
                    info.available = True
                    logger.info(f"Найдено обновление: {self.current_version} -> {latest_version}")
                else:
                    info.available = False
                    logger.info(f"Установлена актуальная версия: {self.current_version}")

                return info

        except Exception as e:
            logger.error(f"Ошибка при проверке обновлений: {e}")
            info.error = str(e)
            return info

    def _is_newer(self, latest: str, current: str) -> bool:
        """Сравнение версий x.y.z."""
        try:
            l_parts = [int(p) for p in latest.split('.')]
            c_parts = [int(p) for p in current.split('.')]
            while len(l_parts) < 3: l_parts.append(0)
            while len(c_parts) < 3: c_parts.append(0)
            return l_parts > c_parts
        except:
            return latest != current

    def get_download_url(self) -> Optional[str]:
        """Возвращает URL скачивания для текущей платформы."""
        if not self.latest_info:
            return None

        platforms = self.latest_info.get("platforms", {})
        if sys.platform == "win32":
            return platforms.get("windows")
        elif sys.platform == "darwin":
            return platforms.get("macos")
        else:
            return platforms.get("linux")

    def download_update(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Скачивает обновление во временную папку.
        """
        url = self.get_download_url()
        if not url:
            return False, None, "URL для скачивания не найден"

        try:
            ext = ".exe" if sys.platform == "win32" else ".dmg" if sys.platform == "darwin" else ".AppImage"
            temp_dir = Path(os.getenv("TEMP", "/tmp")) / "MindTypeUpdates"
            temp_dir.mkdir(parents=True, exist_ok=True)
            self._temp_path = temp_dir / f"MindType_Setup_{self.latest_info.get('version', 'update')}{ext}"

            logger.info(f"Скачивание обновления: {url} -> {self._temp_path}")

            def reporthook(block_num, block_size, total_size):
                if progress_callback:
                    downloaded = block_num * block_size
                    progress_callback(min(downloaded, total_size), total_size)

            urllib.request.urlretrieve(url, str(self._temp_path), reporthook=reporthook if progress_callback else None)

            return True, self._temp_path, None

        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return False, None, str(e)

    def install_update(self) -> bool:
        """
        Запускает установку и закрывает приложение.
        """
        if not self._temp_path or not self._temp_path.exists():
            logger.error("Файл обновления не найден для установки.")
            return False

        try:
            logger.info(f"Запуск установки: {self._temp_path}")
            if sys.platform == "win32":
                # Запускаем инсталлер в тихом режиме или обычном
                subprocess.Popen([str(self._temp_path)], shell=True)
            elif sys.platform == "linux":
                os.chmod(self._temp_path, 0o755)
                subprocess.Popen([str(self._temp_path)], shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._temp_path)])

            # Закрываем приложение
            sys.exit(0)
            return True
        except Exception as e:
            logger.error(f"Ошибка запуска установки: {e}")
            return False
