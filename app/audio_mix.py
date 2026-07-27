"""Memory-bounded projection of independent PCM WAV tracks for STT."""

from __future__ import annotations

import math
import os
import wave
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from .audio_sources import RecordedTrack


@dataclass
class _TrackReader:
    track: RecordedTrack
    wav: wave.Wave_read
    offset: int
    output_frames: int

    def project(self, output_start: int, output_end: int) -> np.ndarray:
        """Read only source frames needed for one output interval."""
        local_start = output_start - self.offset
        local_end = output_end - self.offset
        positions = (
            np.arange(local_start, local_end, dtype=np.float64)
            * self.track.sample_rate
            / self.output_rate
        )
        source_start = int(math.floor(positions[0]))
        source_end = min(
            self.wav.getnframes(),
            int(math.floor(positions[-1])) + 2,
        )
        self.wav.setpos(source_start)
        raw = self.wav.readframes(source_end - source_start)
        samples = np.frombuffer(raw, dtype="<i2")
        if not len(samples):
            return np.zeros(local_end - local_start, dtype=np.float64)
        mono = samples.reshape(-1, self.track.channels).mean(axis=1)
        source_positions = np.arange(
            source_start,
            source_start + mono.size,
            dtype=np.float64,
        )
        return np.interp(positions, source_positions, mono)

    output_rate: int = 16_000


def _open_track(
    stack: ExitStack,
    track: RecordedTrack,
    *,
    earliest_start: int,
    target_sample_rate: int,
) -> _TrackReader:
    source = stack.enter_context(wave.open(str(track.path), "rb"))
    if source.getsampwidth() != 2:
        raise ValueError("only 16-bit PCM capture tracks can be mixed")
    if source.getframerate() != track.sample_rate:
        raise ValueError("track sample rate does not match its metadata")
    if source.getnchannels() != track.channels:
        raise ValueError("track channel count does not match its metadata")
    offset_ns = track.started_at_monotonic_ns - earliest_start
    offset = round(offset_ns * target_sample_rate / 1_000_000_000)
    output_frames = math.ceil(
        source.getnframes() * target_sample_rate / track.sample_rate
    )
    return _TrackReader(
        track=track,
        wav=source,
        offset=offset,
        output_frames=output_frames,
        output_rate=target_sample_rate,
    )


def mix_tracks_to_wav(
    tracks: Sequence[RecordedTrack],
    output_path: Path,
    *,
    target_sample_rate: int = 16_000,
    chunk_frames: int = 65_536,
) -> Path:
    """Align by monotonic start and average active tracks in bounded chunks."""
    if not tracks:
        raise ValueError("at least one audio track is required")
    if target_sample_rate <= 0 or chunk_frames <= 0:
        raise ValueError("sample rate and chunk size must be positive")
    earliest_start = min(track.started_at_monotonic_ns for track in tracks)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with ExitStack() as stack:
            readers = [
                _open_track(
                    stack,
                    track,
                    earliest_start=earliest_start,
                    target_sample_rate=target_sample_rate,
                )
                for track in tracks
            ]
            total_frames = max(
                reader.offset + reader.output_frames for reader in readers
            )
            if total_frames == 0:
                raise ValueError("audio tracks contain no frames")

            raw_output = stack.enter_context(destination.open("xb"))
            output = stack.enter_context(wave.open(raw_output, "wb"))
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(target_sample_rate)

            for chunk_start in range(0, total_frames, chunk_frames):
                chunk_end = min(total_frames, chunk_start + chunk_frames)
                mixed = np.zeros(chunk_end - chunk_start, dtype=np.float64)
                contributors = np.zeros(
                    chunk_end - chunk_start,
                    dtype=np.uint8,
                )
                for reader in readers:
                    overlap_start = max(chunk_start, reader.offset)
                    overlap_end = min(
                        chunk_end,
                        reader.offset + reader.output_frames,
                    )
                    if overlap_start >= overlap_end:
                        continue
                    projected = reader.project(overlap_start, overlap_end)
                    start = overlap_start - chunk_start
                    end = overlap_end - chunk_start
                    mixed[start:end] += projected
                    contributors[start:end] += 1
                active = contributors > 0
                mixed[active] /= contributors[active]
                pcm = np.rint(
                    np.clip(mixed, -32768, 32767)
                ).astype("<i2")
                output.writeframes(pcm.tobytes())

            output.close()
            raw_output.flush()
            os.fsync(raw_output.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination
