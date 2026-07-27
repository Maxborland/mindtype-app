"""
Модуль для транскрибции аудио и видео файлов.
Поддерживает пакетную обработку и извлечение аудио из видео.
"""

import logging
import os
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional
import threading
import queue
import time

from .text_processor.repetition_filter import (
    filter_hallucinated_segments,
    check_transcription_quality,
)
from .optional_features import (
    effective_diarization_backend,
    local_diarization_available,
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
        cloud_executor=None,
        cloud_summary_executor=None,
        cloud_transcribe_options: Optional[Dict] = None,
        cloud_summary_options: Optional[Dict] = None,
        cloud_poll_interval: float = 1.0,
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
        backend = effective_diarization_backend(
            postprocess.diarization_backend,
            api_key=postprocess.diarization_api_key,
            local_available=local_diarization_available(),
        )
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
        self.cloud_executor = cloud_executor
        self.cloud_summary_executor = cloud_summary_executor
        self.cloud_transcribe_options = dict(
            cloud_transcribe_options or {}
        )
        self.cloud_summary_options = (
            dict(cloud_summary_options)
            if cloud_summary_options is not None
            else None
        )
        self.cloud_poll_interval = max(0.0, float(cloud_poll_interval))

        self._tasks: List[FileTask] = []
        self._queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._cancelled = threading.Event()
        self._shutdown_requested = threading.Event()
        self._temp_files: List[Path] = []
        self._summarizer = None  # Ленивая инициализация
        self._text_processor = None  # Ленивая инициализация

    @property
    def tasks(self) -> List[FileTask]:
        """Получить список задач."""
        return self._tasks.copy()

    @property
    def cancel_requested(self) -> bool:
        return self._cancelled.is_set()

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
        if (
            self._running.is_set()
            or self._shutdown_requested.is_set()
        ):
            return

        self._running.set()
        self._cancelled.clear()

        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def cancel(self) -> list[FileTask]:
        """Отменить обработку."""
        self._cancelled.set()
        self._running.clear()
        if self.uses_local_transcriber:
            cancel_current = getattr(
                self.transcriber,
                "cancel_current",
                None,
            )
            if callable(cancel_current):
                try:
                    cancel_current()
                except Exception:
                    pass

        cancelled_tasks = []
        for task in self._tasks:
            if task.status == FileStatus.PENDING:
                task.status = FileStatus.CANCELLED
                cancelled_tasks.append(task)
                if self._on_completed:
                    self._on_completed(task)
        return cancelled_tasks

    def stop_for_shutdown(self, timeout_seconds: float = 5.0) -> bool:
        """Stop and join work while preserving any durable cloud job."""
        self._shutdown_requested.set()
        self._running.clear()
        if self.uses_local_transcriber:
            cancel_current = getattr(
                self.transcriber,
                "cancel_current",
                None,
            )
            if callable(cancel_current):
                try:
                    cancel_current()
                except Exception:
                    logger.exception(
                        "Could not stop local transcription for shutdown"
                    )
        worker = self._worker_thread
        if worker is None or worker is threading.current_thread():
            return True
        worker.join(max(0.0, float(timeout_seconds)))
        return not worker.is_alive()

    def _worker(self) -> None:
        """Рабочий поток для обработки очереди."""
        try:
            if self.cloud_executor is None:
                try:
                    prepare_operation = getattr(
                        self.transcriber,
                        "prepare_operation",
                        None,
                    )
                    if callable(prepare_operation):
                        prepare_operation()
                    self.transcriber.load_model(
                        model_size=self.model_size,
                        compute_type=self.compute_type,
                        device=self.device,
                        models_dir=str(self.models_dir),
                    )
                except Exception as e:
                    if self._shutdown_requested.is_set():
                        return
                    for task in self._tasks:
                        if task.status == FileStatus.PENDING:
                            task.status = (
                                FileStatus.CANCELLED
                                if self._cancelled.is_set()
                                else FileStatus.ERROR
                            )
                            if task.status is FileStatus.ERROR:
                                task.error_message = (
                                    f"Ошибка загрузки модели: {e}"
                                )
                            if self._on_completed:
                                self._on_completed(task)
                    return

            while self._running.is_set():
                try:
                    task = self._queue.get(timeout=0.5)
                except queue.Empty:
                    remaining = [
                        t for t in self._tasks if t.status == FileStatus.PENDING
                    ]
                    if not remaining:
                        break
                    continue

                if self._cancelled.is_set():
                    task.status = FileStatus.CANCELLED
                    if self._on_completed:
                        self._on_completed(task)
                    continue

                try:
                    self._process_task(task)
                except Exception as exc:
                    if self._shutdown_requested.is_set():
                        return
                    task.status = (
                        FileStatus.CANCELLED
                        if self._cancelled.is_set()
                        else FileStatus.ERROR
                    )
                    if task.status is FileStatus.ERROR:
                        task.error_message = str(exc)
                    if self._on_completed:
                        self._on_completed(task)
        finally:
            for tmp in self._temp_files:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            self._temp_files.clear()
            self._running.clear()

    def _process_task(self, task: FileTask) -> None:
        """Обработать одну задачу."""
        if self.cloud_executor is not None:
            self._process_cloud_task(task)
            return
        processing_path = task.processing_path
        audio_path = processing_path

        def finish_cancelled() -> bool:
            if self._shutdown_requested.is_set():
                return True
            if not self._cancelled.is_set():
                return False
            task.status = FileStatus.CANCELLED
            task.progress = 0
            if self._on_completed:
                self._on_completed(task)
            return True

        try:
            # Если видео - извлекаем аудио
            if task.is_video:
                task.status = FileStatus.EXTRACTING
                task.progress = 10
                if self._on_progress:
                    self._on_progress(task)

                if finish_cancelled():
                    return

                audio_path = extract_audio_from_video(processing_path)
                self._temp_files.append(audio_path)
                task.progress = 20
                if finish_cancelled():
                    return

            # Транскрибция
            task.status = FileStatus.TRANSCRIBING
            task.progress = 25
            if self._on_progress:
                self._on_progress(task)

            if finish_cancelled():
                return

            # Получаем длительность
            duration = get_file_duration(processing_path)
            if finish_cancelled():
                return

            # Транскрибируем
            segments_data, detected_lang, prob = self.transcriber.transcribe_with_timestamps(
                audio_path=audio_path,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            )
            if finish_cancelled():
                return

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
                file_path=(
                    Path(task.display_name)
                    if task.display_name
                    else task.file_path
                ),
                segments=segments,
                detected_language=detected_lang,
                language_probability=prob,
                duration=duration if duration > 0 else (segments[-1].end if segments else 0),
                model_used=self.model_size,
            )

            # Постобработка транскрипции (если включена)
            logger.info(f"Проверка постобработки: enable={self.enable_postprocessing}, text_len={len(task.result.full_text) if task.result.full_text else 0}")
            if self.enable_postprocessing and task.result.full_text:
                if finish_cancelled():
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
                    if finish_cancelled():
                        return
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
                if finish_cancelled():
                    return

                task.status = FileStatus.SUMMARIZING
                task.progress = 70
                if self._on_progress:
                    self._on_progress(task)

                try:
                    if (
                        self.summary_provider == "mindtype_cloud"
                        and self.cloud_summary_executor is not None
                    ):
                        if not self._summarize_local_result_in_cloud(task):
                            if self._shutdown_requested.is_set():
                                return
                            if finish_cancelled():
                                return
                            raise RuntimeError(
                                "MindType Cloud summary did not complete"
                            )
                    else:
                        summary, metrics = self._summarize_text(
                            task.result.text_for_summary,
                            task,
                        )
                        if finish_cancelled():
                            return
                        if not summary or len(summary) < 10:
                            raise ValueError(
                                "Суммаризация вернула пустой или слишком "
                                "короткий результат"
                            )
                        task.result.summary = summary
                        task.result.summary_metrics = (
                            metrics.to_dict() if metrics else None
                        )
                        task.result.summary_preset_name = (
                            self.summary_preset_name or None
                        )
                except Exception as e:
                    if finish_cancelled():
                        return
                    logger.error(f"Ошибка суммаризации для {task.file_path.name}: {e}")
                    # Теперь мы считаем это ошибкой задачи, если саммаризация была включена и не удалась
                    task.status = FileStatus.ERROR
                    task.error_message = f"Ошибка саммаризации: {str(e)}"
                    if self._on_completed:
                        self._on_completed(task)
                    return

            if finish_cancelled():
                return
            task.status = FileStatus.COMPLETED
            task.progress = 100

        except Exception as e:
            if self._shutdown_requested.is_set():
                return
            if self._cancelled.is_set():
                task.status = FileStatus.CANCELLED
                task.progress = 0
            else:
                task.status = FileStatus.ERROR
                task.error_message = str(e)

        if self._on_completed:
            self._on_completed(task)

    @staticmethod
    def _result_from_canonical(
        payload: Dict,
        *,
        fallback_path: Path,
    ) -> TranscriptionResult:
        transcript = payload["transcript"]
        source = payload["source"]
        route = payload.get("route", {})
        segments = [
            TranscriptionSegment(
                start=float(segment["start_ms"]) / 1000,
                end=float(segment["end_ms"]) / 1000,
                text=str(segment["text"]),
                speaker=segment.get("speaker_id"),
                words=list(segment.get("words") or []),
            )
            for segment in transcript["segments"]
        ]
        speaker_stats = [
            SpeakerStats(
                speaker_id=str(speaker["speaker_id"]),
                speaker_name=str(
                    speaker.get("display_name") or speaker["speaker_id"]
                ),
                total_duration=float(
                    speaker.get("total_duration_ms", 0)
                )
                / 1000,
                segment_count=int(speaker.get("segment_count", 0)),
                word_count=int(speaker.get("word_count", 0)),
            )
            for speaker in payload.get("speakers", [])
        ]
        summary = payload.get("summary")
        transcription_route = route.get("transcription", {})
        result = TranscriptionResult(
            file_path=Path(source.get("display_name") or fallback_path),
            segments=segments,
            detected_language=str(transcript.get("language") or "und"),
            language_probability=float(
                transcript.get("confidence")
                if transcript.get("confidence") is not None
                else 0.0
            ),
            duration=float(source.get("duration_ms", 0)) / 1000,
            model_used=str(transcription_route.get("model") or "auto"),
            summary=(
                str(summary.get("text"))
                if isinstance(summary, dict) and summary.get("text")
                else None
            ),
            processed_text=transcript.get("processed_text"),
            speaker_stats=speaker_stats or None,
            num_speakers=len(speaker_stats),
            speaker_names={
                item.speaker_id: item.speaker_name
                for item in speaker_stats
            },
            summary_preset_name=(
                str(summary.get("preset"))
                if isinstance(summary, dict) and summary.get("preset")
                else None
            ),
        )
        return result

    def _process_cloud_task(self, task: FileTask) -> None:
        from .operation_models import OperationStage, OperationStatus

        while True:
            if self._shutdown_requested.is_set():
                return
            if self._cancelled.is_set():
                try:
                    operation = self.cloud_executor.cancel(
                        task.operation_id
                    )
                except Exception:
                    task.cancellation_pending = True
                    raise
            else:
                operation = self.cloud_executor.advance_transcription(
                    task.operation_id,
                    options=self.cloud_transcribe_options,
                    summary_options=self.cloud_summary_options,
                )

            if operation.status is OperationStatus.COMPLETED:
                if (
                    operation.canonical_result_path is None
                    or not operation.canonical_result_path.is_file()
                ):
                    raise RuntimeError(
                        "Cloud operation completed without a local result"
                    )
                payload = json.loads(
                    operation.canonical_result_path.read_text(
                        encoding="utf-8"
                    )
                )
                task.result = self._result_from_canonical(
                    payload,
                    fallback_path=task.file_path,
                )
                task.status = FileStatus.COMPLETED
                task.progress = 100
                if self._on_completed:
                    self._on_completed(task)
                return
            if operation.status is OperationStatus.CANCELLED:
                task.status = FileStatus.CANCELLED
                task.progress = 0
                if self._on_completed:
                    self._on_completed(task)
                return
            if operation.status is OperationStatus.RETRYABLE:
                task.status = FileStatus.PENDING
                task.progress = 0
                task.error_message = (
                    operation.last_error_code or "CLOUD_RETRY_REQUIRED"
                )
                self._running.clear()
                if self._on_completed:
                    self._on_completed(task)
                return
            if operation.status is OperationStatus.FAILED:
                task.status = FileStatus.ERROR
                task.error_message = (
                    operation.last_error_code or "CLOUD_PROCESSING_FAILED"
                )
                if self._on_completed:
                    self._on_completed(task)
                return

            if operation.stage is OperationStage.SUMMARIZE:
                task.status = FileStatus.SUMMARIZING
                task.progress = max(task.progress, 70)
            else:
                task.status = FileStatus.TRANSCRIBING
                task.progress = max(task.progress, 25)
            if self._on_progress:
                self._on_progress(task)
            self._wait_for_cloud_poll()

    def _summarize_local_result_in_cloud(self, task: FileTask) -> bool:
        """Poll one idempotent summary job without repeating local STT."""
        from .operation_models import OperationStage, OperationStatus

        canonical_transcript = (
            self.cloud_summary_executor.coordinator
            .canonical_payload_for_file_task(task)
        )
        while True:
            if self._shutdown_requested.is_set():
                return False
            if self._cancelled.is_set():
                try:
                    operation = self.cloud_summary_executor.cancel(
                        task.operation_id
                    )
                except Exception:
                    task.cancellation_pending = True
                    raise
            else:
                operation = self.cloud_summary_executor.advance_summary(
                    task.operation_id,
                    canonical_transcript=canonical_transcript,
                    options=self.cloud_summary_options or {},
                )
            if operation.status is OperationStatus.COMPLETED:
                result_path = operation.canonical_result_path
                if result_path is None or not result_path.is_file():
                    raise RuntimeError(
                        "Cloud summary completed without a local result"
                    )
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                task.result = self._result_from_canonical(
                    payload,
                    fallback_path=task.file_path,
                )
                return True
            if operation.status is OperationStatus.CANCELLED:
                return False
            if operation.status in {
                OperationStatus.FAILED,
                OperationStatus.RETRYABLE,
            }:
                raise RuntimeError(
                    operation.last_error_code or "CLOUD_SUMMARY_FAILED"
                )
            task.status = FileStatus.SUMMARIZING
            task.progress = max(task.progress, 70)
            if operation.stage is OperationStage.SUMMARIZE:
                task.progress = max(task.progress, 75)
            if self._on_progress:
                self._on_progress(task)
            self._wait_for_cloud_poll()

    def _wait_for_cloud_poll(self) -> None:
        if self._shutdown_requested.is_set():
            return
        if self._cancelled.is_set():
            time.sleep(self.cloud_poll_interval)
            return
        self._shutdown_requested.wait(self.cloud_poll_interval)

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
    def uses_local_transcriber(self) -> bool:
        return self.cloud_executor is None

    @property
    def completed_count(self) -> int:
        """Количество завершённых задач."""
        return sum(1 for t in self._tasks if t.status == FileStatus.COMPLETED)

    @property
    def total_count(self) -> int:
        """Общее количество задач."""
        return len(self._tasks)
