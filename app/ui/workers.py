"""
Фоновые воркеры для UI MindType.

Все QThread классы для асинхронных операций.
"""

import json
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from ..transcriber import Transcriber
    from ..updater import Updater
    from ..file_transcriber import FileTranscriptionQueue, FileTask, FileStatus
    from ..report_generator import ReportGenerator


class TranscribeWorker(QThread):
    """Воркер для транскрипции аудио."""
    progress = pyqtSignal(str, str, float)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(str, str, float, str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        transcriber: "Transcriber",
        audio_path: Path,
        model_size: str,
        compute_type: str,
        device: str,
        cpu_threads: int,
        num_workers: int,
        language: str,
        beam_size: int,
        vad_filter: bool,
        models_dir: Path,
    ) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.audio_path = audio_path
        self.model_size = model_size
        self.compute_type = compute_type
        self.device = device
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.models_dir = models_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Отменить транскрипцию."""
        self._cancelled = True
        cancel_current = getattr(self.transcriber, "cancel_current", None)
        if callable(cancel_current):
            try:
                cancel_current()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        """Проверить, отменена ли транскрипция."""
        return self._cancelled

    def _on_progress(self, status: str, current: int, total: int) -> None:
        self.status_update.emit(status)

    def run(self) -> None:
        last_text = ""
        detected_lang: str = ""
        detected_prob: float = 0.0
        try:
            if self._cancelled:
                self.cancelled.emit()
                return

            prepare_operation = getattr(self.transcriber, "prepare_operation", None)
            if callable(prepare_operation):
                prepare_operation()

            self.status_update.emit("loading_model")
            self.transcriber.load_model(
                model_size=self.model_size,
                compute_type=self.compute_type,
                device=self.device,
                cpu_threads=self.cpu_threads,
                num_workers=self.num_workers,
                models_dir=str(self.models_dir),
                progress_callback=self._on_progress,
            )

            if self._cancelled:
                self.cancelled.emit()
                return

            self.status_update.emit("transcribing")
            for partial, lang, prob in self.transcriber.transcribe_stream(
                self.audio_path,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
            ):
                if self._cancelled:
                    self.cancelled.emit()
                    return
                last_text = partial
                detected_lang = lang or ""
                detected_prob = prob
                self.progress.emit(partial, detected_lang, prob)
            if self._cancelled:
                self.cancelled.emit()
                return
            self.finished.emit(last_text, detected_lang, detected_prob, "")
        except Exception as exc:
            if self._cancelled:
                self.cancelled.emit()
                return
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.finished.emit(last_text, detected_lang, detected_prob, err)


class CloudDictationWorker(QThread):
    """Poll one durable cloud dictation without loading a local model."""

    progress = pyqtSignal(str, str, float)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(str, str, float, str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        executor,
        operation_id: str,
        *,
        options: Mapping[str, object],
        poll_interval_ms: int = 1_000,
    ) -> None:
        super().__init__()
        self.executor = executor
        self.operation_id = operation_id
        self.options = dict(options)
        self.poll_interval_ms = max(0, int(poll_interval_ms))
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        try:
            self.executor.cancel(self.operation_id)
        except Exception:
            pass

    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        from ..operation_models import OperationStage, OperationStatus

        try:
            while True:
                if self._cancelled:
                    self.executor.cancel(self.operation_id)
                    self.cancelled.emit()
                    return
                operation = self.executor.advance_transcription(
                    self.operation_id,
                    options=self.options,
                )
                if operation.status is OperationStatus.COMPLETED:
                    result_path = operation.canonical_result_path
                    if result_path is None or not result_path.is_file():
                        raise RuntimeError(
                            "Cloud dictation completed without a local result"
                        )
                    payload = json.loads(
                        result_path.read_text(encoding="utf-8")
                    )
                    transcript = payload["transcript"]
                    text = " ".join(
                        str(segment.get("text") or "").strip()
                        for segment in transcript["segments"]
                        if str(segment.get("text") or "").strip()
                    )
                    confidence = transcript.get("confidence")
                    self.finished.emit(
                        text,
                        str(transcript.get("language") or "und"),
                        (
                            float(confidence)
                            if confidence is not None
                            else 0.0
                        ),
                        "",
                    )
                    return
                if operation.status is OperationStatus.CANCELLED:
                    self.cancelled.emit()
                    return
                if operation.status in {
                    OperationStatus.FAILED,
                    OperationStatus.RETRYABLE,
                }:
                    self.finished.emit(
                        "",
                        "",
                        0.0,
                        operation.last_error_code
                        or "CLOUD_TRANSCRIPTION_FAILED",
                    )
                    return
                self.status_update.emit(
                    "summarizing"
                    if operation.stage is OperationStage.SUMMARIZE
                    else "transcribing"
                )
                self.msleep(self.poll_interval_ms)
        except Exception as error:
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.finished.emit("", "", 0.0, str(error))


class ModelDownloadWorker(QThread):
    """Воркер для загрузки моделей."""
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(str, str)

    def __init__(
        self,
        transcriber: "Transcriber",
        model_size: str,
        models_dir: Path,
    ) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.model_size = model_size
        self.models_dir = models_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _on_progress(self, status: str, current: int, total: int) -> None:
        if self._cancelled:
            raise InterruptedError("Download cancelled")
        self.progress.emit(status, current, total)

    def run(self) -> None:
        try:
            path = self.transcriber.download_model(
                self.model_size,
                self.models_dir,
                progress_callback=self._on_progress,
            )
            if self._cancelled:
                self.finished.emit("", "cancelled")
            else:
                self.finished.emit(str(path), "")
        except InterruptedError:
            self.finished.emit("", "cancelled")
        except Exception as exc:
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.finished.emit("", err)


class UpdateCheckWorker(QThread):
    """Воркер для асинхронной проверки обновлений."""
    finished = pyqtSignal(object)  # UpdateInfo

    def __init__(self, updater: "Updater") -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        info = self.updater.check_for_updates()
        self.finished.emit(info)


class UpdateDownloadWorker(QThread):
    """Воркер для асинхронного скачивания обновлений."""
    progress = pyqtSignal(int, int)  # downloaded, total
    finished = pyqtSignal(bool, str, str)  # success, path, error

    def __init__(self, updater: "Updater") -> None:
        super().__init__()
        self.updater = updater

    def run(self) -> None:
        def on_progress(downloaded: int, total: int) -> None:
            self.progress.emit(downloaded, total)

        success, path, error = self.updater.download_update(on_progress)
        self.finished.emit(success, str(path) if path else "", error or "")


class FileTranscriptionWorker(QThread):
    """Воркер для транскрипции файлов."""
    task_progress = pyqtSignal(object)  # FileTask
    task_completed = pyqtSignal(object)  # FileTask
    all_completed = pyqtSignal()

    def __init__(
        self,
        queue: "FileTranscriptionQueue",
        output_dir: Path,
        output_format: str,
        ui_language: str,
    ):
        super().__init__()
        self.queue = queue
        self.output_dir = output_dir
        self.output_format = output_format
        self.ui_language = ui_language

        # Импортируем здесь чтобы избежать circular imports
        from ..report_generator import ReportGenerator
        self._report_generator = ReportGenerator(ui_language)

    def run(self):
        # Импортируем здесь чтобы избежать circular imports
        from ..file_transcriber import FileStatus

        # Устанавливаем callbacks
        def on_progress(task):
            self.task_progress.emit(task)

        def on_completed(task):
            # Генерируем отчёт если успешно
            if task.status == FileStatus.COMPLETED and task.result:
                if getattr(self.queue, "cancel_requested", False):
                    task.status = FileStatus.CANCELLED
                    task.progress = 0
                    self.task_completed.emit(task)
                    return
                try:
                    task.status = FileStatus.GENERATING
                    task.progress = 95
                    self.task_progress.emit(task)

                    created_files = self._report_generator.generate(
                        task.result,
                        self.output_dir,
                        self.output_format,
                    )

                    if getattr(self.queue, "cancel_requested", False):
                        for path in created_files.values():
                            path.unlink(missing_ok=True)
                        task.output_files = {}
                        task.status = FileStatus.CANCELLED
                        task.progress = 0
                    else:
                        task.output_files = created_files
                        task.status = FileStatus.COMPLETED
                        task.progress = 100
                except Exception as e:
                    if getattr(self.queue, "cancel_requested", False):
                        task.status = FileStatus.CANCELLED
                        task.progress = 0
                    else:
                        task.status = FileStatus.ERROR
                        task.error_message = str(e)

            self.task_completed.emit(task)

        self.queue._on_progress = on_progress
        self.queue._on_completed = on_completed

        # Запускаем очередь
        self.queue.start()

        # Ждём завершения
        while self.queue.is_running:
            self.msleep(100)

        self.all_completed.emit()
