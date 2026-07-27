from pathlib import Path

from PyQt6.QtWidgets import QApplication

from app.ui.dialogs import CrashReportDialog


def test_crash_report_send_requires_explicit_opt_in(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    dialog = CrashReportDialog("traceback", tmp_path / "crash.txt")
    try:
        assert dialog.send_checkbox.isChecked() is False
    finally:
        dialog.close()
        app.processEvents()
