from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple, Protocol, List, Dict, Any, Union
import sys
import os
import logging

from .transcriber_cpp import WhisperCppTranscriber
from .transcriber_onnx import WhisperOnnxTranscriber
from .text_processor import remove_repetitions, HallucinationDetector

logger = logging.getLogger("transcriber")

# Оставляем импорты для обратной совместимости или если нужен legacy режим
try:
    import ctranslate2
    from faster_whisper import WhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False

ProgressCallback = Callable[[str, int, int], None]  # (status, current, total)

class TranscriberBackend(Protocol):
    def load_model(
        self,
        model_size: str,
        compute_type: str,
        device: str,
        cpu_threads: int = 4,
        num_workers: int = 1,
        models_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None: ...

    def transcribe(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Tuple[str, Optional[str], float]: ...

    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
        word_timestamps: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[str], float]: ...

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
    ) -> Iterable[Tuple[str, Optional[str], float]]: ...


class FasterWhisperTranscriber:
    """Legacy backend using faster-whisper."""
    def __init__(self) -> None:
        self.model_size: Optional[str] = None
        self.compute_type: Optional[str] = None
        self.device: Optional[str] = None
        self.model: Optional[Any] = None
        self.models_dir: Optional[Path] = None

    def load_model(self, model_size, compute_type, device, cpu_threads=4, num_workers=1, models_dir=None, progress_callback=None):
        if not HAS_FASTER_WHISPER:
            raise RuntimeError("faster-whisper не установлен")

        from faster_whisper import WhisperModel

        # ... (логика загрузки из оригинального transcriber.py) ...
        # Для краткости я перенесу сюда основной функционал
        dev = self._pick_device(device)
        target_dir = Path(models_dir) if models_dir else None

        if (self.model and self.model_size == model_size and
            self.compute_type == compute_type and self.device == dev):
            return

        if progress_callback:
            progress_callback("Загрузка модели (faster-whisper)...", 0, 100)

        self.model = WhisperModel(
            model_size,
            device=dev,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=num_workers,
            download_root=str(target_dir) if target_dir else None,
        )
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = dev
        if progress_callback:
            progress_callback("Модель загружена", 100, 100)

    def _pick_device(self, preferred: str) -> str:
        if preferred == "auto":
            return "cuda" if self._cuda_is_usable() else "cpu"
        return preferred

    def _cuda_is_usable(self) -> bool:
        try:
            import ctranslate2
            return ctranslate2.get_cuda_device_count() > 0
        except (ImportError, RuntimeError, Exception):
            return False

    def transcribe(self, audio_path, language, beam_size, vad_filter, progress_callback=None):
        # Anti-hallucination параметры
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=None if language == "auto" else language,
            vad_filter=vad_filter,
            compression_ratio_threshold=2.4,  # Фильтр сегментов с высоким сжатием
            no_speech_threshold=0.6,  # Более строгий порог детекции тишины
            log_prob_threshold=-1.0,  # Фильтрация низковероятных выводов
            condition_on_previous_text=True,  # Оставляем контекст для качества
            repetition_penalty=1.1,  # Штраф за повторения
        )

        # Детектор зацикливания - пропускает повторы, но продолжает
        detector = HallucinationDetector(
            similarity_threshold=0.80,
            max_similar_segments=3,
        )

        texts = []
        skipped = 0
        for s in segments_iter:
            text = s.text.strip()

            # Пропускаем повторяющиеся сегменты
            if detector.check(text):
                skipped += 1
                continue

            texts.append(text)

        if skipped > 0:
            logger.info(f"Пропущено {skipped} повторяющихся сегментов")

        full_text = " ".join(texts).strip()

        # Post-processing: удаление повторений
        full_text = remove_repetitions(full_text, max_repeats=2)

        return full_text, info.language, info.language_probability

    def transcribe_with_timestamps(self, audio_path, language, beam_size, vad_filter, word_timestamps=False):
        # Anti-hallucination параметры
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=None if language == "auto" else language,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            condition_on_previous_text=True,
            repetition_penalty=1.1,  # Штраф за повторения
        )

        # Детектор зацикливания - пропускает повторы, но продолжает транскрипцию
        detector = HallucinationDetector(
            similarity_threshold=0.80,
            max_similar_segments=3,
        )

        segments = []
        skipped = 0
        for s in segments_iter:
            text = s.text.strip()

            # check() возвращает True если сегмент нужно пропустить
            if detector.check(text):
                skipped += 1
                continue  # Пропускаем повтор, но продолжаем транскрипцию

            # Post-processing текста сегмента
            text = remove_repetitions(text, max_repeats=2)
            segments.append({"start": s.start, "end": s.end, "text": text})

        if skipped > 0:
            logger.info(f"Пропущено {skipped} повторяющихся сегментов")

        return segments, info.language, info.language_probability

    def transcribe_stream(self, audio_path, language, beam_size, vad_filter):
        # Anti-hallucination параметры
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=None if language == "auto" else language,
            vad_filter=vad_filter,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            condition_on_previous_text=True,
            repetition_penalty=1.1,
        )

        # Детектор зацикливания - пропускает повторы, но продолжает
        detector = HallucinationDetector(
            similarity_threshold=0.80,
            max_similar_segments=3,
        )

        full_text = ""
        for s in segments_iter:
            text = s.text.strip()

            # Пропускаем повторяющиеся сегменты
            if detector.check(text):
                continue

            full_text = (full_text + " " + text).strip()
            # Post-processing: удаление повторений
            clean_text = remove_repetitions(full_text, max_repeats=2)
            yield clean_text, info.language, info.language_probability


