"""
Модуль для сбора и сохранения crash-репортов.

При необработанном исключении:
1. Собирает информацию о системе и ошибке
2. Сохраняет репорт в файл
3. Отправляет репорт на сервер (с согласия пользователя)
4. Показывает диалог пользователю
"""

import json
import logging
import os
import platform
import sys
import traceback
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, Callable, List, Tuple

from .constants import MAX_BREADCRUMBS
from .env import is_app_frozen

logger = logging.getLogger("mindtype.crash_reporter")

# Email поддержки
SUPPORT_EMAIL = "help@mindtype.space"


class BreadcrumbManager:
    """Thread-safe менеджер breadcrumbs для отслеживания действий пользователя."""

    def __init__(self, max_size: int = MAX_BREADCRUMBS):
        self._breadcrumbs: deque = deque(maxlen=max_size)
        self._lock = Lock()

    def add(self, message: str) -> None:
        """Добавить breadcrumb с timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._breadcrumbs.append(f"[{timestamp}] {message}")

    def get_recent(self, count: int = 20) -> List[str]:
        """Получить последние N breadcrumbs."""
        with self._lock:
            items = list(self._breadcrumbs)
            return items[-count:] if count < len(items) else items

    def get_all(self) -> List[str]:
        """Получить все breadcrumbs."""
        with self._lock:
            return list(self._breadcrumbs)

    def clear(self) -> None:
        """Очистить все breadcrumbs."""
        with self._lock:
            self._breadcrumbs.clear()


# Глобальный экземпляр (синглтон)
_breadcrumb_manager = BreadcrumbManager()


def add_breadcrumb(message: str) -> None:
    """
    Добавить breadcrumb (запись о действии пользователя).

    Используется для отслеживания последовательности действий перед ошибкой.
    """
    _breadcrumb_manager.add(message)


def get_breadcrumbs(count: int = 20) -> List[str]:
    """Получить последние N breadcrumbs."""
    return _breadcrumb_manager.get_recent(count)


def get_crashes_dir() -> Path:
    """Получить директорию для хранения crash-репортов."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    crashes_dir = base / "MindType" / "crashes"
    crashes_dir.mkdir(parents=True, exist_ok=True)
    return crashes_dir


def get_system_info() -> dict:
    """Собрать информацию о системе."""
    from .version import __version__

    info = {
        "app_version": __version__,
        "platform": sys.platform,
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": sys.version,
        "is_frozen": is_app_frozen(),
    }

    # Qt версия (если доступна)
    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        info["qt_version"] = QT_VERSION_STR
        info["pyqt_version"] = PYQT_VERSION_STR
    except ImportError:
        pass

    return info


