"""
Менеджер лицензий - главный модуль системы лицензирования.
Поддерживает гибридный режим: онлайн валидация + оффлайн кэш.
"""

import hashlib
import hmac
import json
import logging
import os
import platform
import socket
import sys
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Callable

from .entitlement import (
    EntitlementClaims,
    EntitlementLeaseStore,
    EntitlementLeaseVerifier,
    LeaseValidationError,
    write_durable_text,
)
from .key_validator import KeyValidator
from .trial import TrialManager, TRIAL_DURATION_DAYS, TRIAL_TRANSCRIPTION_LIMIT_SECONDS

logger = logging.getLogger("mindtype.license")


class LicenseStatus(Enum):
    """Статус лицензии."""
    VALID = "valid"              # Активирована полная лицензия
    TRIAL = "trial"              # Trial период активен
    TRIAL_EXPIRED = "trial_expired"  # Trial истёк
    INVALID = "invalid"          # Невалидный ключ


class ValidationResult(Enum):
    """Результат онлайн валидации."""
    SUCCESS = "success"
    INVALID_KEY = "invalid_key"
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    DEACTIVATED = "deactivated"
    DEVICE_LIMIT = "device_limit"
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "server_error"
    RATE_LIMITED = "rate_limited"


@dataclass
class LicenseInfo:
    """Информация о лицензии."""
    status: LicenseStatus
    license_key: Optional[str] = None
    activation_date: Optional[datetime] = None
    trial_remaining_days: int = 0
    trial_remaining_minutes: float = 0
    trial_start_date: Optional[datetime] = None
    plan: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[datetime] = None
    activated_devices: int = 0
    max_devices: int = 1

    @property
    def is_active(self) -> bool:
        """Проверить, активна ли лицензия (полная или trial)."""
        return self.status in (LicenseStatus.VALID, LicenseStatus.TRIAL)

    @property
    def is_trial(self) -> bool:
        """Проверить, это trial или полная лицензия."""
        return self.status == LicenseStatus.TRIAL

    @property
    def is_full_license(self) -> bool:
        """Проверить, это полная лицензия."""
        return self.status == LicenseStatus.VALID


def _get_data_dir() -> Path:
    """Получить директорию для хранения данных приложения."""
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux и др.
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base / "MindType"


# P9: Cache for device ID to avoid repeated expensive computation
_cached_device_id: Optional[str] = None
_device_id_lock = threading.Lock()
_device_id_future: Optional[Future] = None
_background_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="license-bg")


