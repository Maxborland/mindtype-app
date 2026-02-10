import json
import os
import subprocess
import sys
import re
import logging
import time
import shutil
import numpy as np
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, Iterable

from .accelerator import get_best_provider, get_provider_options

# Настройка локального логгера
logger = logging.getLogger("transcriber_cpp")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    try:
        log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "transcriber_cpp.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
    except Exception:
        # In restricted environments (tests/sandbox), writing outside the workspace
        # can fail. Don't crash on import: fall back to a no-op handler.
        logger.addHandler(logging.NullHandler())

class VADFilter:
    """Лёгкий фильтр голоса на основе Silero VAD (ONNX)."""

    def __init__(self, model_path: Path):
        import onnxruntime as ort
        self.model_path = model_path

        # Используем NPU если доступен, иначе CPU
        provider = get_best_provider("npu")
        options = get_provider_options(provider)

        self.session = ort.InferenceSession(
            str(model_path),
            providers=[provider],
            provider_options=[options] if options else None
        )
        logger.info(f"VADFilter инициализирован с моделью: {model_path} на {provider}")

    def is_speech(self, audio_data: np.ndarray, threshold: float = 0.5, sample_rate: int = 16000) -> bool:
        """Проверка, есть ли речь в фрагменте аудио."""
        # Модель ожидает определённый размер чанка. Согласно логам, ожидается 576.
        window_size = 576

        if len(audio_data) == 0:
            return False

        # Паддинг до кратности window_size
        if len(audio_data) % window_size != 0:
            audio_data = np.pad(audio_data, (0, window_size - len(audio_data) % window_size))

        # Состояния для RNN
        h = np.zeros((1, 1, 128), dtype=np.float32)
        c = np.zeros((1, 1, 128), dtype=np.float32)

        # Обработка по чанкам
        for i in range(0, len(audio_data), window_size):
            chunk = audio_data[i:i+window_size].reshape(1, window_size)
            # Входные данные должны быть float32
            if chunk.dtype != np.float32:
                chunk = chunk.astype(np.float32)

            # Нормализация (Silero ожидает [-1, 1])
            if np.max(np.abs(chunk)) > 1.01: # Небольшой запас для float
                chunk = chunk / 32768.0

            ort_inputs = {
                "input": chunk,
                "h": h,
                "c": c
            }
            try:
                outputs = self.session.run(None, ort_inputs)
                # Обрабатываем разные форматы вывода
                if isinstance(outputs, (list, tuple)) and len(outputs) >= 1:
                    out = outputs[0]
                    # Проверяем форму вывода
                    if isinstance(out, np.ndarray):
                        if out.size > 0:
                            prob = out.flat[0] if out.ndim > 0 else float(out)
                            if prob > threshold:
                                return True
                        # Обновляем состояния для следующей итерации
                        if len(outputs) >= 3:
                            h = outputs[1]
                            c = outputs[2]
                    else:
                        # Скалярный вывод
                        if float(out) > threshold:
                            return True
                else:
                    logger.warning(f"VAD: неожиданный формат вывода: {type(outputs)}")
            except Exception as e:
                logger.error(f"VAD session run error: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                # Фоллбэк: считаем что речь есть если VAD упал, чтобы не пропустить транскрипцию
                return True
        return False

class WhisperCppTranscriber:
    """Транскрибер на основе whisper.cpp бинарника."""

    def __init__(self):
        self.model_path: Optional[Path] = None
        self.binary_path: Path = self._find_binary()
        self.device: str = "auto"
        self.gpu_backend: str = self._detect_gpu_backend()
        self.threads: int = 4
        self._vad = None
        # Preferred model download sources (CDN/mirrors). If empty, _download_model()
        # falls back to built-in defaults.
        self._download_sources: List[str] = []

        # Убеждаемся, что бинарник есть и готов к работе
        self._ensure_binary()
        logger.info(f"Инициализирован WhisperCppTranscriber. Платформа: {sys.platform}, Backend: {self.gpu_backend}, Бинарник: {self.binary_path}")

    def set_download_sources(self, sources: List[str]) -> None:
        """Set ordered list of download sources for GGML whisper.cpp models."""
        cleaned: List[str] = []
        for src in sources or []:
            try:
                s = str(src).strip()
            except Exception:
                continue
            if not s:
                continue
            cleaned.append(s)
        self._download_sources = cleaned

    def _detect_gpu_backend(self) -> str:
        """Определить доступный GPU backend."""
        if sys.platform == "darwin":
            return "metal"

        if sys.platform == "win32":
            # На Windows мы используем DirectML бинарник (обычно поставляется в комплекте)
            return "directml"

        # Linux: проверяем наличие Vulkan
        if shutil.which("vulkaninfo") or Path("/usr/lib/x86_64-linux-gnu/libvulkan.so.1").exists():
            return "vulkan"

        return "cpu"

    def _find_binary(self) -> Path:
        """Найти путь к бинарнику в зависимости от платформы."""
        base_path = Path(__file__).parent.parent / "bin"

        if sys.platform == "win32":
            return base_path / "win-x64" / "whisper-cli.exe"
        elif sys.platform == "darwin":
            # На Mac обычно ставится через brew или лежит в bin
            brew_path = Path("/usr/local/bin/whisper-cli")
            if brew_path.exists(): return brew_path
            return base_path / "darwin-arm64" / "whisper-cli"
        else:
            return base_path / "linux-x64" / "whisper-cli"

    def _ensure_binary(self) -> None:
        """Проверить наличие бинарника и права доступа."""
        if not self.binary_path.exists():
            if sys.platform == "win32":
                logger.error(f"Бинарник для Windows не найден: {self.binary_path}")
                # Для Windows мы ожидаем, что он уже там, так как автозагрузка сложнее из-за DLL
            else:
                logger.info(f"Бинарник не найден по пути {self.binary_path}. Попытка автоматической настройки...")
                self._setup_linux_macos_binary()

        # На Unix-системах проверяем права на выполнение
        if sys.platform != "win32" and self.binary_path.exists():
            try:
                st = os.stat(self.binary_path)
                os.chmod(self.binary_path, st.st_mode | 0o111)
            except Exception as e:
                logger.warning(f"Не удалось установить права на выполнение для {self.binary_path}: {e}")

    def _setup_linux_macos_binary(self) -> None:
        """Инструкции или автоматика для настройки бинарника на Linux/Mac."""
        if sys.platform == "linux":
            print("\n" + "="*50)
            print("ПОДСКАЗКА ДЛЯ LINUX:")
            print(f"Бинарник whisper-cli не найден в {self.binary_path.parent}")
            print("Вы можете скомпилировать его одной командой:")
            print(f"git clone https://github.com/ggerganov/whisper.cpp && cd whisper.cpp && make -j whisper-cli")
            print(f"Затем скопируйте файл 'whisper-cli' в {self.binary_path.parent}")
            print("="*50 + "\n")
        elif sys.platform == "darwin":
            print("\n" + "="*50)
            print("ПОДСКАЗКА ДЛЯ macOS:")
            print("Установите whisper.cpp через Homebrew:")
            print("brew install whisper-cpp")
            print("Или скомпилируйте вручную через 'make'.")
            print("="*50 + "\n")

    def _decode_bytes(self, b: bytes) -> str:
        """Надёжное декодирование вывода процесса."""
        if not b: return ""
        # Пробуем UTF-8, потом системные кодировки Windows
        for enc in ["utf-8", "cp1251", "cp866"]:
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_whisper_json_items(data: Any) -> List[Dict[str, Any]]:
        """
        whisper.cpp JSON shape can vary by version/flags.

        Known variants:
        - {"transcription": [ ... ]}
        - {"segments": [ ... ]}
        - {"result": {"transcription": [ ... ]}}
        - {"result": {"segments": [ ... ]}}
        - [ ... ] (rare; treat as already-a-list)
        """
        if isinstance(data, dict):
            if isinstance(data.get("transcription"), list):
                return [x for x in data.get("transcription", []) if isinstance(x, dict)]
            if isinstance(data.get("segments"), list):
                return [x for x in data.get("segments", []) if isinstance(x, dict)]

            result = data.get("result")
            if isinstance(result, dict):
                if isinstance(result.get("transcription"), list):
                    return [x for x in result.get("transcription", []) if isinstance(x, dict)]
                if isinstance(result.get("segments"), list):
                    return [x for x in result.get("segments", []) if isinstance(x, dict)]

            return []

        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]

        return []

    @staticmethod
    def _parse_timestamp_to_seconds(ts: Any) -> Optional[float]:
        if not isinstance(ts, str):
            return None
        ts = ts.strip()
        # Formats: HH:MM:SS.mmm or HH:MM:SS,mmm
        m = re.match(r"^(\\d{2,}):(\\d{2}):(\\d{2})[\\.,](\\d{1,3})$", ts)
        if not m:
            return None
        h = int(m.group(1))
        mi = int(m.group(2))
        s = int(m.group(3))
        ms = int(m.group(4).ljust(3, "0"))
        return h * 3600 + mi * 60 + s + (ms / 1000.0)

    @classmethod
    def _extract_segment_times(cls, seg: Dict[str, Any]) -> Tuple[float, float]:
        offsets = seg.get("offsets")
        if isinstance(offsets, dict):
            start_ms = offsets.get("from")
            end_ms = offsets.get("to")
            if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)):
                return float(start_ms) / 1000.0, float(end_ms) / 1000.0

        timestamps = seg.get("timestamps")
        if isinstance(timestamps, dict):
            s = cls._parse_timestamp_to_seconds(timestamps.get("from"))
            e = cls._parse_timestamp_to_seconds(timestamps.get("to"))
            if s is not None and e is not None:
                return s, e

        for a, b in (("start", "end"), ("from", "to"), ("t0", "t1")):
            sa = seg.get(a)
            sb = seg.get(b)
            if isinstance(sa, (int, float)) and isinstance(sb, (int, float)):
                s = float(sa)
                e = float(sb)
                # Heuristic: segment lengths in ms are usually thousands; in seconds usually < 60.
                if (e - s) > 100:
                    s /= 1000.0
                    e /= 1000.0
                return s, e

        return 0.0, 0.0

    @staticmethod
    def _clean_stdout_text(stdout: str) -> str:
        if not stdout:
            return ""

        filtered_lines: List[str] = []
        for line in stdout.splitlines():
            s = line.strip()
            if not s:
                continue
            # Some whisper.cpp builds can emit logs to stdout.
            if s.startswith(("ggml_", "whisper_", "output_json:", "system_info:")):
                continue
            filtered_lines.append(s)

        text = "\\n".join(filtered_lines)
        text = re.sub(
            r"\\[\\d{2}:\\d{2}:\\d{2}\\.\\d{3}\\s*-+>\\s*\\d{2}:\\d{2}:\\d{2}\\.\\d{3}\\]\\s*",
            "",
            text,
        )
        return " ".join(text.split()).strip()

    def load_model(
        self,
        model_size: str,
        compute_type: str = "default",
        device: str = "auto",
        cpu_threads: int = 4,
        num_workers: int = 1,
        models_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> None:
        """Загрузить (проверить наличие) GGML модель."""
        self.device = device
        self.threads = cpu_threads

        if not models_dir:
            models_dir = Path(__file__).parent.parent / "models"
        else:
            models_dir = Path(models_dir)

        models_dir.mkdir(parents=True, exist_ok=True)

        # Нормализуем и санируем имя модели
        model_name = model_size.lower()
        if model_name.startswith("ggml-"):
            model_name = model_name[5:]
        if model_name.endswith(".bin"):
            model_name = model_name[:-4]

        # Оставляем только безопасные символы
        model_name = "".join(c for c in model_name if c.isalnum() or c in ".-_")

        model_filename = f"ggml-{model_name}.bin"

        # Защита от path traversal
        try:
            target_path = (models_dir / model_filename).resolve()
            base_resolved = models_dir.resolve()
            if not str(target_path).startswith(str(base_resolved)):
                logger.error(f"Попытка выхода за пределы папки моделей: {target_path}")
                raise ValueError("Некорректное имя модели")
            self.model_path = target_path
        except Exception as e:
            if isinstance(e, ValueError): raise
            self.model_path = models_dir / model_filename

        logger.info(f"Загрузка модели: {model_name}, ожидаемый файл: {self.model_path}")

        if not self.model_path.exists():
            # Prefer bundled models shipped with the app when available (offline/first-run UX).
            try:
                from .config import BUNDLED_MODELS_DIR

                bundled_path = (BUNDLED_MODELS_DIR / model_filename)
                if bundled_path.exists():
                    self.model_path = bundled_path
                    logger.info(f"Используем встроенную модель: {self.model_path}")
                    if progress_callback:
                        progress_callback("model_loaded", 100, 100)
                    return
            except Exception:
                # If config can't be imported in restricted environments/tests, ignore.
                pass

            logger.info(f"Файл модели не найден, начинаем загрузку...")
            if progress_callback:
                progress_callback("downloading_model", 0, 100)
            self._download_model(
                model_name,
                models_dir,
                progress_callback,
                sources=self._download_sources or None,
            )
        else:
            logger.info(f"Файл модели уже существует.")
            if progress_callback:
                progress_callback("model_loaded", 100, 100)

    def _download_model(
        self,
        model_name: str,
        models_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        sources: Optional[List[str]] = None,
    ) -> None:
        """
        Скачать GGML модель.

        В некоторых регионах Hugging Face может быть недоступен или работать
        нестабильно, поэтому мы поддерживаем несколько источников (CDN/зеркала)
        и скачиваем модель напрямую по URL.

        Каждый источник может быть:
        - базовым URL (скачиваем <base>/<filename>)
        - шаблоном с {repo_id} и {filename}
        """
        import urllib.parse
        import urllib.request
        import urllib.error

        repo_id = "ggerganov/whisper.cpp"
        filename = f"ggml-{model_name}.bin"
        dest_path = models_dir / filename

        default_sources: List[str] = [
            # MindType CDN (if available)
            "https://cdn.mindtype.space/models/whispercpp",
            "https://mindtype.space/models/whispercpp",
            # HF mirrors and HF
            "https://hf-mirror.com/{repo_id}/resolve/main/{filename}",
            "https://huggingface.co/{repo_id}/resolve/main/{filename}",
        ]

        sources_to_try: List[str] = list(sources or default_sources)

        # Emergency override (comma-separated) for support/debugging.
        env_sources = os.getenv("MINDTYPE_MODEL_DOWNLOAD_SOURCES", "").strip()
        if env_sources:
            parsed = [s.strip() for s in env_sources.split(",") if s.strip()]
            if parsed:
                sources_to_try = parsed

        def _build_url(src: str) -> str:
            if "{" in src and "}" in src:
                try:
                    return src.format(repo_id=repo_id, filename=filename)
                except Exception:
                    pass
            return src.rstrip("/") + "/" + filename

        def _download_url(url: str) -> None:
            part_path = dest_path.with_suffix(dest_path.suffix + ".part")

            headers = {"User-Agent": "MindType"}

            downloaded = 0
            try:
                if part_path.exists():
                    downloaded = int(part_path.stat().st_size)
            except Exception:
                downloaded = 0

            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            req = urllib.request.Request(url, headers=headers)

            # Use certifi bundle when available (packaged apps can lack system CA store).
            context = None
            try:
                import ssl
                import certifi
                context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                context = None

            open_kwargs = {"timeout": 30}
            if context is not None:
                open_kwargs["context"] = context

            with urllib.request.urlopen(req, **open_kwargs) as resp:
                status = getattr(resp, "status", None) or resp.getcode()

                # If resume is not supported by this source, don't clobber the
                # existing partial download (it might be resumable from another source).
                if downloaded > 0 and status != 206:
                    # Some servers respond 416 when the Range starts at EOF.
                    if status == 416:
                        try:
                            cr = (resp.headers.get("Content-Range") or "").strip()
                            # e.g. "bytes */77691713"
                            m = re.search(r"/\s*(\d+)\s*$", cr)
                            total_full = int(m.group(1)) if m else 0
                        except Exception:
                            total_full = 0

                        try:
                            if total_full > 0 and part_path.exists() and part_path.stat().st_size == total_full:
                                part_path.replace(dest_path)
                                return
                        except Exception:
                            pass

                    raise RuntimeError(f"resume not supported (status {status})")

                total = 0
                try:
                    clen = resp.headers.get("Content-Length")
                    if clen:
                        total = int(clen)
                except Exception:
                    total = 0
                if status == 206 and total > 0:
                    total += downloaded

                # Sanity checks: protect against HTML error pages / wrong content.
                ctype = ""
                try:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                except Exception:
                    ctype = ""
                if ctype and ("text/html" in ctype or "application/json" in ctype):
                    # If we only have a tiny partial, it's almost certainly an error page.
                    try:
                        if part_path.exists() and part_path.stat().st_size < 1024 * 1024:
                            part_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise RuntimeError(f"unexpected content type: {ctype}")

                if total > 0 and total < 5 * 1024 * 1024:
                    # Whisper models are much larger than a few MB.
                    try:
                        if part_path.exists() and part_path.stat().st_size < 1024 * 1024:
                            part_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise RuntimeError(f"unexpected file size: {total} bytes")

                if progress_callback:
                    progress_callback("downloading_model", downloaded, total)

                mode = "ab" if downloaded > 0 else "wb"
                with open(part_path, mode) as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback("downloading_model", downloaded, total)

            if not part_path.exists() or part_path.stat().st_size <= 0:
                raise RuntimeError("downloaded file is empty")

            # If we know expected size, ensure we downloaded the whole file.
            if total > 0 and downloaded != total:
                raise RuntimeError(f"incomplete download: {downloaded}/{total} bytes")

            # Extra safety: if the downloaded file is suspiciously small, reject it.
            try:
                if part_path.stat().st_size < 5 * 1024 * 1024:
                    try:
                        part_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    raise RuntimeError("downloaded file is too small")
            except Exception:
                # If stat fails, treat as error.
                raise

            part_path.replace(dest_path)

        part_path = dest_path.with_suffix(dest_path.suffix + ".part")

        def _part_size() -> int:
            try:
                if part_path.exists():
                    return int(part_path.stat().st_size)
            except Exception:
                return 0
            return 0

        # Large model downloads can be flaky in some networks (abrupt EOF / connection resets).
        # We keep retrying across sources while we are making progress (resume via .part + Range).
        last_progress_size = _part_size()
        no_progress_rounds = 0
        max_no_progress_rounds = 2
        errors_by_url: Dict[str, str] = {}

        while True:
            round_progress = False

            for src in sources_to_try:
                url = _build_url(src)
                parsed = urllib.parse.urlparse(url)
                if parsed.scheme not in ("https", "http"):
                    errors_by_url[url] = "unsupported scheme"
                    continue

                before = _part_size()
                try:
                    logger.info(f"Скачивание {filename} из {url}...")
                    _download_url(url)
                    self.model_path = dest_path
                    logger.info(f"Модель успешно скачана: {self.model_path}")
                    return
                except InterruptedError:
                    # Cancellation should stop immediately and propagate to the worker/UI.
                    raise
                except Exception as e:
                    errors_by_url[url] = str(e)
                    after = _part_size()
                    if after > before:
                        round_progress = True
                    logger.warning(f"Ошибка скачивания: {url}: {e}")
                    # Avoid hammering the same endpoint in tight loops.
                    time.sleep(0.5)
                    continue

            current_size = _part_size()
            if current_size > last_progress_size:
                round_progress = True
                last_progress_size = current_size

            if round_progress:
                no_progress_rounds = 0
                continue

            no_progress_rounds += 1
            if no_progress_rounds >= max_no_progress_rounds:
                break

        # Summarize last errors per URL (keep it short for UI).
        error_items = [f"{u}: {m}" for (u, m) in list(errors_by_url.items())[:4]]
        err_summary = "; ".join(error_items) + ("; ..." if len(errors_by_url) > 4 else "")
        raise RuntimeError(
            f"Не удалось скачать модель {model_name}."
            f" partial={_part_size()} bytes. {err_summary}"
        )

    def download_model(
        self,
        model_size: str,
        models_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Path:
        """Метод для явного скачивания модели."""
        self.load_model(model_size, models_dir=models_dir, progress_callback=progress_callback)
        return self.model_path

    def _get_vad(self) -> Optional[VADFilter]:
        if self._vad is None:
            vad_model_path = Path(__file__).parent / "assets" / "silero_vad.onnx"
            if vad_model_path.exists():
                try:
                    self._vad = VADFilter(vad_model_path)
                except Exception as e:
                    logger.error(f"Не удалось инициализировать VAD: {e}")
                    import traceback
                    logger.debug(traceback.format_exc())
                    # Возвращаем None, чтобы не использовать VAD если он не работает
                    return None
            else:
                logger.warning(f"VAD модель не найдена по пути: {vad_model_path}")
        return self._vad

    def _convert_to_wav(self, audio_path: Path) -> Path:
        """Конвертировать аудио в WAV 16kHz mono (требуется для whisper.cpp)."""
        import soundfile as sf
        import librosa
        import tempfile

        try:
            # Загружаем аудио (любой формат, который поддерживает librosa/soundfile)
            data, sr = librosa.load(str(audio_path), sr=16000, mono=True)

            # Создаем временный файл
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            temp_path = Path(temp_path)

            # Сохраняем как 16-bit PCM WAV
            sf.write(str(temp_path), data, 16000, subtype='PCM_16')

            logger.info(f"Аудио конвертировано: {audio_path.name} -> {temp_path.name}")
            return temp_path
        except Exception as e:
            logger.error(f"Ошибка конвертации аудио {audio_path}: {e}")
            # Если не удалось, возвращаем оригинал и надеемся на лучшее
            return audio_path

    def transcribe(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Tuple[str, Optional[str], float]:
        """Транскрипция через вызов бинарника."""
        if not self.model_path or not self.model_path.exists():
            logger.error(f"Попытка транскрипции без модели: {self.model_path}")
            raise RuntimeError(f"Модель не найдена по пути: {self.model_path}")

        # Конвертируем в WAV если нужно
        is_temp_wav = False
        working_audio_path = audio_path
        if audio_path.suffix.lower() != ".wav":
            working_audio_path = self._convert_to_wav(audio_path)
            is_temp_wav = working_audio_path != audio_path

        try:
            # VAD фильтрация перед вызовом бинарника
            if vad_filter:
                vad = self._get_vad()
                if vad:
                    logger.info("Выполняется VAD проверка перед транскрипцией...")
                    import soundfile as sf
                    try:
                        data, samplerate = sf.read(str(working_audio_path))
                        if len(data) == 0:
                            logger.warning("VAD: Аудио файл пуст")
                            return "", language, 1.0
                        is_speech = vad.is_speech(data, sample_rate=samplerate)
                        if not is_speech:
                            logger.info("VAD: Речь не обнаружена, пропускаем транскрипцию.")
                            return "", language, 1.0
                        logger.debug(f"VAD: Речь обнаружена, продолжаем транскрипцию")
                    except Exception as e:
                        logger.error(f"VAD error: {e}, продолжаем транскрипцию без VAD")
                        import traceback
                        logger.debug(traceback.format_exc())
                        # Продолжаем транскрипцию если VAD упал

            result_id = int(time.time())
            result_base = working_audio_path.parent / f"result_{result_id}"

            cmd = self._build_cmd(working_audio_path, language, beam_size, False)
            cmd.extend(["-oj", "-of", str(result_base)])

            logger.info(f"Запуск транскрипции: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            import threading
            def track_progress(pipe, callback):
                # Читаем stderr как байты и декодируем построчно
                for line_bytes in pipe:
                    line = self._decode_bytes(line_bytes)
                    if "progress =" in line and callback:
                        try:
                            match = re.search(r"progress\s*=\s*(\d+)%", line)
                            if match:
                                callback("transcribing", int(match.group(1)), 100)
                        except (ValueError, AttributeError, TypeError):
                            pass

            if progress_callback:
                thread = threading.Thread(target=track_progress, args=(process.stderr, progress_callback))
                thread.daemon = True
                thread.start()

            try:
                # Timeout: 30 minutes max for transcription
                stdout_bytes, stderr_bytes = process.communicate(timeout=1800)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()  # Clean up
                raise RuntimeError("Транскрипция прервана: превышено время ожидания (30 мин)")
            stdout = self._decode_bytes(stdout_bytes)
            stderr = self._decode_bytes(stderr_bytes)

            if process.returncode != 0:
                logger.error(f"whisper-cli.exe error: {stderr}")
                raise RuntimeError(f"Ошибка whisper.cpp: {stderr}")

            json_path = result_base.with_suffix(".json")

            try:
                full_text = ""
                if json_path.exists():
                    with open(json_path, "r", encoding="utf-8", errors="replace") as f:
                        data = json.load(f)
                    try:
                        os.remove(json_path)
                    except OSError:
                        pass

                    items = self._extract_whisper_json_items(data)
                    if items:
                        full_text = " ".join([str(seg.get("text", "")).strip() for seg in items])

                # Если из JSON ничего не получили, чистим stdout от таймкодов
                if not full_text.strip():
                    logger.warning("JSON пуст или не найден, используем stdout.")
                    # Очищаем [00:00:00.000 --> 00:00:00.000] или [00:00:00.000 -> 00:00:00.000]
                    full_text = self._clean_stdout_text(stdout)

                logger.info(f"Транскрипция завершена. Символов: {len(full_text)}")
                return full_text.strip(), language, 1.0
            except Exception as e:
                logger.error(f"Ошибка парсинга: {e}")
                # Если JSON упал, но есть очищенный stdout - используем его
                if stdout:
                    clean_stdout = self._clean_stdout_text(stdout)
                    if clean_stdout:
                        return clean_stdout.strip(), language, 1.0
                raise RuntimeError(f"Не удалось распарсить результат: {e}")
        finally:
            # Очистка временного файла
            if is_temp_wav and working_audio_path.exists():
                try:
                    os.remove(working_audio_path)
                except OSError:
                    pass

    def transcribe_with_timestamps(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
        word_timestamps: bool = False,
    ) -> Tuple[List[Dict], Optional[str], float]:
        """Транскрипция с таймкодами."""
        if not self.model_path or not self.model_path.exists():
            raise RuntimeError(f"Модель не найдена: {self.model_path}")

        # Конвертируем в WAV если нужно
        is_temp_wav = False
        working_audio_path = audio_path
        if audio_path.suffix.lower() != ".wav":
            working_audio_path = self._convert_to_wav(audio_path)
            is_temp_wav = working_audio_path != audio_path

        try:
            # Генерируем уникальное имя для результата
            result_id = int(time.time())
            result_base = working_audio_path.parent / f"result_ts_{result_id}"

            cmd = self._build_cmd(working_audio_path, language, beam_size, False)
            cmd.extend(["-ojf", "-of", str(result_base)]) # Full JSON

            if word_timestamps:
                cmd.extend(["-ml", "1"])

            logger.info(f"Запуск транскрипции с таймкодами: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            try:
                # Timeout: 30 minutes max for transcription
                stdout_bytes, stderr_bytes = process.communicate(timeout=1800)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()  # Clean up
                raise RuntimeError("Транскрипция прервана: превышено время ожидания (30 мин)")
            stdout = self._decode_bytes(stdout_bytes)
            stderr = self._decode_bytes(stderr_bytes)

            if process.returncode != 0:
                logger.error(f"whisper-cli.exe error: {stderr}")
                raise RuntimeError(f"Ошибка whisper.cpp: {stderr}")

            json_path = result_base.with_suffix(".json")
            try:
                if json_path.exists():
                    with open(json_path, "r", encoding="utf-8", errors="replace") as f:
                        data = json.load(f)

                    try:
                        os.remove(json_path)
                    except OSError:
                        pass

                    items = self._extract_whisper_json_items(data)

                    segments: List[Dict[str, Any]] = []
                    for seg in items:
                        start_s, end_s = self._extract_segment_times(seg)
                        segments.append({
                            "start": start_s,
                            "end": end_s,
                            "text": str(seg.get("text", "")).strip(),
                        })

                    # If JSON exists but doesn't include any segments we can parse,
                    # fall back to stdout. This can happen if whisper.cpp changes JSON keys.
                    if not segments:
                        text = self._clean_stdout_text(stdout)
                        if text:
                            segments = [{"start": 0.0, "end": 0.0, "text": text}]

                    res_lang = language
                    if isinstance(data, dict):
                        res_lang = (
                            (data.get("result") or {}).get("language")
                            or data.get("language")
                            or res_lang
                        )
                    logger.info(f"Получено {len(segments)} сегментов.")
                    return segments, res_lang, 1.0
                else:
                    logger.error(f"JSON файл не создан: {json_path}")
                    # Фоллбэк на парсинг stdout если JSON нет
                    segments = []
                    for line in stdout.split('\n'):
                        line = line.strip()
                        if not line: continue
                        match = re.search(r'\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-+>\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)', line)
                        if match:
                            def to_sec(ts):
                                h, m, s = ts.split(':')
                                return int(h)*3600 + int(m)*60 + float(s)
                            segments.append({
                                "start": to_sec(match.group(1)),
                                "end": to_sec(match.group(2)),
                                "text": match.group(3).strip()
                            })
                    if segments:
                        return segments, language, 1.0
                    text = self._clean_stdout_text(stdout)
                    if text:
                        return [{"start": 0.0, "end": 0.0, "text": text}], language, 1.0
                    return [], language, 0.0
            except Exception as e:
                logger.error(f"JSON error: {e}")
                raise RuntimeError(f"Ошибка парсинга JSON: {e}")
        finally:
            if is_temp_wav and working_audio_path.exists():
                try:
                    os.remove(working_audio_path)
                except OSError:
                    pass

    def transcribe_stream(
        self,
        audio_path: Path,
        language: str = "auto",
        beam_size: int = 5,
        vad_filter: bool = False,
    ) -> Iterable[Tuple[str, Optional[str], float]]:
        """Стриминговая транскрипция через парсинг stdout."""
        if not self.model_path or not self.model_path.exists():
            raise RuntimeError("Модель не загружена")

        # Конвертируем в WAV если нужно
        is_temp_wav = False
        working_audio_path = audio_path
        if audio_path.suffix.lower() != ".wav":
            working_audio_path = self._convert_to_wav(audio_path)
            is_temp_wav = working_audio_path != audio_path

        try:
            # VAD фильтрация
            if vad_filter:
                vad = self._get_vad()
                if vad:
                    import soundfile as sf
                    try:
                        data, samplerate = sf.read(str(working_audio_path))
                        if not vad.is_speech(data, sample_rate=samplerate):
                            logger.info("VAD (stream): Речь не обнаружена.")
                            yield "", language, 1.0
                            return
                    except Exception as e:
                        logger.error(f"VAD stream error: {e}")

            cmd = self._build_cmd(working_audio_path, language, beam_size, False)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            full_text = ""
            for line_bytes in process.stdout:
                text = self._decode_bytes(line_bytes).strip()
                if text:
                    clean_text = re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-+>\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*', '', text)
                    if clean_text:
                        full_text = (full_text + " " + clean_text).strip()
                        yield full_text, language, 1.0

            try:
                process.wait(timeout=1800)  # 30 minutes max
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                logger.error("Транскрипция прервана: превышено время ожидания")
        finally:
            if is_temp_wav and working_audio_path.exists():
                try:
                    os.remove(working_audio_path)
                except OSError:
                    pass

    def _build_cmd(self, audio_path: Path, language: str, beam_size: int, vad_filter: bool) -> List[str]:
        """Собрать команду для запуска."""
        cmd = [
            str(self.binary_path),
            "-m", str(self.model_path),
            "-f", str(audio_path),
            "-t", str(self.threads),
            "-bs", str(beam_size),
        ]

        if language and language != "auto":
            cmd.extend(["-l", language])
        else:
            cmd.extend(["-l", "auto"])

        if self.device == "cpu" or self.gpu_backend == "cpu":
            cmd.append("-ng") # Отключить GPU
        elif self.gpu_backend == "vulkan":
            # Для Vulkan можно явно указать устройство, если нужно
            pass
        elif self.gpu_backend == "directml" and sys.platform == "win32":
            # На Windows DirectML используется по умолчанию в соответствующих сборках
            pass

        cmd.append("-np") # Не печатать лог в stdout
        return cmd
