import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.transcription_models import FileStatus, FileTask


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_completed_task_shows_non_blocking_warning(qapp):
    from app.ui.file_widgets import FileQueueItemWidget

    task = FileTask(
        file_path=Path("meeting.mp4"),
        status=FileStatus.COMPLETED,
        progress=100,
        warning="Не удалось сохранить в библиотеку",
    )

    widget = FileQueueItemWidget(task, translate_func=lambda key: key)
    widget.show()
    qapp.processEvents()

    assert "status_completed" in widget._status_label.text()
    assert task.warning in widget._status_label.text()

    widget.close()
