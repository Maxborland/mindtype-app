"""
Модуль постобработки транскрипций.

Включает:
- Диаризация спикеров (SpeakerDiarizer)
- Восстановление пунктуации (PunctuationRestorer)
- Удаление филлеров (FillerRemover)
- Нормализация текста (TextNormalizer)
- Коррекция ошибок ASR (ASRCorrector)
- Главный пайплайн (TextProcessingPipeline)
"""

from .config import ProcessingConfig
from .fillers import FillerRemover
from .corrector import ASRCorrector
from .punctuation import PunctuationRestorer
from .normalizer import TextNormalizer
from .diarization import SpeakerDiarizer, DiarizationResult, SpeakerSegment, SpeakerStatistics
from .pipeline import TextProcessingPipeline
from .repetition_filter import (
    remove_repetitions,
    detect_repetition_ratio,
    HallucinationDetector,
    filter_hallucinated_segments,
)

__all__ = [
    "ProcessingConfig",
    "FillerRemover",
    "ASRCorrector",
    "PunctuationRestorer",
    "TextNormalizer",
    "SpeakerDiarizer",
    "DiarizationResult",
    "SpeakerSegment",
    "SpeakerStatistics",
    "TextProcessingPipeline",
    "remove_repetitions",
    "detect_repetition_ratio",
    "HallucinationDetector",
    "filter_hallucinated_segments",
]

