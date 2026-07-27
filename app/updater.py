import os
import sys
import json
import logging
import platform
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable, List, Iterable
from enum import Enum, auto
from .release_trust_root import (
    UPDATE_AUTHENTICODE_SIGNER,
    UPDATE_ED25519_PUBLIC_KEY,
)
from .update_manifest import (
    UpdateManifestError,
    VerifiedUpdateManifest,
    device_is_in_rollout,
    verify_update_manifest,
)
from .update_installer import (
    InstallerVerificationError,
    download_verified_installer,
    verify_downloaded_installer,
)
from .version import __version__, __channel__

logger = logging.getLogger("mindtype.updater")

# Основной URL для проверки обновлений (свой backend)
try:
    from .env import get_api_url
    PRIMARY_VERSION_URL = get_api_url("/api/updates/latest")
except ImportError:
    PRIMARY_VERSION_URL = "https://mindtype.space/api/updates/latest"

# A fallback is allowed only when it serves the same signed-envelope contract.
# The former raw GitHub version.json URL was stale and unsigned.
VERSION_URLS: List[str] = [PRIMARY_VERSION_URL]
UPDATE_DOWNLOAD_HOSTS = {
    "mindtype.space",
    "releases.mindtype.space",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

AUTOMATIC_UPDATE_DISABLED_MESSAGE = (
    "Безопасное обновление недоступно: цепочка доверия не подтверждена."
)
MAX_UPDATE_MANIFEST_BYTES = 64 * 1024

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
    def __init__(
        self,
        current_version: str = __version__,
        channel: str = __channel__,
        *,
        update_public_key: str = UPDATE_ED25519_PUBLIC_KEY,
        expected_signer: str = UPDATE_AUTHENTICODE_SIGNER,
        rollout_device_id: str = "",
        allowed_download_hosts: Iterable[str] = UPDATE_DOWNLOAD_HOSTS,
        update_directory: Optional[Path] = None,
    ):
        self.current_version = current_version
        self.channel = channel
        self.latest_info: Optional[Dict[str, Any]] = None
        self.verified_manifest: Optional[VerifiedUpdateManifest] = None
        self._temp_path: Optional[Path] = None
        self._update_public_key = update_public_key
        self._expected_signer = expected_signer
        self._rollout_device_id = rollout_device_id
        self._allowed_download_hosts = set(allowed_download_hosts)
        self._update_directory = (
            Path(update_directory)
            if update_directory is not None
            else Path(
                os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
            )
            / "MindType"
            / "updates"
        )

    @staticmethod
    def _architecture() -> str:
        machine = (
            platform.machine()
            or os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE")
            or ""
        ).casefold()
        if machine in {"amd64", "x86_64"}:
            return "x86_64"
        if machine in {"arm64", "aarch64"}:
            return "arm64"
        if not machine and struct.calcsize("P") == 8:
            return "x86_64"
        return machine

    def check_for_updates(self) -> UpdateInfo:
        """
        Проверяет наличие обновлений.
        Использует свой backend как основной источник с fallback на GitHub.
        """
        info = UpdateInfo()
        last_error = None
        if not self._update_public_key or not self._expected_signer:
            info.error = (
                "Проверка обновлений недоступна: в сборке нет "
                "доверенного ключа обновлений."
            )
            return info

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

                    raw_envelope = response.read(
                        MAX_UPDATE_MANIFEST_BYTES + 1
                    )
                    if len(raw_envelope) > MAX_UPDATE_MANIFEST_BYTES:
                        raise UpdateManifestError(
                            "update manifest response is too large"
                        )
                    envelope = json.loads(raw_envelope.decode('utf-8'))
                    manifest = verify_update_manifest(
                        envelope,
                        public_key=self._update_public_key,
                        expected_channel=self.channel,
                        expected_platform="windows",
                        expected_architecture=self._architecture(),
                        expected_signer=self._expected_signer,
                        allowed_hosts=self._allowed_download_hosts,
                    )
                    self.verified_manifest = manifest
                    self.latest_info = {
                        "version": manifest.version,
                        "minimum_supported_version": (
                            manifest.minimum_supported_version
                        ),
                        "release_notes": manifest.release_notes,
                        "rollout_percentage": manifest.rollout_percentage,
                        "platforms": {
                            "windows": {
                                "url": manifest.url,
                                "sha256": manifest.sha256,
                                "size": manifest.size,
                                "authenticode_signer": (
                                    manifest.authenticode_signer
                                ),
                            }
                        },
                    }

                    latest_version = manifest.version
                    info.version = latest_version
                    info.release_notes = manifest.release_notes

                    if self._is_newer(latest_version, self.current_version):
                        info.available = device_is_in_rollout(
                            device_id=(
                                self._rollout_device_id
                                or "anonymous-local-device"
                            ),
                            version=latest_version,
                            percentage=manifest.rollout_percentage,
                        )
                        if info.available:
                            logger.info(
                                "Найдено обновление: %s -> %s",
                                self.current_version,
                                latest_version,
                            )
                        else:
                            logger.info(
                                "Обновление %s пока вне rollout устройства",
                                latest_version,
                            )
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
            except UpdateManifestError as e:
                last_error = f"Недоверенный manifest обновления: {e}"
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

    def download_update(self, progress_callback: Optional[Callable[[int, int], None]] = None) -> Tuple[bool, Optional[Path], Optional[str]]:
        """Download and authenticate the installer without executing it."""
        manifest = self.verified_manifest
        if manifest is None or not self._update_public_key or not self._expected_signer:
            return False, None, AUTOMATIC_UPDATE_DISABLED_MESSAGE
        if sys.platform != "win32" or manifest.platform != "windows":
            return False, None, "Обновление поддерживается только в Windows."
        destination = (
            self._update_directory
            / f"MindType-{manifest.version}-Setup.exe"
        )
        try:
            downloaded = download_verified_installer(
                manifest,
                destination,
                allowed_hosts=self._allowed_download_hosts,
                progress_callback=progress_callback,
            )
        except (InstallerVerificationError, OSError, urllib.error.URLError) as exc:
            logger.warning("Безопасная загрузка обновления отклонена: %s", exc)
            return False, None, str(exc)
        self._temp_path = downloaded
        return True, downloaded, None

    def install_update(self) -> bool:
        """Re-verify and launch the installer without shell interpolation."""
        manifest = self.verified_manifest
        installer = self._temp_path
        if (
            sys.platform != "win32"
            or manifest is None
            or installer is None
        ):
            logger.warning(AUTOMATIC_UPDATE_DISABLED_MESSAGE)
            return False
        try:
            verify_downloaded_installer(installer, manifest)
            subprocess.Popen(
                [str(installer.resolve(strict=True))],
                cwd=str(installer.parent.resolve()),
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (InstallerVerificationError, OSError) as exc:
            logger.warning("Запуск обновления отклонён: %s", exc)
            return False
        return True
