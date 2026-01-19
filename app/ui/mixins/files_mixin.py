"""
Миксин для обработки файлов в MainWindow.

Содержит методы:
- _on_files_dropped: обработка drag & drop файлов
- _on_start_processing: запуск обработки очереди
- _on_file_task_progress: прогресс обработки файла
- _on_file_task_completed: завершение обработки файла
- _on_all_files_completed: завершение обработки всех файлов
- _rebuild_file_queue_ui: перестроение UI очереди
"""

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

if TYPE_CHECKING:
    from ...file_transcriber import FileTranscriptionQueue, FileTask, FileStatus
    from ..workers import FileTranscriptionWorker
    from ..file_widgets import FileQueueItemWidget


class FilesMixin:
    """Миксин для функциональности обработки файлов."""

    # Атрибуты, которые должны быть определены в MainWindow
    _file_tasks: List["FileTask"]
    _file_queue: Optional["FileTranscriptionQueue"]
    _file_worker: Optional["FileTranscriptionWorker"]
    _output_dir: Path
    _file_queue_widgets: dict  # task_id -> FileQueueItemWidget

    def _on_files_dropped(self, files: List[Path]) -> None:
        """Обработка добавления файлов через drag & drop."""
        from ...file_transcriber import FileTask, FileStatus, is_supported_file
        from ...crash_reporter import add_breadcrumb

        add_breadcrumb(f"Files dropped: {len(files)} files")

        # Исключаем только файлы в процессе или ожидающие обработки
        processing_statuses = (FileStatus.PENDING, FileStatus.EXTRACTING, 
                               FileStatus.TRANSCRIBING, FileStatus.SUMMARIZING, 
                               FileStatus.GENERATING)

        for file_path in files:
            if not is_supported_file(file_path):
                continue

            # Проверяем, не в процессе ли уже этот файл
            existing = [t for t in self._file_tasks 
                        if t.file_path == file_path and t.status in processing_statuses]
            if existing:
                continue

            # Удаляем старую завершённую задачу с тем же путём если есть
            self._file_tasks = [t for t in self._file_tasks if t.file_path != file_path]

            # Создаём задачу
            task = FileTask(file_path)
            self._file_tasks.append(task)

        self._rebuild_file_queue_ui()

    def _on_select_files(self) -> None:
        """Обработка выбора файлов через диалог."""
        from PyQt6.QtWidgets import QFileDialog
        from ...file_transcriber import ALL_EXTENSIONS

        extensions = " ".join(f"*{ext}" for ext in ALL_EXTENSIONS)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("select_files"),
            "",
            f"Audio/Video ({extensions})"
        )

        if files:
            self._on_files_dropped([Path(f) for f in files])

    def _on_remove_task(self, task: "FileTask") -> None:
        """Удалить задачу из очереди."""
        from ...file_transcriber import FileStatus

        if task.status in (FileStatus.PENDING, FileStatus.ERROR, FileStatus.CANCELLED):
            self._file_tasks.remove(task)
            self._rebuild_file_queue_ui()

    def _on_open_task_folder(self, task: "FileTask") -> None:
        """Открыть папку с результатом."""
        if task.output_path and task.output_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(task.output_path.parent)))

    def _on_clear_queue(self) -> None:
        """Очистить очередь файлов."""
        from ...file_transcriber import FileStatus

        # Оставляем только файлы в процессе обработки
        self._file_tasks = [
            t for t in self._file_tasks
            if t.status in (FileStatus.EXTRACTING, FileStatus.TRANSCRIBING, 
                            FileStatus.SUMMARIZING, FileStatus.GENERATING)
        ]
        self._rebuild_file_queue_ui()

    def _on_start_processing(self) -> None:
        """Начать обработку файлов."""
        from ...crash_reporter import add_breadcrumb
        from ...file_transcriber import FileTranscriptionQueue, FileStatus
        from ..workers import FileTranscriptionWorker

        if not self._file_tasks:
            return

        pending_tasks = [t for t in self._file_tasks if t.status == FileStatus.PENDING]
        if not pending_tasks:
            return

        add_breadcrumb(f"Starting file processing: {len(pending_tasks)} files")

        # Создаём директорию вывода
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Запоминаем параметры запуска
        self._file_processing_batch_size = len(pending_tasks)
        self._file_output_format = self.output_format_combo.currentData()
        self._last_completed_task: Optional["FileTask"] = None

        # Создаём очередь
        cfg = self.config.config

        # Загружаем промпты из пресета и объединяем с кастомными
        from ...summary_presets import get_preset_prompts
        preset_id = cfg.get("summary_preset", "pm")
        preset_prompts = get_preset_prompts(preset_id)
        custom_prompts_saved = cfg.get("custom_prompts", {})
        # Кастомные промпты перезаписывают промпты из пресета
        custom_prompts = {**preset_prompts, **custom_prompts_saved} if custom_prompts_saved else preset_prompts

        self._file_queue = FileTranscriptionQueue(
            transcriber=self.transcriber,
            model_size=cfg.get("model_size", "large-v3"),
            compute_type=cfg.get("compute_type", "int8"),
            device=cfg.get("device", "auto"),
            language=cfg.get("language", "ru"),
            beam_size=int(cfg.get("beam_size", 5)),
            vad_filter=bool(cfg.get("vad_filter", True)),
            models_dir=self.models_dir,
            enable_summary=self.enable_summary_checkbox.isChecked(),
            on_thinking=lambda text: self.thinking_signal.emit(text),
            enable_thinking=True,
            custom_prompts=custom_prompts,
            # OpenRouter настройки
            summary_provider="openrouter",
            openrouter_api_key=cfg.get("openrouter_api_key", ""),
            openrouter_model=cfg.get("openrouter_model", ""),
            openrouter_reasoning=True,
            openrouter_reasoning_effort=cfg.get("openrouter_reasoning_effort", "medium"),
            # Постобработка
            enable_postprocessing=cfg.get("enable_postprocessing", True),
            postprocessing_diarization=cfg.get("postprocessing_diarization", True),
            postprocessing_punctuation=cfg.get("postprocessing_punctuation", True),
            postprocessing_fillers=cfg.get("postprocessing_fillers", True),
            postprocessing_normalize=cfg.get("postprocessing_normalize", True),
            postprocessing_correct=cfg.get("postprocessing_correct", True),
        )

        # Добавляем файлы
        for task in pending_tasks:
            self._file_queue._tasks.append(task)
            self._file_queue._queue.put(task)

        # Создаём и запускаем воркер
        self._file_worker = FileTranscriptionWorker(
            queue=self._file_queue,
            output_dir=self._output_dir,
            output_format=self.output_format_combo.currentData(),
            ui_language=self._ui_lang,
        )
        self._file_worker.task_progress.connect(self._on_file_task_progress)
        self._file_worker.task_completed.connect(self._on_file_task_completed)
        self._file_worker.all_completed.connect(self._on_all_files_completed)
        self._file_worker.start()

    def _on_file_task_progress(self, task_id: str, progress: int, status: str) -> None:
        """Обработчик прогресса обработки файла."""
        from ...file_transcriber import FileStatus

        # Находим задачу
        task = next((t for t in self._file_tasks if t.id == task_id), None)
        if not task:
            return

        # Обновляем статус
        task.progress = progress

        # Конвертируем строковый статус в enum
        status_map = {
            "extracting": FileStatus.EXTRACTING,
            "transcribing": FileStatus.TRANSCRIBING,
            "summarizing": FileStatus.SUMMARIZING,
            "generating": FileStatus.GENERATING,
        }
        if status in status_map:
            task.status = status_map[status]

        # Обновляем виджет
        if task_id in self._file_queue_widgets:
            self._file_queue_widgets[task_id].update_status()

    def _on_file_task_completed(self, task_id: str, success: bool, output_path: str, error: str) -> None:
        """Обработчик завершения обработки файла."""
        from ...file_transcriber import FileStatus

        # Находим задачу
        task = next((t for t in self._file_tasks if t.id == task_id), None)
        if not task:
            return

        if success:
            task.status = FileStatus.COMPLETED
            task.output_path = Path(output_path) if output_path else None
            task.progress = 100
            self._last_completed_task = task
        else:
            task.status = FileStatus.ERROR
            task.error_message = error

        # Обновляем виджет
        if task_id in self._file_queue_widgets:
            self._file_queue_widgets[task_id].update_status()

    def _on_all_files_completed(self) -> None:
        """Обработчик завершения обработки всех файлов."""
        from PyQt6.QtWidgets import QMessageBox
        from ...file_transcriber import FileStatus

        # Обновляем UI кнопок
        self._rebuild_file_queue_ui()

        # Показываем уведомление
        completed = [t for t in self._file_tasks if t.status == FileStatus.COMPLETED]
        failed = [t for t in self._file_tasks if t.status == FileStatus.ERROR]

        msg = f"{self._t('processing_complete')}\n\n"
        msg += f"{self._t('completed')}: {len(completed)}\n"
        if failed:
            msg += f"{self._t('failed')}: {len(failed)}"

        QMessageBox.information(self, self._t("processing_complete"), msg)

        # Открываем папку с результатами если есть успешные
        if completed and self._output_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))

    def _rebuild_file_queue_ui(self) -> None:
        """Перестроить UI очереди файлов."""
        from ..file_widgets import FileQueueItemWidget

        # Очищаем существующие виджеты
        while self._file_queue_layout.count() > 1:
            item = self._file_queue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._file_queue_widgets = {}

        # Добавляем виджеты для каждой задачи
        for task in self._file_tasks:
            widget = FileQueueItemWidget(task, translate_func=self._t)
            widget.remove_clicked.connect(self._on_remove_task)
            widget.open_clicked.connect(self._on_open_task_folder)
            self._file_queue_layout.insertWidget(self._file_queue_layout.count() - 1, widget)
            self._file_queue_widgets[task.id] = widget

        # Обновляем состояние кнопок
        from ...file_transcriber import FileStatus
        has_pending = any(t.status == FileStatus.PENDING for t in self._file_tasks)
        self.start_processing_btn.setEnabled(has_pending)
        self.clear_queue_btn.setEnabled(len(self._file_tasks) > 0)

    # Абстрактные методы, которые должны быть реализованы в MainWindow
    def _t(self, key: str) -> str:
        """Получить перевод строки."""
        raise NotImplementedError
