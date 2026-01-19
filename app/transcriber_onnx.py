import logging
import os
import re
import sys
import numpy as np
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .accelerator import get_best_provider, get_provider_options

logger = logging.getLogger(__name__)

class WhisperOnnxTranscriber:
    """Транскрибер на основе ONNX Runtime для поддержки NPU."""

    def __init__(self):
        self.model_path: Optional[Path] = None
        self.processor = None
        self.model = None
        self.device = "auto"
        self.provider = "CPUExecutionProvider"
        self.provider_options = {}

    def load_model(
        self,
        model_size: str,
        compute_type: str,
        device: str,
        cpu_threads: int = 4,
        num_workers: int = 1,
        models_dir: Optional[Path] = None,
        progress_callback: Optional[Any] = None,
    ):
        """Загрузка ONNX модели."""
        try:
            from transformers import WhisperProcessor
            from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
        except ImportError:
            raise RuntimeError("Необходимые библиотеки (transformers, optimum) не установлены")

        self.device = device
        self.provider = get_best_provider(device)
        self.provider_options = get_provider_options(self.provider)

        logger.info(f"Загрузка ONNX модели {model_size} на {self.provider}")

        if progress_callback:
            progress_callback(f"Загрузка ONNX модели ({model_size})...", 10, 100)

        model_id = f"openai/whisper-{model_size}"
        # В реальном приложении мы бы проверяли локальный кэш в models_dir

        # Загрузка процессора
        self.processor = WhisperProcessor.from_pretrained(model_id)

        # Загрузка модели через Optimum
        self.model = ORTModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            provider=self.provider,
            provider_options=self.provider_options,
            export=True, # Экспортировать в ONNX если нет локально
        )

        if progress_callback:
            progress_callback("ONNX модель загружена", 100, 100)

    def transcribe(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        progress_callback: Optional[Any] = None,
    ) -> Tuple[str, Optional[str], float]:
        """Синхронная транскрипция."""
        import librosa

        audio, _ = librosa.load(str(audio_path), sr=16000)
        input_features = self.processor(audio, sampling_rate=16000, return_tensors="pt").input_features

        # Генерация текста
        predicted_ids = self.model.generate(
            input_features,
            max_length=448,
            num_beams=beam_size,
            language=None if language == "auto" else language,
            task="transcribe"
        )

        transcription = self.processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

        return transcription.strip(), language, 1.0

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
    ) -> Iterable[Tuple[str, Optional[str], float]]:
        """Стриминговая транскрипция (симуляция через чанки для ONNX)."""
        # В полноценной реализации здесь должен быть алгоритм для стриминга
        # Для начала просто возвращаем полный результат как один чанк
        text, lang, prob = self.transcribe(audio_path, language, beam_size, vad_filter)
        yield text, lang, prob

    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        word_timestamps: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], float]:
        """Транскрипция с таймштампами."""
        # Optimum поддерживает return_timestamps
        # Реализация будет позже при необходимости
        text, lang, prob = self.transcribe(audio_path, language, beam_size, vad_filter)
        return [{"start": 0, "end": 0, "text": text}], lang, prob



