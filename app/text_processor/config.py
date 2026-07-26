"""
Конфигурация пайплайна постобработки транскрипций.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ProcessingConfig:
    """Конфигурация постобработки транскрипций."""

    # Включение/выключение компонентов
    enable_diarization: bool = True
    enable_punctuation: bool = True
    enable_fillers: bool = True
    enable_normalize: bool = True
    enable_correct: bool = True

    # Бэкенд диаризации:
    #   "local"      — MFCC + sklearn (отдельный optional pack)
    #   "openrouter" — chat-LLM через OpenRouter (нужен API ключ; точнее на диалогах)
    #   "disabled"   — диаризация недоступна в установленном runtime.
    diarization_backend: str = "local"
    # OpenRouter для LLM-диаризации
    diarization_api_key: str = ""
    diarization_model: str = ""

    # Диаризация (MFCC + sklearn - лёгкая версия)
    diarization_min_speakers: int = 1
    diarization_max_speakers: int = 8  # Ограничение количества спикеров
    diarization_segment_duration: float = 2.0  # Длина сегмента в секундах
    diarization_threshold: float = 15.0  # Порог для AgglomerativeClustering (после нормализации)

    # Пунктуация
    punctuation_model: str = "oliverguhr/fullstop-punctuation-multilang-large"

    # Филлеры - кастомные списки
    custom_fillers_ru: List[str] = field(default_factory=list)
    custom_fillers_en: List[str] = field(default_factory=list)
    filler_preserve_context: bool = True  # Не удалять если часть фразы

    # Нормализация
    normalize_numbers: bool = True
    normalize_dates: bool = True
    normalize_currency: bool = True
    normalize_time: bool = True

    # Коррекция
    custom_corrections: Dict[str, str] = field(default_factory=dict)
    use_llm_correction: bool = False  # Использовать LLM для сложных случаев

    # Кэширование моделей
    models_cache_dir: Optional[Path] = None

    # Язык
    language: str = "ru"

    def __post_init__(self):
        if self.models_cache_dir is None:
            self.models_cache_dir = Path.home() / ".cache" / "mindtype" / "text_processor"

