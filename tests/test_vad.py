from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from app.vad import SpeechRegion, WebRtcVadSegmenter


class EnergyBackend:
    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        del sample_rate
        samples = struct.unpack(f"<{len(frame) // 2}h", frame)
        return max((abs(value) for value in samples), default=0) > 1000


def _write_frames(path: Path, levels: list[int], frame_ms: int = 30) -> None:
    sample_rate = 16_000
    samples_per_frame = sample_rate * frame_ms // 1000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for level in levels:
            output.writeframesraw(
                struct.pack(f"<{samples_per_frame}h", *([level] * samples_per_frame))
            )


def test_vad_emits_distinct_regions_with_padding_and_overlap(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    _write_frames(
        audio,
        [0] * 5 + [4000] * 5 + [0] * 6 + [4000] * 5 + [0] * 2,
    )
    segmenter = WebRtcVadSegmenter(
        backend=EnergyBackend(),
        frame_ms=30,
        max_silence_ms=90,
        speech_padding_ms=30,
        overlap_ms=60,
        min_speech_ms=60,
    )

    regions = segmenter.regions(audio)

    assert len(regions) == 2
    assert regions[0].start_ms == 120
    assert regions[0].end_ms == 390
    assert regions[1].start_ms == 390
    assert regions[1].end_ms == 690
    assert regions[0].end_ms > 300  # first raw speech end; overlap/padding retained


def test_vad_keeps_incomplete_final_frame(tmp_path: Path) -> None:
    audio = tmp_path / "tail.wav"
    sample_rate = 16_000
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack("<160h", *([5000] * 160)))  # 10 ms

    segmenter = WebRtcVadSegmenter(
        backend=EnergyBackend(),
        frame_ms=30,
        max_silence_ms=90,
        speech_padding_ms=0,
        overlap_ms=0,
        min_speech_ms=1,
    )

    assert segmenter.regions(audio) == [SpeechRegion(start_ms=0, end_ms=10)]


def test_region_writer_preserves_requested_bounds(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    target = tmp_path / "region.wav"
    _write_frames(source, [1000] * 10)
    segmenter = WebRtcVadSegmenter(backend=EnergyBackend())

    segmenter.write_region(
        source,
        target,
        SpeechRegion(start_ms=60, end_ms=210),
    )

    with wave.open(str(target), "rb") as written:
        assert written.getframerate() == 16_000
        assert written.getnchannels() == 1
        assert written.getsampwidth() == 2
        assert written.getnframes() == 2_400


def test_real_webrtc_backend_accepts_production_pcm_contract(tmp_path: Path) -> None:
    pytest.importorskip("webrtcvad")
    audio = tmp_path / "silence.wav"
    _write_frames(audio, [0] * 4)

    assert WebRtcVadSegmenter().regions(audio) == []


def test_vad_scan_honours_cancellation_between_frames(tmp_path: Path) -> None:
    audio = tmp_path / "cancel.wav"
    _write_frames(audio, [4000] * 5)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 1

    with pytest.raises(InterruptedError, match="cancelled"):
        WebRtcVadSegmenter(backend=EnergyBackend()).regions(
            audio, cancel_requested=cancelled
        )
