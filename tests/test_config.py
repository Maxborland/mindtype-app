"""
Тесты для модуля config.

Тестирует:
- Значения по умолчанию
- Загрузку и сохранение конфигурации
- Обработку некорректного JSON
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_frozen_build_entitlement_trust_root_ignores_environment(
    monkeypatch,
):
    from app import env

    monkeypatch.setenv("MINDTYPE_LICENSE_PUBLIC_KEY", "attacker-key")
    monkeypatch.setattr(env, "_is_production", lambda: True)
    monkeypatch.setattr(
        env,
        "_PRODUCTION_LICENSE_ED25519_PUBLIC_KEY",
        "release-key",
    )

    assert env._get_license_ed25519_public_key() == "release-key"


class TestDefaultConfig:
    """Тесты для значений по умолчанию."""

    def test_config_default_values(self):
        """_default_config должен возвращать корректные значения по умолчанию."""
        from app.config import _default_config

        defaults = _default_config()

        assert isinstance(defaults, dict)
        assert "model_size" in defaults
        assert "compute_type" in defaults
        assert "device" in defaults
        assert "language" in defaults
        assert "hotkey" in defaults

        # Проверяем конкретные значения
        assert defaults["compute_type"] == "int8"
        assert defaults["device"] == "auto"
        assert defaults["language"] == "ru"
        assert defaults["hotkey"] == "ctrl+alt+v"
        assert defaults["vad_filter"] is True

    def test_config_contains_overlay_settings(self):
        """_default_config должен содержать настройки overlay."""
        from app.config import _default_config

        defaults = _default_config()

        assert "overlay_position" in defaults
        assert "overlay_margin" in defaults
        assert "overlay_wave_gain" in defaults
        assert "overlay_opacity" in defaults

        assert defaults["overlay_position"] == "bottom-center"
        assert defaults["overlay_margin"] == 20

    def test_config_contains_openrouter_settings(self):
        """_default_config должен содержать настройки OpenRouter."""
        from app.config import _default_config

        defaults = _default_config()

        assert "openrouter_api_key" in defaults
        assert "openrouter_model" in defaults
        assert "openrouter_reasoning" in defaults
        assert "openrouter_reasoning_effort" in defaults

        assert defaults["openrouter_api_key"] == ""
        assert defaults["openrouter_reasoning"] is True

    def test_config_contains_postprocessing_settings(self):
        """_default_config должен содержать настройки постобработки."""
        from app.config import _default_config

        defaults = _default_config()

        assert "enable_postprocessing" in defaults
        assert "postprocessing_diarization" in defaults
        assert "postprocessing_punctuation" in defaults
        assert "postprocessing_fillers" in defaults
        assert "postprocessing_normalize" in defaults
        assert "postprocessing_correct" in defaults

        # Все включены по умолчанию
        assert defaults["enable_postprocessing"] is True
        assert defaults["postprocessing_diarization"] is True

    def test_config_contains_assistant_settings(self):
        """_default_config должен содержать настройки ассистента."""
        from app.config import _default_config

        defaults = _default_config()

        assert "assistant_enabled" in defaults
        assert "assistant_hotkey" in defaults
        assert "assistant_use_wake_word" in defaults
        assert "assistant_wake_word" in defaults

        assert defaults["assistant_enabled"] is False
        assert defaults["assistant_hotkey"] == "ctrl+shift+a"


class TestConfigManager:
    """Тесты для ConfigManager."""

    def test_config_manager_init(self):
        """ConfigManager должен инициализироваться."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()

                assert manager.config is not None
                assert isinstance(manager.config, dict)

    def test_config_load_creates_default(self):
        """load должен создавать конфиг по умолчанию если файла нет."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()

                # Должен быть создан файл конфига
                assert manager.config_path.exists()

    def test_config_load_merges_with_defaults(self):
        """load должен объединять сохранённые значения с дефолтами."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "MindType"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "config.json"

            # Создаём частичный конфиг
            partial_config = {"language": "en", "custom_key": "custom_value"}
            config_path.write_text(json.dumps(partial_config), encoding="utf-8")

            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()

                # Должен быть сохранённый язык
                assert manager.config["language"] == "en"
                # И дефолтные значения
                assert "hotkey" in manager.config
                assert "device" in manager.config

    def test_config_save(self):
        """save должен сохранять конфиг в файл."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()
                manager.config["test_key"] = "test_value"
                manager.save()

                # Проверяем файл
                with manager.config_path.open("r", encoding="utf-8") as f:
                    saved = json.load(f)

                assert saved.get("test_key") == "test_value"

    def test_config_update(self):
        """update должен обновлять и сохранять конфиг."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()
                manager.update(language="de", beam_size=10)

                assert manager.config["language"] == "de"
                assert manager.config["beam_size"] == 10

                # Проверяем что сохранилось
                with manager.config_path.open("r", encoding="utf-8") as f:
                    saved = json.load(f)

                assert saved["language"] == "de"
                assert saved["beam_size"] == 10


class TestConfigInvalidJson:
    """Тесты для обработки некорректного JSON."""

    def test_config_invalid_json(self):
        """load должен обрабатывать некорректный JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "MindType"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "config.json"

            # Записываем некорректный JSON
            config_path.write_text("{ invalid json }", encoding="utf-8")

            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                # Не должно падать
                manager = ConfigManager()

                # Должны быть дефолтные значения
                assert manager.config["language"] == "ru"
                assert manager.config["hotkey"] == "ctrl+alt+v"

    def test_config_empty_file(self):
        """load должен обрабатывать пустой файл."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "MindType"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "config.json"

            # Записываем пустой файл
            config_path.write_text("", encoding="utf-8")

            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                # Не должно падать
                manager = ConfigManager()

                # Должны быть дефолтные значения
                assert "language" in manager.config


class TestLegacyModelFormat:
    """Тесты для обработки legacy формата модели."""

    def test_config_fixes_legacy_model_format(self):
        """load должен исправлять legacy формат '[OK] model'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "MindType"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "config.json"

            # Создаём конфиг с legacy форматом
            legacy_config = {"model_size": "[OK] large-v3"}
            config_path.write_text(json.dumps(legacy_config), encoding="utf-8")

            with patch.dict('os.environ', {'APPDATA': tmpdir}):
                from app.config import ConfigManager

                manager = ConfigManager()

                # Должен быть исправленный формат
                assert manager.config["model_size"] == "large-v3"
                assert "[OK]" not in manager.config["model_size"]


class TestBaseDirDetection:
    """Тесты для определения базовой директории."""

    def test_get_base_dir_dev_mode(self):
        """_get_base_dir должен возвращать директорию исходников в dev режиме."""
        from app.config import _get_base_dir

        # В тестах мы в dev режиме
        base_dir = _get_base_dir()

        assert base_dir.exists()
        assert "mindtype-app" in str(base_dir)

    def test_default_models_dir(self):
        """DEFAULT_MODELS_DIR должен указывать на папку models."""
        from app.config import DEFAULT_MODELS_DIR

        assert "models" in str(DEFAULT_MODELS_DIR)
