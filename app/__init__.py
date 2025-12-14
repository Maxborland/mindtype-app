"""
MindType application package.

Важно (Windows + Python 3.8+):
Python больше не использует PATH для поиска DLL так, как раньше (безопасный режим
загрузки). Для CUDA/cuDNN DLL, установленных через pip-пакеты NVIDIA в venv,
нужно явно добавить директории через os.add_dll_directory() ДО импорта модулей,
которые тянут GPU-библиотеки (ctranslate2/onnxruntime и т.п.).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_DIR_HANDLES: list[object] = []


def _add_dll_dir(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    try:
        # На Windows сохраняем handle, иначе директория может "отвалиться"
        _DLL_DIR_HANDLES.append(os.add_dll_directory(str(path)))
    except Exception:
        # На не-Windows или если add_dll_directory недоступен — просто игнорируем
        pass


def ensure_nvidia_dll_dirs() -> None:
    """Добавить DLL директории NVIDIA (cudnn/cublas/cuda_runtime) из venv в search path."""
    if sys.platform != "win32":
        return

    base = Path(sys.prefix)
    nvidia_root = base / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.exists():
        return

    for rel in (
        ("cudnn", "bin"),
        ("cublas", "bin"),
        ("cuda_runtime", "bin"),
    ):
        _add_dll_dir(nvidia_root.joinpath(*rel))


# Вызываем сразу при импорте пакета, чтобы последующие submodules могли импортироваться без ошибок DLL.
ensure_nvidia_dll_dirs()









