"""
Модели данных транскрипции файлов: статус задачи, сегмент, результат, статистика спикеров.

Вынесено из file_transcriber — чистые данные без I/O, легко переиспользуются и тестируются.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional
import uuid

from .media_io import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS


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
    # Отображаемые имена спикеров: SPEAKER_00 -> «Спикер 1»
    speaker_names: Dict[str, str] = field(default_factory=dict)
    # Имя пресета промптов, которым делалось саммари (для отчёта)
    summary_preset_name: Optional[str] = None

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
    output_files: Dict[str, Path] = field(default_factory=dict)
    trial_time_charged: bool = False
    operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cloud_job_id: Optional[str] = None

    def claim_trial_time_charge(self) -> bool:
        """Вернуть True только для первого списания времени этой задачи."""
        if self.trial_time_charged:
            return False
        self.trial_time_charged = True
        return True

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


# --- Конфиг-объекты для FileTranscriptionQueue (вместо ~25 плоских параметров) ---

@dataclass
class TranscribeOptions:
    """Параметры распознавания."""
    model_size: str
    compute_type: str
    device: str
    language: str
    beam_size: int
    vad_filter: bool
    models_dir: Path


@dataclass
class SummaryOptions:
    """Параметры суммаризации (+ legacy OpenRouter-поля для обратной совместимости)."""
    enable: bool = False
    enable_thinking: bool = True
    custom_prompts: Optional[Dict[str, str]] = None
    preset_name: str = ""  # Отображаемое имя пресета (для отчёта)
    provider: str = "local"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    reasoning: bool = False
    reasoning_effort: str = "medium"
    # Legacy OpenRouter (обратная совместимость)
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_reasoning: bool = False
    openrouter_reasoning_effort: str = "medium"


@dataclass
class PostProcessOptions:
    """Параметры постобработки транскрипта."""
    enable: bool = False
    diarization: bool = True
    punctuation: bool = True
    fillers: bool = True
    normalize: bool = True
    correct: bool = True
    # Бэкенд диаризации: "auto" (OpenRouter при наличии ключа, иначе локальная),
    # "local" (MFCC + sklearn) или "openrouter" (chat-LLM, fallback на локальную)
    diarization_backend: str = "auto"
    diarization_api_key: str = ""   # OpenRouter API ключ для LLM-диаризации
    diarization_model: str = ""     # Модель LLM-диаризации
