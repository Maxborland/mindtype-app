"""
Единая загрузка аудио в формат, который ожидают распознаватели: 16 кГц, моно, float32.

Раньше один и тот же вызов `librosa.load(..., sr=16000, mono=True)` был продублирован
в transcriber_cpp / transcriber_onnx / transcriber_openrouter. Здесь — один источник.
(Извлечение аудио из видео через ffmpeg/PyAV — отдельная операция в file_transcriber.)
"""

from pathlib import Path
from typing import Tuple, Union

import numpy as np

SAMPLE_RATE = 16000


def load_16k_mono(audio_path: Union[str, Path]) -> Tuple["np.ndarray", int]:
    """Загрузить любой поддерживаемый аудиофайл как (float32 [-1,1], 16000) моно."""
    import librosa  # тяжёлый импорт — лениво, как и в бэкендах

    data, sr = librosa.load(str(audio_path), sr=SAMPLE_RATE, mono=True)
    return data, sr


def to_wav_16k_mono(audio_path: Union[str, Path], out_path: Union[str, Path]) -> Path:
    """Сконвертировать поддерживаемое soundfile-аудио в PCM16 WAV.

    This path is part of the lightweight base runtime, so it deliberately does
    not depend on the optional librosa/numba diarization pack.
    """
    import soundfile as sf

    data, source_rate = sf.read(
        str(audio_path),
        dtype="float32",
        always_2d=True,
    )
    if source_rate <= 0:
        raise ValueError("source sample rate must be positive")
    mono = data.mean(axis=1, dtype=np.float32)
    if source_rate != SAMPLE_RATE and mono.size:
        target_frames = max(
            1,
            round(mono.size * SAMPLE_RATE / source_rate),
        )
        source_positions = np.arange(mono.size, dtype=np.float64)
        target_positions = (
            np.arange(target_frames, dtype=np.float64)
            * source_rate
            / SAMPLE_RATE
        )
        mono = np.interp(
            target_positions,
            source_positions,
            mono,
        ).astype(np.float32)
    sf.write(
        str(out_path),
        mono,
        SAMPLE_RATE,
        subtype="PCM_16",
        format="WAV",
    )
    return Path(out_path)
