import json
import os
import sys
import logging
from pathlib import Path
from typing import Any, Dict
from .env import mask_secret

try:
    import keyring
except ImportError:
    keyring = None

logger = logging.getLogger("mindtype.config")


def _get_base_dir() -> Path:
    """Get application base directory (works for both dev and compiled)."""
    # Check for Nuitka (__compiled__) or PyInstaller (frozen)
    if getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__"):
        # Compiled with Nuitka/PyInstaller - use exe location
        return Path(sys.executable).resolve().parent
    else:
        # Development mode - use source location
        return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
DEFAULT_MODELS_DIR = BASE_DIR / "models"


def _get_default_model() -> str:
    """Get default model - use tiny in compiled mode if large not available."""
    if getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__"):
        # In compiled mode, check which models are available
        tiny_path = DEFAULT_MODELS_DIR / "tiny"
        large_path = DEFAULT_MODELS_DIR / "large-v3"
        if large_path.exists():
            return "large-v3"
        elif tiny_path.exists():
            return "tiny"
    return "large-v3"


def _default_config() -> Dict[str, Any]:
    return {
        "model_size": _get_default_model(),
        "compute_type": "int8",
        "device": "auto",
        "language": "ru",
        "ui_language": "ru",                 # Язык интерфейса приложения
        "beam_size": 5,
        "vad_filter": True,
        "hotkey": "ctrl+alt+v",
        "microphone": None,
        "cpu_threads": 4,
        "num_workers": 1,
        "models_dir": str(DEFAULT_MODELS_DIR),
        "accelerator": "auto",               # auto, npu, gpu, cpu
        "transcriber_backend": "whisper_cpp", # whisper_cpp, faster_whisper, onnx
        # Overlay настройки
        "overlay_position": "bottom-center", # bottom-right, bottom-left, top-right, top-left, bottom-center, top-center
        "overlay_margin": 20,                # Отступ от края экрана
        "overlay_wave_gain": 1.5,            # Усиление волн (1.0 - 10.0)
        "overlay_opacity": 230,              # Прозрачность фона (0-255)
        # Саммаризация (мульти-провайдер)
        "llm_provider": "openrouter",        # openai, anthropic, gemini, ollama, openrouter
        "llm_reasoning_enabled": True,       # Включить reasoning mode
        "llm_reasoning_effort": "medium",    # low / medium / high
        "summary_preset": "pm",              # Пресет промптов: pm, student, generic
        # OpenAI
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        # Anthropic
        "anthropic_api_key": "",
        "anthropic_model": "claude-3-haiku-20240307",
        # Google Gemini
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash",
        # Ollama (локальный)
        "ollama_base_url": "http://localhost:11434",
        "ollama_model": "",
        # OpenRouter (private-only)
        "openrouter_api_key": "",
        "openrouter_model": "",
        # Постобработка транскрипций
        "enable_postprocessing": True,      # Включить постобработку
        "postprocessing_diarization": True,  # Диаризация спикеров (MFCC + sklearn, лёгкая)
        "postprocessing_punctuation": True,  # Восстановление пунктуации
        "postprocessing_fillers": True,      # Удаление слов-паразитов
        "postprocessing_normalize": True,    # Нормализация чисел/дат
        "postprocessing_correct": True,      # Коррекция ошибок ASR
        # Голосовой ассистент
        "assistant_enabled": False,          # Включить голосового ассистента
        "assistant_hotkey": "ctrl+shift+a",  # Горячие клавиши для активации ассистента
        "assistant_use_wake_word": True,     # Использовать wake word
        "assistant_wake_word": "hey_jarvis", # Wake word для активации
        "assistant_wake_threshold": 0.5,     # Порог детекции wake word (0.0-1.0)
        "assistant_beep_on_wake": True,      # Звуковой сигнал при активации
        "assistant_tts_voice": "ru-RU-DmitryNeural",  # Голос TTS
        "assistant_tts_rate": 0,             # Скорость речи (-50 до +50)
        "assistant_tts_language": "ru",      # Язык TTS
        "assistant_personality": "friendly",  # Шаблон личности
        "assistant_system_prompt": "Ты дружелюбный голосовой ассистент. Отвечай кратко и по делу.",
        "assistant_normalize_numbers": True,  # Нормализовать числа
        "assistant_normalize_dates": True,    # Нормализовать даты
        "assistant_normalize_translit": True, # Транслитерация
        "assistant_normalize_abbrev": True,   # Аббревиатуры
        "assistant_recording_timeout": 3.0,   # Таймаут записи (сек)
    }


class ConfigManager:
    def __init__(self) -> None:
        base = Path(os.getenv("APPDATA", Path.home()))
        self.config_dir = base / "MindType"
        self.config_path = self.config_dir / "config.json"
        self.config: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            self.config = _default_config()
            self.save()
            return self.config
        try:
            with self.config_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        merged = _default_config()
        merged.update(data)

        # Fix legacy "[OK] model" format from older versions
        if "model_size" in merged and merged["model_size"].startswith("[OK] "):
            merged["model_size"] = merged["model_size"].replace("[OK] ", "")

        # Загружаем API ключи из keyring если доступно
        if keyring:
            api_key_fields = [
                "openai_api_key",
                "anthropic_api_key",
                "gemini_api_key",
                "openrouter_api_key",
            ]
            for key_field in api_key_fields:
                try:
                    stored_key = keyring.get_password("mindtype", key_field)
                    if stored_key:
                        merged[key_field] = stored_key
                except Exception as e:
                    logger.error(f"Ошибка загрузки {key_field} из keyring: {e}")

        # In compiled mode, verify model exists or fallback to available one
        if getattr(sys, 'frozen', False) or hasattr(sys, "__compiled__"):
            model_size = merged.get("model_size", "tiny")
            model_path = DEFAULT_MODELS_DIR / model_size
            if not model_path.exists():
                # Try to find any available model
                if DEFAULT_MODELS_DIR.exists():
                    for subdir in DEFAULT_MODELS_DIR.iterdir():
                        if subdir.is_dir() and (subdir / "model.bin").exists():
                            merged["model_size"] = subdir.name
                            break

        self.config = merged
        return self.config

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Сохраняем API ключи в keyring если доступно
        api_key_fields = [
            "openai_api_key",
            "anthropic_api_key",
            "gemini_api_key",
            "openrouter_api_key",
        ]

        data_to_save = self.config.copy()

        for key_field in api_key_fields:
            api_key = self.config.get(key_field, "")
            if keyring and api_key and api_key != "key_in_keyring":
                try:
                    keyring.set_password("mindtype", key_field, api_key)
                    # Маскируем ключ в JSON файле
                    data_to_save[key_field] = "key_in_keyring"
                except Exception as e:
                    logger.error(f"Ошибка сохранения {key_field} в keyring: {e}")

        with self.config_path.open("w", encoding="utf-8") as fh:
            json.dump(data_to_save, fh, ensure_ascii=False, indent=2)

    def update(self, **kwargs: Any) -> None:
        self.config.update(kwargs)
        self.save()


