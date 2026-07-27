from __future__ import annotations

import ctypes
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Optional


MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _WindowsKillOnCloseJob:
    """Kill assigned native children when the desktop process handle closes."""

    def __init__(self, process: subprocess.Popen[Any], *, kernel32=None):
        api = kernel32 or ctypes.windll.kernel32
        if kernel32 is None:
            api.CreateJobObjectW.argtypes = [
                ctypes.c_void_p,
                wintypes.LPCWSTR,
            ]
            api.CreateJobObjectW.restype = wintypes.HANDLE
            api.SetInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            api.SetInformationJobObject.restype = wintypes.BOOL
            api.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]
            api.AssignProcessToJobObject.restype = wintypes.BOOL
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle.restype = wintypes.BOOL
        handle = api.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._api = api
        self._handle = handle
        information = _JobObjectExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        try:
            if not api.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            process_handle = getattr(process, "_handle", None)
            if not process_handle:
                raise RuntimeError("native process handle is unavailable")
            if not api.AssignProcessToJobObject(handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            api.CloseHandle(handle)
            self._handle = None
            raise

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            self._api.CloseHandle(handle)


def _guard_native_process(
    process: subprocess.Popen[Any],
) -> Optional[_WindowsKillOnCloseJob]:
    if sys.platform != "win32" or not getattr(process, "_handle", None):
        return None
    return _WindowsKillOnCloseJob(process)


@dataclass(frozen=True)
class WhisperServerConfig:
    server_path: Path
    model_path: Path
    threads: int = 4
    use_gpu: bool = True

    def validated(self) -> "WhisperServerConfig":
        server = self.server_path.resolve()
        model = self.model_path.resolve()
        if not server.is_file():
            raise RuntimeError(f"whisper-server не найден: {server}")
        if not model.is_file():
            raise RuntimeError(f"Модель whisper.cpp не найдена: {model}")
        if not 1 <= int(self.threads) <= 128:
            raise ValueError("Количество потоков должно быть от 1 до 128")
        return WhisperServerConfig(server, model, int(self.threads), bool(self.use_gpu))


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WhisperServerRuntime:
    """Own one loopback-only whisper-server and serialize inference requests."""

    def __init__(
        self,
        *,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        connection_factory: Callable[..., http.client.HTTPConnection] = http.client.HTTPConnection,
        port_factory: Callable[[], int] = _free_loopback_port,
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout: float = 60.0,
        upload_chunk_size: int = 1024 * 1024,
        log_path: Optional[Path] = None,
        lifetime_guard_factory: Callable[
            [subprocess.Popen[Any]],
            Optional[Any],
        ] = _guard_native_process,
    ) -> None:
        if upload_chunk_size < 64 * 1024 or upload_chunk_size > 4 * 1024 * 1024:
            raise ValueError("Размер upload chunk должен быть от 64 KiB до 4 MiB")
        self._popen = popen_factory
        self._connect = connection_factory
        self._port_factory = port_factory
        self._token_factory = token_factory
        self._sleep = sleep
        self._startup_timeout = max(0.05, float(startup_timeout))
        self._upload_chunk_size = int(upload_chunk_size)
        self._log_path = log_path or (
            Path(os.getenv("APPDATA", Path.home())) / "MindType" / "whisper-server.log"
        )
        self._lifetime_guard_factory = lifetime_guard_factory

        self._lifecycle_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._cancel_requested = threading.Event()
        self._process: Optional[subprocess.Popen[Any]] = None
        self._process_guard: Optional[Any] = None
        self._config: Optional[WhisperServerConfig] = None
        self._port: Optional[int] = None
        self._request_path: Optional[str] = None
        self._active_connection: Optional[http.client.HTTPConnection] = None
        self._log_file: Optional[BinaryIO] = None
        self.last_connection: Optional[http.client.HTTPConnection] = None

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return self._process is not None and self._process.poll() is None

    def prepare_operation(self) -> None:
        if self._request_lock.locked():
            raise RuntimeError("Другая локальная транскрипция уже выполняется")
        self._cancel_requested.clear()

    def _command(
        self, config: WhisperServerConfig, port: int, request_path: str
    ) -> list[str]:
        command = [
            str(config.server_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--request-path",
            request_path,
            "--inference-path",
            "/inference",
            "-m",
            str(config.model_path),
            "-t",
            str(config.threads),
        ]
        if not config.use_gpu:
            command.append("-ng")
        return command

    def ensure_started(self, config: WhisperServerConfig) -> None:
        normalized = config.validated()
        with self._lifecycle_lock:
            if self._cancel_requested.is_set():
                raise InterruptedError("Транскрипция отменена")
            if (
                self._process is not None
                and self._process.poll() is None
                and self._config == normalized
            ):
                return

            self._stop_locked(grace_timeout=2.0)
            port = self._port_factory()
            request_path = "/" + self._token_factory().strip("/")
            if request_path == "/":
                raise RuntimeError("Не удалось создать приватный маршрут whisper-server")

            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(self._log_path, "ab", buffering=0)
            command = self._command(normalized, port, request_path)
            try:
                process = self._popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=self._log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    ),
                )
                guard = self._lifetime_guard_factory(process)
            except Exception:
                if "process" in locals():
                    self._process = process
                    self._stop_locked(grace_timeout=0.5)
                self._close_log_locked()
                raise
            self._process = process
            self._process_guard = guard
            self._config = normalized
            self._port = port
            self._request_path = request_path

        try:
            self._wait_until_ready()
        except Exception:
            with self._lifecycle_lock:
                self._stop_locked(grace_timeout=0.5)
            raise

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self._startup_timeout
        last_error: Optional[BaseException] = None
        while time.monotonic() < deadline:
            if self._cancel_requested.is_set():
                raise InterruptedError("Транскрипция отменена")
            with self._lifecycle_lock:
                process = self._process
                port = self._port
                request_path = self._request_path
            if process is None or port is None or request_path is None:
                raise RuntimeError("whisper-server не был запущен")
            code = process.poll()
            if code is not None:
                raise RuntimeError(
                    f"whisper-server завершился при запуске (exit code {code}); "
                    f"подробности: {self._log_path}"
                )

            connection = self._connect("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", request_path + "/")
                response = connection.getresponse()
                response.read(1024)
                if int(response.status) == 200:
                    return
                last_error = RuntimeError(f"HTTP {response.status}")
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
            finally:
                connection.close()
            self._sleep(0.1)

        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(
            f"whisper-server не стал готов за {self._startup_timeout:.1f} с{detail}; "
            f"подробности: {self._log_path}"
        )

    def infer(
        self,
        config: WhisperServerConfig,
        audio_path: Path,
        *,
        language: str = "auto",
        beam_size: int = 5,
        word_timestamps: bool = False,
    ) -> dict[str, Any]:
        if not self._request_lock.acquire(blocking=False):
            raise RuntimeError("Другая локальная транскрипция уже выполняется")
        try:
            if self._cancel_requested.is_set():
                raise InterruptedError("Транскрипция отменена")
            audio = audio_path.resolve()
            if not audio.is_file():
                raise RuntimeError(f"Аудиофайл не найден: {audio}")
            self.ensure_started(config)
            return self._send_inference(
                audio,
                language=language,
                beam_size=beam_size,
                word_timestamps=word_timestamps,
            )
        finally:
            self._request_lock.release()

    def _send_inference(
        self,
        audio_path: Path,
        *,
        language: str,
        beam_size: int,
        word_timestamps: bool,
    ) -> dict[str, Any]:
        with self._lifecycle_lock:
            port = self._port
            request_path = self._request_path
        if port is None or request_path is None:
            raise RuntimeError("whisper-server не запущен")

        boundary = "----MindType" + secrets.token_hex(16)
        fields = {
            "response_format": "verbose_json",
            "beam_size": str(max(1, int(beam_size))),
            "token_timestamps": "true" if word_timestamps else "false",
        }
        if language and language != "auto":
            fields["language"] = language

        preamble = self._multipart_preamble(
            boundary, fields, filename=audio_path.name
        )
        footer = f"\r\n--{boundary}--\r\n".encode("ascii")
        content_length = len(preamble) + audio_path.stat().st_size + len(footer)

        connection = self._connect("127.0.0.1", port, timeout=1800)
        with self._lifecycle_lock:
            if self._cancel_requested.is_set():
                connection.close()
                raise InterruptedError("Транскрипция отменена")
            self._active_connection = connection
            self.last_connection = connection

        try:
            connection.putrequest("POST", request_path + "/inference")
            connection.putheader(
                "Content-Type", f"multipart/form-data; boundary={boundary}"
            )
            connection.putheader("Content-Length", str(content_length))
            connection.endheaders()
            connection.send(preamble)
            with open(audio_path, "rb") as source:
                while True:
                    if self._cancel_requested.is_set():
                        raise InterruptedError("Транскрипция отменена")
                    chunk = source.read(self._upload_chunk_size)
                    if not chunk:
                        break
                    connection.send(chunk)
            connection.send(footer)
            if self._cancel_requested.is_set():
                raise InterruptedError("Транскрипция отменена")
            response = connection.getresponse()
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise RuntimeError("Ответ whisper-server превышает допустимый размер")
            if int(response.status) != 200:
                detail = payload.decode("utf-8", errors="replace")[:1000]
                raise RuntimeError(
                    f"whisper-server вернул HTTP {response.status}: {detail}"
                )
            return self._validate_response(payload)
        except InterruptedError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            if self._cancel_requested.is_set():
                raise InterruptedError("Транскрипция отменена") from exc
            raise RuntimeError(f"Ошибка соединения с whisper-server: {exc}") from exc
        finally:
            with self._lifecycle_lock:
                if self._active_connection is connection:
                    self._active_connection = None
            connection.close()

    @staticmethod
    def _multipart_preamble(
        boundary: str, fields: Mapping[str, str], *, filename: str
    ) -> bytes:
        parts: list[bytes] = []
        for name, value in fields.items():
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        safe_filename = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{safe_filename}"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode("utf-8")
        )
        return b"".join(parts)

    @staticmethod
    def _validate_response(payload: bytes) -> dict[str, Any]:
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("whisper-server вернул некорректный JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("whisper-server вернул некорректный объект")
        if not isinstance(data.get("text"), str):
            raise RuntimeError("whisper-server не вернул текст")
        segments = data.get("segments")
        if not isinstance(segments, list):
            raise RuntimeError("whisper-server не вернул сегменты")
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
                raise RuntimeError("whisper-server вернул некорректный сегмент")
            start, end = WhisperServerRuntime._segment_bounds(segment)
            if start is not None and end is not None and start > end:
                raise RuntimeError("whisper-server вернул обратные таймкоды")
            words = segment.get("words")
            if words is not None and not isinstance(words, list):
                raise RuntimeError("whisper-server вернул некорректные word timestamps")
        language = data.get("language")
        if language is not None and not isinstance(language, str):
            raise RuntimeError("whisper-server вернул некорректный язык")
        return data

    @staticmethod
    def _segment_bounds(segment: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
        start = segment.get("start")
        end = segment.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            return float(start), float(end)
        offsets = segment.get("offsets")
        if isinstance(offsets, dict):
            left, right = offsets.get("from"), offsets.get("to")
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return float(left), float(right)
        return None, None

    def cancel(self, grace_timeout: float = 2.0) -> None:
        self._cancel_requested.set()
        with self._lifecycle_lock:
            connection = self._active_connection
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass
            self._stop_locked(grace_timeout=grace_timeout)

    def stop(self, grace_timeout: float = 2.0) -> None:
        with self._lifecycle_lock:
            self._stop_locked(grace_timeout=grace_timeout)

    def _stop_locked(self, grace_timeout: float) -> None:
        process = self._process
        process_guard = self._process_guard
        self._process = None
        self._process_guard = None
        self._config = None
        self._port = None
        self._request_path = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=grace_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=grace_timeout)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
        finally:
            if process_guard is not None:
                process_guard.close()
        self._close_log_locked()

    def _close_log_locked(self) -> None:
        log_file = self._log_file
        self._log_file = None
        if log_file is not None:
            try:
                log_file.close()
            except OSError:
                pass

    def __enter__(self) -> "WhisperServerRuntime":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