def _compute_device_id() -> str:
    """
    Internal function to compute device ID. Called in background thread.
    Генерация уникального ID устройства на основе hardware fingerprint.
    Используется для привязки лицензии к конкретному компьютеру.
    """
    info_parts = [
        platform.node(),  # hostname
        platform.machine(),  # processor architecture
        platform.system(),  # OS name
    ]

    # На Windows добавляем Volume Serial Number системного диска
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volume_serial = ctypes.c_ulong()
            kernel32.GetVolumeInformationW(
                "C:\\", None, 0, ctypes.byref(volume_serial), None, None, None, 0
            )
            info_parts.append(str(volume_serial.value))
        except Exception:
            pass

        # Добавляем MAC адрес
        try:
            import uuid
            mac = uuid.getnode()
            info_parts.append(str(mac))
        except Exception:
            pass

    # На macOS добавляем hardware UUID
    elif sys.platform == "darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["system_profiler", "SPHardwareDataType"],
                capture_output=True, text=True
            )
            for line in result.stdout.split("\n"):
                if "Hardware UUID" in line:
                    info_parts.append(line.split(":")[1].strip())
                    break
        except Exception:
            pass

    # На Linux добавляем machine-id
    else:
        try:
            with open("/etc/machine-id", "r") as f:
                info_parts.append(f.read().strip())
        except Exception:
            pass

    # Создаём хеш из всех компонентов
    combined = "|".join(info_parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def _start_device_id_computation() -> None:
    """P9: Start device ID computation in background thread at module load time."""
    global _device_id_future
    with _device_id_lock:
        if _device_id_future is None:
            _device_id_future = _background_executor.submit(_compute_device_id)


def _get_device_id() -> str:
    """
    P9: Get device ID, computing lazily if needed.
    If background computation is in progress, wait for it.
    If not started, compute synchronously (fallback).
    """
    global _cached_device_id, _device_id_future

    # Fast path: already computed
    if _cached_device_id is not None:
        return _cached_device_id

    with _device_id_lock:
        # Double-check after acquiring lock
        if _cached_device_id is not None:
            return _cached_device_id

        # If background computation was started, wait for it
        if _device_id_future is not None:
            try:
                _cached_device_id = _device_id_future.result(timeout=10.0)
                return _cached_device_id
            except Exception as e:
                logger.warning(f"Background device ID computation failed: {e}")
                # Fall through to synchronous computation

        # Fallback: compute synchronously
        _cached_device_id = _compute_device_id()
        return _cached_device_id


# P9: Start background computation when module is loaded
_start_device_id_computation()


def _get_device_name() -> str:
    """Получить человекочитаемое имя устройства."""
    hostname = socket.gethostname()
    os_name = platform.system()
    return f"{hostname} ({os_name})"


def _get_hmac_secret() -> str:
    """Получить секретный ключ для HMAC подписи."""
    # Импортируем здесь, чтобы избежать циклических импортов
    try:
        from ..env import LICENSE_HMAC_SECRET
        return LICENSE_HMAC_SECRET
    except ImportError:
        # Fallback: генерируем machine-based secret
        info = [platform.node(), platform.machine(), platform.system(), platform.processor()]
        # Соль генерируется из характеристик машины для уникальности
        salt = hashlib.md5(("|".join(info) + "lic").encode()).hexdigest()[:16]
        combined = "|".join(info) + "|" + salt
        return hashlib.sha256(combined.encode()).hexdigest()


def _sign_data(data: dict) -> str:
    """Создать HMAC подпись для данных."""
    secret = _get_hmac_secret()
    # Сортируем ключи для консистентности
    data_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
    signature = hmac.new(
        secret.encode(),
        data_str.encode(),
        hashlib.sha256
    ).hexdigest()
    return signature


def _verify_signature(data: dict, signature: str) -> bool:
    """Проверить HMAC подпись данных."""
    expected = _sign_data(data)
    return hmac.compare_digest(expected, signature)


class LicenseManager:
    """
    Менеджер лицензий.

    Поддерживает гибридный режим работы:
    - Онлайн валидация при активации
    - Кэширование лицензии локально
    - Периодическая ревалидация
    - Оффлайн работа с кэшем
    """

    def __init__(
        self,
        *,
        lease_verifier: Optional[EntitlementLeaseVerifier] = None,
    ):
        self._data_dir = _get_data_dir()
        self._license_file = self._data_dir / "license.dat"
        self._lease_file = self._data_dir / "entitlement.lease"
        self._lease_marker_file = self._data_dir / "entitlement.seen"
        self._trial_manager = TrialManager()
        self._license_data: Optional[dict] = None
        self._lease_claims: Optional[EntitlementClaims] = None
        self._lease_error_code: Optional[str] = None
        self._deactivation_cleanup: list[Callable[[], None]] = []
        self._cloud_deactivator: Optional[Callable[[], None]] = None
        self._device_id = _get_device_id()
        self._device_name = _get_device_name()
        if lease_verifier is None:
            try:
                from ..env import LICENSE_ED25519_PUBLIC_KEY

                if LICENSE_ED25519_PUBLIC_KEY:
                    lease_verifier = EntitlementLeaseVerifier(
                        LICENSE_ED25519_PUBLIC_KEY
                    )
            except (ImportError, LeaseValidationError) as exc:
                logger.error("Entitlement verifier is unavailable: %s", exc)
        self._lease_store = (
            EntitlementLeaseStore(
                self._lease_file,
                lease_verifier,
                device_id=self._device_id,
            )
            if lease_verifier is not None
            else None
        )
        self._load_license()

    def _load_license(self) -> None:
        """Загрузить данные лицензии из кэша."""
        self._lease_claims = None
        self._lease_error_code = None
        if self._lease_file.exists():
            if self._lease_store is None:
                self._license_data = None
                self._lease_error_code = "ENTITLEMENT_VERIFIER_UNAVAILABLE"
                return
            try:
                self._lease_claims = self._lease_store.load()
            except (LeaseValidationError, OSError, UnicodeError) as exc:
                self._license_data = None
                self._lease_error_code = getattr(
                    exc,
                    "code",
                    "ENTITLEMENT_CACHE_INVALID",
                )
                return
        if self._lease_marker_file.exists() and self._lease_claims is None:
            self._license_data = None
            self._lease_error_code = "ENTITLEMENT_REQUIRED"
            return
        if not self._license_file.exists():
            self._license_data = None
            return

        try:
            with open(self._license_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Проверяем подпись для защиты от подделки
            signature = data.pop("_signature", None)
            if signature and _verify_signature(data, signature):
                self._license_data = data
            else:
                # Подпись невалидна - файл был изменён
                self._license_data = None
                self._license_file.unlink(missing_ok=True)
        except Exception:
            self._license_data = None
            self._license_file.unlink(missing_ok=True)

    def _clear_cached_license(self) -> None:
        """Удалить локальное утверждение о лицензии."""
        self._license_data = None
        self._lease_claims = None
        self._lease_error_code = None
        self._license_file.unlink(missing_ok=True)
        if self._lease_store is not None:
            self._lease_store.clear()
        else:
            self._lease_file.unlink(missing_ok=True)
        self._lease_marker_file.unlink(missing_ok=True)

    def add_deactivation_cleanup(
        self,
        callback: Callable[[], None],
    ) -> None:
        """Register local cloud credentials that must follow deactivation."""
        if callback not in self._deactivation_cleanup:
            self._deactivation_cleanup.append(callback)

    def set_cloud_deactivator(
        self,
        callback: Callable[[], None],
    ) -> None:
        """Use the signed cloud session when the legacy key is gone."""
        self._cloud_deactivator = callback

    def install_entitlement_lease(
        self,
        token: str,
        *,
        now: Optional[datetime] = None,
    ) -> EntitlementClaims:
        """Verify and atomically adopt a server-issued offline lease."""
        if self._lease_store is None:
            raise LeaseValidationError(
                "ENTITLEMENT_VERIFIER_UNAVAILABLE",
                "desktop build has no entitlement public key",
            )
        claims = self._lease_store.save(
            token,
            now=now,
            before_publish=lambda: write_durable_text(
                self._lease_marker_file,
                "1",
            ),
            authoritative_clock_rebuild=True,
        )
        self._lease_claims = claims
        self._lease_error_code = None
        self._license_data = None
        self._license_file.unlink(missing_ok=True)
        return claims

    def _refresh_entitlement_lease(self) -> None:
        if self._lease_store is None:
            return
        if not self._lease_file.exists():
            self._lease_claims = None
            if self._lease_marker_file.exists():
                self._license_data = None
                self._lease_error_code = "ENTITLEMENT_REQUIRED"
            return
        try:
            self._lease_claims = self._lease_store.load()
            self._lease_error_code = None
        except (LeaseValidationError, OSError, UnicodeError) as exc:
            self._lease_claims = None
            self._lease_error_code = getattr(
                exc,
                "code",
                "ENTITLEMENT_CACHE_INVALID",
            )

    def _save_license(self) -> None:
        """Сохранить данные лицензии в кэш с подписью."""
        if self._license_data is None:
            return

        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Создаём копию для сохранения с подписью
        data_to_save = self._license_data.copy()
        data_to_save["_signature"] = _sign_data(self._license_data)

        with open(self._license_file, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, indent=2)

    def _get_api_config(self) -> Tuple[str, int]:
        """Получить конфигурацию API."""
        try:
            from ..env import API_BASE_URL, API_TIMEOUT
            return API_BASE_URL, API_TIMEOUT
        except ImportError:
            return "http://localhost:3000", 30

    def _make_api_request(self, endpoint: str, data: dict) -> Tuple[Optional[dict], Optional[str]]:
        """
        Выполнить POST запрос к API.

        Returns:
            Tuple (response_data, error_code)
        """
        base_url, timeout = self._get_api_config()
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        try:
            request_data = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=request_data,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'MindType/1.0'
                },
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=timeout) as response:
                response_data = json.loads(response.read().decode('utf-8'))
                return response_data, None

        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read().decode('utf-8'))
                error_code = error_body.get('error', 'unknown')
            except Exception:
                error_code = f"http_{e.code}"
            return None, error_code

        except urllib.error.URLError:
            return None, "network_error"

        except Exception as e:
            return None, f"error_{str(e)}"

    def _make_api_request_async(
        self,
        endpoint: str,
        data: dict,
        callback: Optional[callable] = None
    ) -> Future:
        """
        P10: Non-blocking API request that runs in background thread.

        Args:
            endpoint: API endpoint
            data: Request data
            callback: Optional callback(response, error) called when complete

        Returns:
            Future that will contain (response_data, error_code) tuple
        """
        def _do_request():
            result = self._make_api_request(endpoint, data)
            if callback:
                try:
                    callback(result[0], result[1])
                except Exception as e:
                    logger.error(f"API callback error: {e}")
            return result

        return _background_executor.submit(_do_request)

    def activate_online(self, license_key: str) -> Tuple[ValidationResult, str, Optional[dict]]:
        """
        Активировать лицензию через онлайн запрос к серверу.

        Args:
            license_key: Лицензионный ключ

        Returns:
            Tuple (result, message, server_data)
        """
        # Локальная валидация формата
        if not KeyValidator.validate(license_key):
            return ValidationResult.INVALID_KEY, "invalid_key_format", None

        normalized_key = KeyValidator.normalize_key(license_key).replace("-", "")
        formatted_key = KeyValidator.format_key(license_key)

        # Отправляем запрос на сервер
        request_data = {
            "licenseKey": formatted_key,
            "deviceId": self._device_id,
            "deviceName": self._device_name,
        }

        response, error = self._make_api_request("/api/license/validate", request_data)

        if error:
            # Маппинг ошибок
            error_mapping = {
                "network_error": (ValidationResult.NETWORK_ERROR, "network_error"),
                "rate_limit_exceeded": (ValidationResult.RATE_LIMITED, "rate_limited"),
                "invalid_format": (ValidationResult.INVALID_KEY, "invalid_key_format"),
                "not_found": (ValidationResult.NOT_FOUND, "license_not_found"),
                "deactivated": (ValidationResult.DEACTIVATED, "license_deactivated"),
                "expired": (ValidationResult.EXPIRED, "license_expired"),
                "device_limit": (ValidationResult.DEVICE_LIMIT, "device_limit_reached"),
            }
            result, msg = error_mapping.get(error, (ValidationResult.SERVER_ERROR, error))
            return result, msg, None

        if response and response.get("valid"):
            signed_lease = response.get("entitlementLease")
            if signed_lease:
                try:
                    self.install_entitlement_lease(signed_lease)
                except LeaseValidationError as exc:
                    logger.error(
                        "Server returned unusable entitlement lease: %s",
                        exc.code,
                    )
                    return (
                        ValidationResult.SERVER_ERROR,
                        exc.code.lower(),
                        None,
                    )
                # Compatibility until the access/refresh session is wired into
                # every existing cloud consumer. The signed lease remains the
                # entitlement authority; this cache only supplies the legacy
                # bearer credential and a revalidation route for one release.
                self._license_data = {
                    "license_key": normalized_key,
                    "device_id": self._device_id,
                    "plan": response.get("plan", "personal"),
                    "email": response.get("email"),
                    "validated_at": datetime.now().isoformat(),
                    "expires_at": response.get("expiresAt"),
                    "activated_devices": response.get(
                        "activatedDevices",
                        1,
                    ),
                    "max_devices": response.get("maxDevices", 1),
                }
                self._save_license()
                return (
                    ValidationResult.SUCCESS,
                    response.get("message", "activation_success"),
                    response,
                )
            # Успешная активация - сохраняем в кэш
            self._license_data = {
                "license_key": normalized_key,
                "device_id": self._device_id,
                "plan": response.get("plan", "personal"),
                "email": response.get("email"),
                "validated_at": datetime.now().isoformat(),
                "expires_at": response.get("expiresAt"),
                "activated_devices": response.get("activatedDevices", 1),
                "max_devices": response.get("maxDevices", 1),
            }
            self._save_license()

            return ValidationResult.SUCCESS, response.get("message", "activation_success"), response

        return ValidationResult.SERVER_ERROR, "unknown_error", None

    def deactivate_online(self) -> Tuple[bool, str]:
        """
        Деактивировать лицензию на сервере.

        Returns:
            Tuple (success, message)
        """
        if self._license_data is None:
            if self._cloud_deactivator is None or self._lease_claims is None:
                return False, "no_license"
            try:
                self._cloud_deactivator()
            except Exception as exc:
                code = str(getattr(exc, "code", "") or "")
                if bool(getattr(exc, "authoritative", False)):
                    self._finish_local_deactivation()
                if code == "PROVIDER_UNAVAILABLE":
                    return False, "network_error"
                return False, code.lower() or "deactivation_failed"
            self._finish_local_deactivation()
            return True, "deactivation_success"

        formatted_key = KeyValidator.format_key(self._license_data.get("license_key", ""))

        request_data = {
            "licenseKey": formatted_key,
            "deviceId": self._device_id,
        }

        response, error = self._make_api_request("/api/license/deactivate", request_data)

        if error:
            if error == "network_error":
                return False, "network_error"
            return False, error

        if response and response.get("success"):
            self._finish_local_deactivation()
            return True, "deactivation_success"

        return False, "deactivation_failed"

    def _finish_local_deactivation(self) -> None:
        self._clear_cached_license()
        for cleanup in tuple(self._deactivation_cleanup):
            try:
                cleanup()
            except Exception:
                logger.exception(
                    "Cloud session credentials could not be fully cleared"
                )

    def needs_revalidation(self) -> bool:
        """Проверить, нужна ли ревалидация лицензии."""
        if self._license_data is None:
            return False

        validated_at_str = self._license_data.get("validated_at")
        if not validated_at_str:
            return True

        try:
            validated_at = datetime.fromisoformat(validated_at_str)

            # Получаем интервал ревалидации из конфига
            try:
                from ..env import LICENSE_REVALIDATION_INTERVAL
                interval = LICENSE_REVALIDATION_INTERVAL
            except ImportError:
                interval = 604800  # 7 дней по умолчанию

            deadline = validated_at + timedelta(seconds=interval)
            if self._lease_claims is not None:
                refresh_before_expiry = (
                    self._lease_claims.expires_at - timedelta(days=1)
                )
                if validated_at.tzinfo is None:
                    refresh_before_expiry = refresh_before_expiry.replace(
                        tzinfo=None
                    )
                deadline = min(deadline, refresh_before_expiry)
            current = (
                datetime.now(deadline.tzinfo)
                if deadline.tzinfo is not None
                else datetime.now()
            )
            return current >= deadline
        except Exception:
            return True

    def revalidate_if_needed(self) -> Optional[ValidationResult]:
        """
        Ревалидировать лицензию, если прошло достаточно времени.

        Returns:
            Результат валидации или None, если ревалидация не нужна
        """
        if not self.needs_revalidation():
            return None

        if self._license_data is None:
            return None

        key = KeyValidator.format_key(self._license_data.get("license_key", ""))
        result, _, _ = self.activate_online(key)
        if result in {
            ValidationResult.NOT_FOUND,
            ValidationResult.DEACTIVATED,
            ValidationResult.EXPIRED,
        }:
            self._clear_cached_license()
        return result

    def revalidate_if_needed_async(
        self,
        callback: Optional[Callable[[Optional[ValidationResult]], None]] = None,
    ) -> Optional[Future]:
        """Запустить ревалидацию устаревшего cache без блокировки UI."""
        if not self.needs_revalidation():
            return None

        future = _background_executor.submit(self.revalidate_if_needed)
        if callback is not None:
            def _notify(done: Future) -> None:
                try:
                    callback(done.result())
                except Exception as exc:
                    logger.warning("License revalidation callback failed: %s", exc)

            future.add_done_callback(_notify)
        return future

    def get_license_info(self) -> LicenseInfo:
        """
        Получить информацию о текущей лицензии.

        Returns:
            LicenseInfo с текущим статусом
        """
        self._refresh_entitlement_lease()
        if self._lease_claims is not None:
            claims = self._lease_claims
            legacy = self._license_data or {}
            legacy_key = legacy.get("license_key")
            max_devices = claims.limits.get("max_devices", 1)
            if isinstance(max_devices, bool) or not isinstance(max_devices, int):
                max_devices = 1
            return LicenseInfo(
                status=LicenseStatus.VALID,
                license_key=(
                    KeyValidator.format_key(legacy_key)
                    if legacy_key
                    else None
                ),
                activation_date=claims.issued_at,
                plan=claims.plan,
                email=legacy.get("email"),
                expires_at=claims.expires_at,
                activated_devices=legacy.get("activated_devices", 1),
                max_devices=max_devices,
            )
        if self._lease_error_code is not None:
            return LicenseInfo(status=LicenseStatus.INVALID)

        # Compatibility: legacy machine-HMAC cache is accepted for one release.
        if self._license_data is not None:
            key = self._license_data.get("license_key")
            if key:
                # Проверяем срок действия
                expires_at = None
                if self._license_data.get("expires_at"):
                    try:
                        expires_at = datetime.fromisoformat(
                            self._license_data["expires_at"].replace("Z", "+00:00")
                        )
                        if expires_at < datetime.now(expires_at.tzinfo):
                            # Лицензия истекла
                            return LicenseInfo(
                                status=LicenseStatus.TRIAL_EXPIRED,
                                license_key=KeyValidator.format_key(key),
                            )
                    except Exception:
                        pass

                activation_date = None
                if self._license_data.get("validated_at"):
                    try:
                        activation_date = datetime.fromisoformat(
                            self._license_data["validated_at"]
                        )
                    except Exception:
                        pass

                return LicenseInfo(
                    status=LicenseStatus.VALID,
                    license_key=KeyValidator.format_key(key),
                    activation_date=activation_date,
                    plan=self._license_data.get("plan"),
                    email=self._license_data.get("email"),
                    expires_at=expires_at,
                    activated_devices=self._license_data.get("activated_devices", 1),
                    max_devices=self._license_data.get("max_devices", 1),
                )

        # Проверяем trial
        is_active, remaining_days, remaining_minutes, start_date = self._trial_manager.get_trial_info()

        if is_active:
            return LicenseInfo(
                status=LicenseStatus.TRIAL,
                trial_remaining_days=remaining_days,
                trial_remaining_minutes=remaining_minutes,
                trial_start_date=start_date,
            )
        else:
            return LicenseInfo(
                status=LicenseStatus.TRIAL_EXPIRED,
                trial_remaining_days=0,
                trial_remaining_minutes=0,
                trial_start_date=start_date,
            )

    def add_transcription_time(
        self,
        seconds: float,
        *,
        operation_id: Optional[str] = None,
    ) -> bool:
        """Добавить использованное время транскрипции (для trial)."""
        info = self.get_license_info()
        if info.is_trial:
            return self._trial_manager.add_transcription_time(
                seconds,
                operation_id=operation_id,
            )
        return False

    def activate(self, license_key: str) -> tuple[bool, str]:
        """
        Активировать лицензию (только онлайн).

        Args:
            license_key: Лицензионный ключ

        Returns:
            Tuple (success, message)
        """
        result, message, _ = self.activate_online(license_key)
        return result == ValidationResult.SUCCESS, message

    def deactivate(self) -> bool:
        """
        Деактивировать лицензию.

        Returns:
            True если успешно деактивирована
        """
        if self._license_data:
            success, _ = self.deactivate_online()
            # Даже если сервер вернул ошибку, мы удаляем локальный кэш
            # чтобы пользователь мог попробовать активировать другой ключ

        self._clear_cached_license()
        return True

    def start_trial(self) -> bool:
        """
        Начать trial период.

        Returns:
            True если trial успешно начат
        """
        return self._trial_manager.start_trial()

    def check_access(self) -> tuple[bool, LicenseInfo]:
        """
        Проверить доступ к приложению.

        Returns:
            Tuple (has_access, license_info)
        """
        info = self.get_license_info()

        # Если полная лицензия - доступ есть
        if info.status == LicenseStatus.VALID:
            return True, info
        if info.status == LicenseStatus.INVALID:
            return False, info

        # Если trial не начат - начинаем его
        if not self._trial_manager.has_trial_started():
            self._trial_manager.start_trial()
            info = self.get_license_info()

        # Проверяем статус trial
        return info.is_active, info

    def check_transcription_entitlement(
        self,
        required_seconds: float = 0,
    ) -> tuple[bool, LicenseInfo]:
        """Единый gate для диктовки и обработки файлов."""
        has_access, info = self.check_access()
        if not has_access:
            return False, info
        if info.is_trial and max(0.0, required_seconds) > (
            info.trial_remaining_minutes * 60
        ):
            return False, info
        return True, info

    def get_trial_remaining_days(self) -> int:
        """Получить оставшиеся дни trial."""
        return self._trial_manager.get_remaining_days()

    def get_device_id(self) -> str:
        """Получить ID текущего устройства."""
        return self._device_id

    def get_entitlement_lease_store(
        self,
    ) -> Optional[EntitlementLeaseStore]:
        """Verified lease store shared with the cloud session boundary."""
        return self._lease_store

    def clear_authoritative_cache(self) -> None:
        """Fail closed after the server authoritatively rejects entitlement."""
        self._lease_claims = None
        self._license_data = None
        self._lease_error_code = "ENTITLEMENT_REQUIRED"
        write_durable_text(self._lease_marker_file, "1")
        if self._lease_store is not None:
            self._lease_store.clear()
        else:
            self._lease_file.unlink(missing_ok=True)
        self._license_file.unlink(missing_ok=True)

    def get_device_name(self) -> str:
        """Получить имя текущего устройства."""
        return self._device_name

    @staticmethod
    def get_trial_duration() -> int:
        """Получить длительность trial периода в днях."""
        return TRIAL_DURATION_DAYS


# Глобальный экземпляр менеджера лицензий
_license_manager: Optional[LicenseManager] = None


def get_license_manager() -> LicenseManager:
    """Получить глобальный экземпляр менеджера лицензий."""
    global _license_manager
    if _license_manager is None:
        _license_manager = LicenseManager()
    return _license_manager
