"""
Wake Word Detection используя openWakeWord.

Поддержка встроенных и кастомных wake words.
"""

import logging
import threading
import queue
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import sounddevice as sd

try:
    from openwakeword.model import Model as WakeWordModel
    from openwakeword import get_pretrained_model_paths
    from openwakeword.utils import download_models as oww_download_models
except ImportError:
    WakeWordModel = None
    get_pretrained_model_paths = None
    oww_download_models = None

logger = logging.getLogger(__name__)


# Callback при детекции wake word
WakeWordCallback = Callable[[], None]


class WakeWordDetector:
    """Детектор wake words в фоновом режиме."""

    # Встроенные модели openWakeWord
    BUILTIN_MODELS = {
        "hey_jarvis": "hey_jarvis_v0.1",
        "alexa": "alexa_v0.1",
        "hey_mycroft": "hey_mycroft_v0.1",
        "hey_rhasspy": "hey_rhasspy_v0.1",
    }

    def __init__(
        self,
        wake_word: str = "hey_jarvis",
        threshold: float = 0.5,
        sample_rate: int = 16000,
    ):
        """
        Args:
            wake_word: Название wake word (из BUILTIN_MODELS или путь к модели)
            threshold: Порог детекции (0.0-1.0)
            sample_rate: Частота дискретизации
        """
        self.wake_word = wake_word
        self.threshold = threshold
        self.sample_rate = sample_rate

        self._model: Optional[WakeWordModel] = None
        self._stream: Optional[sd.RawInputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._callback: Optional[WakeWordCallback] = None

        # Очередь для аудио данных
        self._audio_queue: "queue.Queue[Optional[bytes]]" = queue.Queue()

        # Инициализация модели
        self._init_model()

    def _init_model(self) -> None:
        """Инициализировать модель openWakeWord."""
        logger.info(f"[Wake Word] Инициализация детектора wake word: '{self.wake_word}' (порог: {self.threshold})")

        if WakeWordModel is None:
            logger.error("[Wake Word] ❌ openWakeWord не установлен. Установите: pip install openwakeword")
            return

        # Проверяем и скачиваем модели если нужно
        model_name = self.BUILTIN_MODELS.get(self.wake_word, self.wake_word)
        if get_pretrained_model_paths:
            try:
                logger.debug(f"[Wake Word] Проверяю доступность модели: {model_name}")
                paths = get_pretrained_model_paths(model_name)
                if paths:
                    logger.debug(f"[Wake Word] ✅ Модель уже скачана: {paths}")
                else:
                    logger.info(f"[Wake Word] 📥 Модель {model_name} не найдена, скачиваю...")
                    if oww_download_models:
                        try:
                            oww_download_models()
                            logger.info("[Wake Word] ✅ Модели openWakeWord успешно скачаны")
                        except Exception as download_err:
                            logger.warning(f"[Wake Word] ⚠️ Ошибка скачивания моделей: {download_err}")
                    else:
                        logger.warning("[Wake Word] ⚠️ Функция скачивания моделей недоступна")
            except Exception as e:
                logger.debug(f"[Wake Word] Проверка доступности моделей: {e}")

        try:
            # Если wake_word в встроенных - используем его
            if self.wake_word in self.BUILTIN_MODELS:
                model_name = self.BUILTIN_MODELS[self.wake_word]
                logger.info(f"[Wake Word] 📦 Загрузка встроенной модели: {model_name}")

                # Пробуем разные варианты загрузки
                # 1. Сначала пробуем без указания framework (openWakeWord сам выберет)
                try:
                    logger.debug("[Wake Word] Пробую загрузку без указания framework...")
                    self._model = WakeWordModel(wakeword_models=[model_name])
                    logger.info("[Wake Word] ✅ Модель загружена (автоматический выбор framework)")
                except Exception as auto_error:
                    logger.debug(f"[Wake Word] Автоматический выбор не сработал: {auto_error}")
                    # 2. Пробуем с ONNX явно
                    try:
                        logger.debug("[Wake Word] Пробую загрузку с ONNX runtime...")
                        self._model = WakeWordModel(
                            wakeword_models=[model_name],
                            inference_framework='onnx'
                        )
                        logger.info("[Wake Word] ✅ Модель загружена с ONNX runtime")
                    except Exception as onnx_error:
                        logger.debug(f"[Wake Word] ONNX не сработал: {onnx_error}")
                        # 3. Пробуем с tflite явно
                        try:
                            logger.debug("[Wake Word] Пробую загрузку с tflite runtime...")
                            self._model = WakeWordModel(
                                wakeword_models=[model_name],
                                inference_framework='tflite'
                            )
                            logger.info("[Wake Word] ✅ Модель загружена с tflite runtime")
                        except Exception as tflite_error:
                            logger.error(f"[Wake Word] ❌ Все варианты загрузки не сработали")
                            logger.error(f"[Wake Word] Детали ошибок:")
                            logger.error(f"[Wake Word]   - Автоматический выбор: {str(auto_error)[:200]}")
                            logger.error(f"[Wake Word]   - ONNX runtime: {str(onnx_error)[:200]}")
                            logger.error(f"[Wake Word]   - tflite runtime: {str(tflite_error)[:200]}")

                            # Формируем понятное сообщение для пользователя
                            error_msg = (
                                f"❌ Не удалось загрузить модель wake word '{model_name}'.\n\n"
                                "Возможные причины и решения:\n"
                                "1) Модели не скачаны - openWakeWord должен скачать их автоматически при первом использовании.\n"
                                "   Проверьте интернет-соединение и попробуйте снова.\n\n"
                                "2) На Python 3.13/Windows tflite-runtime недоступен.\n"
                                "   openWakeWord должен использовать ONNX модели автоматически.\n\n"
                                "3) Попробуйте переустановить openwakeword:\n"
                                "   pip install --upgrade openwakeword\n\n"
                                "4) Убедитесь что onnxruntime установлен:\n"
                                "   pip install onnxruntime"
                            )
                            logger.error(f"[Wake Word] {error_msg}")
                            raise Exception(error_msg)
            else:
                # Иначе - пытаемся загрузить кастомную модель
                model_path = Path(self.wake_word)
                if model_path.exists():
                    logger.info(f"[Wake Word] 📦 Загрузка кастомной модели: {model_path}")
                    self._model = WakeWordModel(wakeword_models=[str(model_path)])
                    logger.info("[Wake Word] ✅ Кастомная модель загружена")
                else:
                    logger.warning(f"[Wake Word] ⚠️ Модель не найдена: {self.wake_word}, используем fallback")
                    # Fallback к hey_jarvis
                    try:
                        self._model = WakeWordModel(
                            wakeword_models=["hey_jarvis_v0.1"],
                            inference_framework='onnx'
                        )
                        logger.info("[Wake Word] ✅ Fallback модель загружена (hey_jarvis)")
                    except Exception:
                        self._model = WakeWordModel(wakeword_models=["hey_jarvis_v0.1"])
                        logger.info("[Wake Word] ✅ Fallback модель загружена (hey_jarvis, tflite)")

            logger.info(f"[Wake Word] ✅ Модель wake word готова к работе. Ожидаю активацию: '{self.wake_word}'")
        except Exception as e:
            logger.error(f"[Wake Word] ❌ Ошибка загрузки модели wake word: {e}")
            self._model = None

    def _audio_callback(self, indata, frames, time, status) -> None:
        """Callback для захвата аудио."""
        if status:
            logger.warning(f"Audio callback status: {status}")
        self._audio_queue.put(bytes(indata))

    def _detection_loop(self) -> None:
        """Основной цикл детекции wake word."""
        if not self._model:
            logger.error("[Wake Word] ❌ Модель wake word не инициализирована")
            return

        logger.info("[Wake Word] 🎤 Цикл детекции запущен, слушаю микрофон...")

        # Буфер для накопления аудио
        buffer = np.array([], dtype=np.int16)
        # Размер чанка для модели (обычно 1280 сэмплов для 16kHz)
        chunk_size = 1280

        # Счетчик для периодического логирования
        chunk_count = 0
        last_status_log = 0

        while self._running.is_set():
            try:
                # Получаем аудио данные
                audio_bytes = self._audio_queue.get(timeout=1.0)
                if audio_bytes is None:
                    break

                # Конвертируем в numpy array
                audio_chunk = np.frombuffer(audio_bytes, dtype=np.int16)
                buffer = np.concatenate([buffer, audio_chunk])

                # Обрабатываем полные чанки
                while len(buffer) >= chunk_size:
                    chunk = buffer[:chunk_size]
                    buffer = buffer[chunk_size:]
                    chunk_count += 1

                    # Нормализуем к [-1, 1]
                    normalized = chunk.astype(np.float32) / 32768.0

                    # Предсказание модели
                    prediction = self._model.predict(normalized)

                    # Проверяем все модели
                    for model_name, score in prediction.items():
                        # Логируем высокие скоры (близкие к порогу) для отладки
                        if score > self.threshold * 0.7:  # 70% от порога
                            logger.debug(f"[Wake Word] 📊 Модель '{model_name}': {score:.3f} (порог: {self.threshold})")

                        if score >= self.threshold:
                            logger.info(f"[Wake Word] 🔊 WAKE WORD ОБНАРУЖЕН! Модель: {model_name}, Уверенность: {score:.2f}")
                            if self._callback:
                                logger.info("[Wake Word] ⚡ Вызываю callback активации...")
                                self._callback()
                            # Очищаем буфер после детекции
                            buffer = np.array([], dtype=np.int16)
                            break

                    # Периодическое логирование статуса (каждые ~10 секунд при 16kHz)
                    if chunk_count - last_status_log >= 100:  # ~10 секунд
                        logger.info(f"[Wake Word] ✅ Работаю... обработано {chunk_count} чанков аудио")
                        last_status_log = chunk_count

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Wake Word] ❌ Ошибка в цикле детекции: {e}")

        logger.info("[Wake Word] 🛑 Цикл детекции остановлен")

    def start(
        self,
        device: Optional[int] = None,
        callback: Optional[WakeWordCallback] = None,
    ) -> bool:
        """
        Запустить детекцию wake word.

        Args:
            device: ID устройства записи (None = default)
            callback: Функция, вызываемая при детекции wake word

        Returns:
            True если успешно запущено
        """
        if self._running.is_set():
            logger.warning("[Wake Word] ⚠️ Детектор уже запущен")
            return False

        if not self._model:
            logger.error("[Wake Word] ❌ Модель wake word не инициализирована. Невозможно запустить.")
            return False

        self._callback = callback

        # Получаем имя устройства для логирования
        device_name = "по умолчанию"
        if device is not None:
            try:
                devices = sd.query_devices()
                if device < len(devices):
                    device_name = devices[device]['name']
            except (sd.PortAudioError, IndexError, KeyError, TypeError):
                device_name = f"устройство #{device}"

        logger.info(f"[Wake Word] 🚀 Запуск детектора... (устройство: {device_name}, частота: {self.sample_rate}Hz)")

        try:
            # Запускаем аудио стрим
            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                blocksize=1280,  # Размер блока для openWakeWord
                device=device,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            self._stream.start()
            logger.info("[Wake Word] ✅ Аудио стрим запущен")

            # Запускаем поток обработки
            self._running.set()
            self._thread = threading.Thread(target=self._detection_loop, daemon=True)
            self._thread.start()
            logger.info("[Wake Word] ✅ Поток обработки запущен")

            logger.info(f"[Wake Word] ✅✅✅ ДЕТЕКТОР ЗАПУЩЕН И РАБОТАЕТ! Ожидаю wake word: '{self.wake_word}'")
            return True

        except Exception as e:
            logger.error(f"[Wake Word] ❌ Ошибка запуска детектора: {e}")
            self._running.clear()
            if self._stream:
                self._stream.close()
                self._stream = None
            return False

    def stop(self) -> None:
        """Остановить детекцию wake word."""
        if not self._running.is_set():
            logger.debug("[Wake Word] Детектор уже остановлен")
            return

        logger.info("[Wake Word] 🛑 Останавливаем детектор...")
        self._running.clear()

        # Останавливаем аудио стрим
        if self._stream:
            logger.debug("[Wake Word] Останавливаю аудио стрим...")
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.debug("[Wake Word] ✅ Аудио стрим остановлен")

        # Останавливаем поток обработки
        self._audio_queue.put(None)
        if self._thread:
            logger.debug("[Wake Word] Ожидаю завершения потока обработки...")
            self._thread.join(timeout=2.0)
            self._thread = None
            logger.debug("[Wake Word] ✅ Поток обработки остановлен")

        self._callback = None
        logger.info("[Wake Word] ✅✅✅ ДЕТЕКТОР ОСТАНОВЛЕН")

    @property
    def running(self) -> bool:
        """Проверить, запущен ли детектор."""
        return self._running.is_set()

    @classmethod
    def list_available_models(cls) -> List[str]:
        """Получить список доступных встроенных моделей."""
        return list(cls.BUILTIN_MODELS.keys())


def is_openwakeword_available() -> bool:
    """Проверить, доступен ли openWakeWord."""
    return WakeWordModel is not None

