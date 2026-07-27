"""Behavior contract for the source and frozen application smoke mode."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_smoke_mode_exits_without_creating_user_state(tmp_path):
    environment = os.environ.copy()
    environment["APPDATA"] = str(tmp_path / "appdata")
    environment["QT_QPA_PLATFORM"] = "offscreen"

    process = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--smoke-test"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert not (Path(environment["APPDATA"]) / "MindType").exists()
