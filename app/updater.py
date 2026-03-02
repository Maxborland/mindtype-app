import os
import sys
import json
import logging
import urllib.request
import urllib.parse
import subprocess
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable, List
from enum import Enum, auto
from .version import __version__, __channel__

logger = logging.getLogger("mindtype.updater")

# Основной URL для проверки обновлений (свой backend)
try:
    from .env import get_api_url
    PRIMARY_VERSION_URL = get_api_url("/api/updates/latest")
except ImportError:
    PRIMARY_VERSION_URL = "https://mindtype.space/api/updates/latest"

# Fallback URL на GitHub (если основной сервер недоступен)
GITHUB_REPO = "wispr-flow-clone/mindtype"
FALLBACK_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"

# Список URL для проверки (в порядке приоритета)
VERSION_URLS: List[str] = [PRIMARY_VERSION_URL, FALLBACK_VERSION_URL]

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
        Проверяет наличие обновлений.
        Использует свой backend как основной источник с fallback на GitHub.
        """
        info = UpdateInfo()
        last_error = None

        for base_url in VERSION_URLS:
            try:
                logger.info(f"Проверка обновлений на {base_url}...")
                # Добавляем случайный параметр чтобы избежать кэширования
                cache_buster = os.urandom(4).hex()
                if "?" in base_url:
                    url = f"{base_url}&t={cache_buster}"
                else:
                    url = f"{base_url}?t={cache_buster}"

                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': f'MindType/{self.current_version}',
                        'Accept': 'application/json',
                    }
                )

                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status != 200:
                        last_error = f"Ошибка сервера: {response.status}"
                        logger.warning(f"{base_url}: {last_error}")
                        continue

                    data = json.loads(response.read().decode('utf-8'))
                    self.latest_info = data

                    latest_version = data.get("version")
                    if not latest_version:
                        last_error = "Неверный формат version.json"
                        logger.warning(f"{base_url}: {last_error}")
                        continue

                    info.version = latest_version
                    info.release_notes = data.get("release_notes", "")

                    if self._is_newer(latest_version, self.current_version):
                        info.available = True
                        logger.info(f"Найдено обновление: {self.current_version} -> {latest_version}")
                    else:
                        info.available = False
                        logger.info(f"Установлена актуальная версия: {self.current_version}")

                    # Успешно получили информацию - выходим из цикла
                    return info

            except urllib.error.HTTPError as e:
                last_error = f"HTTP ошибка {e.code}: {e.reason}"
                logger.warning(f"{base_url}: {last_error}")
                continue
            except urllib.error.URLError as e:
                last_error = f"Сетевая ошибка: {e.reason}"
                logger.warning(f"{base_url}: {last_error}")
                continue
            except json.JSONDecodeError as e:
                last_error = f"Ошибка парсинга JSON: {e}"
                logger.warning(f"{base_url}: {last_error}")
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"{base_url}: Ошибка при проверке обновлений: {e}")
                continue

        # Все источники недоступны
        logger.error(f"Все источники обновлений недоступны. Последняя ошибка: {last_error}")
        info.error = last_error or "Не удалось проверить обновления"
        return info

    def _is_newer(self, latest: str, current: str) -> bool:
        """Сравнение версий x.y.z."""
        try:
            l_parts = [int(p) for p in latest.split('.')]
            c_parts = [int(p) for p in current.split('.')]
            while len(l_parts) < 3: l_parts.append(0)
            while len(c_parts) < 3: c_parts.append(0)
            return l_parts > c_parts
        except (ValueError, AttributeError):
            return latest != current

    def get_download_info(self) -> Tuple[Optional[str], Optional[str]]:
        """Возвращает URL скачивания и ожидаемый SHA256 хеш для текущей платформы."""
        if not self.latest_info:
            return None, None

        platforms = self.latest_info.get("platforms", {})
        platform_key = ""
        if sys.platform == "win32":
            platform_key = "windows"
        elif sys.platform == "darwin":
            platform_key = "macos"
        else:
            platform_key = "linux"

        data = platforms.get(platform_key)
        if isinstance(data, dict):
            return data.get("url"), data.get("sha256")
        return data, None

    def _verify_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Проверяет SHA256 хеш файла."""
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            actual_hash = sha256_hash.hexdigest().lower()
            return actual_hash == expected_hash.lower()
        except Exception as e:
            logger.error(f"Ошибка при проверке хеша: {e}")
            return False

    def download_update(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        Скачивает обновление во временную папку с проверкой хеша.
        """
        url, expected_hash = self.get_download_info()
        if not url:
            return False, None, "URL для скачивания не найден"

        # Безопасность: проверяем домен (whitelist)
        ALLOWED_DOWNLOAD_DOMAINS = [
            "github.com",
            "objects.githubusercontent.com",
            "raw.githubusercontent.com",
            "mindtype.space",  # Свой сервер
            "cdn.mindtype.space",  # CDN (если будет)
        ]
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.netloc not in ALLOWED_DOWNLOAD_DOMAINS:
            return False, None, f"Небезопасный URL для скачивания: {parsed_url.netloc}"

        try:
            ext = ".exe" if sys.platform == "win32" else ".dmg" if sys.platform == "darwin" else ".AppImage"

            # Проверка расширения в URL
            if not url.lower().endswith(ext):
                return False, None, f"Неверное расширение файла в URL: ожидается {ext}"

            temp_dir = Path(os.getenv("TEMP", "/tmp")) / "MindTypeUpdates"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize version string to prevent path traversal
            import re
            raw_version = self.latest_info.get('version', 'update')
            # Only allow alphanumeric, dots, hyphens (valid semver chars)
            safe_version = re.sub(r'[^a-zA-Z0-9.\-]', '', raw_version)[:32]
            if not safe_version:
                safe_version = 'update'

            self._temp_path = temp_dir / f"MindType_Setup_{safe_version}{ext}"

            logger.info(f"Скачивание обновления: {url} -> {self._temp_path}")

            def reporthook(block_num, block_size, total_size):
                if progress_callback:
                    downloaded = block_num * block_size
                    progress_callback(min(downloaded, total_size), total_size)

            urllib.request.urlretrieve(url, str(self._temp_path), reporthook=reporthook if progress_callback else None)

            # Проверка хеша если он предоставлен
            if expected_hash:
                logger.info(f"Проверка хеша SHA256...")
                if not self._verify_hash(self._temp_path, expected_hash):
                    if self._temp_path.exists():
                        self._temp_path.unlink()
                    return False, None, "Ошибка проверки целостности файла (хеш не совпадает)"
                logger.info("Хеш совпадает.")
            else:
                logger.warning("Ожидаемый хеш не указан в version.json. Установка может быть небезопасной.")

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
            # Безопасность: не используем shell=True
            if sys.platform == "win32":
                subprocess.Popen([str(self._temp_path)])
            elif sys.platform == "linux":
                os.chmod(self._temp_path, 0o700)
                subprocess.Popen([str(self._temp_path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._temp_path)])

            # Закрываем приложение
            sys.exit(0)
            return True
        except Exception as e:
            logger.error(f"Ошибка запуска установки: {e}")
            return False
