from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.audio_sources import (
    AudioCaptureResult,
    AudioCaptureStatus,
    AudioDevice,
    AudioSourceKind,
    MultiTrackAudioRecorder,
    RecordedTrack,
    SystemAudioRecorder,
)


class _FakeRecorder:
    def __init__(
        self,
        blocks: list[np.ndarray],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.blocks = blocks
        self.error = error
        self.closed = False

    def __enter__(self) -> "_FakeRecorder":
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def record(self, *, numframes: int) -> np.ndarray:
        del numframes
        if self.blocks:
            return self.blocks.pop(0)
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        time.sleep(0.005)
        return np.empty((0, 2), dtype=np.float32)


class _FakeMicrophone:
    def __init__(
        self,
        *,
        identifier: str,
        name: str,
        isloopback: bool,
        recorder: _FakeRecorder,
    ) -> None:
        self.id = identifier
        self.name = name
        self.isloopback = isloopback
        self._recorder = recorder

    def recorder(self, **_kwargs: object) -> _FakeRecorder:
        return self._recorder


class _FakeSoundCard:
    def __init__(self, microphones: list[_FakeMicrophone]) -> None:
        self.microphones = microphones
        self.discovery_calls = 0

    def all_microphones(self, *, include_loopback: bool) -> list[_FakeMicrophone]:
        assert include_loopback is True
        self.discovery_calls += 1
        return list(self.microphones)


def test_audio_source_kind_rejects_unknown_values() -> None:
    assert AudioSourceKind("microphone") is AudioSourceKind.MICROPHONE
    with pytest.raises(ValueError):
        AudioSourceKind("desktop")


def test_system_devices_only_include_loopback_microphones() -> None:
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="mic-1",
                name="Laptop microphone",
                isloopback=False,
                recorder=_FakeRecorder([]),
            ),
            _FakeMicrophone(
                identifier="speaker-1",
                name="Laptop speakers",
                isloopback=True,
                recorder=_FakeRecorder([]),
            ),
        ]
    )

    devices = SystemAudioRecorder(backend=backend).list_devices()

    assert devices == [
        AudioDevice(
            device_id="speaker-1",
            name="Laptop speakers",
            source=AudioSourceKind.SYSTEM,
        )
    ]


def test_system_recorder_writes_pcm_and_monotonic_track(tmp_path: Path) -> None:
    pcm = np.array([[0.5, -0.5], [1.0, -1.0]], dtype=np.float32)
    native = _FakeRecorder([pcm])
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=native,
            )
        ]
    )
    recorder = SystemAudioRecorder(
        backend=backend,
        temp_dir=tmp_path,
        sample_rate=48_000,
        channels=2,
        block_frames=2,
    )

    recorder.start(device_id="speaker-1")
    deadline = time.monotonic() + 1
    while native.blocks and time.monotonic() < deadline:
        time.sleep(0.005)
    result = recorder.stop()

    assert result.status is AudioCaptureStatus.COMPLETED
    assert result.error is None
    assert result.track is not None
    assert result.track.source is AudioSourceKind.SYSTEM
    assert result.track.started_at_monotonic_ns <= result.track.ended_at_monotonic_ns
    with wave.open(str(result.track.path), "rb") as audio:
        assert audio.getframerate() == 48_000
        assert audio.getnchannels() == 2
        assert audio.getnframes() == 2


def test_device_disconnect_preserves_partial_system_recording(
    tmp_path: Path,
) -> None:
    native = _FakeRecorder(
        [np.array([[0.25, -0.25]], dtype=np.float32)],
        error=OSError("device disconnected"),
    )
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=native,
            )
        ]
    )
    recorder = SystemAudioRecorder(
        backend=backend,
        temp_dir=tmp_path,
        block_frames=1,
    )

    recorder.start(device_id="speaker-1")
    deadline = time.monotonic() + 1
    while recorder.recording and time.monotonic() < deadline:
        time.sleep(0.005)
    result = recorder.stop()

    assert result.status is AudioCaptureStatus.INTERRUPTED
    assert result.error is not None
    assert "device disconnected" in result.error
    assert result.track is not None
    assert result.track.path.is_file()
    with wave.open(str(result.track.path), "rb") as audio:
        assert audio.getnframes() == 1


