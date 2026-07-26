"""
Тесты для модуля crash_reporter.

Тестирует:
- Генерацию crash-репортов
- Сохранение репортов в файл
- Sanitization чувствительных данных
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestGenerateCrashReport:
    """Тесты для generate_crash_report."""

    def test_generate_report_contains_traceback(self):
        """Репорт должен содержать traceback."""
        from app.crash_reporter import generate_crash_report

        try:
            raise ValueError("Test error message")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            report = generate_crash_report(exc_type, exc_value, exc_tb)

        assert "ValueError" in report
        assert "Test error message" in report
        assert "TRACEBACK" in report
        assert "test_generate_report_contains_traceback" in report

    def test_generate_report_contains_system_info(self):
        """Репорт должен содержать системную информацию."""
        from app.crash_reporter import generate_crash_report

        try:
            raise RuntimeError("Test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            report = generate_crash_report(exc_type, exc_value, exc_tb)

        assert "SYSTEM INFORMATION" in report
        assert "app_version" in report
        assert "platform" in report
        assert "python_version" in report

    def test_generate_report_contains_breadcrumbs(self):
        """Репорт должен содержать breadcrumbs если они есть."""
        from app.crash_reporter import (
            add_breadcrumb,
            clear_breadcrumbs,
            generate_crash_report,
        )

        # Очищаем breadcrumbs
        clear_breadcrumbs()

        # Добавляем breadcrumbs
        add_breadcrumb("User clicked button")
        add_breadcrumb("Started recording")

        try:
            raise RuntimeError("Test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            report = generate_crash_report(exc_type, exc_value, exc_tb)

        assert "RECENT ACTIONS" in report
        assert "User clicked button" in report
        assert "Started recording" in report

        # Очищаем после теста
        clear_breadcrumbs()


class TestSaveCrashReport:
    """Тесты для save_crash_report."""

    def test_save_report_creates_file(self):
        """save_crash_report должен создавать файл."""
        from app.crash_reporter import save_crash_report, get_crashes_dir

        report_text = "Test crash report content"

        with patch.object(Path, 'write_text') as mock_write:
            with patch('app.crash_reporter.get_crashes_dir') as mock_dir:
                mock_dir.return_value = Path(tempfile.gettempdir()) / "mindtype_test_crashes"
                mock_dir.return_value.mkdir(parents=True, exist_ok=True)

                result_path = save_crash_report(report_text)

                assert result_path.name.startswith("crash_")
                assert result_path.name.endswith(".txt")

    def test_save_report_uses_correct_directory(self):
        """save_crash_report должен использовать правильную директорию."""
        from app.crash_reporter import get_crashes_dir

        crashes_dir = get_crashes_dir()

        assert "MindType" in str(crashes_dir)
        assert "crashes" in str(crashes_dir)


class TestSanitizeText:
    """Тесты для sanitize_text."""

    def test_sanitize_removes_api_keys(self):
        """sanitize_text должен маскировать API ключи."""
        from app.crash_reporter import sanitize_text

        text = "Error with key sk-1234567890abcdefghijklmnop"
        sanitized = sanitize_text(text)

        assert "sk-1234567890abcdefghijklmnop" not in sanitized
        assert "sk-***REDACTED***" in sanitized

    def test_sanitize_removes_license_keys(self):
        """sanitize_text должен маскировать лицензионные ключи."""
        from app.crash_reporter import sanitize_text

        text = "License: MTAB12-CD34-EF56-GH78"
        sanitized = sanitize_text(text)

        assert "MTAB12-CD34-EF56-GH78" not in sanitized
        assert "MT****-****-****-****" in sanitized

    def test_sanitize_removes_user_paths_windows(self):
        """sanitize_text должен анонимизировать пути пользователя (Windows)."""
        from app.crash_reporter import sanitize_text

        with patch('sys.platform', 'win32'):
            text = r"File: C:\Users\JohnDoe\Documents\file.txt"
            sanitized = sanitize_text(text)

            assert "JohnDoe" not in sanitized
            assert "<user>" in sanitized

    def test_sanitize_removes_user_paths_linux(self):
        """sanitize_text должен анонимизировать пути пользователя (Linux)."""
        from app.crash_reporter import sanitize_text

        with patch('sys.platform', 'linux'):
            text = "File: /home/johndoe/documents/file.txt"
            sanitized = sanitize_text(text)

            assert "johndoe" not in sanitized
            assert "<user>" in sanitized


class TestBreadcrumbs:
    """Тесты для breadcrumbs."""

    def test_add_breadcrumb(self):
        """add_breadcrumb должен добавлять записи."""
        from app.crash_reporter import add_breadcrumb, clear_breadcrumbs, get_breadcrumbs

        clear_breadcrumbs()

        add_breadcrumb("Test action 1")
        add_breadcrumb("Test action 2")

        breadcrumbs = get_breadcrumbs()
        assert len(breadcrumbs) == 2
        assert "Test action 1" in breadcrumbs[0]
        assert "Test action 2" in breadcrumbs[1]

        clear_breadcrumbs()

    def test_breadcrumbs_limit(self):
        """Breadcrumbs должны ограничиваться максимальным количеством."""
        from app.crash_reporter import (
            MAX_BREADCRUMBS,
            add_breadcrumb,
            clear_breadcrumbs,
            get_breadcrumbs,
        )

        # Добавляем больше чем лимит
        clear_breadcrumbs()
        for i in range(MAX_BREADCRUMBS + 10):
            add_breadcrumb(f"Action {i}")

        # Лимит применяется после добавления
        breadcrumbs = get_breadcrumbs(MAX_BREADCRUMBS + 10)
        assert len(breadcrumbs) == MAX_BREADCRUMBS

        # Проверяем что сохранились последние элементы
        assert f"Action {MAX_BREADCRUMBS + 9}" in breadcrumbs[-1]
        assert "Action 10" in breadcrumbs[0]

        # Очищаем после теста
        clear_breadcrumbs()


class TestCrashHandler:
    """Тесты для crash handler."""

    def test_install_crash_handler(self):
        """install_crash_handler должен устанавливать обработчик."""
        from app.crash_reporter import install_crash_handler, uninstall_crash_handler, _crash_handler

        original_hook = sys.excepthook

        install_crash_handler()
        assert sys.excepthook == _crash_handler

        uninstall_crash_handler()
        assert sys.excepthook == sys.__excepthook__

        # Восстанавливаем оригинальный hook
        sys.excepthook = original_hook

    def test_crash_handler_ignores_keyboard_interrupt(self):
        """Crash handler должен игнорировать KeyboardInterrupt."""
        from app.crash_reporter import _crash_handler

        with patch('sys.__excepthook__') as mock_hook:
            _crash_handler(KeyboardInterrupt, KeyboardInterrupt(), None)
            mock_hook.assert_called_once()


class TestGetSystemInfo:
    """Тесты для get_system_info."""

    def test_get_system_info_returns_dict(self):
        """get_system_info должен возвращать словарь."""
        from app.crash_reporter import get_system_info

        info = get_system_info()

        assert isinstance(info, dict)
        assert "app_version" in info
        assert "platform" in info
        assert "python_version" in info
        assert "is_frozen" in info

    def test_get_system_info_contains_version(self):
        """get_system_info должен содержать версию приложения."""
        from app.crash_reporter import get_system_info
        from app.version import __version__

        info = get_system_info()

        assert info["app_version"] == __version__


class TestSendCrashReportToServer:
    """Тесты для send_crash_report_to_server."""

    def test_send_crash_report_success(self):
        """Успешная отправка crash-репорта на сервер."""
        from app.crash_reporter import send_crash_report_to_server
        import json

        # Мокаем urllib.request.urlopen
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"success": True}).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        try:
            raise ValueError("Test error")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

            with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
                success, message = send_crash_report_to_server(exc_type, exc_value, exc_tb)

            assert success is True
            assert "success" in message.lower()

            # Проверяем что запрос был отправлен
            mock_urlopen.assert_called_once()
            call_args = mock_urlopen.call_args
            request = call_args[0][0]

            # Проверяем что данные корректные
            sent_data = json.loads(request.data.decode('utf-8'))
            assert sent_data["errorType"] == "ValueError"
            assert "Test error" in sent_data["errorMessage"]
            assert "appVersion" in sent_data
            assert "platform" in sent_data

    def test_send_crash_report_network_error(self):
        """Обработка сетевой ошибки при отправке."""
        from app.crash_reporter import send_crash_report_to_server
        import urllib.error

        try:
            raise RuntimeError("Test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

            with patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
                success, message = send_crash_report_to_server(exc_type, exc_value, exc_tb)

            assert success is False
            assert "Network error" in message

    def test_send_crash_report_server_error(self):
        """Обработка ошибки сервера при отправке."""
        from app.crash_reporter import send_crash_report_to_server
        import urllib.error

        try:
            raise RuntimeError("Test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

            with patch('urllib.request.urlopen') as mock_urlopen:
                error = urllib.error.HTTPError(
                    url="http://test.com",
                    code=500,
                    msg="Internal Server Error",
                    hdrs={},
                    fp=None
                )
                mock_urlopen.side_effect = error
                success, message = send_crash_report_to_server(exc_type, exc_value, exc_tb)

            assert success is False
            assert "500" in message

    def test_send_crash_report_includes_breadcrumbs(self):
        """Crash-репорт должен включать breadcrumbs."""
        from app.crash_reporter import (
            add_breadcrumb,
            clear_breadcrumbs,
            send_crash_report_to_server,
        )
        import json

        # Очищаем и добавляем breadcrumbs
        clear_breadcrumbs()
        add_breadcrumb("Action 1")
        add_breadcrumb("Action 2")

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"success": True}).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        try:
            raise ValueError("Test")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

            with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
                send_crash_report_to_server(exc_type, exc_value, exc_tb)

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            sent_data = json.loads(request.data.decode('utf-8'))

            assert "breadcrumbs" in sent_data
            assert len(sent_data["breadcrumbs"]) == 2
            assert "Action 1" in sent_data["breadcrumbs"][0]
            assert "Action 2" in sent_data["breadcrumbs"][1]

        clear_breadcrumbs()

    def test_send_crash_report_sanitizes_data(self):
        """Crash-репорт должен санитизировать чувствительные данные."""
        from app.crash_reporter import send_crash_report_to_server
        import json

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"success": True}).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        try:
            # Создаём ошибку с API ключом в сообщении
            raise ValueError("Error with API key sk-1234567890abcdefghijklmnop")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

            with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
                send_crash_report_to_server(exc_type, exc_value, exc_tb)

            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            sent_data = json.loads(request.data.decode('utf-8'))

            # API ключ должен быть замаскирован
            assert "sk-1234567890abcdefghijklmnop" not in sent_data["errorMessage"]
            assert "sk-***REDACTED***" in sent_data["errorMessage"]


class TestGetCrashReportUrl:
    """Тесты для get_crash_report_url."""

    def test_get_crash_report_url_returns_string(self):
        """get_crash_report_url должен возвращать URL строку."""
        from app.crash_reporter import get_crash_report_url

        url = get_crash_report_url()

        assert isinstance(url, str)
        assert url.startswith("http")
        assert "/api/crash-report" in url

    def test_get_crash_report_url_uses_env(self):
        """get_crash_report_url должен использовать переменную окружения."""
        from app.crash_reporter import get_crash_report_url

        with patch('app.env.get_api_url') as mock_get_api_url:
            mock_get_api_url.return_value = "https://custom.example.com/api/crash-report"
            url = get_crash_report_url()

            assert url == "https://custom.example.com/api/crash-report"


class TestGetDeviceId:
    """Тесты для get_device_id."""

    def test_get_device_id_returns_string_or_none(self):
        """get_device_id должен возвращать строку или None."""
        from app.crash_reporter import get_device_id

        device_id = get_device_id()

        assert device_id is None or isinstance(device_id, str)

    def test_get_device_id_handles_error(self):
        """get_device_id должен возвращать None при ошибке."""
        from app.crash_reporter import get_device_id

        with patch('app.licensing.license_manager._get_device_id') as mock_device_id:
            mock_device_id.side_effect = Exception("Test error")
            result = get_device_id()

            # Должен вернуть None вместо исключения
            assert result is None