def sanitize_text(text: str) -> str:
    """
    Удалить чувствительные данные из текста.

    Маскирует:
    - API ключи (OpenAI, Anthropic, Google, OpenRouter, and generic patterns)
    - Лицензионные ключи
    - Bearer tokens
    - Пути пользователя
    - Environment variable values that look like secrets
    """
    import re

    # =================================================================
    # SECURITY: Comprehensive secret redaction patterns
    # Using multiple specific patterns + generic fallbacks
    # =================================================================

    # OpenAI keys: sk-... or sk-proj-...
    text = re.sub(r'sk-[a-zA-Z0-9_-]{20,}', 'sk-***REDACTED***', text)

    # Anthropic keys: sk-ant-...
    text = re.sub(r'sk-ant-[a-zA-Z0-9_-]{20,}', 'sk-ant-***REDACTED***', text)

    # Google API keys: AIza...
    text = re.sub(r'AIza[a-zA-Z0-9_-]{30,}', 'AIza***REDACTED***', text)

    # OpenRouter keys: sk-or-...
    text = re.sub(r'sk-or-[a-zA-Z0-9_-]{20,}', 'sk-or-***REDACTED***', text)

    # Groq keys: gsk_...
    text = re.sub(r'gsk_[a-zA-Z0-9_-]{20,}', 'gsk_***REDACTED***', text)

    # Together AI keys: ...
    text = re.sub(r'[a-f0-9]{64}', '***REDACTED_HEX64***', text)

    # Bearer tokens in headers
    text = re.sub(
        r'[Bb]earer\s+[a-zA-Z0-9_.-]{20,}',
        'Bearer ***REDACTED***',
        text
    )

    # Authorization header values
    text = re.sub(
        r'[Aa]uthorization[=:]\s*["\']?[a-zA-Z0-9_.-]{20,}["\']?',
        'Authorization=***REDACTED***',
        text
    )

    # Generic api_key=value, api-key=value, apikey=value patterns
    text = re.sub(
        r'(api[_-]?key|apikey|secret|token|password|credential)[=:]\s*["\']?[a-zA-Z0-9_.-]{8,}["\']?',
        r'\1=***REDACTED***',
        text,
        flags=re.IGNORECASE
    )

    # Environment variable assignments that look like secrets
    text = re.sub(
        r'(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|OPENROUTER_API_KEY|API_KEY|SECRET_KEY|AUTH_TOKEN)[=:]\s*["\']?[^\s"\']{8,}["\']?',
        r'\1=***REDACTED***',
        text
    )

    # Маскируем лицензионные ключи (MindType format)
    text = re.sub(
        r'MT[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}',
        'MT****-****-****-****',
        text
    )

    # Generic license key patterns (XXXX-XXXX-XXXX-XXXX)
    text = re.sub(
        r'\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}-[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b',
        '****-****-****-****',
        text
    )

    # HMAC secrets (hex strings of 32+ chars that look like secrets)
    text = re.sub(
        r'(hmac|secret|hash)[_-]?[a-fA-F0-9]{32,}',
        r'\1_***REDACTED***',
        text,
        flags=re.IGNORECASE
    )

    # Анонимизируем пути пользователя
    if sys.platform == "win32":
        text = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\<user>', text)
        text = re.sub(r'C:/Users/[^/]+', r'C:/Users/<user>', text)
    else:
        text = re.sub(r'/home/[^/]+', '/home/<user>', text)
        text = re.sub(r'/Users/[^/]+', '/Users/<user>', text)

    # Email addresses (partial masking)
    text = re.sub(
        r'([a-zA-Z0-9._%+-]{2})[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'\1***@\2',
        text
    )

    return text


def generate_crash_report(
    exc_type: type,
    exc_value: BaseException,
    exc_tb,
) -> str:
    """
    Сгенерировать полный crash-репорт.

    Args:
        exc_type: Тип исключения
        exc_value: Значение исключения
        exc_tb: Traceback

    Returns:
        Текст репорта
    """
    # Header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 70,
        "MINDTYPE CRASH REPORT",
        f"Time: {timestamp}",
        "=" * 70,
        "",
    ]

    # System information
    lines.append("--- SYSTEM INFORMATION ---")
    sys_info = get_system_info()
    for key, value in sys_info.items():
        lines.append(f"{key}: {value}")
    lines.append("")

    # Exception
    lines.append("--- EXCEPTION ---")
    lines.append(f"Type: {exc_type.__name__}")
    lines.append(f"Message: {exc_value}")
    lines.append("")

    # Traceback
    lines.append("--- TRACEBACK ---")
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    lines.extend([line.rstrip() for line in tb_lines])
    lines.append("")

    # Recent actions (breadcrumbs)
    recent_breadcrumbs = _breadcrumb_manager.get_recent(20)
    if recent_breadcrumbs:
        lines.append("--- RECENT ACTIONS ---")
        lines.extend(recent_breadcrumbs)
        lines.append("")

    # Instructions
    lines.append("=" * 70)
    lines.append("To submit this report:")
    lines.append(f"1. Send this file to {SUPPORT_EMAIL}")
    lines.append("2. Describe what you were doing before the error")
    lines.append("=" * 70)

    report = "\n".join(lines)

    # Sanitize чувствительные данные
    report = sanitize_text(report)

    return report


def save_crash_report(report: str) -> Path:
    """
    Сохранить crash-репорт в файл.

    Args:
        report: Текст репорта

    Returns:
        Путь к сохранённому файлу
    """
    crashes_dir = get_crashes_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"crash_{timestamp}.txt"
    filepath = crashes_dir / filename

    filepath.write_text(report, encoding="utf-8")
    logger.info(f"Crash report saved to: {filepath}")

    return filepath


# Callback для показа диалога (устанавливается из main.py)
# Сигнатура: (report_text, report_path, exc_info) -> None
_show_crash_dialog: Optional[Callable[[str, Path, tuple], None]] = None


def set_crash_dialog_callback(callback: Callable[[str, Path, tuple], None]) -> None:
    """
    Установить callback для показа диалога при crash.

    Args:
        callback: Функция (report_text, report_path, exc_info) -> None
                  где exc_info = (exc_type, exc_value, exc_tb)
    """
    global _show_crash_dialog
    _show_crash_dialog = callback


