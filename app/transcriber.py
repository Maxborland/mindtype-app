from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple, Protocol, List, Dict, Any, Union
import sys
import os

from .transcriber_cpp import WhisperCppTranscriber

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
        except:
            return False

    def transcribe(self, audio_path, language, beam_size, vad_filter, progress_callback=None):
        segments, info = self.model.transcribe(str(audio_path), beam_size=beam_size, language=None if language == "auto" else language, vad_filter=vad_filter)
        text = " ".join([s.text for s in segments])
        return text.strip(), info.language, info.language_probability

    def transcribe_with_timestamps(self, audio_path, language, beam_size, vad_filter, word_timestamps=False):
        segments_iter, info = self.model.transcribe(str(audio_path), beam_size=beam_size, language=None if language == "auto" else language, vad_filter=vad_filter, word_timestamps=word_timestamps)
        segments = []
        for s in segments_iter:
            segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        return segments, info.language, info.language_probability

    def transcribe_stream(self, audio_path, language, beam_size, vad_filter):
        segments, info = self.model.transcribe(str(audio_path), beam_size=beam_size, language=None if language == "auto" else language, vad_filter=vad_filter)
        full_text = ""
        for s in segments:
            full_text = (full_text + " " + s.text.strip()).strip()
            yield full_text, info.language, info.language_probability


def _prefer_cpp() -> bool:
    """Решать, использовать ли whisper.cpp по умолчанию."""
    if sys.platform == "win32":
        # На Windows всегда предпочитаем whisper.cpp, если есть бинарник
        binary = Path(__file__).parent.parent / "bin" / "win-x64" / "whisper-cli.exe"
        return binary.exists()
    return False

def create_transcriber(backend: str = "auto") -> TranscriberBackend:
    """Фабрика для создания транскрибера."""
    if backend == "whisper.cpp" or (backend == "auto" and _prefer_cpp()):
        return WhisperCppTranscriber()

    if HAS_FASTER_WHISPER:
        return FasterWhisperTranscriber()

    # Если ничего не подошло, пробуем CPP как последний шанс
    return WhisperCppTranscriber()

# Для обратной совместимости с существующим кодом, который делает Transcriber()
class Transcriber:
    def __init__(self, backend: str = "auto"):
        self._impl = create_transcriber(backend)

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
