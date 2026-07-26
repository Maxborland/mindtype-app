"""
Запись аудио с поддержкой callback для уровня громкости (waveform).
"""

import queue
import tempfile
import threading
import wave
from collections import deque
from pathlib import Path
from typing import Callable, Deque, List, Optional

import numpy as np
import sounddevice as sd


# Callback для уровня громкости: принимает список нормализованных значений [0.0-1.0]
LevelCallback = Callable[[List[float]], None]


class AudioRecorder:
    def __init__(self, samplerate: int = 16000, channels: int = 1) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = "int16"
        self._stream: Optional[sd.RawInputStream] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=256)
        self._tmp_path: Optional[Path] = None
        self._running = threading.Event()
        self._overflowed = threading.Event()
        self._writer_error: Optional[BaseException] = None
        self._level_callback: Optional[LevelCallback] = None
        # P12: Use deque instead of list for O(1) operations (list.pop(0) was O(n))
        self._level_history: Deque[float] = deque(maxlen=32)
        self._level_history_lock = threading.Lock()  # Защита для _level_history
        self._history_max_len = 32  # Количество баров для waveform

        # Для мониторинга микрофона (без записи)
        self._monitor_stream: Optional[sd.RawInputStream] = None
        self._monitoring = threading.Event()
        self._monitor_callback: Optional[LevelCallback] = None

    def list_input_devices(self) -> List[str]:
        devices = []
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append(f"{idx}: {dev['name']}")
        return devices

    def _callback(self, indata, frames, time, status) -> None:  # type: ignore[override]
        if status:
            # Non-critical statuses are ignored; errors will surface on stop if fatal.
            pass

        data = bytes(indata)
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            self._overflowed.set()

        # Вычисляем уровень громкости для waveform
        if self._level_callback:
            try:
                # Конвертируем bytes в numpy array
                audio_data = np.frombuffer(data, dtype=np.int16)
                # RMS (Root Mean Square) для получения уровня громкости
                if len(audio_data) > 0:
                    rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                    # Нормализуем к [0, 1] (int16 max = 32767)
                    # Уменьшаем делитель для большей чувствительности к тихим звукам
                    normalized = min(1.0, rms / 2000)

                    # Добавляем в историю
                    # P12: deque with maxlen handles overflow automatically (O(1))
                    with self._level_history_lock:
                        self._level_history.append(normalized)
                        # Отправляем копию истории в callback
                        history_copy = list(self._level_history)
                    self._level_callback(history_copy)
            except Exception:
                pass  # Игнорируем ошибки в callback

    def start(
        self,
        device: Optional[int] = None,
        level_callback: Optional[LevelCallback] = None,
    ) -> None:
        if self._running.is_set():
            return

        self._level_callback = level_callback
        with self._level_history_lock:
            self._level_history.clear()
        self._queue = queue.Queue(maxsize=256)
        self._overflowed.clear()
        self._writer_error = None

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        self._tmp_path = Path(tmp.name)
        tmp.close()

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=1024,  # Меньший размер блока для более частых обновлений
                device=device,
                dtype=self.dtype,
                channels=self.channels,
                callback=self._callback,
            )
        except sd.PortAudioError as e:
            self._tmp_path.unlink(missing_ok=True)
            self._tmp_path = None
            raise RuntimeError(f"Не удалось открыть устройство записи: {e}") from e

        def _writer() -> None:
            assert self._tmp_path is not None
            try:
                with wave.open(str(self._tmp_path), "wb") as wf:
                    wf.setnchannels(self.channels)
                    wf.setsampwidth(np.dtype(self.dtype).itemsize)
                    wf.setframerate(self.samplerate)
                    while True:
                        chunk = self._queue.get()
                        if chunk is None:
                            break
                        wf.writeframes(chunk)
            except BaseException as exc:
                self._writer_error = exc

        self._writer_thread = threading.Thread(target=_writer, daemon=True)
        self._writer_thread.start()
        try:
            self._stream.start()
        except sd.PortAudioError as exc:
            self._queue.put(None)
            self._writer_thread.join(timeout=5.0)
            try:
                self._stream.close()
            finally:
                self._stream = None
                self._writer_thread = None
                if self._tmp_path:
                    self._tmp_path.unlink(missing_ok=True)
                self._tmp_path = None
            raise RuntimeError(f"Не удалось запустить устройство записи: {exc}") from exc

        self._running.set()

    def stop(self, timeout: float = 5.0) -> Optional[Path]:
        if not self._running.is_set():
            return None
        self._running.clear()
        self._level_callback = None

        if self._stream:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full as exc:
            raise RuntimeError("Не удалось завершить запись: аудиобуфер переполнен") from exc
        if self._writer_thread:
            self._writer_thread.join(timeout=timeout)
            if self._writer_thread.is_alive():
                raise RuntimeError("Не удалось завершить запись: WAV-файл ещё записывается")
            self._writer_thread = None
        path = self._tmp_path
        self._tmp_path = None
        if self._writer_error:
            if path:
                path.unlink(missing_ok=True)
            error = self._writer_error
            self._writer_error = None
            raise RuntimeError(f"Не удалось записать WAV-файл: {error}") from error
        if self._overflowed.is_set():
            if path:
                path.unlink(missing_ok=True)
            raise RuntimeError("Запись повреждена: аудиобуфер был переполнен")
        return path

    @property
    def recording(self) -> bool:
        return self._running.is_set()

    # === Мониторинг микрофона (без записи) ===

    def _monitor_callback_fn(self, indata, frames, time, status) -> None:
        """Callback для мониторинга уровня микрофона."""
        if not self._monitor_callback:
            return
        try:
            audio_data = np.frombuffer(bytes(indata), dtype=np.int16)
            if len(audio_data) > 0:
                rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                # Нормализуем к [0, 1]
                normalized = min(1.0, rms / 2000)
                self._monitor_callback([normalized])
        except Exception:
            pass

    def start_monitoring(
        self,
        device: Optional[int] = None,
        level_callback: Optional[LevelCallback] = None,
    ) -> bool:
        """Начать мониторинг уровня микрофона без записи."""
        if self._monitoring.is_set():
            return True

        self._monitor_callback = level_callback

        try:
            self._monitor_stream = sd.RawInputStream(
                samplerate=self.samplerate,
                blocksize=2048,
                device=device,
                dtype=self.dtype,
                channels=self.channels,
                callback=self._monitor_callback_fn,
            )
            self._monitoring.set()
            self._monitor_stream.start()
            return True
        except sd.PortAudioError:
            self._monitor_stream = None
            return False

    def stop_monitoring(self) -> None:
        """Остановить мониторинг микрофона."""
        if not self._monitoring.is_set():
            return
        self._monitoring.clear()
        self._monitor_callback = None
        if self._monitor_stream:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None

    @property
    def monitoring(self) -> bool:
        return self._monitoring.is_set()