def _crash_handler(exc_type: type, exc_value: BaseException, exc_tb) -> None:
    """
    Глобальный обработчик необработанных исключений.
    """
    # Игнорируем KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # Логируем
    logger.critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_tb)
    )

    try:
        # Генерируем репорт
        report = generate_crash_report(exc_type, exc_value, exc_tb)

        # Сохраняем в файл
        report_path = save_crash_report(report)

        # Показываем диалог если установлен callback
        if _show_crash_dialog:
            try:
                exc_info = (exc_type, exc_value, exc_tb)
                _show_crash_dialog(report, report_path, exc_info)
            except Exception as dialog_error:
                logger.error(f"Failed to show crash dialog: {dialog_error}")
                # Fallback: печатаем в консоль
                print("\n" + "=" * 50)
                print("CRITICAL ERROR - Crash report saved to:")
                print(str(report_path))
                print("=" * 50 + "\n")
        else:
            # Нет диалога - печатаем в консоль
            print("\n" + "=" * 50)
            print("CRITICAL ERROR - Crash report saved to:")
            print(str(report_path))
            print("=" * 50 + "\n")

    except Exception as handler_error:
        # Если не удалось обработать - хотя бы выводим в stderr
        logger.error(f"Crash handler failed: {handler_error}")
        sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_crash_handler() -> None:
    """
    Установить глобальный обработчик crash'ей.

    Вызывать в начале main() перед созданием QApplication.
    """
    sys.excepthook = _crash_handler
    logger.info("Crash handler installed")


def uninstall_crash_handler() -> None:
    """Восстановить стандартный обработчик исключений."""
    sys.excepthook = sys.__excepthook__
    logger.info("Crash handler uninstalled")


def get_crash_report_url() -> str:
    """Получить URL для отправки crash-репортов."""
    try:
        from .env import get_api_url
        return get_api_url("/api/crash-report")
    except ImportError:
        return "https://mindtype.space/api/crash-report"


def get_device_id() -> Optional[str]:
    """Получить анонимизированный ID устройства."""
    try:
        from .licensing.license_manager import _get_device_id
        return _get_device_id()
    except Exception:
        return None


def send_crash_report_to_server(
    exc_type: type,
    exc_value: BaseException,
    exc_tb,
) -> Tuple[bool, str]:
    """
    Отправить crash-репорт на сервер.

    Args:
        exc_type: Тип исключения
        exc_value: Значение исключения
        exc_tb: Traceback

    Returns:
        Tuple (success, message)
    """
    try:
        from .version import __version__

        # Формируем данные для отправки
        sys_info = get_system_info()

        # Генерируем traceback строку
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        traceback_str = "".join(tb_lines)

        # Sanitize чувствительные данные
        traceback_str = sanitize_text(traceback_str)
        error_message = sanitize_text(str(exc_value))

        # Санитизируем breadcrumbs перед отправкой
        recent_breadcrumbs = _breadcrumb_manager.get_recent(20)
        sanitized_breadcrumbs = [sanitize_text(b) for b in recent_breadcrumbs]

        payload = {
            "appVersion": __version__,
            "platform": sys.platform,
            "pythonVersion": sys.version.split()[0],
            "osVersion": f"{platform.system()} {platform.release()}",
            "errorType": exc_type.__name__,
            "errorMessage": error_message[:500],  # Ограничиваем длину
            "traceback": traceback_str[:50000],  # Ограничиваем размер
            "breadcrumbs": sanitized_breadcrumbs,
            "deviceId": get_device_id(),
        }

        # Отправляем
        url = get_crash_report_url()
        data = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': f'MindType/{__version__}'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('success'):
                logger.info("Crash report sent successfully")
                return True, "Crash report sent successfully"
            else:
                return False, result.get('message', 'Unknown error')

    except urllib.error.HTTPError as e:
        error_msg = f"Server error: {e.code}"
        logger.warning(f"Failed to send crash report: {error_msg}")
        return False, error_msg

    except urllib.error.URLError as e:
        error_msg = f"Network error: {e.reason}"
        logger.warning(f"Failed to send crash report: {error_msg}")
        return False, error_msg

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.warning(f"Failed to send crash report: {error_msg}")
        return False, error_msg
