"""
Модуль для транскрибции аудио и видео файлов.
Поддерживает пакетную обработку и извлечение аудио из видео.
"""

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

# Поддерживаемые форматы
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv', '.m4v'}
ALL_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


class FileStatus(Enum):
    """Статус обработки файла."""
    PENDING = "pending"
    EXTRACTING = "extracting"  # Извлечение аудио из видео
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"  # Суммаризация через LLM
    GENERATING = "generating"  # Генерация отчёта
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class TranscriptionSegment:
    """Сегмент транскрипции с таймкодами."""
    start: float
    end: float
    text: str
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

    @property
    def full_text(self) -> str:
        """Полный текст транскрипции."""
        return " ".join(seg.text for seg in self.segments if seg.text)

    @property
    def has_summary(self) -> bool:
        """Есть ли саммари."""
        return self.summary is not None and len(self.summary) > 0

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


@dataclass
class FileTask:
    """Задача на обработку файла."""
    file_path: Path
    status: FileStatus = FileStatus.PENDING
    progress: int = 0  # 0-100
    error_message: str = ""
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
    """
    if output_path is None:
        # Создаём временный файл
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        output_path = Path(tmp.name)
        tmp.close()

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

            # Суммаризация (если включена)
            if self.enable_summary and task.result.full_text:
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
                    summary, metrics = self._summarize_text(task.result.full_text, task)
                    task.result.summary = summary
                    task.result.summary_metrics = metrics.to_dict() if metrics else None
                except Exception as e:
                    # Суммаризация не критична — продолжаем без неё
                    task.result.summary = None
                    task.result.summary_metrics = {"error": str(e)}

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

        # Ленивая инициализация суммаризатора с настройками
        if self._summarizer is None:
            config = SummarizerConfig(
                enable_thinking=self.enable_thinking,
                custom_prompts=self.custom_prompts,
            )
            self._summarizer = get_summarizer(config)
        else:
            # Обновляем настройки если изменились
            self._summarizer.config.enable_thinking = self.enable_thinking
            self._summarizer.config.custom_prompts = self.custom_prompts

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


