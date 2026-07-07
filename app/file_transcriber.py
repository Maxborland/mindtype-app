"""
Модуль для транскрибции аудио и видео файлов.
Поддерживает пакетную обработку и извлечение аудио из видео.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional
import threading
import queue

from .text_processor.repetition_filter import (
    filter_hallucinated_segments,
    check_transcription_quality,
)

# Настройка логирования в файл
def _setup_logger():
    logger = logging.getLogger("file_transcriber")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        # Файл логов в %APPDATA%/MindType/file_transcriber.log
        try:
            log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "file_transcriber.log"

            handler = logging.FileHandler(log_file, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            ))
            logger.addHandler(handler)
        except Exception:
            # Restricted environments (tests/sandbox) may disallow writing outside the workspace.
            logger.addHandler(logging.NullHandler())
    return logger

logger = _setup_logger()

# Модели данных и медиа-IO вынесены в отдельные модули; реэкспорт для обратной
# совместимости (внешний код импортирует эти имена из file_transcriber).
from .media_io import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    ALL_EXTENSIONS,
    is_supported_file,
    get_file_duration,
    extract_audio_from_video,
)
from .transcription_models import (
    FileStatus,
    SpeakerStats,
    TranscriptionSegment,
    TranscriptionResult,
    FileTask,
    ProgressCallback,
    CompletedCallback,
    TranscribeOptions,
    SummaryOptions,
    PostProcessOptions,
)


ThinkingCallback = Callable[[str], None]  # Для стриминга AI thinking


class FileTranscriptionQueue:
    """Очередь для пакетной транскрибции файлов с опциональной суммаризацией."""

    def __init__(
        self,
        transcriber,  # Transcriber instance
        transcribe: TranscribeOptions,
        summary: Optional[SummaryOptions] = None,
        postprocess: Optional[PostProcessOptions] = None,
        on_progress: Optional[ProgressCallback] = None,
        on_completed: Optional[CompletedCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,  # Callback для AI thinking
    ):
        summary = summary or SummaryOptions()
        postprocess = postprocess or PostProcessOptions()

        self.transcriber = transcriber
        # Распаковка конфиг-объектов в плоские поля (тело очереди читает self.X).
        self.model_size = transcribe.model_size
        self.compute_type = transcribe.compute_type
        self.device = transcribe.device
        self.language = transcribe.language
        self.beam_size = transcribe.beam_size
        self.vad_filter = transcribe.vad_filter
        self.models_dir = transcribe.models_dir

        self.enable_summary = summary.enable
        self.enable_thinking = summary.enable_thinking
        self.custom_prompts = summary.custom_prompts
        self.summary_preset_name = summary.preset_name
        self.summary_provider = summary.provider
        self.summary_api_key = summary.api_key
        self.summary_model = summary.model
        self.summary_base_url = summary.base_url
        self.summary_reasoning = summary.reasoning
        self.summary_reasoning_effort = summary.reasoning_effort
        # Legacy
        self.openrouter_api_key = summary.openrouter_api_key
        self.openrouter_model = summary.openrouter_model
        self.openrouter_reasoning = summary.openrouter_reasoning
        self.openrouter_reasoning_effort = summary.openrouter_reasoning_effort

        # Настройки постобработки
        self.enable_postprocessing = postprocess.enable
        self.postprocessing_diarization = postprocess.diarization
        # Разрешаем "auto": OpenRouter при наличии ключа, иначе локальная
        backend = postprocess.diarization_backend
        if backend == "auto":
            backend = "openrouter" if postprocess.diarization_api_key.strip() else "local"
        self.postprocessing_diarization_backend = backend
        self.postprocessing_diarization_api_key = postprocess.diarization_api_key
        self.postprocessing_diarization_model = postprocess.diarization_model
        self.postprocessing_punctuation = postprocess.punctuation
        self.postprocessing_fillers = postprocess.fillers
        self.postprocessing_normalize = postprocess.normalize
        self.postprocessing_correct = postprocess.correct

        # Логируем настройки постобработки
        logger.info("=" * 50)
        logger.info("FileTranscriptionQueue инициализирована")
        logger.info(f"  enable_postprocessing: {self.enable_postprocessing}")
        logger.info(f"  postprocessing_diarization: {self.postprocessing_diarization}")
        logger.info("=" * 50)

        self._on_progress = on_progress
        self._on_completed = on_completed
        self._on_thinking = on_thinking

        self._tasks: List[FileTask] = []
        self._queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._cancelled = threading.Event()
        self._temp_files: List[Path] = []
        self._summarizer = None  # Ленивая инициализация
        self._text_processor = None  # Ленивая инициализация

    @property
    def tasks(self) -> List[FileTask]:
        """Получить список задач."""
        return self._tasks.copy()

    def add_files(self, file_paths: List[Path]) -> List[FileTask]:
        """
        Добавить файлы в очередь.

        Args:
            file_paths: Список путей к файлам

        Returns:
            Список созданных задач
        """
        new_tasks = []
        for path in file_paths:
            if is_supported_file(path) and path.exists():
                task = FileTask(file_path=path)
                self._tasks.append(task)
                self._queue.put(task)
                new_tasks.append(task)
        return new_tasks

    def remove_task(self, task: FileTask) -> bool:
        """Удалить задачу из очереди (если она ещё не обрабатывается)."""
        if task in self._tasks and task.status == FileStatus.PENDING:
            self._tasks.remove(task)
            return True
        return False

    def clear_completed(self) -> None:
        """Удалить завершённые задачи."""
        self._tasks = [t for t in self._tasks if t.status not in
                      (FileStatus.COMPLETED, FileStatus.ERROR, FileStatus.CANCELLED)]

    def start(self) -> None:
        """Запустить обработку очереди."""
        if self._running.is_set():
            return

        self._running.set()
        self._cancelled.clear()

        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def cancel(self) -> None:
        """Отменить обработку."""
        self._cancelled.set()
        self._running.clear()

        # Помечаем все pending задачи как отменённые
        for task in self._tasks:
            if task.status == FileStatus.PENDING:
                task.status = FileStatus.CANCELLED

    def _worker(self) -> None:
        """Рабочий поток для обработки очереди."""
        # Загружаем модель один раз
        try:
            self.transcriber.load_model(
                model_size=self.model_size,
                compute_type=self.compute_type,
                device=self.device,
                models_dir=str(self.models_dir),
            )
        except Exception as e:
            # Помечаем все задачи как ошибочные
            for task in self._tasks:
                if task.status == FileStatus.PENDING:
                    task.status = FileStatus.ERROR
                    task.error_message = f"Ошибка загрузки модели: {e}"
                    if self._on_completed:
                        self._on_completed(task)
            self._running.clear()
            return

        while self._running.is_set():
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                # Проверяем, есть ли ещё задачи
                remaining = [t for t in self._tasks if t.status == FileStatus.PENDING]
                if not remaining:
                    break
                continue

            if self._cancelled.is_set():
                task.status = FileStatus.CANCELLED
                if self._on_completed:
                    self._on_completed(task)
                continue

            self._process_task(task)

        # Очистка временных файлов
        for tmp in self._temp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        self._temp_files.clear()

        self._running.clear()

    def _process_task(self, task: FileTask) -> None:
        """Обработать одну задачу."""
        audio_path = task.file_path

        try:
            # Если видео - извлекаем аудио
            if task.is_video:
                task.status = FileStatus.EXTRACTING
                task.progress = 10
                if self._on_progress:
                    self._on_progress(task)

                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                audio_path = extract_audio_from_video(task.file_path)
                self._temp_files.append(audio_path)
                task.progress = 20

            # Транскрибция
            task.status = FileStatus.TRANSCRIBING
            task.progress = 25
            if self._on_progress:
                self._on_progress(task)

            if self._cancelled.is_set():
                task.status = FileStatus.CANCELLED
                if self._on_completed:
                    self._on_completed(task)
                return

            # Получаем длительность
            duration = get_file_duration(task.file_path)

            # Транскрибируем
            segments_data, detected_lang, prob = self.transcriber.transcribe_with_timestamps(
                audio_path=audio_path,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            )

            if not segments_data:
                logger.warning(f"Транскрипция вернула 0 сегментов для {task.file_path.name}")
                raise ValueError("Транскрипция не вернула ни одного сегмента. Проверьте аудиофайл и настройки.")

            # Фильтруем галлюцинации Whisper (повторы, известные паттерны)
            segments_data, had_hallucinations = filter_hallucinated_segments(segments_data)
            if had_hallucinations:
                logger.warning(f"Обнаружены галлюцинации Whisper в {task.file_path.name}")

            # Проверяем качество транскрипции
            quality_ok, quality_warning = check_transcription_quality(
                segments_data, duration
            )
            if not quality_ok:
                logger.warning(f"Низкое качество транскрипции: {quality_warning}")
                if not segments_data or all(
                    not s.get("text", "").strip() for s in segments_data
                ):
                    raise ValueError(quality_warning)
                # Если есть хоть какой-то текст — продолжаем, но добавим предупреждение
                task.warning = quality_warning

            task.progress = 60
            if self._on_progress:
                self._on_progress(task)

            # Конвертируем в TranscriptionSegment
            segments = [
                TranscriptionSegment(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    words=s.get("words", [])
                )
                for s in segments_data
            ]

            # Создаём результат
            task.result = TranscriptionResult(
                file_path=task.file_path,
                segments=segments,
                detected_language=detected_lang,
                language_probability=prob,
                duration=duration if duration > 0 else (segments[-1].end if segments else 0),
                model_used=self.model_size,
            )

            # Постобработка транскрипции (если включена)
            logger.info(f"Проверка постобработки: enable={self.enable_postprocessing}, text_len={len(task.result.full_text) if task.result.full_text else 0}")
            if self.enable_postprocessing and task.result.full_text:
                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                task.status = FileStatus.PROCESSING
                task.progress = 62
                if self._on_progress:
                    self._on_progress(task)

                try:
                    logger.info(f"Начинаем постобработку для {task.file_path.name}")
                    logger.info(f"  audio_path: {audio_path}")
                    logger.info(f"  segments_count: {len(segments_data)}")
                    processed_result = self._process_text(
                        task.result.full_text,
                        audio_path,
                        segments_data,
                        task,
                    )
                    logger.info(f"Постобработка завершена. Stats: {processed_result.processing_stats}")
                    task.result.processed_text = processed_result.processed_text
                    task.result.processing_stats = processed_result.processing_stats

                    # Извлекаем статистику спикеров из диаризации
                    if processed_result.has_speakers and processed_result.diarization:
                        diar_result = processed_result.diarization

                        # 1. Сливаем слишком мелких спикеров (ошибки кластеризации).
                        # Только для локальной диаризации: LLM-разметка достоверна
                        # и для спикеров с одной репликой.
                        backend = (processed_result.processing_stats or {}).get("diarization_backend")
                        if backend != "openrouter":
                            diar_result = self._text_processor.diarizer.merge_short_speakers(diar_result)

                        # 2. Выравниваем с текстом транскрипции (чтобы посчитать слова)
                        # Преобразуем segments транскрипции в формат словаря, который ждет align
                        raw_segments = [
                            {"start": s.start, "end": s.end, "text": s.text}
                            for s in task.result.segments
                        ]
                        diar_result = self._text_processor.diarizer.align_with_transcription(diar_result, raw_segments)

                        # 3. Теперь обновляем num_speakers и считаем статистику (уже есть текст и правильные спикеры)
                        task.result.num_speakers = diar_result.num_speakers
                        task.result.speaker_names = dict(diar_result.speaker_names)

                        speaker_statistics = diar_result.get_speaker_statistics()
                        if speaker_statistics:
                            task.result.speaker_stats = [
                                SpeakerStats(
                                    speaker_id=ss.speaker_id,
                                    speaker_name=ss.speaker_name,
                                    total_duration=ss.total_duration,
                                    segment_count=ss.segment_count,
                                    word_count=ss.word_count,
                                )
                                for ss in speaker_statistics
                            ]

                        # 4. Обновляем сегменты транскрипции (чтобы покрасились в HTML)
                        if diar_result.segments:
                            self._update_segments_with_speakers(task, diar_result.segments)

                            # Также обновим processed_result, если нужно, чтобы в pipeline сохранилось
                            processed_result.diarization = diar_result

                    task.progress = 68
                except Exception as e:
                    # Постобработка не критична — продолжаем без неё
                    task.result.processing_stats = {"error": str(e)}

            # Суммаризация (если включена)
            if self.enable_summary and task.result.text_for_summary:
                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    return

                task.status = FileStatus.SUMMARIZING
                task.progress = 70
                if self._on_progress:
                    self._on_progress(task)

                try:
                    summary, metrics = self._summarize_text(task.result.text_for_summary, task)
                    if not summary or len(summary) < 10:
                        raise ValueError("Суммаризация вернула пустой или слишком короткий результат")
                    task.result.summary = summary
                    task.result.summary_metrics = metrics.to_dict() if metrics else None
                    task.result.summary_preset_name = self.summary_preset_name or None
                except Exception as e:
                    logger.error(f"Ошибка суммаризации для {task.file_path.name}: {e}")
                    # Теперь мы считаем это ошибкой задачи, если саммаризация была включена и не удалась
                    task.status = FileStatus.ERROR
                    task.error_message = f"Ошибка саммаризации: {str(e)}"
                    if self._on_completed:
                        self._on_completed(task)
                    return

            task.status = FileStatus.COMPLETED
            task.progress = 100

        except Exception as e:
            task.status = FileStatus.ERROR
            task.error_message = str(e)

        if self._on_completed:
            self._on_completed(task)

    def _summarize_text(self, text: str, task: FileTask):
        """Выполнить суммаризацию текста."""
        from .summarizer import get_summarizer, SummarizerConfig

        # Определяем параметры: универсальные или legacy openrouter
        api_key = self.summary_api_key or self.openrouter_api_key
        model = self.summary_model or self.openrouter_model
        reasoning = self.summary_reasoning or self.openrouter_reasoning
        reasoning_effort = self.summary_reasoning_effort if self.summary_api_key else self.openrouter_reasoning_effort

        # Ленивая инициализация суммаризатора с настройками
        if self._summarizer is None:
            config = SummarizerConfig(
                enable_thinking=self.enable_thinking,
                custom_prompts=self.custom_prompts,
                provider=self.summary_provider,
                api_key=api_key,
                model=model,
                base_url=self.summary_base_url,
                reasoning_enabled=reasoning,
                reasoning_effort=reasoning_effort,
                # Legacy (для обратной совместимости)
                openrouter_api_key=self.openrouter_api_key,
                openrouter_model=self.openrouter_model,
                openrouter_reasoning=self.openrouter_reasoning,
                openrouter_reasoning_effort=self.openrouter_reasoning_effort,
            )
            self._summarizer = get_summarizer(config)
        else:
            # Обновляем настройки если изменились
            self._summarizer.config.enable_thinking = self.enable_thinking
            self._summarizer.config.custom_prompts = self.custom_prompts
            self._summarizer.config.provider = self.summary_provider
            self._summarizer.config.api_key = api_key
            self._summarizer.config.model = model
            self._summarizer.config.base_url = self.summary_base_url
            self._summarizer.config.reasoning_enabled = reasoning
            self._summarizer.config.reasoning_effort = reasoning_effort
            # Legacy
            self._summarizer.config.openrouter_api_key = self.openrouter_api_key
            self._summarizer.config.openrouter_model = self.openrouter_model
            self._summarizer.config.openrouter_reasoning = self.openrouter_reasoning
            self._summarizer.config.openrouter_reasoning_effort = self.openrouter_reasoning_effort

        # Загружаем модель если нужно
        if not self._summarizer.is_loaded:
            def progress_cb(status: str, current: int, total: int):
                task.progress = 70 + int(10 * current / max(total, 1))
                if self._on_progress:
                    self._on_progress(task)

            # Используем стандартную папку для модели суммаризатора
            from pathlib import Path
            summarizer_dir = Path.home() / ".cache" / "mindtype" / "summarizer"
            self._summarizer.load_model(
                models_dir=summarizer_dir,
                progress_callback=progress_cb,
            )

        # Суммаризируем
        def summary_progress_cb(status: str, current: int, total: int):
            task.progress = 80 + int(15 * current / max(total, 1))
            if self._on_progress:
                self._on_progress(task)

        return self._summarizer.summarize(
            text,
            progress_callback=summary_progress_cb,
            thinking_callback=self._on_thinking,
        )

    def _update_segments_with_speakers(self, task: FileTask, speaker_segments) -> None:
        """
        Обновляет сегменты транскрипции информацией о спикерах.

        Args:
            task: Задача с результатом транскрипции
            speaker_segments: Сегменты диаризации с информацией о спикерах
        """
        if not task.result or not task.result.segments or not speaker_segments:
            return

        from .text_processor.diarization import assign_speaker_by_overlap

        # Для каждого сегмента транскрипции находим спикера по суммарному
        # перекрытию (устойчиво к дроблению диар-сегментов).
        for trans_seg in task.result.segments:
            best_speaker = assign_speaker_by_overlap(
                trans_seg.start, trans_seg.end, speaker_segments
            )
            if best_speaker:
                trans_seg.speaker = best_speaker

    def _process_text(self, text: str, audio_path: Path, segments_data: List[dict], task: FileTask):
        """Выполнить постобработку текста транскрипции."""
        from .text_processor import TextProcessingPipeline, ProcessingConfig

        logger.info("_process_text вызван")
        logger.info(f"  diarization: {self.postprocessing_diarization}")

        # Ленивая инициализация процессора
        if self._text_processor is None:
            logger.info("Создаём новый TextProcessingPipeline")
            config = ProcessingConfig(
                enable_diarization=self.postprocessing_diarization,
                enable_punctuation=self.postprocessing_punctuation,
                enable_fillers=self.postprocessing_fillers,
                enable_normalize=self.postprocessing_normalize,
                enable_correct=self.postprocessing_correct,
                diarization_backend=self.postprocessing_diarization_backend,
                diarization_api_key=self.postprocessing_diarization_api_key,
                diarization_model=self.postprocessing_diarization_model,
                language=self.language,
            )
            self._text_processor = TextProcessingPipeline(config)
            logger.info("TextProcessingPipeline создан")
        else:
            # Обновляем настройки если изменились
            self._text_processor.config.enable_diarization = self.postprocessing_diarization
            self._text_processor.config.diarization_backend = self.postprocessing_diarization_backend
            self._text_processor.config.diarization_api_key = self.postprocessing_diarization_api_key
            self._text_processor.config.diarization_model = self.postprocessing_diarization_model
            self._text_processor.config.enable_punctuation = self.postprocessing_punctuation
            self._text_processor.config.enable_fillers = self.postprocessing_fillers
            self._text_processor.config.enable_normalize = self.postprocessing_normalize
            self._text_processor.config.enable_correct = self.postprocessing_correct
            self._text_processor.config.language = self.language

        # Callback для прогресса
        def processing_progress_cb(status: str, current: int, total: int):
            task.progress = 62 + int(6 * current / max(total, 1))
            if self._on_progress:
                self._on_progress(task)

        return self._text_processor.process(
            text=text,
            audio_path=audio_path,
            transcription_segments=segments_data,
            progress_callback=processing_progress_cb,
        )

    @property
    def is_running(self) -> bool:
        """Проверить, выполняется ли обработка."""
        return self._running.is_set()

    @property
    def completed_count(self) -> int:
        """Количество завершённых задач."""
        return sum(1 for t in self._tasks if t.status == FileStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Общее количество задач."""
        return len(self._tasks)

