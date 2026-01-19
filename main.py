"""
Точка входа для MindType.

Single instance: при запуске второй копии фокусируется первая.
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
        pass
    os.environ["PATH"] = str(dir_path) + os.pathsep + os.environ.get("PATH", "")


def _ensure_cudnn_on_windows() -> None:
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


_ensure_cudnn_on_windows()

os.environ["NUMBA_DISABLE_JIT"] = "0"
os.environ["NUMBA_CUDA_DRIVER"] = ""


class SingleInstance:
    """Ensure only one instance of the application runs."""

    def __init__(self, app_id: str = "MindType"):
        self.app_id = app_id
        self._lock_file = None
        self._lock_path = Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "MindType" / ".lock"

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running."""
        if pid <= 0:
            return False
        try:
            if sys.platform == "win32":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError):
            return False
        except Exception:
            return True  # Assume running if we can't check

    def _clean_stale_lock(self) -> bool:
        """Remove stale lock file if the process is not running. Returns True if cleaned."""
        if not self._lock_path.exists():
            return False

        try:
            with open(self._lock_path, "r") as f:
                content = f.read().strip()
                if content:
                    pid = int(content)
                    if not self._is_process_running(pid):
                        self._lock_path.unlink(missing_ok=True)
                        return True
        except (ValueError, IOError, OSError):
            # Can't read PID or file is corrupted - try to remove
            try:
                self._lock_path.unlink(missing_ok=True)
                return True
            except Exception:
                pass
        return False

    def try_lock(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)

            # Clean stale lock first
            self._clean_stale_lock()

            if sys.platform == "win32":
                # Windows: use exclusive file lock
                import msvcrt
                self._lock_file = open(self._lock_path, "w")
                try:
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    self._lock_file.write(str(os.getpid()))
                    self._lock_file.flush()
                    return True
                except (IOError, OSError):
                    self._lock_file.close()
                    self._lock_file = None
                    return False
            else:
                # Unix: use fcntl
                import fcntl
                self._lock_file = open(self._lock_path, "w")
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._lock_file.write(str(os.getpid()))
                    self._lock_file.flush()
                    return True
                except (IOError, OSError):
                    self._lock_file.close()
                    self._lock_file = None
                    return False
        except Exception:
            return False

    def release(self) -> None:
        """Release the lock."""
        if self._lock_file:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            finally:
                self._lock_file = None
                try:
                    self._lock_path.unlink(missing_ok=True)
                except Exception:
                    pass


def focus_existing_window() -> bool:
    """Try to focus the existing MindType window. Returns True if found."""
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        # Find window by class or title
        hwnd = user32.FindWindowW(None, "MindType")
        if hwnd:
            # Restore if minimized
            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)
            # Bring to front
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass

    return False


def run_app():
    """Запуск приложения с проверкой single instance."""
    import atexit
    import signal

    single = SingleInstance()

    if not single.try_lock():
        # Another instance is running
        print("MindType is already running. Focusing existing window...")
        focus_existing_window()
        sys.exit(0)

    # Register cleanup on exit and signals
    atexit.register(single.release)

    def signal_handler(signum, frame):
        single.release()
        sys.exit(0)

    # Handle termination signals
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGHUP, signal_handler)

    try:
        from app.main import main
        main()
    finally:
        single.release()


if __name__ == "__main__":
    run_app()
