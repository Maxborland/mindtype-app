"""
Text-to-Speech используя Microsoft Edge TTS.

Поддержка всех языков и голосов Microsoft.
Воспроизведение через sounddevice (без pygame).
"""

import asyncio
import io
import logging
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import edge_tts
except ImportError:
    edge_tts = None

import numpy as np
import sounddevice as sd
import soundfile as sf

# Опциональный pydub для декодирования MP3
try:
    from pydub import AudioSegment
    _HAS_PYDUB = True
except ImportError:
    _HAS_PYDUB = False

logger = logging.getLogger(__name__)


def _load_audio_file(file_path: Path) -> Tuple[np.ndarray, int]:
    """
    Загрузить аудио файл в numpy array.

    Поддерживает WAV напрямую через soundfile.
    Для MP3 использует pydub (если доступен) или ffmpeg.

    Returns:
        (data, samplerate) - numpy array и частота дискретизации

    Raises:
        RuntimeError если не удалось загрузить
    """
    suffix = file_path.suffix.lower()

    # WAV/FLAC/OGG — soundfile справится
    if suffix in (".wav", ".flac", ".ogg"):
        data, samplerate = sf.read(str(file_path), dtype="float32", always_2d=True)
        return data, samplerate

    # MP3 — нужен декодер
    if suffix == ".mp3":
        # Вариант 1: pydub (если установлен)
        if _HAS_PYDUB:
            try:
                audio = AudioSegment.from_mp3(str(file_path))
                # Конвертируем в numpy
                samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
                samples /= 32768.0  # Нормализуем int16 -> float32
                # Если стерео — reshape
                if audio.channels == 2:
                    samples = samples.reshape((-1, 2))
                else:
                    samples = samples.reshape((-1, 1))
                return samples, audio.frame_rate
            except Exception as e:
                logger.warning(f"pydub не смог загрузить MP3: {e}, пробую ffmpeg")

        # Вариант 2: ffmpeg через subprocess
        try:
            # Конвертируем MP3 -> WAV в памяти
            result = subprocess.run(
                ["ffmpeg", "-i", str(file_path), "-f", "wav", "-acodec", "pcm_s16le", "-"],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                wav_data = io.BytesIO(result.stdout)
                data, samplerate = sf.read(wav_data, dtype="float32", always_2d=True)
                return data, samplerate
        except FileNotFoundError:
            logger.warning("ffmpeg не найден в PATH")
        except Exception as e:
            logger.warning(f"ffmpeg ошибка: {e}")

        # Вариант 3: попробуем soundfile напрямую (может сработать если libsndfile скомпилирован с mp3)
        try:
            data, samplerate = sf.read(str(file_path), dtype="float32", always_2d=True)
            return data, samplerate
        except Exception:
            pass

        raise RuntimeError(
            f"Не удалось загрузить MP3: {file_path}. "
            "Установите pydub (pip install pydub) или ffmpeg."
        )

    # Другие форматы — пробуем soundfile
    try:
        data, samplerate = sf.read(str(file_path), dtype="float32", always_2d=True)
        return data, samplerate
    except Exception as e:
        raise RuntimeError(f"Не удалось загрузить аудио {file_path}: {e}")


@dataclass
class Voice:
    """Информация о голосе TTS."""
    short_name: str
    full_name: str
    language: str
    gender: str
    locale: str

    @property
    def display_name(self) -> str:
        """Имя для отображения в UI."""
        # Извлекаем короткое имя из полного
        # ru-RU-DmitryNeural -> Dmitry
        parts = self.short_name.split("-")
        if len(parts) >= 3:
            name = parts[2].replace("Neural", "")
            return f"{name} ({self.gender})"
        return self.short_name


class TTSEngine:
    """Движок синтеза речи на основе Edge TTS."""

    def __init__(self):
        """Инициализация TTS движка."""
        self._voices_cache: Optional[List[Voice]] = None
        self._current_voice: str = "ru-RU-DmitryNeural"
        self._rate: str = "+0%"  # Скорость речи (-50% до +50%)
        self._volume: str = "+0%"  # Громкость

        # Воспроизведение через sounddevice
        self._play_lock = threading.Lock()
        self._is_playing = threading.Event()

        # note: sd использует глобальный stream, поэтому stop() должен быть thread-safe
        logger.info("TTS воспроизведение: sounddevice")

    async def _fetch_voices(self) -> List[Voice]:
        """Получить список доступных голосов из Edge TTS."""
        if edge_tts is None:
            logger.error("edge-tts не установлен")
            return []

        try:
            voices_list = await edge_tts.list_voices()
            voices = []

            for voice_data in voices_list:
                voice = Voice(
                    short_name=voice_data["ShortName"],
                    full_name=voice_data["FriendlyName"],
                    language=voice_data["Locale"].split("-")[0],
                    gender=voice_data["Gender"],
                    locale=voice_data["Locale"],
                )
                voices.append(voice)

            logger.info(f"Загружено {len(voices)} голосов")
            return voices

        except Exception as e:
            logger.error(f"Ошибка получения списка голосов: {e}")
            return []

    def get_voices(self, language: Optional[str] = None) -> List[Voice]:
        """
        Получить список доступных голосов.

        Args:
            language: Фильтр по языку (ru, en, etc.). None = все языки

        Returns:
            Список голосов
        """
        # Кэшируем список голосов
        if self._voices_cache is None:
            # Запускаем асинхронно в синхронной функции
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._voices_cache = loop.run_until_complete(self._fetch_voices())
            loop.close()

        if language:
            return [v for v in self._voices_cache if v.language == language]
        return self._voices_cache

    def get_voices_by_locale(self, locale: str) -> List[Voice]:
        """
        Получить голоса для конкретной локали.

        Args:
            locale: Локаль (ru-RU, en-US, etc.)

        Returns:
            Список голосов
        """
        voices = self.get_voices()
        return [v for v in voices if v.locale == locale]

    def set_voice(self, voice_short_name: str) -> None:
        """Установить текущий голос."""
        self._current_voice = voice_short_name
        logger.info(f"Установлен голос: {voice_short_name}")

    def set_rate(self, rate_percent: int) -> None:
        """
        Установить скорость речи.

        Args:
            rate_percent: Процент изменения скорости (-50 до +50)
        """
        rate_percent = max(-50, min(50, rate_percent))
        self._rate = f"{rate_percent:+d}%"
        logger.info(f"Установлена скорость речи: {self._rate}")

    def set_volume(self, volume_percent: int) -> None:
        """
        Установить громкость.

        Args:
            volume_percent: Процент громкости (-50 до +50)
        """
        volume_percent = max(-50, min(50, volume_percent))
        self._volume = f"{volume_percent:+d}%"

    async def _synthesize_async(self, text: str, output_file: Path) -> bool:
        """
        Синтезировать речь асинхронно.

        Args:
            text: Текст для синтеза
            output_file: Путь к выходному файлу (MP3)

        Returns:
            True если успешно
        """
        if edge_tts is None:
            logger.error("edge-tts не установлен")
            return False

        try:
            # edge-tts выводит MP3 по умолчанию
            communicate = edge_tts.Communicate(
                text=text,
                voice=self._current_voice,
                rate=self._rate,
                volume=self._volume,
            )

            await communicate.save(str(output_file))
            logger.info(f"Синтез речи завершен: {output_file}")
            return True

        except Exception as e:
            logger.error(f"Ошибка синтеза речи: {e}")
            return False

    def synthesize(self, text: str, output_file: Optional[Path] = None) -> Optional[Path]:
        """
        Синтезировать речь.

        Args:
            text: Текст для синтеза
            output_file: Путь к выходному файлу (None = временный файл)

        Returns:
            Путь к аудио файлу или None при ошибке
        """
        if not text:
            logger.warning("Пустой текст для синтеза")
            return None

        # Создаем временный файл если не указан (edge-tts выводит MP3)
        if output_file is None:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            output_file = Path(tmp.name)
            tmp.close()

        # Запускаем синтез
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(self._synthesize_async(text, output_file))
        loop.close()

        if success and output_file.exists():
            return output_file
        return None

    def play(self, audio_file: Path, blocking: bool = True) -> bool:
        """
        Воспроизвести аудио файл.

        Args:
            audio_file: Путь к аудио файлу (MP3, WAV, и др.)
            blocking: Блокировать до завершения воспроизведения

        Returns:
            True если успешно начато воспроизведение
        """
        if not audio_file.exists():
            logger.error(f"Аудио файл не найден: {audio_file}")
            return False

        try:
            with self._play_lock:
                # Останавливаем предыдущее воспроизведение, если оно ещё идёт
                self.stop()

                # Загружаем аудио (поддержка MP3 через pydub/ffmpeg)
                data, samplerate = _load_audio_file(audio_file)

                # sounddevice ожидает shape (frames, channels)
                if not isinstance(data, np.ndarray) or data.size == 0:
                    logger.error(f"Пустой аудио файл: {audio_file}")
                    return False

                self._is_playing.set()
                sd.play(data, samplerate=samplerate)
                logger.info(f"Воспроизведение: {audio_file}")

                def _wait_and_clear() -> None:
                    try:
                        sd.wait()
                    finally:
                        self._is_playing.clear()

                if blocking:
                    _wait_and_clear()
                else:
                    threading.Thread(target=_wait_and_clear, daemon=True).start()

                return True

        except Exception as e:
            logger.error(f"Ошибка воспроизведения: {e}")
            self._is_playing.clear()
            return False

    def stop(self) -> None:
        """Остановить текущее воспроизведение."""
        try:
            sd.stop()
        except Exception:
            pass
        self._is_playing.clear()

    def speak(self, text: str, blocking: bool = True) -> bool:
        """
        Синтезировать и воспроизвести текст.

        Args:
            text: Текст для озвучивания
            blocking: Блокировать до завершения

        Returns:
            True если успешно
        """
        audio_file = self.synthesize(text)
        if audio_file:
            success = self.play(audio_file, blocking=blocking)
            # Удаляем временный файл после воспроизведения
            try:
                audio_file.unlink()
            except Exception:
                pass
            return success
        return False

    @property
    def current_voice(self) -> str:
        """Получить текущий голос."""
        return self._current_voice

    @property
    def is_speaking(self) -> bool:
        """Проверить, идет ли воспроизведение."""
        return self._is_playing.is_set()


# Глобальный экземпляр
_tts_engine: Optional[TTSEngine] = None


def get_tts_engine() -> TTSEngine:
    """Получить глобальный TTS движок."""
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = TTSEngine()
    return _tts_engine


def is_edge_tts_available() -> bool:
    """Проверить, доступен ли Edge TTS."""
    return edge_tts is not None


# Предопределенные русские голоса
RUSSIAN_VOICES = {
    "dmitry": "ru-RU-DmitryNeural",
    "svetlana": "ru-RU-SvetlanaNeural",
}

# Популярные голоса других языков
POPULAR_VOICES = {
    "en-US": ["en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural"],
    "en-GB": ["en-GB-SoniaNeural", "en-GB-RyanNeural"],
    "de-DE": ["de-DE-KatjaNeural", "de-DE-ConradNeural"],
    "fr-FR": ["fr-FR-DeniseNeural", "fr-FR-HenriNeural"],
    "es-ES": ["es-ES-ElviraNeural", "es-ES-AlvaroNeural"],
    "zh-CN": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
    "ja-JP": ["ja-JP-NanamiNeural", "ja-JP-KeitaNeural"],
}

