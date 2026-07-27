"""Typed Windows audio-source lifecycle for microphone and WASAPI loopback."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol

import numpy as np


class AudioSourceKind(str, Enum):
    MICROPHONE = "microphone"
    SYSTEM = "system"
    MICROPHONE_SYSTEM = "microphone_system"


class AudioCaptureStatus(str, Enum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class AudioDevice:
    device_id: str
    name: str
    source: AudioSourceKind


@dataclass(frozen=True)
class RecordedTrack:
    source: AudioSourceKind
    path: Path
    sample_rate: int
    channels: int
    started_at_monotonic_ns: int
    ended_at_monotonic_ns: int

    def canonical_channel(self, *, sha256: Optional[str] = None) -> dict[str, Any]:
        channel: dict[str, Any] = {
            "source": self.source.value,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "started_at_monotonic_ns": self.started_at_monotonic_ns,
            "ended_at_monotonic_ns": self.ended_at_monotonic_ns,
        }
        if sha256 is not None:
            channel["sha256"] = sha256
        return channel


@dataclass(frozen=True)
class AudioCaptureResult:
    status: AudioCaptureStatus
    track: Optional[RecordedTrack]
    error: Optional[str] = None


@dataclass(frozen=True)
class MultiTrackCapture:
    results: tuple[AudioCaptureResult, ...]

    @property
    def interrupted(self) -> bool:
        return any(
            result.status is AudioCaptureStatus.INTERRUPTED
            for result in self.results
        )

    @property
    def tracks(self) -> tuple[RecordedTrack, ...]:
        return tuple(
            result.track for result in self.results if result.track is not None
        )


class _SoundCardBackend(Protocol):
    def all_microphones(self, *, include_loopback: bool) -> list[Any]: ...


def _load_soundcard() -> _SoundCardBackend:
    try:
        import soundcard
    except ImportError as exc:
        raise RuntimeError(
            "Windows system audio is unavailable: SoundCard is not installed"
        ) from exc
    return soundcard


def _device_id(device: Any) -> str:
    identifier = getattr(device, "id", None)
    if identifier is None:
        identifier = getattr(device, "_id", None)
    if identifier is None:
        raise RuntimeError("WASAPI device has no stable backend identifier")
    return str(identifier)


class SystemAudioRecorder:
    """Record one WASAPI loopback endpoint to a separate stereo WAV."""

    def __init__(
        self,
        *,
        backend: Optional[_SoundCardBackend] = None,
        temp_dir: Optional[Path] = None,
        sample_rate: int = 48_000,
        channels: int = 2,
        block_frames: int = 1_024,
        queue_blocks: int = 256,
    ) -> None:
        if sample_rate <= 0 or channels <= 0 or block_frames <= 0:
            raise ValueError("audio dimensions must be positive")
        if queue_blocks <= 0:
            raise ValueError("queue_blocks must be positive")
        self._backend = backend
        self._temp_dir = Path(temp_dir) if temp_dir is not None else None
        self.sample_rate = sample_rate
        self.channels = channels
        self.block_frames = block_frames
        self._queue_blocks = queue_blocks
        self._queue: queue.Queue[Optional[bytes]] = queue.Queue(
            maxsize=queue_blocks
        )
        self._stop_requested = threading.Event()
        self._active = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._path: Optional[Path] = None
        self._started_at_ns: Optional[int] = None
        self._ended_at_ns: Optional[int] = None
        self._capture_error: Optional[str] = None
        self._writer_error: Optional[str] = None
        self._writer_stop_sent = False

    @property
    def _soundcard(self) -> _SoundCardBackend:
        if self._backend is None:
            self._backend = _load_soundcard()
        return self._backend

    def _loopback_devices(self) -> list[Any]:
        return [
            device
            for device in self._soundcard.all_microphones(include_loopback=True)
            if bool(getattr(device, "isloopback", False))
        ]

    def list_devices(self) -> list[AudioDevice]:
        return [
            AudioDevice(
                device_id=_device_id(device),
                name=str(getattr(device, "name", _device_id(device))),
                source=AudioSourceKind.SYSTEM,
            )
            for device in self._loopback_devices()
        ]

    def _resolve_device(self, device_id: Optional[str]) -> Any:
        devices = self._loopback_devices()
        if not devices:
            raise RuntimeError("No Windows system-audio loopback device is available")
        if device_id is None:
            return devices[0]
        for device in devices:
            if _device_id(device) == str(device_id):
                return device
        raise RuntimeError("The selected system-audio device is no longer available")

    def start(self, device_id: Optional[str] = None) -> None:
        if self._active.is_set():
            return
        if self._capture_thread is not None or self._writer_thread is not None:
            raise RuntimeError(
                "previous system-audio capture has not finished finalizing"
            )
        device = self._resolve_device(device_id)
        temporary = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".wav",
            dir=self._temp_dir,
        )
        self._path = Path(temporary.name)
        temporary.close()
        self._queue = queue.Queue(maxsize=self._queue_blocks)
        self._stop_requested.clear()
        self._capture_error = None
        self._writer_error = None
        self._writer_stop_sent = False
        self._started_at_ns = time.monotonic_ns()
        self._ended_at_ns = None
        self._active.set()
        session_path = self._path
        session_queue = self._queue

        def write_wav() -> None:
            assert session_path is not None
            try:
                with wave.open(str(session_path), "wb") as output:
                    output.setnchannels(self.channels)
                    output.setsampwidth(2)
                    output.setframerate(self.sample_rate)
                    while True:
                        block = session_queue.get()
                        if block is None:
                            break
                        output.writeframes(block)
            except BaseException as exc:
                self._writer_error = str(exc)
                self._stop_requested.set()

        def capture() -> None:
            try:
                with device.recorder(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    blocksize=self.block_frames,
                ) as native:
                    while not self._stop_requested.is_set():
                        frames = np.asarray(
                            native.record(numframes=self.block_frames),
                            dtype=np.float32,
                        )
                        if frames.size == 0:
                            continue
                        if frames.ndim == 1:
                            frames = frames.reshape(-1, 1)
                        if frames.shape[1] != self.channels:
                            raise RuntimeError(
                                "WASAPI returned an unexpected channel count"
                            )
                        pcm = np.rint(
                            np.clip(frames, -1.0, 1.0) * 32767.0
                        ).astype("<i2", copy=False)
                        try:
                            session_queue.put_nowait(pcm.tobytes(order="C"))
                        except queue.Full:
                            self._capture_error = (
                                "system audio buffer overflowed; partial audio preserved"
                            )
                            self._stop_requested.set()
            except BaseException as exc:
                self._capture_error = str(exc)
                self._stop_requested.set()
            finally:
                self._ended_at_ns = time.monotonic_ns()
                self._active.clear()
                try:
                    session_queue.put(None, timeout=2.0)
                except queue.Full:
                    if self._capture_error is None:
                        self._capture_error = (
                            "system audio writer did not drain its bounded buffer"
                        )
                else:
                    self._writer_stop_sent = True

        self._writer_thread = threading.Thread(
            target=write_wav,
            name="mindtype-system-audio-writer",
            daemon=True,
        )
        self._capture_thread = threading.Thread(
            target=capture,
            name="mindtype-system-audio-capture",
            daemon=True,
        )
        self._writer_thread.start()
        self._capture_thread.start()

    def stop(self, timeout: float = 5.0) -> AudioCaptureResult:
        path = self._path
        if path is None:
            return AudioCaptureResult(
                status=AudioCaptureStatus.INTERRUPTED,
                track=None,
                error="system audio was not recording",
            )
        self._stop_requested.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=timeout)
            if self._capture_thread.is_alive():
                self._capture_error = (
                    "system audio device did not stop before timeout"
                )
            else:
                self._capture_thread = None
        if self._writer_thread is not None and self._capture_thread is None:
            if not self._writer_stop_sent:
                try:
                    self._queue.put(None, timeout=max(0.0, timeout))
                except queue.Full:
                    self._writer_error = (
                        "system audio WAV writer did not accept its stop signal"
                    )
                else:
                    self._writer_stop_sent = True
            self._writer_thread.join(timeout=timeout)
            if self._writer_thread.is_alive():
                self._writer_error = "system audio WAV writer did not finish"
            else:
                self._writer_thread = None

        ended_at = self._ended_at_ns or time.monotonic_ns()
        started_at = self._started_at_ns or ended_at
        capture_finalized = (
            self._capture_thread is None
            and self._writer_thread is None
        )
        track = (
            RecordedTrack(
                source=AudioSourceKind.SYSTEM,
                path=path,
                sample_rate=self.sample_rate,
                channels=self.channels,
                started_at_monotonic_ns=started_at,
                ended_at_monotonic_ns=max(started_at, ended_at),
            )
            if capture_finalized and path.is_file()
            else None
        )
        error = self._capture_error or self._writer_error
        status = (
            AudioCaptureStatus.INTERRUPTED
            if error is not None
            else AudioCaptureStatus.COMPLETED
        )
        if capture_finalized:
            self._path = None
            self._started_at_ns = None
            self._ended_at_ns = None
        return AudioCaptureResult(status=status, track=track, error=error)

    @property
    def recording(self) -> bool:
        return self._active.is_set()

    @property
    def finalizing(self) -> bool:
        return (
            self._active.is_set()
            or self._capture_thread is not None
            or self._writer_thread is not None
            or self._path is not None
        )


class MultiTrackAudioRecorder:
    """Coordinate independent microphone and system-audio recorders."""

    def __init__(self, *, microphone: Any, system: SystemAudioRecorder) -> None:
        self.microphone = microphone
        self.system = system
        self._source: Optional[AudioSourceKind] = None
        self._results: list[AudioCaptureResult] = []
        self._microphone_finalized = False
        self._system_finalized = False
        self._discard_results_on_finalize = False

    def start(
        self,
        source: AudioSourceKind,
        *,
        microphone_device: Optional[int] = None,
        system_device: Optional[str] = None,
        level_callback: Any = None,
    ) -> None:
        if self._source is not None:
            raise RuntimeError("audio session is still finalizing or recording")
        normalized_source = AudioSourceKind(source)
        self._source = normalized_source
        self._results = []
        self._microphone_finalized = False
        self._system_finalized = False
        self._discard_results_on_finalize = False
        system_started = False
        try:
            if normalized_source in {
                AudioSourceKind.SYSTEM,
                AudioSourceKind.MICROPHONE_SYSTEM,
            }:
                self.system.start(device_id=system_device)
                system_started = True
            if normalized_source in {
                AudioSourceKind.MICROPHONE,
                AudioSourceKind.MICROPHONE_SYSTEM,
            }:
                self.microphone.start(
                    device=microphone_device,
                    level_callback=level_callback,
                )
        except Exception:
            if system_started:
                # The microphone failed after loopback had started. Keep the
                # session owned until the system writer can be finalized.
                self._microphone_finalized = True
                partial = self.system.stop()
                if partial.track is not None:
                    partial.track.path.unlink(missing_ok=True)
                    self._system_finalized = True
                    self._source = None
                else:
                    self._discard_results_on_finalize = True
            else:
                self._source = None
            raise

    def stop(self) -> MultiTrackCapture:
        source = self._source
        if source is None:
            return MultiTrackCapture(results=())
        if source in {
            AudioSourceKind.MICROPHONE,
            AudioSourceKind.MICROPHONE_SYSTEM,
        } and not self._microphone_finalized:
            microphone_result = self.microphone.stop_capture()
            if microphone_result.track is not None:
                if self._discard_results_on_finalize:
                    microphone_result.track.path.unlink(missing_ok=True)
                else:
                    self._results.append(microphone_result)
            if (
                microphone_result.track is not None
                or getattr(self.microphone, "finalizing", True) is False
            ):
                if (
                    microphone_result.track is None
                    and not self._discard_results_on_finalize
                ):
                    self._results.append(microphone_result)
                self._microphone_finalized = True
        if source in {
            AudioSourceKind.SYSTEM,
            AudioSourceKind.MICROPHONE_SYSTEM,
        } and not self._system_finalized:
            system_result = self.system.stop()
            if system_result.track is not None:
                if self._discard_results_on_finalize:
                    system_result.track.path.unlink(missing_ok=True)
                else:
                    self._results.append(system_result)
            if (
                system_result.track is not None
                or getattr(self.system, "finalizing", True) is False
            ):
                if (
                    system_result.track is None
                    and not self._discard_results_on_finalize
                ):
                    self._results.append(system_result)
                self._system_finalized = True

        microphone_done = (
            source is AudioSourceKind.SYSTEM or self._microphone_finalized
        )
        system_done = (
            source is AudioSourceKind.MICROPHONE or self._system_finalized
        )
        if not (microphone_done and system_done):
            return MultiTrackCapture(results=())

        capture = MultiTrackCapture(results=tuple(self._results))
        self._source = None
        self._results = []
        self._discard_results_on_finalize = False
        return capture

    @property
    def recording(self) -> bool:
        return self._source is not None
