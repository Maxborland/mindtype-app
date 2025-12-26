"""
Точка входа (dev) для MindType.

Важно: на Windows CUDA-зависимые библиотеки (ctranslate2 / faster-whisper) могут
падать на старте, если cuDNN DLL не находится в поисковом пути (PATH / add_dll_directory).
Здесь мы НЕ отключаем GPU, а лишь пытаемся добавить cuDNN/bin в DLL search path,
если пользователь установил cuDNN (или положил DLL рядом с проектом).
"""

import os
import sys
from pathlib import Path


def _prepend_windows_dll_dir(dir_path: Path) -> None:
    if sys.platform != "win32":
        return
    if not dir_path.exists():
        return
    try:
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(dir_path))
    except Exception:
        # add_dll_directory может быть недоступен/запрещён политиками — не падаем
        pass
    os.environ["PATH"] = str(dir_path) + os.pathsep + os.environ.get("PATH", "")


def _ensure_cudnn_on_windows() -> None:
    if sys.platform != "win32":
        return

    # 1) Явно заданная пользователем папка
    explicit = os.environ.get("MINDTYPE_CUDNN_DIR") or os.environ.get("CUDNN_PATH") or os.environ.get("CUDNN_HOME")
    candidates: list[Path] = []
    if explicit:
        p = Path(explicit)
        candidates.extend([p, p / "bin"])

    # 2) Локальная папка рядом с проектом/экзешником (удобно для переносимости)
    base_dir = Path(sys.executable).resolve().parent if (getattr(sys, "frozen", False) or hasattr(sys, "__compiled__")) else Path(__file__).resolve().parent
    candidates.extend([
        base_dir / "vendor" / "cudnn" / "bin",
        base_dir / "cudnn" / "bin",
    ])

    # 3) CUDA Toolkit bin (CUDA_PATH, CUDA_PATH_V*)
    seen_roots: set[str] = set()
    for key in ["CUDA_PATH"] + sorted(k for k in os.environ.keys() if k.startswith("CUDA_PATH_V")):
        root = os.environ.get(key)
        if not root or root in seen_roots:
            continue
        seen_roots.add(root)
        candidates.append(Path(root) / "bin")

    # 4) NVIDIA cuDNN standalone install: C:\Program Files\NVIDIA\CUDNN\v9.xx\bin\<cuda_ver>\
    #    Пытаемся найти версию для CUDA 12.x (12.9, 12.8, 12.1 и т.д.)
    cudnn_base = Path(r"C:\Program Files\NVIDIA\CUDNN")
    if cudnn_base.is_dir():
        # Ищем папки v9.xx (сортируем в обратном порядке, чтобы новые версии были первыми)
        for v_dir in sorted(cudnn_base.iterdir(), key=lambda p: p.name, reverse=True):
            if v_dir.is_dir() and v_dir.name.startswith("v"):
                bin_dir = v_dir / "bin"
                if bin_dir.is_dir():
                    # Внутри bin/ ищем подпапки 12.x, 11.x и т.д.
                    for cuda_ver in sorted(bin_dir.iterdir(), key=lambda p: p.name, reverse=True):
                        if cuda_ver.is_dir():
                            candidates.append(cuda_ver)

    # 5) Поиск в site-packages/nvidia (если установлены pip-пакеты nvidia-*)
    #    Обычно это venv/Lib/site-packages/nvidia/.../bin
    try:
        # Пытаемся найти папку site-packages относительно executable или __file__
        if getattr(sys, "frozen", False):
            # В скомпилированном виде (one-dir) это обычно _internal или рядом
            site_packages = [Path(sys.executable).parent / "_internal"]
        else:
            # В dev-режиме: .../venv/Lib/site-packages
            # sys.path содержит пути, поищем там
            site_packages = [Path(p) for p in sys.path if "site-packages" in p]

        for sp in site_packages:
            if not sp.exists():
                continue
            nvidia_dir = sp / "nvidia"
            if nvidia_dir.is_dir():
                # Рекурсивно ищем bin папки
                for root, dirs, files in os.walk(nvidia_dir):
                    if "bin" in dirs:
                        bin_path = Path(root) / "bin"
                        candidates.append(bin_path)
                    # Иногда DLL лежат прямо в корне пакета (например, cudnn/bin может не быть, а lib есть)
                    # Но обычно структура nvidia/<package>/bin или nvidia/<package>/lib
    except Exception:
        pass

    dll_names = ["cudnn_ops64_9.dll", "cudnn64_9.dll", "cudnn_ops_infer64_8.dll", "cudnn64_8.dll"]
    for d in candidates:
        try:
            if not d.is_dir():
                continue
            if any((d / name).exists() for name in dll_names):
                _prepend_windows_dll_dir(d)
                break
        except Exception:
            continue


# Добавляем cuDNN/bin в DLL search path (если найден)
_ensure_cudnn_on_windows()

# Отключаем CUDA только для numba (используется librosa/feature extraction); к GPU Whisper это не относится.
os.environ["NUMBA_DISABLE_JIT"] = "0"  # JIT включён, но без CUDA
os.environ["NUMBA_CUDA_DRIVER"] = ""  # Отключаем CUDA драйвер для numba

from app.main import main


if __name__ == "__main__":
    main()


