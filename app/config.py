import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

from .constants import API_KEY_FIELDS
from .env import is_app_frozen, mask_secret

try:
    import keyring
except ImportError:
    keyring = None

logger = logging.getLogger("mindtype.config")


def _get_base_dir() -> Path:
    """Get application base directory (works for both dev and compiled)."""
    if is_app_frozen():
        # Compiled with Nuitka/PyInstaller - use exe location
        return Path(sys.executable).resolve().parent
    else:
        # Development mode - use source location
        return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()

def _get_bundled_models_dir() -> Path:
    """
    Locate models shipped with the app.

    Layouts differ between dev and packagers:
    - Dev: <repo>/models
    - PyInstaller onedir: <exe_dir>/_internal/models (and sometimes <exe_dir>/models)
    - PyInstaller onefile: sys._MEIPASS/models
    - Nuitka: typically <exe_dir>/models
    """
    candidates: list[Path] = [BASE_DIR / "models"]

    if is_app_frozen():
        # PyInstaller onedir commonly puts data under _internal.
        candidates.append(BASE_DIR / "_internal" / "models")

        # PyInstaller onefile extracts to a temp dir pointed by _MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            mp = Path(meipass)
            candidates.append(mp / "models")
            candidates.append(mp / "_internal" / "models")

    for p in candidates:
        try:
            if p.exists():
                return p
        except Exception:
            continue

    # Default to the first candidate even if it doesn't exist yet.
    return candidates[0]


# Models bundled with the app (read-only in many installs, especially on Windows).
BUNDLED_MODELS_DIR = _get_bundled_models_dir()


def _get_default_models_dir() -> Path:
    """
    Get a writable default directory for downloaded transcription models.

    On Windows we keep everything under %APPDATA%\\MindType to avoid
    write-permission issues in Program Files / app install folders.
    """
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

    return base / "MindType" / "models"


# Writable location for downloaded models.
DEFAULT_MODELS_DIR = _get_default_models_dir()


def _get_default_model() -> str:
    """Get default model - use tiny in compiled mode if large not available."""
    if is_app_frozen():
        # In compiled mode, check which models are available
        ggml_large = BUNDLED_MODELS_DIR / "ggml-large-v3.bin"
        ggml_tiny = BUNDLED_MODELS_DIR / "ggml-tiny.bin"

        # Support both whisper.cpp GGML layout and HF-style dirs used by some backends.
        large_dir = BUNDLED_MODELS_DIR / "large-v3"
        tiny_dir = BUNDLED_MODELS_DIR / "tiny"

        if ggml_large.exists() or large_dir.exists():
            return "large-v3"
        if ggml_tiny.exists() or tiny_dir.exists():
            return "tiny"
    return "large-v3"


