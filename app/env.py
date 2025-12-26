"""
Конфигурация приложения через переменные окружения.
Загружает настройки из .env файла или системных переменных.
"""

import os
import sys
from pathlib import Path
from typing import Optional

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

# Базовый URL API сервера (для лицензий и обновлений)
API_BASE_URL: str = _get_env("MINDTYPE_API_URL", "http://localhost:3000")

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

# Секретный ключ для HMAC подписи кэша лицензии
# ВАЖНО: В production должен быть уникальным и секретным!
LICENSE_HMAC_SECRET: str = _get_env("MINDTYPE_LICENSE_SECRET", "MindType2024LicenseSecret")


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