def test_stop_does_not_publish_track_while_capture_still_owns_wav(
    tmp_path: Path,
) -> None:
    entered_record = threading.Event()
    release_record = threading.Event()

    class _BlockedRecorder(_FakeRecorder):
        def record(self, *, numframes: int) -> np.ndarray:
            del numframes
            entered_record.set()
            release_record.wait(timeout=2)
            return np.empty((0, 2), dtype=np.float32)

    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=_BlockedRecorder([]),
            )
        ]
    )
    recorder = SystemAudioRecorder(backend=backend, temp_dir=tmp_path)

    recorder.start(device_id="speaker-1")
    assert entered_record.wait(timeout=1)
    unfinished = recorder.stop(timeout=0.01)

    assert unfinished.status is AudioCaptureStatus.INTERRUPTED
    assert unfinished.track is None

    release_record.set()
    finalized = recorder.stop(timeout=1)

    assert finalized.status is AudioCaptureStatus.INTERRUPTED
    assert finalized.track is not None
    assert finalized.track.path.is_file()


def test_system_recorder_rejects_restart_until_previous_writer_finalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.audio_sources as audio_sources

    writer_started = threading.Event()
    release_writer = threading.Event()

    class _BlockedWave:
        def __enter__(self) -> "_BlockedWave":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def setnchannels(self, _value: int) -> None:
            return None

        def setsampwidth(self, _value: int) -> None:
            return None

        def setframerate(self, _value: int) -> None:
            return None

        def writeframes(self, _value: bytes) -> None:
            writer_started.set()
            release_writer.wait(timeout=2)

    monkeypatch.setattr(
        audio_sources.wave,
        "open",
        lambda *_args, **_kwargs: _BlockedWave(),
    )
    native = _FakeRecorder(
        [np.ones((1, 2), dtype=np.float32)]
    )
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=native,
            )
        ]
    )
    recorder = SystemAudioRecorder(
        backend=backend,
        temp_dir=tmp_path,
        block_frames=1,
    )

    recorder.start(device_id="speaker-1")
    assert writer_started.wait(timeout=1)
    unfinished = recorder.stop(timeout=0.01)
    assert unfinished.track is None

    try:
        with pytest.raises(RuntimeError, match="previous system-audio capture"):
            recorder.start(device_id="speaker-1")
    finally:
        release_writer.set()
        recorder.stop(timeout=1)


def test_device_is_rediscovered_when_capture_starts(tmp_path: Path) -> None:
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=_FakeRecorder([]),
            )
        ]
    )
    recorder = SystemAudioRecorder(backend=backend, temp_dir=tmp_path)

    recorder.list_devices()
    recorder.start(device_id="speaker-1")
    recorder.stop()

    assert backend.discovery_calls == 2