def _default_config() -> Dict[str, Any]:
    return {
        # Setup wizard state
        "setup_completed": False,            # True после завершения визарда
        "simple_mode": True,                 # True = Simple, False = Advanced
        "use_mindtype_cloud": False,         # True = MindType Cloud, False = свой API ключ
        # Model settings
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
        # Optional override for transcription model download sources (whisper.cpp ggml-*.bin).
        # If empty, the app uses built-in defaults (CDN/mirrors + Hugging Face).
        "model_download_sources": [],
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
        "summary_preset": "pm",              # Пресет промптов: pm, student, generic, call или user-<id>
        "user_presets": {},                  # Пользовательские пресеты: {id: {name, prompts{4 ключа}}}
        "report_format": "both",             # Формат отчёта: html, pdf, both
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
        # OpenRouter транскрипция (STT-эндпоинт, альтернатива whisper.cpp)
        "openrouter_transcribe_model": "",       # STT-модель (openai/whisper-1, ...)
        "openrouter_transcribe_chunk_sec": 30,   # размер чанка аудио, сек
        # Legacy aliases for backward compatibility
        "openrouter_reasoning": True,
        "openrouter_reasoning_effort": "medium",
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

        # Normalize reasoning keys from older config formats.
        if "llm_reasoning_enabled" not in data:
            if "reasoning_enabled" in data:
                merged["llm_reasoning_enabled"] = bool(data["reasoning_enabled"])
            elif "openrouter_reasoning" in data:
                merged["llm_reasoning_enabled"] = bool(data["openrouter_reasoning"])

        if "llm_reasoning_effort" not in data:
            if "reasoning_effort" in data:
                merged["llm_reasoning_effort"] = data["reasoning_effort"]
            elif "openrouter_reasoning_effort" in data:
                merged["llm_reasoning_effort"] = data["openrouter_reasoning_effort"]

        # Keep legacy OpenRouter keys in sync for older code paths/configs.
        merged["openrouter_reasoning"] = bool(merged.get("llm_reasoning_enabled", True))
        merged["openrouter_reasoning_effort"] = merged.get("llm_reasoning_effort", "medium")

        # Fix legacy "[OK] model" format from older versions
        if "model_size" in merged and merged["model_size"].startswith("[OK] "):
            merged["model_size"] = merged["model_size"].replace("[OK] ", "")

        # Загружаем API ключи из keyring если доступно
        if keyring:
            for key_field in API_KEY_FIELDS:
                try:
                    stored_key = keyring.get_password("mindtype", key_field)
                    if stored_key:
                        merged[key_field] = stored_key
                except Exception as e:
                    # SECURITY: Don't log key names or key values.
                    logger.error(
                        "Ошибка загрузки ключа из keyring (redacted): %s",
                        type(e).__name__,
                    )

        # In compiled mode, verify model exists or fallback to available one
        if is_app_frozen():
            model_size = merged.get("model_size", "tiny")
            # Prefer models in the configured models_dir (writable), but also
            # support bundled models shipped with the app.
            search_roots = []
            try:
                search_roots.append(Path(merged.get("models_dir", str(DEFAULT_MODELS_DIR))))
            except Exception:
                pass
            search_roots.append(BUNDLED_MODELS_DIR)

            def _has_model(root: Path, name: str) -> bool:
                # whisper.cpp GGML models
                if (root / f"ggml-{name}.bin").exists():
                    return True
                # HuggingFace-style model dirs (legacy/other backends)
                if (root / name).is_dir() and ((root / name) / "model.bin").exists():
                    return True
                return False

            if not any(_has_model(r, model_size) for r in search_roots):
                # Try to find any available model in any root (GGML first).
                for root in search_roots:
                    try:
                        if not root.exists():
                            continue
                        for f in root.iterdir():
                            if f.is_file() and f.name.startswith("ggml-") and f.name.endswith(".bin"):
                                merged["model_size"] = f.name[len("ggml-"):-len(".bin")]
                                raise StopIteration
                        for subdir in root.iterdir():
                            if subdir.is_dir() and (subdir / "model.bin").exists():
                                merged["model_size"] = subdir.name
                                raise StopIteration
                    except StopIteration:
                        break
                    except Exception:
                        continue

        self.config = merged
        return self.config

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)

        data_to_save = self.config.copy()

        # Сохраняем API ключи в keyring если доступно
        for key_field in API_KEY_FIELDS:
            api_key = self.config.get(key_field, "")
            if api_key and api_key != "key_in_keyring":
                if keyring:
                    try:
                        keyring.set_password("mindtype", key_field, api_key)
                        # Маскируем ключ в JSON файле - никогда не сохраняем plaintext
                        data_to_save[key_field] = "key_in_keyring"
                    except Exception as e:
                        # SECURITY: Don't log key names or key values.
                        logger.error(
                            "Ошибка сохранения ключа в keyring (redacted): %s",
                            type(e).__name__,
                        )
                        # SECURITY: Don't save plaintext key to JSON on keyring failure
                        data_to_save[key_field] = ""
                        logger.warning("API ключ НЕ сохранён из-за ошибки keyring")
                else:
                    # SECURITY: keyring not available - don't save plaintext keys
                    logger.warning("keyring недоступен - API ключ не будет сохранён")
                    data_to_save[key_field] = ""

        with self.config_path.open("w", encoding="utf-8") as fh:
            json.dump(data_to_save, fh, ensure_ascii=False, indent=2)

    def update(self, **kwargs: Any) -> None:
        self.config.update(kwargs)
        self.save()
