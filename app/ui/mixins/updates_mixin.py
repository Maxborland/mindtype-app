"""
Миксин для управления обновлениями в MainWindow.

Содержит методы:
- _check_for_updates: проверка наличия обновлений
- _download_update: скачивание обновления
- _on_update_check_finished: обработчик завершения проверки
- _on_update_download_progress: прогресс скачивания
- _on_update_download_finished: завершение скачивания
"""

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMessageBox

if TYPE_CHECKING:
    from ..workers import UpdateCheckWorker, UpdateDownloadWorker
    from ...updater import Updater, UpdateInfo


class UpdatesMixin:
    """Миксин для функциональности обновлений."""

    # Атрибуты, которые должны быть определены в MainWindow
    updater: "Updater"
    check_update_btn: object
    update_status_label: object
    update_progress: object
    _update_check_worker: "UpdateCheckWorker"
    _update_download_worker: "UpdateDownloadWorker"

    def _check_for_updates(self) -> None:
        """Проверить наличие обновлений."""
        from ..workers import UpdateCheckWorker

        if self._update_check_worker and self._update_check_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("checking_updates"))
        self.update_status_label.setVisible(False)

        self._update_check_worker = UpdateCheckWorker(self.updater)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_check_worker.start()

        self._add_journal_entry("pending", "checking_updates", is_translatable=True)

    def _on_update_check_finished(self, info: "UpdateInfo") -> None:
        """Обработчик завершения проверки обновлений."""
        self.check_update_btn.setEnabled(True)
        self.check_update_btn.setText(self._t("check_updates"))

        if info.error:
            self.update_status_label.setText(self._t("network_error"))
            self.update_status_label.setStyleSheet("font-size: 11px; color: #cc0000;")
            self.update_status_label.setVisible(True)
            self._add_journal_entry("error", "update_error", text=info.error, is_translatable=True)
            return

        if info.available:
            self.update_status_label.setText(
                f"{self._t('update_available')}: v{info.version}"
            )
            self.update_status_label.setStyleSheet("font-size: 11px; color: #006600; font-weight: bold;")
            self.update_status_label.setVisible(True)

            # Показываем кнопку обновления
            self.check_update_btn.setText(self._t("update_now"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._download_update)

            self._add_journal_entry("success", "update_available",
                                   extra_key=f"v{info.version}", is_translatable=True)

            # Показываем диалог с информацией
            if info.release_notes:
                QMessageBox.information(
                    self,
                    self._t("update_available"),
                    f"{self._t('update_version').replace('{version}', info.version)}\n\n"
                    f"{info.release_notes}"
                )
        else:
            self.update_status_label.setText(self._t("no_updates"))
            self.update_status_label.setStyleSheet("font-size: 11px;")
            self.update_status_label.setVisible(True)
            self._add_journal_entry("success", "no_updates", is_translatable=True)

    def _download_update(self) -> None:
        """Скачать обновление."""
        from ..workers import UpdateDownloadWorker

        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self.check_update_btn.setEnabled(False)
        self.check_update_btn.setText(self._t("downloading_update"))
        self.update_progress.setValue(0)
        self.update_progress.setVisible(True)

        self._update_download_worker = UpdateDownloadWorker(self.updater)
        self._update_download_worker.progress.connect(self._on_update_download_progress)
        self._update_download_worker.finished.connect(self._on_update_download_finished)
        self._update_download_worker.start()

        self._add_journal_entry("pending", "downloading_update", is_translatable=True)

    def _on_update_download_progress(self, downloaded: int, total: int) -> None:
        """Обработчик прогресса скачивания."""
        if total > 0:
            percent = int(downloaded * 100 / total)
            self.update_progress.setValue(percent)

            # Показываем размер
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.update_status_label.setText(
                f"{self._t('downloading_update')} {downloaded_mb:.1f} / {total_mb:.1f} MB"
            )

    def _on_update_download_finished(self, success: bool, path: str, error: str) -> None:
        """Обработчик завершения скачивания."""
        self.update_progress.setVisible(False)
        self.check_update_btn.setEnabled(True)

        if success:
            self.update_status_label.setText(self._t("update_ready"))
            self.update_status_label.setStyleSheet("font-size: 11px; color: #006600; font-weight: bold;")
            self.check_update_btn.setText(self._t("update_now"))

            # Предлагаем установить
            reply = QMessageBox.question(
                self,
                self._t("update_ready"),
                self._t("update_ready") + "\n\n" +
                "Приложение будет закрыто для установки обновления.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._add_journal_entry("success", "update_ready", is_translatable=True)
                self.updater.install_update()
        else:
            self.update_status_label.setText(f"{self._t('update_error')}: {error}")
            self.update_status_label.setStyleSheet("font-size: 11px; color: #cc0000;")
            self.check_update_btn.setText(self._t("check_updates"))
            self.check_update_btn.clicked.disconnect()
            self.check_update_btn.clicked.connect(self._check_for_updates)
            self._add_journal_entry("error", "update_error", text=error, is_translatable=True)

    # Абстрактные методы, которые должны быть реализованы в MainWindow
    def _t(self, key: str) -> str:
        """Получить перевод строки."""
        raise NotImplementedError

    def _add_journal_entry(self, status: str, title_key: str, text: str = "", extra_key: str = "", is_translatable: bool = True) -> None:
        """Добавить запись в журнал."""
        raise NotImplementedError
