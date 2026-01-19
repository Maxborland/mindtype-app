"""
Конфигурация приложения через переменные окружения.
Загружает настройки из .env файла или системных переменных.
"""

import hashlib
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mindtype.env")

# Попытка загрузить python-dotenv (опционально)
try:
    from dotenv import load_dotenv

    # Ищем .env файл в директории приложения
    if getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__"):
        # Запущено как exe (PyInstaller/Nuitka)
        app_dir = Path(sys.executable).parent
    else:
        # Запущено как скрипт
        app_dir = Path(__file__).parent.parent

    env_file = app_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass  # python-dotenv не установлен, используем только системные переменные


# Production API URL - должен быть заменён на реальный при сборке
_PRODUCTION_API_URL = "https://mindtype.space"


def _is_production() -> bool:
    """Проверить, запущено ли приложение в production режиме."""
    return getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__")


def _get_env(key: str, default: str) -> str:
    """Получить строковую переменную окружения."""
    return os.getenv(key, default)


def _get_env_int(key: str, default: int) -> int:
    """Получить целочисленную переменную окружения."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_env_bool(key: str, default: bool) -> bool:
    """Получить булеву переменную окружения."""
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


# =============================================================================
# API Configuration
# =============================================================================

def _get_api_base_url() -> str:
    """
    Получить базовый URL API.
    В production используется production URL, в dev - localhost.
    """
    env_url = os.getenv("MINDTYPE_API_URL")
    if env_url:
        return env_url

    # В production режиме используем production URL
    if _is_production():
        return _PRODUCTION_API_URL

    # В dev режиме - localhost
    return "http://localhost:3000"


# Базовый URL API сервера (для лицензий и обновлений)
API_BASE_URL: str = _get_api_base_url()

# Таймаут запросов к API (секунды)
API_TIMEOUT: int = _get_env_int("MINDTYPE_API_TIMEOUT", 30)


# =============================================================================
# Updates Configuration
# =============================================================================

# Интервал автоматической проверки обновлений (секунды, по умолчанию 24 часа)
UPDATE_CHECK_INTERVAL: int = _get_env_int("MINDTYPE_UPDATE_INTERVAL", 86400)

# Автоматически проверять обновления при запуске
UPDATE_AUTO_CHECK: bool = _get_env_bool("MINDTYPE_UPDATE_AUTO_CHECK", True)

# Разрешить автоматическое скачивание обновлений
UPDATE_AUTO_DOWNLOAD: bool = _get_env_bool("MINDTYPE_UPDATE_AUTO_DOWNLOAD", False)


# =============================================================================
# License Configuration
# =============================================================================

# Интервал ревалидации лицензии (секунды, по умолчанию 7 дней)
LICENSE_REVALIDATION_INTERVAL: int = _get_env_int("MINDTYPE_LICENSE_REVALIDATION", 604800)


def _generate_machine_hmac_secret() -> str:
    """
    Генерирует уникальный HMAC секрет на основе характеристик машины.
    Это предотвращает простой перенос кэша лицензии между машинами.
    """
    import platform

    # Собираем информацию о машине
    machine_info = [
        platform.node(),
        platform.machine(),
        platform.system(),
        platform.processor(),
    ]

    # На Windows добавляем Volume Serial Number
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            volume_serial = ctypes.c_ulong()
            kernel32.GetVolumeInformationW(
                "C:\\", None, 0, ctypes.byref(volume_serial), None, None, None, 0
            )
            machine_info.append(str(volume_serial.value))
        except Exception:
            pass

    # Создаём хеш с солью из env или уникальной для машины
    # Соль должна быть уникальной для каждой установки
    salt = os.getenv("MINDTYPE_MACHINE_SALT", "")
    if not salt:
        # Генерируем соль на основе характеристик машины
        salt = hashlib.md5(("|".join(machine_info) + "v1").encode()).hexdigest()[:16]
    combined = "|".join(machine_info) + "|" + salt
    return hashlib.sha256(combined.encode()).hexdigest()


def _get_license_hmac_secret() -> str:
    """
    Получить HMAC секрет для подписи кэша лицензии.

    Порядок приоритета:
    1. Переменная окружения MINDTYPE_LICENSE_SECRET
    2. Уникальный секрет на основе характеристик машины
    """
    env_secret = os.getenv("MINDTYPE_LICENSE_SECRET")
    if env_secret:
        return env_secret

    # Генерируем уникальный секрет для этой машины
    return _generate_machine_hmac_secret()


# Секретный ключ для HMAC подписи кэша лицензии
# Генерируется уникально для каждой машины, либо берётся из env
LICENSE_HMAC_SECRET: str = _get_license_hmac_secret()


# =============================================================================
# Debug Configuration
# =============================================================================

# Режим отладки
DEBUG: bool = _get_env_bool("MINDTYPE_DEBUG", False)

# Логировать HTTP запросы
LOG_HTTP_REQUESTS: bool = _get_env_bool("MINDTYPE_LOG_HTTP", False)


# =============================================================================
# Application Info
# =============================================================================

from .version import __version__

# Версия приложения (используется для проверки обновлений)
APP_VERSION: str = __version__

# Название приложения
APP_NAME: str = "MindType"

# Платформа (определяется автоматически)
PLATFORM: str = sys.platform  # "win32", "darwin", "linux"


# =============================================================================
# Utility Functions
# =============================================================================

def get_api_url(endpoint: str) -> str:
    """
    Получить полный URL для API endpoint.

    Args:
        endpoint: Путь endpoint (например, "/api/license/validate")

    Returns:
        Полный URL
    """
    base = API_BASE_URL.rstrip("/")
    endpoint = endpoint.lstrip("/")
    return f"{base}/{endpoint}"


def get_update_url() -> str:
    """Получить URL для проверки обновлений."""
    return get_api_url(f"/api/updates/latest?platform={PLATFORM}&current_version={APP_VERSION}")


def get_license_validate_url() -> str:
    """Получить URL для валидации лицензии."""
    return get_api_url("/api/license/validate")


def get_license_deactivate_url() -> str:
    """Получить URL для деактивации лицензии."""
    return get_api_url("/api/license/deactivate")


def mask_secret(secret: Optional[str]) -> str:
    """
    Маскирует секретные данные (API ключи, лицензии) для логирования.
    Пример: sk-12345678 -> sk-1...5678
    """
    if not secret:
        return "None"
    if len(secret) <= 10:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"


def validate_production_config() -> list[str]:
    """
    Проверяет конфигурацию для production.

    Returns:
        Список предупреждений (пустой если всё ок)
    """
    warnings_list = []

    if not _is_production():
        return warnings_list

    # Проверяем API URL
    if API_BASE_URL == "http://localhost:3000":
        warnings_list.append(
            "API_BASE_URL установлен на localhost. "
            "Установите MINDTYPE_API_URL или пересоберите с правильным _PRODUCTION_API_URL."
        )

    # Проверяем HTTPS для production
    if not API_BASE_URL.startswith("https://"):
        warnings_list.append(
            f"API_BASE_URL ({API_BASE_URL}) не использует HTTPS. "
            "В production рекомендуется использовать HTTPS."
        )

    return warnings_list


def log_config_warnings() -> None:
    """Логирует предупреждения о конфигурации."""
    for warning in validate_production_config():
        logger.warning(f"[Config] {warning}")


# Для отладки
if __name__ == "__main__":
    print("=== MindType Environment Configuration ===")
    print()
    print(f"APP_NAME:           {APP_NAME}")
    print(f"APP_VERSION:        {APP_VERSION}")
    print(f"PLATFORM:           {PLATFORM}")
    print()
    print(f"API_BASE_URL:       {API_BASE_URL}")
    print(f"API_TIMEOUT:        {API_TIMEOUT}s")
    print()
    print(f"UPDATE_CHECK_INTERVAL:  {UPDATE_CHECK_INTERVAL}s ({UPDATE_CHECK_INTERVAL // 3600}h)")
    print(f"UPDATE_AUTO_CHECK:      {UPDATE_AUTO_CHECK}")
    print(f"UPDATE_AUTO_DOWNLOAD:   {UPDATE_AUTO_DOWNLOAD}")
    print()
    print(f"LICENSE_REVALIDATION:   {LICENSE_REVALIDATION_INTERVAL}s ({LICENSE_REVALIDATION_INTERVAL // 86400}d)")
    print()
    print(f"DEBUG:              {DEBUG}")
    print(f"LOG_HTTP_REQUESTS:  {LOG_HTTP_REQUESTS}")
    print()
    print("=== URLs ===")
    print(f"Updates:    {get_update_url()}")
    print(f"Validate:   {get_license_validate_url()}")
    print(f"Deactivate: {get_license_deactivate_url()}")


