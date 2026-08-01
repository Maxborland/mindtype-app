"""Windows cuDNN discovery used immediately before local model loading."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_DIRECTORY_HANDLES: list[object] = []


def _prepend_windows_dll_dir(dir_path: Path) -> None:
    if sys.platform != "win32":
        return
    if not dir_path.exists():
        return
    try:
        if hasattr(os, "add_dll_directory"):
            handle = os.add_dll_directory(str(dir_path))
            _DLL_DIRECTORY_HANDLES.append(handle)
    except Exception:
        pass
    os.environ["PATH"] = str(dir_path) + os.pathsep + os.environ.get("PATH", "")


def ensure_cudnn_on_windows() -> None:
    if sys.platform != "win32":
        return

    explicit = os.environ.get("MINDTYPE_CUDNN_DIR") or os.environ.get("CUDNN_PATH") or os.environ.get("CUDNN_HOME")
    candidates: list[Path] = []
    if explicit:
        p = Path(explicit)
        candidates.extend([p, p / "bin"])

    base_dir = Path(sys.executable).resolve().parent if (getattr(sys, "frozen", False) or hasattr(sys, "__compiled__")) else Path(__file__).resolve().parent
    candidates.extend([
        base_dir / "vendor" / "cudnn" / "bin",
        base_dir / "cudnn" / "bin",
    ])

    seen_roots: set[str] = set()
    for key in ["CUDA_PATH"] + sorted(k for k in os.environ.keys() if k.startswith("CUDA_PATH_V")):
        root = os.environ.get(key)
        if not root or root in seen_roots:
            continue
        seen_roots.add(root)
        candidates.append(Path(root) / "bin")

    cudnn_base = Path(r"C:\Program Files\NVIDIA\CUDNN")
    if cudnn_base.is_dir():
        for v_dir in sorted(cudnn_base.iterdir(), key=lambda p: p.name, reverse=True):
            if v_dir.is_dir() and v_dir.name.startswith("v"):
                bin_dir = v_dir / "bin"
                if bin_dir.is_dir():
                    for cuda_ver in sorted(bin_dir.iterdir(), key=lambda p: p.name, reverse=True):
                        if cuda_ver.is_dir():
                            candidates.append(cuda_ver)

    try:
        if getattr(sys, "frozen", False):
            site_packages = [Path(sys.executable).parent / "_internal"]
        else:
            site_packages = [Path(p) for p in sys.path if "site-packages" in p]

        for sp in site_packages:
            if not sp.exists():
                continue
            nvidia_dir = sp / "nvidia"
            if nvidia_dir.is_dir():
                for root, dirs, files in os.walk(nvidia_dir):
                    if "bin" in dirs:
                        bin_path = Path(root) / "bin"
                        candidates.append(bin_path)
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
