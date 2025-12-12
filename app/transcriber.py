from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

import ctranslate2
from faster_whisper import WhisperModel
from huggingface_hub import HfApi
import sys

# Маппинг имён моделей на repo_id huggingface
_MODEL_REPO_MAP = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
}


def _pick_device(preferred: str) -> str:
    if preferred != "auto":
        return preferred
    try:
        if ctranslate2.get_device_count("cuda") > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


ProgressCallback = Callable[[str, int, int], None]  # (status, current, total)


def _get_repo_id(model_size: str) -> str:
    """Получить repo_id для модели."""
    if model_size in _MODEL_REPO_MAP:
        return _MODEL_REPO_MAP[model_size]
    # Если это уже repo_id (содержит /)
    if "/" in model_size:
        return model_size
    # Попробуем стандартный формат
    return f"Systran/faster-whisper-{model_size}"


def _patch_faster_whisper_assets_path_for_compiled() -> None:
    """
    In Nuitka/PyInstaller builds, faster_whisper may report __file__ as an absolute
    build-time path, causing assets (Silero VAD ONNX) lookup to fail. We patch the
    assets path to be relative to the executable folder if the bundled asset exists.
    """
    is_compiled = getattr(sys, "frozen", False) or hasattr(sys, "__compiled__")
    if not is_compiled:
        return

    base_dir = Path(sys.executable).resolve().parent
    assets_dir = base_dir / "faster_whisper" / "assets"
    onnx_path = assets_dir / "silero_vad_v6.onnx"
    if not onnx_path.exists():
        return

    try:
        import faster_whisper.utils as fw_utils
        import faster_whisper.vad as fw_vad
    except Exception:
        return

    def _get_assets_path() -> str:
        return str(assets_dir)

    # Patch both: vad imports get_assets_path by value (`from ...utils import get_assets_path`)
    fw_utils.get_assets_path = _get_assets_path  # type: ignore[assignment]
    fw_vad.get_assets_path = _get_assets_path  # type: ignore[assignment]

    # Ensure cached model doesn't keep old path.
    try:
        fw_vad.get_vad_model.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


class Transcriber:
    def __init__(self) -> None:
        self.model_size: Optional[str] = None
        self.compute_type: Optional[str] = None
        self.device: Optional[str] = None
        self.model: Optional[WhisperModel] = None
        self.models_dir: Optional[Path] = None

    def load_model(
        self,
        model_size: str,
        compute_type: str,
        device: str,
        cpu_threads: int = 4,
        num_workers: int = 1,
        models_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        _patch_faster_whisper_assets_path_for_compiled()
        dev = _pick_device(device)
        target_dir = Path(models_dir) if models_dir else None
        if target_dir:
            target_dir.mkdir(parents=True, exist_ok=True)

        if (
            self.model
            and self.model_size == model_size
            and self.compute_type == compute_type
            and self.device == dev
            and self.models_dir == target_dir
        ):
            return

        if progress_callback:
            progress_callback("Загрузка модели...", 0, 100)

        # Определяем источник модели
        model_source = model_size
        if target_dir:
            local_model_path = target_dir / model_size
            if local_model_path.exists() and any(local_model_path.iterdir()):
                # Используем локальную модель
                model_source = str(local_model_path)
                if progress_callback:
                    progress_callback(f"Используем локальную модель: {local_model_path}", 50, 100)

        self.model = WhisperModel(
            model_source,
            device=dev,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=num_workers,
            download_root=str(target_dir) if target_dir else None,
            local_files_only=False,
        )
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = dev
        self.models_dir = target_dir

        if progress_callback:
            progress_callback("Модель загружена", 100, 100)

    def download_model(
        self,
        model_size: str,
        models_dir: Path,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Path:
        """Скачать модель в указанную директорию с прогрессом."""
        from huggingface_hub import hf_hub_download

        models_dir.mkdir(parents=True, exist_ok=True)

        repo_id = _get_repo_id(model_size)
        local_dir = models_dir / model_size
        local_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(f"Проверка репозитория {repo_id}...", 0, 100)

        try:
            # Получаем список файлов
            api = HfApi()
            if progress_callback:
                progress_callback(f"Получение списка файлов...", 2, 100)

            files_list = api.list_repo_files(repo_id)

            # Фильтруем файлы, чтобы не качать лишнее (например, веса PyTorch/TensorFlow)
            import fnmatch
            allowed_patterns = [
                "config.json",
                "model.bin",
                "tokenizer.json",
                "vocabulary.*",
                "preprocessor_config.json"
            ]

            filtered_files = []
            for filename in files_list:
                for pattern in allowed_patterns:
                    if fnmatch.fnmatch(filename, pattern):
                        filtered_files.append(filename)
                        break

            total_files = len(filtered_files)

            if total_files == 0:
                raise RuntimeError(f"Не найдены файлы модели в репозитории {repo_id}")

            if progress_callback:
                progress_callback(f"Найдено {total_files} необходимых файлов", 5, 100)

            # Скачиваем каждый файл с прогрессом
            for idx, filename in enumerate(filtered_files):
                percent = 5 + int((idx / total_files) * 90)
                if progress_callback:
                    progress_callback(f"[{idx+1}/{total_files}] {filename}", percent, 100)

                # Скачиваем файл
                hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=str(local_dir),
                    local_dir_use_symlinks=False,
                )

            if progress_callback:
                progress_callback(f"Модель загружена: {local_dir}", 100, 100)

            return local_dir

        except Exception as e:
            if progress_callback:
                progress_callback(f"Ошибка: {e}", 0, 100)
            raise RuntimeError(f"Не удалось загрузить модель {model_size}: {e}") from e

    def transcribe(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
    ) -> Tuple[str, Optional[str], float]:
        if not self.model:
            raise RuntimeError("Модель не загружена")
        lang = None if language == "auto" else language
        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=lang,
            task="transcribe",  # Важно! Без этого может переводить на английский
            vad_filter=vad_filter,
        )
        text_parts = [seg.text for seg in segments]
        full_text = " ".join(t.strip() for t in text_parts if t.strip())
        detected_lang = info.language if info else None
        prob = info.language_probability if info else 0.0
        return full_text, detected_lang, prob

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str,
        beam_size: int,
        vad_filter: bool,
    ) -> Iterable[Tuple[str, Optional[str], float]]:
        if not self.model:
            raise RuntimeError("Модель не загружена")
        lang = None if language == "auto" else language
        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=beam_size,
            language=lang,
            task="transcribe",  # Важно! Без этого может переводить на английский
            vad_filter=vad_filter,
        )
        detected_lang = info.language if info else None
        prob = info.language_probability if info else 0.0
        full_text = ""
        for seg in segments:
            part = seg.text.strip()
            if not part:
                continue
            full_text = (full_text + " " + part).strip()
            yield full_text, detected_lang, prob


