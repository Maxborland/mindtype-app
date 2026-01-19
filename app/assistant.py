"""
Голосовой ассистент - координатор всех компонентов.

Интегрирует:
- Wake word detection
- Транскрипцию (Whisper)
- LLM (OpenRouter)
- TTS (Edge TTS)
- Нормализацию текста
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    import winsound
except ImportError:
    winsound = None

from .audio import AudioRecorder
from .dialog_history import get_dialog_history_manager, Dialog, DialogHistoryManager
from .openrouter import OpenRouterClient
from .text_normalizer import get_normalizer
from .tts import get_tts_engine
from .wake_word import WakeWordDetector
from .transcriber import Transcriber

logger = logging.getLogger(__name__)


class AssistantState(Enum):
    """Состояния голосового ассистента."""
    IDLE = auto()           # Ожидание wake word
    CALIBRATING = auto()    # Калибровка микрофона (измерение шума)
    LISTENING = auto()      # Запись команды пользователя
    TRANSCRIBING = auto()   # Распознавание речи
    PROCESSING = auto()     # Обработка LLM
    SPEAKING = auto()       # Воспроизведение ответа
    WAITING = auto()        # Ожидание ввода пользователя после ответа
    ERROR = auto()          # Ошибка


@dataclass
class AssistantConfig:
    """Конфигурация голосового ассистента."""
    # Wake word
    wake_word: str = "hey_jarvis"
    wake_word_threshold: float = 0.5
    beep_on_wake: bool = True

    # TTS
    tts_voice: str = "ru-RU-DmitryNeural"
    tts_rate: int = 0  # -50 до +50
    tts_language: str = "ru"

    # LLM (только OpenRouter)
    openrouter_model: str = "anthropic/claude-3-haiku"
    openrouter_api_key: str = ""

    # Личность
    system_prompt: str = "Ты дружелюбный голосовой ассистент. Отвечай кратко и по делу."

    # Нормализация текста
    normalize_numbers: bool = True
    normalize_dates: bool = True
    normalize_translit: bool = True
    normalize_abbreviations: bool = True

    # Прочее
    microphone_device: Optional[int] = None
    recording_timeout: float = 3.0  # Устарело, используется VAD
    silence_duration: float = 1.2   # Длительность тишины для автозавершения (сек)
    silence_threshold: float = 0.03 # Порог тишины (0.0 - 1.0) - ниже = тише
    max_recording_time: float = 30.0 # Максимальное время записи (сек)

    # Автокалибровка VAD
    calibration_duration: float = 0.3  # Длительность калибровки (сек)
    noise_multiplier_silence: float = 1.3  # Множитель шума для порога тишины
    noise_multiplier_speech: float = 2.0   # Множитель шума для порога речи
    min_speech_threshold: float = 0.06     # Минимальный порог речи
    max_speech_threshold: float = 0.25     # Максимальный порог речи (не выше)

    # Параметры модели транскрипции
    model_size: str = "large-v3"
    compute_type: str = "int8"
    device: str = "auto"
    models_dir: str = ""
    beam_size: int = 5
    vad_filter: bool = False  # Отключен для ассистента, так как команды короткие

    # Прерывание голосом во время ответа
    voice_interrupt_enabled: bool = True
    voice_interrupt_threshold: float = 0.10  # RMS порог (0..1) - уменьшен для чувствительности
    voice_interrupt_min_hits: int = 3  # Минимум последовательных срабатываний


# Callback-и для событий
StateCallback = Callable[[AssistantState], None]
TranscriptCallback = Callable[[str], None]
ResponseCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]


class VoiceAssistant:
    """Голосовой ассистент."""

    def __init__(self, config: AssistantConfig):
        """
        Args:
            config: Конфигурация ассистента
        """
        self.config = config
        self._state = AssistantState.IDLE
        self._running = False

        # Компоненты
        self._wake_word_detector: Optional[WakeWordDetector] = None
        self._audio_recorder = AudioRecorder()
        self._transcriber: Optional[Transcriber] = None
        self._openrouter_client: Optional[OpenRouterClient] = None
        self._tts_engine = get_tts_engine()
        self._text_normalizer = get_normalizer(config.tts_language)

        # История диалога (через DialogHistoryManager для персистентности)
        self._history_manager = get_dialog_history_manager()
        self._max_history = 10  # Максимум сообщений в контексте LLM

        # Прерывание (hotkey/голос)
        self._interrupt_event = threading.Event()
        self._is_restarting = False  # Флаг для предотвращения race condition в finally
        self._voice_interrupt_lock = threading.Lock()  # Защита для _voice_interrupt_hits
        self._voice_interrupt_hits = 0

        # Защита от множественных запусков потоков обработки
        self._processing_lock = threading.Lock()
        self._is_processing = False

        # Callback-и
        self._on_state_change: Optional[StateCallback] = None
        self._on_transcript: Optional[TranscriptCallback] = None
        self._on_response: Optional[ResponseCallback] = None
        self._on_level: Optional[LevelCallback] = None

        # Инициализация компонентов
        self._init_components()

    def _init_components(self) -> None:
        """Инициализировать все компоненты."""
        logger.info("[Assistant] 🔧 Инициализация компонентов голосового ассистента...")

        # Wake word detector
        try:
            logger.info(f"[Assistant] 📦 Инициализация wake word detector (wake word: '{self.config.wake_word}')...")
            self._wake_word_detector = WakeWordDetector(
                wake_word=self.config.wake_word,
                threshold=self.config.wake_word_threshold,
            )
            if self._wake_word_detector._model:
                logger.info("[Assistant] ✅ Wake word detector инициализирован успешно")
            else:
                logger.warning("[Assistant] ⚠️ Wake word detector создан, но модель не загружена")
        except Exception as e:
            logger.error(f"[Assistant] ❌ Не удалось инициализировать wake word detector: {e}")
            logger.error(
                "[Assistant] 💡 Для работы голосового ассистента на Windows/Python 3.13 требуется "
                "установить дополнительные пакеты. Голосовой ассистент будет недоступен."
            )
            self._wake_word_detector = None

        # TTS настройки
        logger.info(f"[Assistant] 🎤 Настройка TTS (голос: {self.config.tts_voice}, скорость: {self.config.tts_rate})...")
        self._tts_engine.set_voice(self.config.tts_voice)
        self._tts_engine.set_rate(self.config.tts_rate)
        logger.info("[Assistant] ✅ TTS настроен")

        # LLM клиент (только OpenRouter)
        if self.config.openrouter_api_key:
            logger.info(f"[Assistant] 🤖 Инициализация OpenRouter клиента (модель: {self.config.openrouter_model})...")
            try:
                self._openrouter_client = OpenRouterClient(self.config.openrouter_api_key)
                logger.info("[Assistant] ✅ OpenRouter клиент инициализирован")
            except Exception as e:
                logger.error(f"[Assistant] ❌ Ошибка инициализации OpenRouter: {e}")
        else:
            logger.warning("[Assistant] ⚠️ OpenRouter API ключ не установлен. LLM функции недоступны.")

        # Настройки нормализатора
        logger.info("[Assistant] 📝 Настройка нормализатора текста...")
        normalizer = get_normalizer(self.config.tts_language)
        normalizer.set_enabled("numbers", self.config.normalize_numbers)
        normalizer.set_enabled("dates", self.config.normalize_dates)
        normalizer.set_enabled("translit", self.config.normalize_translit)
        normalizer.set_enabled("abbreviations", self.config.normalize_abbreviations)
        logger.info(f"[Assistant] ✅ Нормализатор настроен (числа: {self.config.normalize_numbers}, "
                   f"даты: {self.config.normalize_dates}, транслит: {self.config.normalize_translit}, "
                   f"аббревиатуры: {self.config.normalize_abbreviations})")

        logger.info("[Assistant] ✅ Инициализация компонентов завершена")

    def _set_state(self, state: AssistantState) -> None:
        """Изменить состояние и вызвать callback."""
        old_state = self._state
        self._state = state
        logger.info(f"[Assistant] 🔄 Изменение состояния: {old_state.name} → {state.name}")
        if self._on_state_change:
            self._on_state_change(state)

    def _on_wake_word_detected(self) -> None:
        """Callback при детекции wake word."""
        logger.info("[Assistant] 🔊 WAKE WORD ОБНАРУЖЕН! Активирую ассистента...")

        # Защита от повторного запуска
        if self._state != AssistantState.IDLE:
            logger.warning(f"[Assistant] ⚠️ Ассистент занят (состояние: {self._state.name}), игнорирую активацию")
            return

        if self._audio_recorder.recording:
            logger.warning("[Assistant] ⚠️ Запись уже идёт, игнорирую активацию")
            return

        if self.config.beep_on_wake:
            self._play_activation_beep()

        # Запускаем запись команды в отдельном потоке
        logger.info("[Assistant] 🎤 Начинаю запись команды пользователя...")
        threading.Thread(target=self._record_and_process_command, daemon=True).start()

    def _play_activation_beep(self) -> None:
        """Воспроизвести короткий звуковой сигнал."""
        if os.name == "nt" and winsound:
            try:
                # 880Hz, 150ms - приятный высокий звук
                threading.Thread(target=lambda: winsound.Beep(880, 150), daemon=True).start()
            except Exception:
                pass
        else:
            # Fallback для Linux/macOS — можно добавить через sounddevice если нужно
            pass

    def activate(self) -> None:
        """Публичная активация ассистента (hotkey/GUI)."""
        # Если сейчас слушаем — это второй клик, значит останавливаем запись и обрабатываем
        if self._state == AssistantState.LISTENING:
            logger.info("[Assistant] 🎹 Повторное нажатие во время записи: останавливаю и обрабатываю")
            if self._audio_recorder.recording:
                self._audio_recorder.stop()
            return

        # Если сейчас говорит/думает — трактуем как прерывание и сразу слушаем заново
        if self._state in (AssistantState.SPEAKING, AssistantState.PROCESSING, AssistantState.TRANSCRIBING):
            logger.info(f"[Assistant] 🎹 Активация во время {self._state.name}: прерываю и перехожу к записи")
            self.interrupt(start_listening=True)
            return

        # В обычном режиме — начинаем запись
        self._on_wake_word_detected()

    def force_send(self) -> None:
        """Принудительно завершить запись и отправить на обработку."""
        if self._state in (AssistantState.CALIBRATING, AssistantState.LISTENING):
            logger.info("[Assistant] ✅ Принудительная отправка аудио")
            if hasattr(self, '_recording_finished'):
                self._recording_finished.set()

    def interrupt(self, start_listening: bool = False) -> None:
        """Прервать текущую операцию (TTS/запись/обработка)."""
        logger.info("[Assistant] ⛔ Запрошено прерывание")
        self._interrupt_event.set()

        if start_listening:
            self._is_restarting = True

        try:
            self._tts_engine.stop()
        except Exception:
            pass
        try:
            if self._audio_recorder.recording:
                self._audio_recorder.stop()
        except Exception:
            pass

        if start_listening:
            # Переводим в IDLE и сразу начинаем запись новой команды
            try:
                self._set_state(AssistantState.IDLE)
            except Exception:
                pass
            threading.Thread(target=self._record_and_process_command, daemon=True).start()

    def _start_voice_interrupt_monitoring(self) -> None:
        """Включить мониторинг микрофона во время TTS для прерывания голосом."""
        if not self.config.voice_interrupt_enabled:
            return

        with self._voice_interrupt_lock:
            self._voice_interrupt_hits = 0

        def _on_levels(levels):
            try:
                if self._state not in (AssistantState.SPEAKING, AssistantState.WAITING):
                    return
                if not levels:
                    return
                lvl = float(levels[-1])

                with self._voice_interrupt_lock:
                    if lvl >= self.config.voice_interrupt_threshold:
                        self._voice_interrupt_hits += 1
                        if self._voice_interrupt_hits == 1:
                            logger.debug(f"[Assistant] 🔊 Голос: lvl={lvl:.3f} >= порог {self.config.voice_interrupt_threshold}")
                    else:
                        if self._voice_interrupt_hits > 0:
                            logger.debug(f"[Assistant] 🔇 Тишина: lvl={lvl:.3f} < порог, сброс счётчика")
                        self._voice_interrupt_hits = 0
                    hits = self._voice_interrupt_hits

                if hits >= self.config.voice_interrupt_min_hits:
                    logger.info(f"[Assistant] 🗣️ Прерывание голосом! (hits={hits}, state={self._state.name})")
                    self._interrupt_event.set()
                    with self._voice_interrupt_lock:
                        self._voice_interrupt_hits = 0

                    # Если говорили — прерываем TTS
                    if self._state == AssistantState.SPEAKING:
                        self._tts_engine.stop()

                    # Если были в режиме ожидания — начинаем слушать
                    if self._state == AssistantState.WAITING:
                        # Проверяем что не идёт уже обработка (флаг устанавливается в методе)
                        with self._processing_lock:
                            if self._is_processing:
                                logger.debug("[Assistant] ⚠️ Обработка уже идёт, пропускаем")
                                return

                        logger.info("[Assistant] 🎤 Начинаю запись после прерывания в режиме ожидания")
                        # ВАЖНО: остановить мониторинг ПЕРЕД запуском нового потока,
                        # иначе callback может сработать повторно!
                        self._stop_voice_interrupt_monitoring()
                        self._is_restarting = True
                        threading.Thread(target=self._record_and_process_command, daemon=True).start()
                        return  # Выходим из callback чтобы не было повторных срабатываний
            except Exception:
                pass

        # Мониторинг может не стартовать, если устройство занято — это ок, остаётся hotkey
        # Проверяем наличие метода start_monitoring
        if not hasattr(self._audio_recorder, 'start_monitoring'):
            logger.warning("[Assistant] ⚠️ AudioRecorder не поддерживает start_monitoring, прерывание голосом недоступно")
            return

        try:
            success = self._audio_recorder.start_monitoring(
                device=self.config.microphone_device,
                level_callback=_on_levels,
            )
            if success:
                logger.info(f"[Assistant] 🎤 Мониторинг микрофона запущен (порог: {self.config.voice_interrupt_threshold})")
            else:
                logger.warning("[Assistant] ⚠️ Не удалось запустить мониторинг микрофона (микрофон занят?)")
        except Exception as e:
            logger.warning(f"[Assistant] ⚠️ Не удалось запустить мониторинг для прерывания голосом: {e}")

    def _stop_voice_interrupt_monitoring(self) -> None:
        if hasattr(self._audio_recorder, 'stop_monitoring'):
            try:
                self._audio_recorder.stop_monitoring()
            except Exception:
                pass

    def _record_and_process_command(self) -> None:
        """Записать команду пользователя и обработать её."""
        # Проверяем что не идёт уже обработка (защита от множественных вызовов)
        with self._processing_lock:
            if self._is_processing:
                logger.warning("[Assistant] ⚠️ Обработка уже идёт, пропускаем вызов")
                return
            self._is_processing = True

        audio_file = None
        try:
            logger.info("[Assistant] 🎤 Начинаю запись команды пользователя...")
            self._interrupt_event.clear()

            # === ФАЗА 1: КАЛИБРОВКА ШУМА ===
            self._set_state(AssistantState.CALIBRATING)

            calibration_levels: List[float] = []
            calibration_duration = self.config.calibration_duration  # 0.3 сек
            calibration_done = threading.Event()
            calibration_start = time.time()

            def _calibration_callback(levels):
                if not levels:
                    return
                # Передаём в UI
                if self._on_level:
                    self._on_level(levels[-1])
                calibration_levels.append(levels[-1])
                # Завершаем калибровку по времени
                if time.time() - calibration_start >= calibration_duration:
                    calibration_done.set()

            logger.info(f"[Assistant] 📊 Калибровка микрофона ({calibration_duration}с)...")
            self._audio_recorder.start(
                device=self.config.microphone_device,
                level_callback=_calibration_callback
            )

            # Ждём завершения калибровки (с проверкой прерывания)
            while not calibration_done.is_set():
                if self._interrupt_event.is_set():
                    logger.info("[Assistant] ⛔ Калибровка прервана")
                    self._audio_recorder.stop()
                    return
                calibration_done.wait(timeout=0.1)

            # ОСТАНАВЛИВАЕМ запись калибровки (важно!)
            self._audio_recorder.stop()

            # Проверка прерывания после калибровки
            if self._interrupt_event.is_set():
                logger.info("[Assistant] ⛔ Прервано после калибровки")
                return

            # Рассчитываем noise floor
            if calibration_levels:
                noise_floor = sum(calibration_levels) / len(calibration_levels)
            else:
                noise_floor = 0.05  # Fallback

            # Динамические пороги на основе шума
            silence_threshold = max(
                self.config.silence_threshold,  # минимум из конфига
                noise_floor * self.config.noise_multiplier_silence
            )
            speech_threshold = min(
                self.config.max_speech_threshold,  # максимум 0.25
                max(
                    self.config.min_speech_threshold,  # минимум 0.06
                    noise_floor * self.config.noise_multiplier_speech
                )
            )

            logger.info(f"[Assistant] 📊 Калибровка завершена: шум={noise_floor:.3f}, тишина<{silence_threshold:.3f}, речь>{speech_threshold:.3f}")

            # === ФАЗА 2: ЗАПИСЬ С VAD ===
            self._set_state(AssistantState.LISTENING)

            silence_duration = self.config.silence_duration    # 1.2 сек
            max_recording_time = self.config.max_recording_time # 30 сек
            min_speech_duration = 0.3  # Минимальная длительность речи перед началом отсчёта тишины

            start_time = time.time()
            self._recording_finished = threading.Event()
            self._silence_start_time = None
            self._speech_detected = False
            self._speech_start_time = None
            self._last_log_time = time.time()

            # Callback для VAD
            def _vad_level_callback(levels):
                if not levels:
                    return

                lvl = levels[-1]
                now = time.time()

                # Передаём в UI
                if self._on_level:
                    self._on_level(lvl)

                # Периодический лог уровней (каждые 2 сек)
                if now - self._last_log_time >= 2.0:
                    self._last_log_time = now
                    speech_status = "🗣️речь" if self._speech_detected else "⏳ждём"
                    logger.info(f"[VAD] lvl={lvl:.3f} | речь>{speech_threshold:.3f} | тишина<{silence_threshold:.3f} | {speech_status}")

                # Детекция начала речи
                if lvl >= speech_threshold:
                    if not self._speech_detected:
                        self._speech_detected = True
                        self._speech_start_time = now
                        logger.info(f"[VAD] 🗣️ Речь обнаружена (lvl={lvl:.3f} >= {speech_threshold:.3f})")
                    self._silence_start_time = None  # Сброс счётчика тишины

                # Детекция тишины (только после обнаружения речи)
                elif self._speech_detected and lvl < silence_threshold:
                    # Проверяем, что речь была достаточно долгой
                    speech_duration = now - self._speech_start_time if self._speech_start_time else 0
                    if speech_duration >= min_speech_duration:
                        if self._silence_start_time is None:
                            self._silence_start_time = now
                            logger.info(f"[VAD] 🤫 Тишина началась (lvl={lvl:.3f} < {silence_threshold:.3f})")
                        elif now - self._silence_start_time >= silence_duration:
                            logger.info(f"[VAD] ✅ Тишина {silence_duration}с — завершаю запись")
                            self._recording_finished.set()

            # ЗАПУСКАЕМ запись с VAD callback (чистый старт!)
            logger.info("[Assistant] 🎤 Слушаю... (говорите)")
            self._audio_recorder.start(
                device=self.config.microphone_device,
                level_callback=_vad_level_callback
            )

            # Ждём завершения записи (по VAD, по таймауту или по внешнему стопу)
            while not self._recording_finished.is_set() and self._audio_recorder.recording:
                if self._interrupt_event.is_set():
                    logger.info("[Assistant] ⛔ Запись прервана")
                    break
                if time.time() - start_time > max_recording_time:
                    logger.warning(f"[Assistant] ⏳ Достигнуто макс. время записи ({max_recording_time}с)")
                    break
                time.sleep(0.1)

            logger.info("[Assistant] ⏹️ Останавливаю запись...")
            audio_file = self._audio_recorder.stop()

            if not audio_file or not audio_file.exists():
                logger.error("[Assistant] ❌ Не удалось записать аудио")
                self._set_state(AssistantState.ERROR)
                time.sleep(2)
                return

            logger.info(f"[Assistant] ✅ Аудио записано: {audio_file}")

            # Обрабатываем команду
            self._process_command(audio_file)

        except Exception as e:
            logger.error(f"[Assistant] ❌ Ошибка записи команды: {e}")
            self._set_state(AssistantState.ERROR)
            time.sleep(2)
        finally:
            # Сбрасываем флаг обработки
            with self._processing_lock:
                self._is_processing = False

            # Гарантируем возврат в IDLE, если не перезапускаемся
            if not self._is_restarting:
                if self._state != AssistantState.IDLE:
                    self._set_state(AssistantState.IDLE)
            else:
                # Сбрасываем флаг для следующего цикла
                self._is_restarting = False

            # Удаляем временный файл
            if audio_file:
                try:
                    audio_file.unlink()
                    logger.debug("[Assistant] Временный файл удален")
                except Exception:
                    pass

    def _process_command(self, audio_file: Path) -> None:
        """Обработать записанную команду."""
        try:
            logger.info("[Assistant] 🔄 Начинаю обработку команды...")
            self._set_state(AssistantState.TRANSCRIBING)

            # Транскрибируем аудио
            if not self._transcriber:
                logger.error("[Assistant] ❌ Transcriber не инициализирован")
                return

            # Загружаем модель (будет пропущено если уже загружена)
            logger.debug("[Assistant] 📦 Проверяю/загружаю модель транскрипции...")
            try:
                self._transcriber.load_model(
                    model_size=self.config.model_size,
                    compute_type=self.config.compute_type,
                    device=self.config.device,
                    models_dir=self.config.models_dir,
                )
                logger.debug("[Assistant] ✅ Модель готова к использованию")
            except Exception as e:
                logger.error(f"[Assistant] ❌ Ошибка загрузки модели: {e}")
                return

            logger.info("[Assistant] 📝 Транскрибирую аудио...")
            # transcribe возвращает (text, language, probability)
            result = self._transcriber.transcribe(
                audio_path=audio_file,  # Передаём Path, а не строку
                language="auto",
                beam_size=self.config.beam_size,
                vad_filter=self.config.vad_filter,
            )
            transcript = result[0] if isinstance(result, tuple) else result

            if not transcript or not transcript.strip():
                logger.warning("[Assistant] ⚠️ Пустая транскрипция")
                return

            logger.info(f"[Assistant] 📝 Транскрипция: '{transcript}'")
            if self._on_transcript:
                self._on_transcript(transcript)

            # Получаем ответ от LLM
            self._set_state(AssistantState.PROCESSING)
            logger.info("[Assistant] 🤖 Отправляю запрос в LLM...")
            response = self._get_llm_response(transcript)

            if not response:
                logger.warning("[Assistant] ⚠️ Пустой ответ от LLM")
                return

            logger.info(f"[Assistant] 🤖 Ответ LLM: '{response}'")
            if self._on_response:
                self._on_response(response)

            # Нормализуем текст для TTS
            logger.info("[Assistant] 📝 Нормализую текст для TTS...")
            normalized_response = self._text_normalizer.normalize(response)
            logger.debug(f"[Assistant] Нормализованный текст: '{normalized_response}'")

            # Озвучиваем ответ
            logger.info("[Assistant] 🔊 Синтезирую и воспроизвожу ответ...")
            self._set_state(AssistantState.SPEAKING)
            self._interrupt_event.clear()
            self._start_voice_interrupt_monitoring()
            try:
                self._tts_engine.speak(normalized_response, blocking=True)

                # Если не было прерывания — переходим в режим ожидания (5 сек)
                if not self._interrupt_event.is_set():
                    self._set_state(AssistantState.WAITING)
                    # Мониторинг продолжается (он был запущен выше)
                    # Ждём 5 секунд или прерывания (голосом)
                    for _ in range(50): # 5 секунд (50 * 0.1)
                        if self._interrupt_event.is_set():
                            break
                        time.sleep(0.1)
            finally:
                self._stop_voice_interrupt_monitoring()

            logger.info("[Assistant] ✅ Сессия завершена")

            # Если во время воспроизведения или ожидания было прерывание — сразу начинаем слушать
            if self._interrupt_event.is_set():
                logger.info("[Assistant] 🔁 Прерывание/Речь обнаружена — начинаю слушать новую команду")
                self._is_restarting = True
                threading.Thread(target=self._record_and_process_command, daemon=True).start()
                return

            # Иначе возвращаемся в IDLE
            self._set_state(AssistantState.IDLE)

        except Exception as e:
            logger.error(f"[Assistant] ❌ Ошибка обработки команды: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self._set_state(AssistantState.ERROR)

    def _get_llm_response(self, user_message: str) -> str:
        """Получить ответ от LLM (OpenRouter) с персистентной историей."""
        # Убеждаемся, что есть активный диалог с правильным system prompt
        current_dialog = self._history_manager.get_current_dialog()
        if not current_dialog:
            self._history_manager.start_new_dialog(system_prompt=self.config.system_prompt)
        elif not current_dialog.system_prompt:
            current_dialog.system_prompt = self.config.system_prompt

        # Добавляем сообщение пользователя в историю
        self._history_manager.add_message("user", user_message)
        logger.debug(f"[Assistant] 📨 Сообщение пользователя добавлено в историю")

        # Получаем контекст для LLM (с system prompt и ограничением по количеству)
        messages = self._history_manager.get_current_context_for_llm(max_messages=self._max_history * 2)
        logger.debug(f"[Assistant] 📤 Отправляю запрос в LLM (модель: {self.config.openrouter_model}, сообщений: {len(messages)})")

        try:
            # Используем только OpenRouter
            if self._openrouter_client:
                response = self._openrouter_client.chat_completion(
                    messages=messages,
                    model=self.config.openrouter_model,
                    max_tokens=500,  # Ограничиваем для голосового ответа
                    temperature=0.7,
                )
                logger.debug(f"[Assistant] ✅ Получен ответ от LLM (длина: {len(response) if response else 0} символов)")
            else:
                logger.error("[Assistant] ❌ OpenRouter клиент не инициализирован")
                return "Извините, нужно настроить OpenRouter API ключ."

            # Добавляем ответ в историю (автосохранение внутри)
            if response:
                self._history_manager.add_message("assistant", response)
                logger.debug(f"[Assistant] 💾 Ответ добавлен в историю")

            return response

        except Exception as e:
            logger.error(f"[Assistant] ❌ Ошибка получения ответа от LLM: {e}")
            return "Извините, произошла ошибка."

    def set_transcriber(self, transcriber: Transcriber) -> None:
        """Установить transcriber (из main app)."""
        self._transcriber = transcriber

    def start(self) -> bool:
        """
        Запустить голосового ассистента.

        Returns:
            True если успешно запущен
        """
        logger.info("[Assistant] 🚀 Попытка запуска голосового ассистента...")

        if self._running:
            logger.warning("[Assistant] ⚠️ Ассистент уже запущен")
            return False

        if not self._wake_word_detector:
            logger.error("[Assistant] ❌ Wake word detector не инициализирован. Голосовой ассистент недоступен.")
            logger.info(
                "[Assistant] 💡 Возможные причины: "
                "1) Не установлен tflite-runtime (недоступен на Python 3.13/Windows) "
                "2) Ошибка при загрузке модели wake word"
            )
            return False

        # Запускаем wake word detector
        logger.info("[Assistant] 🎤 Запуск wake word detector...")
        success = self._wake_word_detector.start(
            device=self.config.microphone_device,
            callback=self._on_wake_word_detected,
        )

        if success:
            self._running = True
            self._set_state(AssistantState.IDLE)
            logger.info("[Assistant] ✅✅✅ ГОЛОСОВОЙ АССИСТЕНТ ЗАПУЩЕН И РАБОТАЕТ!")
            logger.info(f"[Assistant] 📋 Конфигурация: wake_word='{self.config.wake_word}', "
                       f"TTS голос='{self.config.tts_voice}', LLM модель='{self.config.openrouter_model}'")
            return True
        else:
            logger.error("[Assistant] ❌ Не удалось запустить wake word detector")
            return False

    def stop(self) -> None:
        """Остановить голосового ассистента."""
        if not self._running:
            logger.debug("[Assistant] Ассистент уже остановлен")
            return

        logger.info("[Assistant] 🛑 Останавливаем голосового ассистента...")

        # Останавливаем wake word detector
        if self._wake_word_detector:
            logger.debug("[Assistant] Останавливаю wake word detector...")
            self._wake_word_detector.stop()

        # Останавливаем воспроизведение
        logger.debug("[Assistant] Останавливаю TTS...")
        self._tts_engine.stop()

        # Останавливаем запись если идёт
        if self._audio_recorder.recording:
            logger.debug("[Assistant] Останавливаю запись аудио...")
            self._audio_recorder.stop()

        self._running = False
        self._set_state(AssistantState.IDLE)
        logger.info("[Assistant] ✅✅✅ ГОЛОСОВОЙ АССИСТЕНТ ОСТАНОВЛЕН")

    def clear_history(self) -> None:
        """Очистить текущий диалог и начать новый."""
        self._history_manager.clear_current_dialog()
        self._history_manager.start_new_dialog(system_prompt=self.config.system_prompt)
        logger.info("[Assistant] История диалога очищена, начат новый диалог")

    def load_dialog(self, dialog: Dialog) -> None:
        """Загрузить диалог из истории для продолжения."""
        self._history_manager.set_current_dialog(dialog)
        logger.info(f"[Assistant] Загружен диалог: {dialog.title}")

    def get_dialog_history_manager(self) -> DialogHistoryManager:
        """Получить менеджер истории диалогов."""
        return self._history_manager

    @property
    def state(self) -> AssistantState:
        """Текущее состояние ассистента."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Проверить, запущен ли ассистент."""
        return self._running

    def set_state_callback(self, callback: StateCallback) -> None:
        """Установить callback для изменения состояния."""
        self._on_state_change = callback

    def set_transcript_callback(self, callback: TranscriptCallback) -> None:
        """Установить callback для транскрипции."""
        self._on_transcript = callback

    def set_response_callback(self, callback: ResponseCallback) -> None:
        """Установить callback для ответа LLM."""
        self._on_response = callback

    def set_level_callback(self, callback: LevelCallback) -> None:
        """Установить callback для уровня громкости."""
        self._on_level = callback


# Предустановленные шаблоны личности
PERSONALITY_TEMPLATES = {
    "friendly": {
        "name": "Дружелюбный помощник",
        "prompt": "Ты дружелюбный голосовой ассистент. Отвечай кратко и по делу, используя разговорный стиль. Будь позитивным и helpful.",
    },
    "professional": {
        "name": "Профессионал",
        "prompt": "Ты профессиональный голосовой ассистент. Отвечай структурированно и формально, предоставляя точную информацию.",
    },
    "creative": {
        "name": "Творческий",
        "prompt": "Ты креативный голосовой ассистент. Отвечай развёрнуто и используй метафоры. Будь вдохновляющим и оригинальным.",
    },
    "programmer": {
        "name": "Программист",
        "prompt": "Ты технический голосовой ассистент для программистов. Отвечай технически точно, приводи примеры кода когда уместно.",
    },
}

