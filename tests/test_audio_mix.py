from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from app.audio_mix import mix_tracks_to_wav
from app.audio_sources import AudioSourceKind, RecordedTrack


def _write_wav(
    path: Path,
    samples: np.ndarray,
    *,
    sample_rate: int,
    channels: int,
) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(np.asarray(samples, dtype="<i2").tobytes())


def test_mix_preserves_originals_and_aligns_tracks_by_monotonic_time(
    tmp_path: Path,
) -> None:
    microphone_path = tmp_path / "mic.wav"
    system_path = tmp_path / "system.wav"
    _write_wav(
        microphone_path,
        np.array([1000, 1000, 1000, 1000]),
        sample_rate=4,
        channels=1,
    )
    _write_wav(
        system_path,
        np.array([[3000, 3000], [3000, 3000]]),
        sample_rate=2,
        channels=2,
    )
    tracks = [
        RecordedTrack(
            source=AudioSourceKind.MICROPHONE,
            path=microphone_path,
            sample_rate=4,
            channels=1,
            started_at_monotonic_ns=0,
            ended_at_monotonic_ns=1_000_000_000,
        ),
        RecordedTrack(
            source=AudioSourceKind.SYSTEM,
            path=system_path,
            sample_rate=2,
            channels=2,
            started_at_monotonic_ns=500_000_000,
            ended_at_monotonic_ns=1_500_000_000,
        ),
    ]
    mixed_path = tmp_path / "source.part"

    mix_tracks_to_wav(
        tracks,
        mixed_path,
        target_sample_rate=4,
        chunk_frames=2,
    )

    with wave.open(str(mixed_path), "rb") as mixed:
        samples = np.frombuffer(mixed.readframes(mixed.getnframes()), dtype="<i2")
        assert mixed.getnchannels() == 1
        assert mixed.getframerate() == 4
    assert samples.tolist() == [1000, 1000, 2000, 2000, 3000, 3000]
    assert microphone_path.is_file()
    assert system_path.is_file()
