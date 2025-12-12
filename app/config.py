import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


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
        # Overlay настройки
        "overlay_position": "bottom-center", # bottom-right, bottom-left, top-right, top-left, bottom-center, top-center
        "overlay_margin": 20,                # Отступ от края экрана
        "overlay_wave_gain": 1.5,            # Усиление волн (1.0 - 10.0)
        "overlay_opacity": 230,              # Прозрачность фона (0-255)
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
        with self.config_path.open("w", encoding="utf-8") as fh:
            json.dump(self.config, fh, ensure_ascii=False, indent=2)

    def update(self, **kwargs: Any) -> None:
        self.config.update(kwargs)
        self.save()


