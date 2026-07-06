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
    """Сконвертировать аудио в WAV 16 кГц моно 16-bit PCM по пути out_path."""
    import soundfile as sf

    data, _ = load_16k_mono(audio_path)
    sf.write(str(out_path), data, SAMPLE_RATE, subtype="PCM_16")
    return Path(out_path)