def test_bounded_queue_reports_overflow_and_preserves_wav(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.audio_sources as audio_sources

    writer_started = threading.Event()
    release_writer = threading.Event()

    class _SlowWave:
        def __enter__(self) -> "_SlowWave":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def setnchannels(self, _value: int) -> None:
            return None

        def setsampwidth(self, _value: int) -> None:
            return None

        def setframerate(self, _value: int) -> None:
            return None

        def writeframes(self, _value: bytes) -> None:
            writer_started.set()
            release_writer.wait(timeout=2)

    monkeypatch.setattr(
        audio_sources.wave,
        "open",
        lambda *_args, **_kwargs: _SlowWave(),
    )
    native = _FakeRecorder(
        [
            np.ones((1, 2), dtype=np.float32),
            np.ones((1, 2), dtype=np.float32),
            np.ones((1, 2), dtype=np.float32),
        ]
    )
    backend = _FakeSoundCard(
        [
            _FakeMicrophone(
                identifier="speaker-1",
                name="Speakers",
                isloopback=True,
                recorder=native,
            )
        ]
    )
    recorder = SystemAudioRecorder(
        backend=backend,
        temp_dir=tmp_path,
        block_frames=1,
        queue_blocks=1,
    )

    recorder.start(device_id="speaker-1")
    assert writer_started.wait(timeout=1)
    deadline = time.monotonic() + 1
    while recorder.recording and time.monotonic() < deadline:
        time.sleep(0.005)
    release_writer.set()
    result = recorder.stop()

    assert result.status is AudioCaptureStatus.INTERRUPTED
    assert "overflow" in (result.error or "")
    assert result.track is not None
    assert result.track.path.is_file()


def test_stop_retries_a_wasapi_writer_sentinel_after_a_full_queue(
    tmp_path: Path,
) -> None:
    recorder = SystemAudioRecorder(
        backend=_FakeSoundCard([]),
        temp_dir=tmp_path,
        queue_blocks=1,
    )
    path = tmp_path / "pending-system.wav"
    path.write_bytes(b"partial")
    recorder._path = path
    recorder._started_at_ns = 1
    recorder._ended_at_ns = 2
    recorder._queue.put_nowait(b"buffered")
    allow_drain = threading.Event()
    saw_sentinel = threading.Event()

    def finish_writer() -> None:
        allow_drain.wait(timeout=1)
        assert recorder._queue.get(timeout=1) == b"buffered"
        assert recorder._queue.get(timeout=1) is None
        saw_sentinel.set()

    recorder._writer_thread = threading.Thread(target=finish_writer)
    recorder._writer_thread.start()
    allow_drain.set()

    result = recorder.stop(timeout=1)

    assert saw_sentinel.is_set()
    assert recorder._writer_stop_sent is True
    assert result.track is not None


def test_multitrack_stop_keeps_each_source_result() -> None:
    microphone = MagicMock()
    microphone.stop_capture.return_value = MagicMock(
        status=AudioCaptureStatus.INTERRUPTED,
        track=RecordedTrack(
            source=AudioSourceKind.MICROPHONE,
            path=Path("mic.wav"),
            sample_rate=16_000,
            channels=1,
            started_at_monotonic_ns=10,
            ended_at_monotonic_ns=20,
        ),
        error="microphone disconnected",
    )
    system = MagicMock()
    system.stop.return_value = MagicMock(
        status=AudioCaptureStatus.COMPLETED,
        track=RecordedTrack(
            source=AudioSourceKind.SYSTEM,
            path=Path("system.wav"),
            sample_rate=48_000,
            channels=2,
            started_at_monotonic_ns=11,
            ended_at_monotonic_ns=21,
        ),
        error=None,
    )
    session = MultiTrackAudioRecorder(microphone=microphone, system=system)

    session.start(AudioSourceKind.MICROPHONE_SYSTEM)
    capture = session.stop()

    assert [result.track.source for result in capture.results] == [
        AudioSourceKind.MICROPHONE,
        AudioSourceKind.SYSTEM,
    ]
    assert capture.interrupted is True
    microphone.start.assert_called_once()
    system.start.assert_called_once()


def test_multitrack_keeps_session_owned_until_system_track_finalizes() -> None:
    microphone = MagicMock()
    system = MagicMock()
    finalized_track = RecordedTrack(
        source=AudioSourceKind.SYSTEM,
        path=Path("system.wav"),
        sample_rate=48_000,
        channels=2,
        started_at_monotonic_ns=10,
        ended_at_monotonic_ns=20,
    )
    system.stop.side_effect = [
        AudioCaptureResult(
            status=AudioCaptureStatus.INTERRUPTED,
            track=None,
            error="system audio WAV writer did not finish",
        ),
        AudioCaptureResult(
            status=AudioCaptureStatus.INTERRUPTED,
            track=finalized_track,
            error="system audio WAV writer did not finish",
        ),
    ]
    session = MultiTrackAudioRecorder(microphone=microphone, system=system)
    session.start(AudioSourceKind.SYSTEM)

    unfinished = session.stop()

    assert unfinished.tracks == ()
    assert session.recording is True
    with pytest.raises(RuntimeError, match="still finalizing"):
        session.start(AudioSourceKind.SYSTEM)

    finalized = session.stop()

    assert finalized.tracks == (finalized_track,)
    assert session.recording is False
    assert system.stop.call_count == 2
