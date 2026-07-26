from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol


SUPPORTED_SAMPLE_RATES = {8_000, 16_000, 32_000, 48_000}


class VadBackend(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


@dataclass(frozen=True)
class SpeechRegion:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("Speech region must satisfy 0 <= start < end")


class WebRtcVadSegmenter:
    """Stream PCM WAV through WebRTC VAD and return speech regions."""

    def __init__(
        self,
        *,
        backend: Optional[VadBackend] = None,
        aggressiveness: int = 2,
        frame_ms: int = 30,
        max_silence_ms: int = 300,
        speech_padding_ms: int = 150,
        overlap_ms: int = 100,
        min_speech_ms: int = 120,
    ) -> None:
        if frame_ms not in (10, 20, 30):
            raise ValueError("WebRTC VAD frame must be 10, 20 or 30 ms")
        if aggressiveness not in (0, 1, 2, 3):
            raise ValueError("WebRTC VAD aggressiveness must be from 0 to 3")
        for name, value in (
            ("max_silence_ms", max_silence_ms),
            ("speech_padding_ms", speech_padding_ms),
            ("overlap_ms", overlap_ms),
            ("min_speech_ms", min_speech_ms),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        self._backend = backend
        self._aggressiveness = aggressiveness
        self.frame_ms = frame_ms
        self.max_silence_ms = max_silence_ms
        self.speech_padding_ms = speech_padding_ms
        self.overlap_ms = overlap_ms
        self.min_speech_ms = min_speech_ms

    def _get_backend(self) -> VadBackend:
        if self._backend is None:
            try:
                import webrtcvad
            except ImportError as exc:
                raise RuntimeError(
                    "WebRTC VAD не установлен для этой версии Python"
                ) from exc
            self._backend = webrtcvad.Vad(self._aggressiveness)
        return self._backend

    @staticmethod
    def _validate_wav(source: wave.Wave_read) -> tuple[int, int]:
        sample_rate = source.getframerate()
        if sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f"WebRTC VAD не поддерживает sample rate {sample_rate}"
            )
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("WebRTC VAD требует mono PCM16 WAV")
        return sample_rate, source.getnframes()

    def regions(
        self,
        audio_path: Path,
        *,
        cancel_requested: Optional[Callable[[], bool]] = None,
    ) -> list[SpeechRegion]:
        backend = self._get_backend()
        with wave.open(str(audio_path), "rb") as source:
            sample_rate, total_frames = self._validate_wav(source)
            samples_per_frame = sample_rate * self.frame_ms // 1000
            bytes_per_frame = samples_per_frame * 2
            voiced: list[bool] = []
            while True:
                if cancel_requested is not None and cancel_requested():
                    raise InterruptedError("VAD segmentation cancelled")
                frame = source.readframes(samples_per_frame)
                if not frame:
                    break
                padded = frame.ljust(bytes_per_frame, b"\0")
                voiced.append(bool(backend.is_speech(padded, sample_rate)))

        if not voiced:
            return []
        total_ms = math.ceil(total_frames * 1000 / sample_rate)
        allowed_silence_frames = self.max_silence_ms // self.frame_ms
        minimum_voiced_frames = max(
            1, math.ceil(self.min_speech_ms / self.frame_ms)
        )
        groups: list[tuple[int, int, int]] = []
        first_voiced: Optional[int] = None
        last_voiced: Optional[int] = None
        voiced_count = 0
        for index, is_voiced in enumerate(voiced):
            if not is_voiced:
                continue
            if (
                last_voiced is not None
                and index - last_voiced - 1 > allowed_silence_frames
            ):
                groups.append((first_voiced or 0, last_voiced, voiced_count))
                first_voiced = index
                voiced_count = 0
            if first_voiced is None:
                first_voiced = index
            last_voiced = index
            voiced_count += 1
        if first_voiced is not None and last_voiced is not None:
            groups.append((first_voiced, last_voiced, voiced_count))

        regions: list[SpeechRegion] = []
        for first, last, count in groups:
            if count < minimum_voiced_frames:
                continue
            start = max(
                0,
                first * self.frame_ms - self.speech_padding_ms,
            )
            if regions:
                start = max(0, start - self.overlap_ms)
            end = min(
                total_ms,
                (last + 1 + allowed_silence_frames) * self.frame_ms,
            )
            if end > start:
                regions.append(SpeechRegion(start, end))
        return regions

    def write_region(
        self,
        source_path: Path,
        target_path: Path,
        region: SpeechRegion,
    ) -> None:
        with wave.open(str(source_path), "rb") as source:
            sample_rate, total_frames = self._validate_wav(source)
            start_frame = min(
                total_frames, region.start_ms * sample_rate // 1000
            )
            end_frame = min(
                total_frames,
                math.ceil(region.end_ms * sample_rate / 1000),
            )
            if end_frame <= start_frame:
                raise ValueError("Speech region is outside the audio file")
            source.setpos(start_frame)
            payload = source.readframes(end_frame - start_frame)
            with wave.open(str(target_path), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(sample_rate)
                target.writeframes(payload)
