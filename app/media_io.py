"""
Работа с медиафайлами: поддерживаемые форматы, длительность, извлечение аудио из видео.

Вынесено из file_transcriber для локальности (одна тема — в одном месте).
Извлечение из видео идёт через ffmpeg, с фолбэком на PyAV.
"""

import logging
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("file_transcriber")

# Поддерживаемые форматы
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv', '.m4v'}
ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
SOUNDFILE_AUDIO_EXTENSIONS = {
    '.mp3',
    '.wav',
    '.flac',
    '.ogg',
    '.opus',
}
MAX_MEDIA_DURATION_SECONDS = 8 * 60 * 60


class MediaDurationTooLong(ValueError):
    """Raised before processing media outside the Windows GA limit."""


class MediaDurationUnavailable(ValueError):
    """Raised when the GA duration and entitlement gates cannot be enforced."""


def enforce_media_duration_limit(duration_seconds: float) -> None:
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise MediaDurationUnavailable(
            "media duration could not be measured safely"
        )
    if duration_seconds > MAX_MEDIA_DURATION_SECONDS:
        raise MediaDurationTooLong(
            "media duration exceeds the 8 hours Windows GA limit"
        )


def _media_binary(name: str) -> Optional[Path]:
    executable = f"{name}.exe" if sys.platform == "win32" else name
    discovered = shutil.which(executable)
    if discovered:
        return Path(discovered)
    roots = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent / "_internal",
        Path(__file__).resolve().parents[1],
    ]
    for root in roots:
        if not str(root):
            continue
        candidate = root / "bin" / "win-x64" / executable
        if candidate.is_file():
            return candidate
    return None


def full_media_probe_available() -> bool:
    """Whether the current runtime can safely inspect advertised video."""
    if _media_binary("ffprobe") is not None:
        return True
    try:
        return importlib.util.find_spec("av") is not None
    except (ImportError, ValueError):
        return False


def supported_extensions() -> set[str]:
    """Formats that this concrete installation can duration-gate."""
    if full_media_probe_available():
        return set(ALL_EXTENSIONS)
    return set(SOUNDFILE_AUDIO_EXTENSIONS)


def is_supported_file(path: Path) -> bool:
    """Проверить, поддерживается ли формат файла в текущей установке."""
    return path.suffix.lower() in supported_extensions()


def get_file_duration(file_path: Path) -> float:
    """
    Получить длительность медиафайла в секундах.
    Uses ffprobe, bundled SoundFile, or optional PyAV and fails closed when
    none of them can measure a positive finite duration.
    """
    try:
        # Пробуем использовать ffprobe
        ffprobe = _media_binary("ffprobe")
        if ffprobe is None:
            raise FileNotFoundError("ffprobe is unavailable")
        result = subprocess.run(
            [
                str(ffprobe), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            if math.isfinite(duration) and duration > 0:
                return duration
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # SoundFile is part of the lightweight Windows base runtime and covers
    # WAV, FLAC, OGG and the codecs available through bundled libsndfile.
    try:
        import soundfile

        info = soundfile.info(str(file_path))
        duration = float(info.duration)
        if math.isfinite(duration) and duration > 0:
            return duration
    except Exception:
        pass

    # Пробуем PyAV как альтернативу
    try:
        import av
        with av.open(str(file_path)) as container:
            if container.duration:
                duration = container.duration / 1000000.0
                if math.isfinite(duration) and duration > 0:
                    return duration
    except Exception:
        pass

    raise MediaDurationUnavailable(
        "media duration could not be measured safely"
    )


def extract_audio_from_video(video_path: Path, output_path: Optional[Path] = None) -> Path:
    """
    Извлечь аудиодорожку из видеофайла.

    Args:
        video_path: Путь к видеофайлу
        output_path: Путь для сохранения аудио (опционально)

    Returns:
        Путь к извлечённому аудиофайлу (WAV)

    Raises:
        FileNotFoundError: Если входной файл не существует
        PermissionError: Если нет прав на чтение файла
    """
    # Validate input path exists and is readable
    video_path = Path(video_path).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Видеофайл не найден: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Путь не является файлом: {video_path}")
    if not os.access(video_path, os.R_OK):
        raise PermissionError(f"Нет прав на чтение файла: {video_path}")

    if output_path is None:
        # Create temp file - use delete=False and handle cleanup manually
        # On Windows, we need to close the file before ffmpeg can write to it
        fd, tmp_name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)  # Close file descriptor immediately
        output_path = Path(tmp_name)

    # Пробуем ffmpeg
    ffmpeg_path = _media_binary("ffmpeg")
    if ffmpeg_path:
        try:
            result = subprocess.run(
                [
                    ffmpeg_path, "-i", str(video_path),
                    "-vn",  # Без видео
                    "-acodec", "pcm_s16le",  # PCM 16-bit
                    "-ar", "16000",  # 16kHz для Whisper
                    "-ac", "1",  # Моно
                    "-y",  # Перезаписывать
                    str(output_path)
                ],
                capture_output=True,
                timeout=600  # 10 минут максимум
            )
            if result.returncode == 0 and output_path.exists():
                return output_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Альтернатива: PyAV
    try:
        import av
        import wave
        import numpy as np

        with av.open(str(video_path)) as container:
            # Находим аудиопоток
            audio_stream = None
            for stream in container.streams:
                if stream.type == 'audio':
                    audio_stream = stream
                    break

            if audio_stream is None:
                raise RuntimeError("Видео не содержит аудиодорожку")

            # Декодируем и ресемплируем
            resampler = av.audio.resampler.AudioResampler(
                format='s16',
                layout='mono',
                rate=16000
            )

            audio_data = []
            for frame in container.decode(audio=0):
                resampled = resampler.resample(frame)
                for r in resampled:
                    audio_data.append(r.to_ndarray())

            if not audio_data:
                raise RuntimeError("Не удалось извлечь аудио")

            # Объединяем и сохраняем
            audio_array = np.concatenate(audio_data, axis=1).flatten()

            with wave.open(str(output_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(16000)
                wf.writeframes(audio_array.astype(np.int16).tobytes())

            return output_path

    except ImportError:
        raise RuntimeError("Требуется ffmpeg или PyAV для обработки видео")
    except Exception as e:
        raise RuntimeError(f"Ошибка извлечения аудио: {e}")
