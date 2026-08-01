"""
Фоновые воркеры для UI MindType.

Все QThread классы для асинхронных операций.
"""

import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QThread, pyqtSignal

if TYPE_CHECKING:
    from ..transcriber import Transcriber
    from ..updater import Updater
    from ..file_transcriber import FileTranscriptionQueue, FileTask, FileStatus
    from ..report_generator import ReportGenerator
    from ..summarizer import SummarizerConfig
    from ..transcript_documents import SummaryTemplate
    from ..transcript_store import TranscriptStore


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
            self.finished.emit(last_text, detected_lang, detected_prob, "")
        except Exception as exc:
            if self._cancelled:
                self.cancelled.emit()
                return
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.finished.emit(last_text, detected_lang, detected_prob, err)


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
                try:
                    task.status = FileStatus.GENERATING
                    task.progress = 95
                    self.task_progress.emit(task)

                    self._report_generator.generate(
                        task.result,
                        self.output_dir,
                        self.output_format,
                    )

                    task.status = FileStatus.COMPLETED
                    task.progress = 100
                except Exception as e:
                    # Report generation is downstream of transcription. Keep
                    # the durable transcript usable even when the selected
                    # HTML/PDF writer fails.
                    task.status = FileStatus.COMPLETED
                    task.warning = "\n".join(
                        part
                        for part in (
                            task.warning,
                            f"Отчёт не создан: {str(e)}",
                        )
                        if part
                    )
                    task.error_message = ""
                    task.progress = 100

            self.task_completed.emit(task)

        self.queue._on_progress = on_progress
        self.queue._on_completed = on_completed

        # Запускаем очередь
        self.queue.start()

        # Ждём завершения
        while self.queue.is_running:
            self.msleep(100)

        self.all_completed.emit()


class CloudAcknowledgeWorker(QThread):
    """Acknowledge a durable Cloud result outside the UI thread."""

    acknowledged = pyqtSignal(str, str)

    def __init__(
        self,
        transcriber,
        job_id: str,
        ack_method: str = "acknowledge_result",
    ) -> None:
        super().__init__()
        self.transcriber = transcriber
        self.job_id = job_id
        self.ack_method = ack_method

    def run(self) -> None:
        try:
            acknowledge = getattr(self.transcriber, self.ack_method)
            acknowledge(self.job_id)
            self.acknowledged.emit(self.job_id, "")
        except Exception as exc:
            error = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            self.acknowledged.emit(self.job_id, error)


class TranscriptSummaryWorker(QThread):
    """Create and durably save a transcript document variant."""

    progress = pyqtSignal(str)
    succeeded = pyqtSignal(str, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        store,
        document_id: str,
        template,
        summarizer_config,
        cloud_client=None,
    ) -> None:
        super().__init__()
        self.store = store
        self.document_id = document_id
        self.template = template
        self.summarizer_config = summarizer_config
        self.cloud_client = cloud_client

    def run(self) -> None:
        try:
            from types import SimpleNamespace
            from uuid import uuid4

            from ..cloud_summary import (
                CloudSummaryClient,
                canonical_from_transcription_result,
                serialize_prompt_templates,
            )
            from ..summarizer import Summarizer
            from ..transcript_documents import create_summary_document

            cloud_summary = (
                CloudSummaryClient(self.cloud_client)
                if self.cloud_client is not None
                else None
            )
            summarizer = (
                None if cloud_summary is not None
                else Summarizer(self.summarizer_config)
            )
            pending_cloud_job: list[str] = []

            def generate(text: str, prompts: dict[str, str]):
                if cloud_summary is not None:
                    document = self.store.get_document(self.document_id)
                    if document is None:
                        raise KeyError(
                            f"Расшифровка {self.document_id} не найдена"
                        )
                    revision = document.current_revision
                    canonical = canonical_from_transcription_result(
                        SimpleNamespace(
                            segments=revision.segments,
                            speaker_names=revision.speaker_names,
                            detected_language=document.detected_language,
                            language_probability=document.language_probability,
                            duration=document.duration,
                            model_used=document.model_used,
                        )
                    )
                    outcome = cloud_summary.summarize(
                        canonical_transcript=canonical,
                        preset=self.template.id,
                        custom_prompt=(
                            serialize_prompt_templates(prompts) or None
                        ),
                        operation_id=str(uuid4()),
                        input_token_estimate=max(1, len(text.split())),
                        max_output_tokens=2_000,
                    )
                    pending_cloud_job.append(outcome.job_id)
                    return outcome.text, {
                        "input": {
                            "tokens": outcome.input_tokens,
                            "chunks": 1,
                        },
                        "processing": {
                            "llm_calls": 1,
                            "time_sec": 0.0,
                        },
                        "quality": {"language_retries": 0},
                        "output_tokens": outcome.output_tokens,
                    }

                assert summarizer is not None
                summarizer.config.custom_prompts = prompts
                if not summarizer.is_loaded:
                    summarizer.load_model(
                        models_dir=(
                            Path.home()
                            / ".cache"
                            / "mindtype"
                            / "summarizer"
                        ),
                        progress_callback=lambda status, _current, _total: (
                            self.progress.emit(status)
                        ),
                    )
                content, metrics = summarizer.summarize(
                    text,
                    progress_callback=lambda status, _current, _total: (
                        self.progress.emit(status)
                    ),
                )
                return content, metrics.to_dict() if metrics else None

            variant = create_summary_document(
                self.store,
                self.document_id,
                self.template,
                generate,
            )
            if cloud_summary is not None and pending_cloud_job:
                job_id = pending_cloud_job[0]
                # The variant is already durable. Register the remote job
                # before attempting cleanup so an ACK failure is retryable.
                self.store.register_cloud_summary_job(self.document_id, job_id)
                try:
                    cloud_summary.acknowledge(job_id)
                except Exception as ack_error:
                    self.progress.emit(
                        f"Cloud summary cleanup pending: {ack_error}"
                    )
                else:
                    self.store.mark_cloud_cleanup_acknowledged(
                        self.document_id,
                        job_id,
                        "summary",
                    )
            self.succeeded.emit(self.document_id, variant.id)
        except Exception as exc:
            error = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            self.failed.emit(error)