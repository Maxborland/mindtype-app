"""
Модуль для транскрибции аудио и видео файлов.
Поддерживает пакетную обработку и извлечение аудио из видео.
"""

import logging
import os
import tempfile
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional
import threading
import queue

from .text_processor.repetition_filter import (
    filter_hallucinated_segments,
    check_transcription_quality,
)

# Настройка логирования в файл
def _setup_logger():
    logger = logging.getLogger("file_transcriber")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        # Файл логов в %APPDATA%/MindType/file_transcriber.log
        log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "file_transcriber.log"

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)
    return logger

logger = _setup_logger()

# Поддерживаемые форматы
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv', '.m4v'}
ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


class FileStatus(Enum):
    """Статус обработки файла."""
    PENDING = "pending"
    EXTRACTING = "extracting"  # Извлечение аудио из видео
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"  # Постобработка транскрипции
    SUMMARIZING = "summarizing"  # Суммаризация через LLM
    GENERATING = "generating"  # Генерация отчёта
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class SpeakerStats:
    """Статистика спикера."""
    speaker_id: str  # "SPEAKER_00", "SPEAKER_01", ...
    speaker_name: str  # Кастомное имя или то же что speaker_id
    total_duration: float  # Общее время говорения в секундах
    segment_count: int  # Количество реплик
    word_count: int  # Количество слов

    @property
    def duration_formatted(self) -> str:
        """Форматированное время говорения."""
        minutes = int(self.total_duration // 60)
        secs = int(self.total_duration % 60)
        return f"{minutes}:{secs:02d}"


@dataclass
class TranscriptionSegment:
    """Сегмент транскрипции с таймкодами."""
    start: float
    end: float
    text: str
    speaker: Optional[str] = None  # ID спикера (SPEAKER_00, SPEAKER_01, ...)
    words: List[dict] = field(default_factory=list)

    @property
    def start_formatted(self) -> str:
        """Форматированное время начала (HH:MM:SS)."""
        return self._format_time(self.start)

    @property
    def end_formatted(self) -> str:
        """Форматированное время конца (HH:MM:SS)."""
        return self._format_time(self.end)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Форматировать секунды в HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


@dataclass
class TranscriptionResult:
    """Результат транскрипции файла."""
    file_path: Path
    segments: List[TranscriptionSegment]
    detected_language: Optional[str]
    language_probability: float
    duration: float  # Длительность в секундах
    model_used: str
    transcription_date: datetime = field(default_factory=datetime.now)
    # Результат суммаризации (опционально)
    summary: Optional[str] = None
    summary_metrics: Optional[dict] = None
    # Результат постобработки (опционально)
    processed_text: Optional[str] = None
    processing_stats: Optional[dict] = None
    # Статистика спикеров (опционально)
    speaker_stats: Optional[List[SpeakerStats]] = None
    num_speakers: int = 0

    @property
    def full_text(self) -> str:
        """Полный текст транскрипции."""
        return " ".join(seg.text for seg in self.segments if seg.text)

    @property
    def text_for_summary(self) -> str:
        """Текст для суммаризации (обработанный или оригинальный)."""
        return self.processed_text if self.processed_text else self.full_text

    @property
    def has_summary(self) -> bool:
        """Есть ли саммари."""
        return self.summary is not None and len(self.summary) > 0

    @property
    def has_processing(self) -> bool:
        """Была ли постобработка."""
        return self.processed_text is not None

    @property
    def has_speakers(self) -> bool:
        """Есть ли разметка спикеров."""
        return self.num_speakers > 1 and self.speaker_stats is not None

    @property
    def duration_formatted(self) -> str:
        """Форматированная длительность."""
        hours = int(self.duration // 3600)
        minutes = int((self.duration % 3600) // 60)
        secs = int(self.duration % 60)
        if hours > 0:
            return f"{hours}ч {minutes}м {secs}с"
        elif minutes > 0:
            return f"{minutes}м {secs}с"
        return f"{secs}с"

    def get_speaker_segments(self, speaker_id: str) -> List[TranscriptionSegment]:
        """Получить все сегменты конкретного спикера."""
        return [seg for seg in self.segments if seg.speaker == speaker_id]


@dataclass
class FileTask:
    """Задача на обработку файла."""
    file_path: Path
    status: FileStatus = FileStatus.PENDING
    progress: int = 0  # 0-100
    error_message: str = ""
    warning: str = ""  # Предупреждение о качестве (не блокирует, но показывается)
    result: Optional[TranscriptionResult] = None

    @property
    def is_video(self) -> bool:
        """Проверить, является ли файл видео."""
        return self.file_path.suffix.lower() in VIDEO_EXTENSIONS

    @property
    def is_audio(self) -> bool:
        """Проверить, является ли файл аудио."""
        return self.file_path.suffix.lower() in AUDIO_EXTENSIONS

    @property
    def file_name(self) -> str:
        """Имя файла."""
        return self.file_path.name


# Типы callback'ов
ProgressCallback = Callable[[FileTask], None]
CompletedCallback = Callable[[FileTask], None]


def is_supported_file(path: Path) -> bool:
    """Проверить, поддерживается ли формат файла."""
    return path.suffix.lower() in ALL_EXTENSIONS


def get_file_duration(file_path: Path) -> float:
    """
    Получить длительность медиафайла в секундах.
    Использует ffprobe если доступен, иначе возвращает 0.
    """
    try:
        # Пробуем использовать ffprobe
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Пробуем PyAV как альтернативу
    try:
        import av
        with av.open(str(file_path)) as container:
            if container.duration:
                return container.duration / 1000000.0  # microseconds to seconds
    except Exception:
        pass

    return 0.0


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
    ffmpeg_path = shutil.which("ffmpeg")
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


ThinkingCallback = Callable[[str], None]  # Для стриминга AI thinking


class FileTranscriptionQueue:
    """Очередь для пакетной транскрибции файлов с опциональной суммаризацией."""

    def __init__(
        self,
        transcriber,  # Transcriber instance
        model_size: str,
        compute_type: str,
        device: str,
        language: str,
        beam_size: int,
        vad_filter: bool,
        models_dir: Path,
        on_progress: Optional[ProgressCallback] = None,
        on_completed: Optional[CompletedCallback] = None,
        enable_summary: bool = False,  # Включить суммаризацию через Qwen3
        on_thinking: Optional[ThinkingCallback] = None,  # Callback для AI thinking
        enable_thinking: bool = True,  # Включить режим размышлений
        custom_prompts: Optional[Dict[str, str]] = None,  # Кастомные промпты
        # Настройки суммаризации (универсальные)
        summary_provider: str = "local",  # "local", "openrouter", "mindtype_cloud", etc.
        summary_api_key: str = "",  # API ключ или лицензионный ключ (для MindType Cloud)
        summary_model: str = "",
        summary_base_url: str = "",  # Для Ollama
        summary_reasoning: bool = False,
        summary_reasoning_effort: str = "medium",
        # Legacy OpenRouter параметры (обратная совместимость)
        openrouter_api_key: str = "",
        openrouter_model: str = "",
        openrouter_reasoning: bool = False,
        openrouter_reasoning_effort: str = "medium",
        # Постобработка транскрипций
        enable_postprocessing: bool = False,
        postprocessing_diarization: bool = True,
        postprocessing_punctuation: bool = True,
        postprocessing_fillers: bool = True,
        postprocessing_normalize: bool = True,
        postprocessing_correct: bool = True,
    ):
        self.transcriber = transcriber
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.models_dir = models_dir
        self.enable_summary = enable_summary
        self.enable_thinking = enable_thinking
        self.custom_prompts = custom_prompts
        self.summary_provider = summary_provider
        self.summary_api_key = summary_api_key
        self.summary_model = summary_model
        self.summary_base_url = summary_base_url
        self.summary_reasoning = summary_reasoning
        self.summary_reasoning_effort = summary_reasoning_effort
        # Legacy
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model
        self.openrouter_reasoning = openrouter_reasoning
        self.openrouter_reasoning_effort = openrouter_reasoning_effort

        # Настройки постобработки
        self.enable_postprocessing = enable_postprocessing
        self.postprocessing_diarization = postprocessing_diarization
        self.postprocessing_punctuation = postprocessing_punctuation
        self.postprocessing_fillers = postprocessing_fillers
        self.postprocessing_normalize = postprocessing_normalize
        self.postprocessing_correct = postprocessing_correct

        # Логируем настройки постобработки
        logger.info("=" * 50)
        logger.info("FileTranscriptionQueue инициализирована")
        logger.info(f"  enable_postprocessing: {enable_postprocessing}")
        logger.info(f"  postprocessing_diarization: {postprocessing_diarization}")
        logger.info("=" * 50)

        self._on_progress = on_progress
        self._on_completed = on_completed
        self._on_thinking = on_thinking

        self._tasks: List[FileTask] = []
        self._queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._cancelled = threading.Event()
        self._temp_files: List[Path] = []
        self._summarizer = None  # Ленивая инициализация
        self._text_processor = None  # Ленивая инициализация

    @property
    def tasks(self) -> List[FileTask]:
        """Получить список задач."""
        return self._tasks.copy()

    def add_files(self, file_paths: List[Path]) -> List[FileTask]:
        """
        Добавить файлы в очередь.

        Args:
            file_paths: Список путей к файлам

        Returns:
            Список созданных задач
        """
        new_tasks = []
        for path in file_paths:
            if is_supported_file(path) and path.exists():
                task = FileTask(file_path=path)
                self._tasks.append(task)
                self._queue.put(task)
                new_tasks.append(task)
        return new_tasks

    def remove_task(self, task: FileTask) -> bool:
        """Удалить задачу из очереди (если она ещё не обрабатывается)."""
        if task in self._tasks and task.status == FileStatus.PENDING:
            self._tasks.remove(task)
            return True
        return False

    def clear_completed(self) -> None:
        """Удалить завершённые задачи."""
        self._tasks = [t for t in self._tasks if t.status not in
                      (FileStatus.COMPLETED, FileStatus.ERROR, FileStatus.CANCELLED)]

    def start(self) -> None:
        """Запустить обработку очереди."""
        if self._running.is_set():
            return

        self._running.set()
        self._cancelled.clear()

        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def cancel(self) -> None:
        """Отменить обработку."""
        self._cancelled.set()
        self._running.clear()

        # Помечаем все pending задачи как отменённые
        for task in self._tasks:
            if task.status == FileStatus.PENDING:
                task.status = FileStatus.CANCELLED

    def _worker(self) -> None:
        """Рабочий поток для обработки очереди."""
        # Загружаем модель один раз
        try:
            self.transcriber.load_model(
                model_size=self.model_size,
                compute_type=self.compute_type,
                device=self.device,
                models_dir=str(self.models_dir),
            )
        except Exception as e:
            # Помечаем все задачи как ошибочные
            for task in self._tasks:
                if task.status == FileStatus.PENDING:
                    task.status = FileStatus.ERROR
                    task.error_message = f"Ошибка загрузки модели: {e}"
                    if self._on_completed:
                        self._on_completed(task)
            self._running.clear()
            return

        while self._running.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                # Проверяем, есть ли ещё задачи
                remaining = [t for t in self._tasks if t.status == FileStatus.PENDING]
                if not remaining:
                    break
                continue

            if self._cancelled.is_set():
                task.status = FileStatus.CANCELLED
                if self._on_completed:
                    self._on_completed(task)
                continue

            self._process_task(task)

        # Очистка временных файлов
        for tmp in self._temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        self._temp_files.clear()

        self._running.clear()

    def _process_task(self, task: FileTask) -> None:
        """Обработать одну задачу."""
        audio_path = task.file_path

        try:
            # Если видео - извлекаем аудио
            if task.is_video:
                task.status = FileStatus.EXTRACTING
                task.progress = 10
                if self._on_progress:
                    self._on_progress(task)

                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                audio_path = extract_audio_from_video(task.file_path)
                self._temp_files.append(audio_path)
                task.progress = 20

            # Транскрибция
            task.status = FileStatus.TRANSCRIBING
            task.progress = 25
            if self._on_progress:
                self._on_progress(task)

            if self._cancelled.is_set():
                task.status = FileStatus.CANCELLED
                if self._on_completed:
                    self._on_completed(task)
                return

            # Получаем длительность
            duration = get_file_duration(task.file_path)

            # Транскрибируем
            segments_data, detected_lang, prob = self.transcriber.transcribe_with_timestamps(
                audio_path=audio_path,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            )

            if not segments_data:
                logger.warning(f"Транскрипция вернула 0 сегментов для {task.file_path.name}")
                raise ValueError("Транскрипция не вернула ни одного сегмента. Проверьте аудиофайл и настройки.")

            # Фильтруем галлюцинации Whisper (повторы, известные паттерны)
            segments_data, had_hallucinations = filter_hallucinated_segments(segments_data)
            if had_hallucinations:
                logger.warning(f"Обнаружены галлюцинации Whisper в {task.file_path.name}")

            # Проверяем качество транскрипции
            quality_ok, quality_warning = check_transcription_quality(
                segments_data, duration
            )
            if not quality_ok:
                logger.warning(f"Низкое качество транскрипции: {quality_warning}")
                if not segments_data or all(
                    not s.get("text", "").strip() for s in segments_data
                ):
                    raise ValueError(quality_warning)
                # Если есть хоть какой-то текст — продолжаем, но добавим предупреждение
                task.warning = quality_warning

            task.progress = 60
            if self._on_progress:
                self._on_progress(task)

            # Конвертируем в TranscriptionSegment
            segments = [
                TranscriptionSegment(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    words=s.get("words", [])
                )
                for s in segments_data
            ]

            # Создаём результат
            task.result = TranscriptionResult(
                file_path=task.file_path,
                segments=segments,
                detected_language=detected_lang,
                language_probability=prob,
                duration=duration if duration > 0 else (segments[-1].end if segments else 0),
                model_used=self.model_size,
            )

            # Постобработка транскрипции (если включена)
            logger.info(f"Проверка постобработки: enable={self.enable_postprocessing}, text_len={len(task.result.full_text) if task.result.full_text else 0}")
            if self.enable_postprocessing and task.result.full_text:
                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                task.status = FileStatus.PROCESSING
                task.progress = 62
                if self._on_progress:
                    self._on_progress(task)

                try:
                    logger.info(f"Начинаем постобработку для {task.file_path.name}")
                    logger.info(f"  audio_path: {audio_path}")
                    logger.info(f"  segments_count: {len(segments_data)}")
                    processed_result = self._process_text(
                        task.result.full_text,
                        audio_path,
                        segments_data,
                        task,
                    )
                    logger.info(f"Постобработка завершена. Stats: {processed_result.processing_stats}")
                    task.result.processed_text = processed_result.processed_text
                    task.result.processing_stats = processed_result.processing_stats

                    # Извлекаем статистику спикеров из диаризации
                    if processed_result.has_speakers and processed_result.diarization:
                        diar_result = processed_result.diarization

                        # 1. Сливаем слишком мелких спикеров (ошибки кластеризации)
                        diar_result = self.pipeline.diarizer.merge_short_speakers(diar_result)

                        # 2. Выравниваем с текстом транскрипции (чтобы посчитать слова)
                        # Преобразуем segments транскрипции в формат словаря, который ждет align
                        raw_segments = [
                            {"start": s.start, "end": s.end, "text": s.text}
                            for s in task.result.segments
                        ]
                        diar_result = self.pipeline.diarizer.align_with_transcription(diar_result, raw_segments)

                        # 3. Теперь обновляем num_speakers и считаем статистику (уже есть текст и правильные спикеры)
                        task.result.num_speakers = diar_result.num_speakers

                        speaker_statistics = diar_result.get_speaker_statistics()
                        if speaker_statistics:
                            task.result.speaker_stats = [
                                SpeakerStats(
                                    speaker_id=ss.speaker_id,
                                    speaker_name=ss.speaker_name,
                                    total_duration=ss.total_duration,
                                    segment_count=ss.segment_count,
                                    word_count=ss.word_count,
                                )
                                for ss in speaker_statistics
                            ]

                        # 4. Обновляем сегменты транскрипции (чтобы покрасились в HTML)
                        if diar_result.segments:
                            self._update_segments_with_speakers(task, diar_result.segments)

                            # Также обновим processed_result, если нужно, чтобы в pipeline сохранилось
                            processed_result.diarization = diar_result

                    task.progress = 68
                except Exception as e:
                    # Постобработка не критична — продолжаем без неё
                    task.result.processing_stats = {"error": str(e)}

            # Суммаризация (если включена)
            if self.enable_summary and task.result.text_for_summary:
                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                task.status = FileStatus.SUMMARIZING
                task.progress = 70
                if self._on_progress:
                    self._on_progress(task)

                try:
                    summary, metrics = self._summarize_text(task.result.text_for_summary, task)
                    if not summary or len(summary) < 10:
                        raise ValueError("Суммаризация вернула пустой или слишком короткий результат")
                    task.result.summary = summary
                    task.result.summary_metrics = metrics.to_dict() if metrics else None
                except Exception as e:
                    logger.error(f"Ошибка суммаризации для {task.file_path.name}: {e}")
                    # Теперь мы считаем это ошибкой задачи, если саммаризация была включена и не удалась
                    task.status = FileStatus.ERROR
                    task.error_message = f"Ошибка саммаризации: {str(e)}"
                    if self._on_completed:
                        self._on_completed(task)
                    return

            task.status = FileStatus.COMPLETED
            task.progress = 100

        except Exception as e:
            task.status = FileStatus.ERROR
            task.error_message = str(e)

        if self._on_completed:
            self._on_completed(task)

    def _summarize_text(self, text: str, task: FileTask):
        """Выполнить суммаризацию текста."""
        from .summarizer import get_summarizer, SummarizerConfig

        # Определяем параметры: универсальные или legacy openrouter
        api_key = self.summary_api_key or self.openrouter_api_key
        model = self.summary_model or self.openrouter_model
        reasoning = self.summary_reasoning or self.openrouter_reasoning
        reasoning_effort = self.summary_reasoning_effort if self.summary_api_key else self.openrouter_reasoning_effort

        # Ленивая инициализация суммаризатора с настройками
        if self._summarizer is None:
            config = SummarizerConfig(
                enable_thinking=self.enable_thinking,
                custom_prompts=self.custom_prompts,
                provider=self.summary_provider,
                api_key=api_key,
                model=model,
                base_url=self.summary_base_url,
                reasoning_enabled=reasoning,
                reasoning_effort=reasoning_effort,
                # Legacy (для обратной совместимости)
                openrouter_api_key=self.openrouter_api_key,
                openrouter_model=self.openrouter_model,
                openrouter_reasoning=self.openrouter_reasoning,
                openrouter_reasoning_effort=self.openrouter_reasoning_effort,
            )
            self._summarizer = get_summarizer(config)
        else:
            # Обновляем настройки если изменились
            self._summarizer.config.enable_thinking = self.enable_thinking
            self._summarizer.config.custom_prompts = self.custom_prompts
            self._summarizer.config.provider = self.summary_provider
            self._summarizer.config.api_key = api_key
            self._summarizer.config.model = model
            self._summarizer.config.base_url = self.summary_base_url
            self._summarizer.config.reasoning_enabled = reasoning
            self._summarizer.config.reasoning_effort = reasoning_effort
            # Legacy
            self._summarizer.config.openrouter_api_key = self.openrouter_api_key
            self._summarizer.config.openrouter_model = self.openrouter_model
            self._summarizer.config.openrouter_reasoning = self.openrouter_reasoning
            self._summarizer.config.openrouter_reasoning_effort = self.openrouter_reasoning_effort

        # Загружаем модель если нужно
        if not self._summarizer.is_loaded:
            def progress_cb(status: str, current: int, total: int):
                task.progress = 70 + int(10 * current / max(total, 1))
                if self._on_progress:
                    self._on_progress(task)

            # Используем стандартную папку для модели суммаризатора
            from pathlib import Path
            summarizer_dir = Path.home() / ".cache" / "mindtype" / "summarizer"
            self._summarizer.load_model(
                models_dir=summarizer_dir,
                progress_callback=progress_cb,
            )

        # Суммаризируем
        def summary_progress_cb(status: str, current: int, total: int):
            task.progress = 80 + int(15 * current / max(total, 1))
            if self._on_progress:
                self._on_progress(task)

        return self._summarizer.summarize(
            text,
            progress_callback=summary_progress_cb,
            thinking_callback=self._on_thinking,
        )

    def _update_segments_with_speakers(self, task: FileTask, speaker_segments) -> None:
        """
        Обновляет сегменты транскрипции информацией о спикерах.

        Args:
            task: Задача с результатом транскрипции
            speaker_segments: Сегменты диаризации с информацией о спикерах
        """
        if not task.result or not task.result.segments or not speaker_segments:
            return

        # Для каждого сегмента транскрипции находим соответствующего спикера
        for trans_seg in task.result.segments:
            best_speaker = None
            best_overlap = 0

            for diar_seg in speaker_segments:
                # Вычисляем перекрытие по времени
                overlap_start = max(trans_seg.start, diar_seg.start)
                overlap_end = min(trans_seg.end, diar_seg.end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = diar_seg.speaker

            if best_speaker:
                trans_seg.speaker = best_speaker

    def _process_text(self, text: str, audio_path: Path, segments_data: List[dict], task: FileTask):
        """Выполнить постобработку текста транскрипции."""
        from .text_processor import TextProcessingPipeline, ProcessingConfig

        logger.info("_process_text вызван")
        logger.info(f"  diarization: {self.postprocessing_diarization}")

        # Ленивая инициализация процессора
        if self._text_processor is None:
            logger.info("Создаём новый TextProcessingPipeline")
            config = ProcessingConfig(
                enable_diarization=self.postprocessing_diarization,
                enable_punctuation=self.postprocessing_punctuation,
                enable_fillers=self.postprocessing_fillers,
                enable_normalize=self.postprocessing_normalize,
                enable_correct=self.postprocessing_correct,
                language=self.language,
            )
            self._text_processor = TextProcessingPipeline(config)
            logger.info("TextProcessingPipeline создан")
        else:
            # Обновляем настройки если изменились
            self._text_processor.config.enable_diarization = self.postprocessing_diarization
            self._text_processor.config.enable_punctuation = self.postprocessing_punctuation
            self._text_processor.config.enable_fillers = self.postprocessing_fillers
            self._text_processor.config.enable_normalize = self.postprocessing_normalize
            self._text_processor.config.enable_correct = self.postprocessing_correct
            self._text_processor.config.language = self.language

        # Callback для прогресса
        def processing_progress_cb(status: str, current: int, total: int):
            task.progress = 62 + int(6 * current / max(total, 1))
            if self._on_progress:
                self._on_progress(task)

        return self._text_processor.process(
            text=text,
            audio_path=audio_path,
            transcription_segments=segments_data,
            progress_callback=processing_progress_cb,
        )

    @property
    def is_running(self) -> bool:
        """Проверить, выполняется ли обработка."""
        return self._running.is_set()

    @property
    def completed_count(self) -> int:
        """Количество завершённых задач."""
        return sum(1 for t in self._tasks if t.status == FileStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Общее количество задач."""
        return len(self._tasks)