def _prefer_cpp() -> bool:
    """Решать, использовать ли whisper.cpp по умолчанию."""
    if sys.platform == "win32":
        # На Windows всегда предпочитаем whisper.cpp, если есть бинарник
        binary = Path(__file__).parent.parent / "bin" / "win-x64" / "whisper-cli.exe"
        return binary.exists()
    return False

def create_transcriber(backend: str = "auto") -> TranscriberBackend:
    """Фабрика для создания транскрибера."""
    if backend == "openrouter":
        from .transcriber_openrouter import OpenRouterTranscriber
        return OpenRouterTranscriber()

    if backend == "onnx":
        return WhisperOnnxTranscriber()

    if backend == "whisper_cpp" or backend == "whisper.cpp" or (backend == "auto" and _prefer_cpp()):
        return WhisperCppTranscriber()

    if backend == "faster_whisper" or (backend == "auto" and HAS_FASTER_WHISPER):
        return FasterWhisperTranscriber()

    # Если ничего не подошло, пробуем CPP как последний шанс
    return WhisperCppTranscriber()

# Для обратной совместимости с существующим кодом, который делает Transcriber()
class Transcriber:
    def __init__(self, backend: str = "auto"):
        self._impl = create_transcriber(backend)

    def set_download_sources(self, sources: List[str]) -> None:
        """Configure where transcription models are downloaded from (if supported)."""
        if hasattr(self._impl, "set_download_sources"):
            try:
                self._impl.set_download_sources(sources)
            except Exception:
                # Don't fail app startup if backend ignores/doesn't accept sources.
                pass

    def load_model(self, *args, **kwargs):
        return self._impl.load_model(*args, **kwargs)

    def transcribe(self, *args, **kwargs):
        return self._impl.transcribe(*args, **kwargs)

    def transcribe_with_timestamps(self, *args, **kwargs):
        return self._impl.transcribe_with_timestamps(*args, **kwargs)

    def transcribe_stream(self, *args, **kwargs):
        return self._impl.transcribe_stream(*args, **kwargs)

    def download_model(self, model_size: str, models_dir: Path, progress_callback=None) -> Path:
        if hasattr(self._impl, "download_model"):
             return self._impl.download_model(model_size, models_dir, progress_callback)
        return Path(models_dir)
