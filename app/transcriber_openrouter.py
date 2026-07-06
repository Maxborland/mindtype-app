"""
Бэкенд транскрипции через OpenRouter STT-эндпоинт.

Альтернатива локальному whisper.cpp: аудио режется на чанки и отправляется
на POST /api/v1/audio/transcriptions (модели openai/whisper-1 и т.п.).
Реализует протокол TranscriberBackend (см. app/transcriber.py).
"""

import base64
import io
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .text_processor import remove_repetitions
from .llm.base import (
    LLMAuthError,
    LLMInvalidModelError,
    LLMInsufficientFundsError,
    LLMRateLimitError,
)

logger = logging.getLogger("transcriber.openrouter")

# Порог RMS-гейта тишины: librosa отдаёт float [-1, 1]. Берём консервативно низкий
# (~-74 dBFS): режем только почти цифровую тишину, чтобы НЕ терять тихую речь
# (низкий gain микрофона). Галлюцинации на остатках ловит remove_repetitions ниже.
_SILENCE_RMS = 2e-4


class OpenRouterTranscriber:
    """Транскрипция через OpenRouter STT с чанкингом."""

    def __init__(self) -> None:
        self._provider = None          # app.llm.openrouter.OpenRouterProvider
        self._model: str = ""
        self._language: str = "auto"
        self._chunk_sec: int = 30
        self._timeout: int = 120

    def load_model(
        self,
        model_size: Optional[str] = None,
        compute_type: str = "default",
        device: str = "auto",
        cpu_threads: int = 4,
        num_workers: int = 1,
        models_dir: Optional[Any] = None,
        progress_callback=None,
    ) -> None:
        # Whisper-параметры (model_size/compute_type/device/...) не применимы к API.
        # ponytail: читаем конфиг на каждый load_model (вызывается перед каждой
        # транскрипцией) — подхватываем смену ключа/модели без пересоздания объекта;
        # ConfigManager дешёв (JSON + keyring).
        from .config import ConfigManager
        from .llm.openrouter import OpenRouterProvider

        cfg = ConfigManager().config
        api_key = (cfg.get("openrouter_api_key") or "").strip()
        self._model = (cfg.get("openrouter_transcribe_model") or "").strip()
        try:
            self._chunk_sec = max(1, int(cfg.get("openrouter_transcribe_chunk_sec", 30)))
        except (TypeError, ValueError):
            self._chunk_sec = 30
        self._language = cfg.get("language", "auto") or "auto"

        if not api_key:
            raise RuntimeError("OpenRouter API ключ не задан (Настройки → AI Provider).")
        if not self._model:
            raise RuntimeError("Не выбрана модель транскрипции OpenRouter (Настройки → Performance).")

        self._provider = OpenRouterProvider(api_key=api_key, timeout=self._timeout)
        if progress_callback:
            progress_callback("model_loaded", 100, 100)

    def _iter_chunks(
        self, audio_path: Path, progress_callback=None
    ) -> Iterable[Tuple[int, float, float, str]]:
        """Нарезать аудио и yield'ить (idx, start_sec, dur_sec, text) по чанкам."""
        import numpy as np
        import soundfile as sf

        from .audio_io import load_16k_mono

        data, sr = load_16k_mono(audio_path)  # любой формат → 16k mono
        if data.size == 0:
            return

        # ponytail: жёсткая нарезка по времени без перекрытия — слово на границе
        # чанка может расколоться; добавить overlap/резку по тишине, если качество
        # просядет.
        step = max(1, self._chunk_sec * sr)
        total = (len(data) + step - 1) // step
        attempted = 0  # сколько чанков реально отправлено (не тишина)
        failed = 0     # сколько из них упало после ретраев

        for idx, start in enumerate(range(0, len(data), step)):
            chunk = data[start:start + step]
            start_sec = start / sr
            dur_sec = len(chunk) / sr

            if float(np.sqrt(np.mean(chunk ** 2))) < _SILENCE_RMS:
                logger.debug("Чанк %d/%d почти тишина — пропускаю", idx + 1, total)
                text = ""
            else:
                attempted += 1
                buf = io.BytesIO()
                sf.write(buf, chunk, sr, format="WAV", subtype="PCM_16")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                try:
                    text = self._provider.transcribe_audio(
                        b64, "wav", self._model, language=self._language
                    )
                except (LLMAuthError, LLMInvalidModelError, LLMInsufficientFundsError, LLMRateLimitError):
                    # Постоянные ошибки (ключ/модель/баланс/лимит) — на каждом чанке одинаковы,
                    # пропускать бессмысленно: прерываем сразу с понятной ошибкой.
                    raise
                except Exception:
                    # ponytail: транзиентный сбой одного чанка (уже после ретраев) не
                    # должен терять весь многочанковый файл — логируем и продолжаем;
                    # для одиночного чанка (диктовка) пробрасываем, чтобы ошибка была видна.
                    if total <= 1:
                        raise
                    failed += 1
                    logger.warning(
                        "Чанк %d/%d не транскрибирован, пропускаю", idx + 1, total, exc_info=True
                    )
                    text = ""

            if progress_callback:
                progress_callback("transcribing", idx + 1, total)
            yield idx, start_sec, dur_sec, text

        # Если все отправленные чанки упали — не отдаём «успешный» пустой результат.
        if attempted > 0 and failed == attempted:
            raise RuntimeError(
                "OpenRouter: не удалось транскрибировать ни один фрагмент (все запросы упали)."
            )
        return

    def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
        progress_callback=None,
    ) -> Tuple[str, Optional[str], float]:
        self._language = language
        parts: List[str] = []
        for _idx, _start, _dur, text in self._iter_chunks(audio_path, progress_callback):
            if text:
                parts.append(text)
        full = remove_repetitions(" ".join(parts).strip(), max_repeats=2)
        return full, (None if language == "auto" else language), 1.0

    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
        word_timestamps: bool = False,
        progress_callback=None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], float]:
        # ponytail: таймкоды с гранулярностью чанка (нет word-level от STT-эндпоинта) —
        # достаточно для SRT, точнее не получить без отдельного API.
        self._language = language
        segments: List[Dict[str, Any]] = []
        for _idx, start, dur, text in self._iter_chunks(audio_path, progress_callback):
            if text:
                segments.append({"start": start, "end": start + dur, "text": text})
        return segments, (None if language == "auto" else language), 1.0

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
    ) -> Iterable[Tuple[str, Optional[str], float]]:
        self._language = language
        lang = None if language == "auto" else language
        full = ""
        for _idx, _start, _dur, text in self._iter_chunks(audio_path):
            if text:
                full = (full + " " + text).strip()
                yield remove_repetitions(full, max_repeats=2), lang, 1.0
