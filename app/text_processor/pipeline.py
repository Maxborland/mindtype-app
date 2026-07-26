"""
Главный пайплайн постобработки транскрипций.

Оркестрирует все компоненты обработки:
1. Диаризация (определение спикеров)
2. Восстановление пунктуации
3. Удаление филлеров
4. Нормализация текста
5. Коррекция ошибок ASR
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import ProcessingConfig

# Используем тот же логгер что и в diarization
logger = logging.getLogger("diarization")
from .corrector import ASRCorrector
from .diarization import DiarizationResult, SpeakerDiarizer
from .fillers import FillerRemover
from .normalizer import TextNormalizer
from .punctuation import PunctuationRestorer


@dataclass
class ProcessingResult:
    """Результат обработки текста."""
    original_text: str
    processed_text: str
    diarization: Optional[DiarizationResult] = None
    processing_stats: Dict = field(default_factory=dict)

    @property
    def has_speakers(self) -> bool:
        """Есть ли разметка спикеров."""
        return self.diarization is not None and self.diarization.num_speakers > 1

    @property
    def improvement_ratio(self) -> float:
        """Коэффициент улучшения (изменение длины текста)."""
        if not self.original_text:
            return 1.0
        return len(self.processed_text) / len(self.original_text)


# Callback для прогресса
ProcessingProgressCallback = Callable[[str, int, int], None]


class TextProcessingPipeline:
    """
    Пайплайн постобработки транскрипций.

    Применяет последовательно все этапы обработки:
    1. Диаризация (если есть аудио)
    2. Восстановление пунктуации
    3. Удаление филлеров
    4. Нормализация чисел/дат
    5. Коррекция ошибок ASR

    Пример использования:
        pipeline = TextProcessingPipeline()
        result = pipeline.process(
            text="ну эээ давайте обсудим бюджет на двадцать третье марта",
            audio_path=Path("meeting.wav"),
        )
        print(result.processed_text)
        # "Давайте обсудим бюджет на 23 марта."
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()

        # Инициализируем компоненты
        self._diarizer = SpeakerDiarizer(self.config)
        self._punctuation = PunctuationRestorer(self.config)
        self._fillers = FillerRemover(self.config)
        self._normalizer = TextNormalizer(self.config)
        self._corrector = ASRCorrector(self.config)

    def process(
        self,
        text: str,
        audio_path: Optional[Path] = None,
        transcription_segments: Optional[List[dict]] = None,
        progress_callback: Optional[ProcessingProgressCallback] = None,
    ) -> ProcessingResult:
        """
        Выполняет полную обработку транскрипции.

        Args:
            text: Исходный текст транскрипции
            audio_path: Путь к аудиофайлу (для диаризации)
            transcription_segments: Сегменты с таймкодами (для alignment)
            progress_callback: Callback для отображения прогресса

        Returns:
            ProcessingResult с обработанным текстом
        """
        if not text:
            return ProcessingResult(original_text="", processed_text="")

        stats = {
            "original_length": len(text),
            "steps_applied": [],
        }

        result_text = text
        diarization_result = None

        # Определяем язык
        language = self.config.language

        # Шаг 1: Диаризация
        if self.config.enable_diarization:
            if progress_callback:
                progress_callback("Диаризация спикеров...", 0, 100)

            diarization_result = self._run_diarization(
                audio_path, transcription_segments, stats, progress_callback
            )

            if diarization_result is not None:
                # Дружелюбные имена по умолчанию: «Спикер 1» вместо SPEAKER_00.
                # LLM-диаризация может вернуть настоящие имена — дополняем
                # только отсутствующие.
                from .diarization import default_speaker_names
                defaults = default_speaker_names(
                    diarization_result.get_unique_speakers(), language
                )
                diarization_result.speaker_names = {
                    **defaults, **diarization_result.speaker_names
                }

                stats["steps_applied"].append("diarization")
                stats["num_speakers"] = diarization_result.num_speakers

                # Форматируем текст с разметкой спикеров
                if diarization_result.num_speakers > 1:
                    result_text = self._diarizer.format_with_speakers(
                        result_text,
                        diarization_result,
                        transcription_segments,
                    )
                    logger.info(f"Диаризация: найдено {diarization_result.num_speakers} спикеров")

        # Шаг 2: Восстановление пунктуации
        if self.config.enable_punctuation:
            if progress_callback:
                progress_callback("Восстановление пунктуации...", 20, 100)

            try:
                result_text = self._punctuation.restore(result_text, language)
                stats["steps_applied"].append("punctuation")
            except Exception as e:
                stats["punctuation_error"] = str(e)

        # Шаг 3: Удаление филлеров
        if self.config.enable_fillers:
            if progress_callback:
                progress_callback("Удаление слов-паразитов...", 40, 100)

            try:
                fillers_before = len(self._fillers.get_fillers_found(result_text, language))
                result_text = self._fillers.remove(result_text, language)
                stats["steps_applied"].append("fillers")
                stats["fillers_removed"] = fillers_before
            except Exception as e:
                stats["fillers_error"] = str(e)

        # Шаг 4: Нормализация
        if self.config.enable_normalize:
            if progress_callback:
                progress_callback("Нормализация текста...", 60, 100)

            try:
                numbers_before = len(self._normalizer.get_numbers_found(result_text))
                result_text = self._normalizer.normalize(result_text, language)
                stats["steps_applied"].append("normalize")
                stats["numbers_normalized"] = numbers_before
            except Exception as e:
                stats["normalize_error"] = str(e)

        # Шаг 5: Коррекция ошибок ASR
        if self.config.enable_correct:
            if progress_callback:
                progress_callback("Коррекция ошибок...", 80, 100)

            try:
                corrections_before = len(self._corrector.get_corrections_found(result_text, language))
                result_text = self._corrector.correct(result_text, language)
                stats["steps_applied"].append("correct")
                stats["corrections_applied"] = corrections_before
            except Exception as e:
                stats["correct_error"] = str(e)

        # Финальная очистка
        result_text = self._final_cleanup(result_text)
        stats["final_length"] = len(result_text)

        if progress_callback:
            progress_callback("Обработка завершена", 100, 100)

        return ProcessingResult(
            original_text=text,
            processed_text=result_text,
            diarization=diarization_result,
            processing_stats=stats,
        )

    def _run_diarization(
        self,
        audio_path: Optional[Path],
        transcription_segments: Optional[List[dict]],
        stats: Dict,
        progress_callback: Optional[ProcessingProgressCallback] = None,
    ) -> Optional[DiarizationResult]:
        """
        Выполнить диаризацию выбранным бэкендом.

        "openrouter" — разметка спикеров chat-моделью по тексту транскрипта
        (нужны transcription_segments и API ключ); при любой ошибке —
        fallback на локальную MFCC-диаризацию.
        "local" — MFCC + sklearn по аудио.
        """
        if self.config.diarization_backend == "disabled":
            stats["diarization_skipped"] = True
            stats["diarization_error"] = "LOCAL_DIARIZATION_PACK_REQUIRED"
            return None

        # --- OpenRouter (LLM) ---
        if self.config.diarization_backend == "openrouter" and transcription_segments:
            from .llm_diarization import LLMDiarizer

            llm_diarizer = LLMDiarizer(
                api_key=self.config.diarization_api_key,
                model=self.config.diarization_model,
            )
            if llm_diarizer.is_available:
                try:
                    result = llm_diarizer.diarize_segments(
                        transcription_segments,
                        language=self.config.language,
                        progress_callback=progress_callback,
                    )
                    stats["diarization_backend"] = "openrouter"
                    return result
                except Exception as e:
                    stats["diarization_llm_error"] = str(e)
                    logger.error(
                        f"LLM-диаризация не удалась ({e}), fallback на локальную"
                    )
            else:
                logger.warning(
                    "LLM-диаризация недоступна (нет ключа/модели), fallback на локальную"
                )

        # --- Локальная (MFCC + sklearn) ---
        if not (audio_path and audio_path.exists()):
            stats["diarization_skipped"] = True
            return None

        if not self._diarizer.is_available:
            error_msg = self._diarizer.load_error or "Диаризация недоступна"
            stats["diarization_error"] = error_msg
            stats["diarization_skipped"] = True
            logger.warning(f"Диаризация пропущена: {error_msg}")
            return None

        try:
            result = self._diarizer.diarize(audio_path)
            # Сливаем «мелких» спикеров (ошибки кластеризации) сразу,
            # чтобы разметка в тексте и статистика совпадали.
            result = self._diarizer.merge_short_speakers(result)
            stats["diarization_backend"] = "local"
            return result
        except Exception as e:
            stats["diarization_error"] = str(e)
            logger.error(f"Ошибка диаризации: {e}")
            return None

    def process_simple(self, text: str, language: Optional[str] = None) -> str:
        """
        Упрощённая обработка текста (без диаризации и статистики).

        Args:
            text: Исходный текст
            language: Язык текста

        Returns:
            Обработанный текст
        """
        if not text:
            return text

        lang = language or self.config.language
        result = text

        # Применяем все шаги кроме диаризации
        if self.config.enable_punctuation:
            result = self._punctuation.restore(result, lang)

        if self.config.enable_fillers:
            result = self._fillers.remove(result, lang)

        if self.config.enable_normalize:
            result = self._normalizer.normalize(result, lang)

        if self.config.enable_correct:
            result = self._corrector.correct(result, lang)

        return self._final_cleanup(result)

    def _final_cleanup(self, text: str) -> str:
        """Финальная очистка текста."""
        import re

        result = text

        # Убираем множественные пробелы
        result = re.sub(r"\s+", " ", result)

        # Убираем пробелы перед знаками препинания
        result = re.sub(r"\s+([.,!?;:])", r"\1", result)

        # Убираем пробелы после открывающих скобок
        result = re.sub(r"(\()\s+", r"\1", result)

        # Убираем пробелы перед закрывающими скобками
        result = re.sub(r"\s+(\))", r"\1", result)

        # Добавляем пробел после знаков препинания если нет
        result = re.sub(r"([.,!?;:])([А-Яа-яA-Za-z])", r"\1 \2", result)

        # Капитализация после точки
        def capitalize_after_period(match):
            return match.group(1) + match.group(2).upper()

        result = re.sub(r"([.!?]\s+)([а-яa-z])", capitalize_after_period, result)

        # Капитализация первой буквы
        if result and result[0].islower():
            result = result[0].upper() + result[1:]

        return result.strip()

    def get_components_status(self) -> Dict[str, bool]:
        """Возвращает статус доступности компонентов."""
        return {
            "diarization": self._diarizer.is_available,
            "punctuation": self._punctuation.is_available,
            "fillers": True,  # Всегда доступен (regex)
            "normalize": True,  # Всегда доступен (правила)
            "correct": True,  # Всегда доступен (словарь)
        }

    def configure(self, **kwargs) -> None:
        """
        Обновляет конфигурацию пайплайна.

        Args:
            **kwargs: Параметры ProcessingConfig
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    @property
    def diarizer(self) -> SpeakerDiarizer:
        """Доступ к диаризатору."""
        return self._diarizer

    @property
    def punctuation_restorer(self) -> PunctuationRestorer:
        """Доступ к восстановителю пунктуации."""
        return self._punctuation

    @property
    def filler_remover(self) -> FillerRemover:
        """Доступ к удалителю филлеров."""
        return self._fillers

    @property
    def normalizer(self) -> TextNormalizer:
        """Доступ к нормализатору."""
        return self._normalizer

    @property
    def corrector(self) -> ASRCorrector:
        """Доступ к корректору."""
        return self._corrector
