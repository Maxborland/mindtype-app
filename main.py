"""
Точка входа для MindType.

Single instance: при запуске второй копии фокусируется первая.
"""

import os
import sys
from pathlib import Path


# cuDNN discovery is performed on demand by the optional local backend.
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
                from ctypes import wintypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    return False
                try:
                    exit_code = wintypes.DWORD()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return exit_code.value == STILL_ACTIVE
                    return False
                finally:
                    kernel32.CloseHandle(handle)
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
