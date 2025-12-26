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
from typing import Callable, Dict, List, Optional, Tuple, Union, Iterable

# Настройка локального логгера
logger = logging.getLogger("transcriber_cpp")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "transcriber_cpp.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)

class VADFilter:
    """Лёгкий фильтр голоса на основе Silero VAD (ONNX)."""

    def __init__(self, model_path: Path):
        import onnxruntime as ort
        self.model_path = model_path
        # Используем CPU для VAD, так как модель крошечная
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"]
        )
        logger.info(f"VADFilter инициализирован с моделью: {model_path}")

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
                out, h, c = self.session.run(None, ort_inputs)
                if out[0][0] > threshold:
                    return True
            except Exception as e:
                logger.error(f"VAD session run error: {e}")
                return True # Фоллбэк: считаем что речь есть если VAD упал
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

        # Убеждаемся, что бинарник есть и готов к работе
        self._ensure_binary()
        logger.info(f"Инициализирован WhisperCppTranscriber. Платформа: {sys.platform}, Backend: {self.gpu_backend}, Бинарник: {self.binary_path}")

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

        # Нормализуем имя модели
        model_name = model_size.lower()
        if model_name.startswith("ggml-"):
            model_name = model_name[5:]
        if model_name.endswith(".bin"):
            model_name = model_name[:-4]

        model_filename = f"ggml-{model_name}.bin"
        self.model_path = models_dir / model_filename

        logger.info(f"Загрузка модели: {model_name}, ожидаемый файл: {self.model_path}")

        if not self.model_path.exists():
            logger.info(f"Файл модели не найден, начинаем загрузку...")
            if progress_callback:
                progress_callback("downloading_model", 0, 100)
            self._download_model(model_name, models_dir, progress_callback)
        else:
            logger.info(f"Файл модели уже существует.")
            if progress_callback:
                progress_callback("model_loaded", 100, 100)

    def _download_model(
        self,
        model_name: str,
        models_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> None:
        """Скачать GGML модель с HuggingFace (ggerganov/whisper.cpp)."""
        from huggingface_hub import hf_hub_download

        repo_id = "ggerganov/whisper.cpp"
        filename = f"ggml-{model_name}.bin"

        try:
            logger.info(f"Скачивание {filename} из {repo_id}...")
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(models_dir),
                local_dir_use_symlinks=False,
            )
            self.model_path = Path(downloaded_path)
            logger.info(f"Модель успешно скачана: {self.model_path}")
        except Exception as e:
            logger.error(f"Ошибка при скачивании модели: {e}")
            raise RuntimeError(f"Не удалось скачать модель {model_name}: {e}")

    def download_model(
        self,
        model_size: str,
        models_dir: Path,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> Path:
        """Метод для явного скачивания модели."""
        self.load_model(model_size, models_dir=models_dir, progress_callback=progress_callback)
        return self.model_path

    def _get_vad(self) -> VADFilter:
        if self._vad is None:
            vad_model_path = Path(__file__).parent / "assets" / "silero_vad.onnx"
            if vad_model_path.exists():
                self._vad = VADFilter(vad_model_path)
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
                        if not vad.is_speech(data, sample_rate=samplerate):
                            logger.info("VAD: Речь не обнаружена, пропускаем транскрипцию.")
                            return "", language, 1.0
                    except Exception as e:
                        logger.error(f"VAD error: {e}")

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
                        except: pass

            if progress_callback:
                thread = threading.Thread(target=track_progress, args=(process.stderr, progress_callback))
                thread.daemon = True
                thread.start()

            stdout_bytes, stderr_bytes = process.communicate()
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
                    try: os.remove(json_path)
                    except: pass

                    if "transcription" in data:
                        full_text = " ".join([seg.get("text", "").strip() for seg in data["transcription"]])

                # Если из JSON ничего не получили, чистим stdout от таймкодов
                if not full_text.strip():
                    logger.warning("JSON пуст или не найден, используем stdout.")
                    # Очищаем [00:00:00.000 --> 00:00:00.000] или [00:00:00.000 -> 00:00:00.000]
                    full_text = re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-+>\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*', '', stdout)
                    # Убираем лишние пустые строки и пробелы
                    full_text = " ".join(full_text.split())

                logger.info(f"Транскрипция завершена. Символов: {len(full_text)}")
                return full_text.strip(), language, 1.0
            except Exception as e:
                logger.error(f"Ошибка парсинга: {e}")
                # Если JSON упал, но есть очищенный stdout - используем его
                if stdout:
                    clean_stdout = re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-+>\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*', '', stdout)
                    clean_stdout = " ".join(clean_stdout.split())
                    if clean_stdout:
                        return clean_stdout.strip(), language, 1.0
                raise RuntimeError(f"Не удалось распарсить результат: {e}")
        finally:
            # Очистка временного файла
            if is_temp_wav and working_audio_path.exists():
                try: os.remove(working_audio_path)
                except: pass

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

            stdout_bytes, stderr_bytes = process.communicate()
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

                    try: os.remove(json_path)
                    except: pass

                    segments = []
                    for seg in data.get("transcription", []):
                        offsets = seg.get("offsets", {})
                        start_ms = offsets.get("from", 0)
                        end_ms = offsets.get("to", 0)

                        segments.append({
                            "start": start_ms / 1000.0,
                            "end": end_ms / 1000.0,
                            "text": seg.get("text", "").strip()
                        })

                    res_lang = data.get("result", {}).get("language", language)
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
                    return [], language, 0.0
            except Exception as e:
                logger.error(f"JSON error: {e}")
                raise RuntimeError(f"Ошибка парсинга JSON: {e}")
        finally:
            if is_temp_wav and working_audio_path.exists():
                try: os.remove(working_audio_path)
                except: pass

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

            process.wait()
        finally:
            if is_temp_wav and working_audio_path.exists():
                try: os.remove(working_audio_path)
                except: pass

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
