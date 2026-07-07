# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


ROOT_DIR = Path(SPECPATH)
APP_NAME = "MindType"

is_windows = sys.platform == "win32"
is_macos = sys.platform == "darwin"

if is_windows:
    icon_file = ROOT_DIR / "assets" / "icons" / "app.ico"
elif is_macos:
    icon_file = ROOT_DIR / "assets" / "icons" / "app.icns"
else:
    icon_file = ROOT_DIR / "assets" / "icons" / "app.png"

datas = [
    (str(ROOT_DIR / "app" / "assets"), "app/assets"),
    (str(ROOT_DIR / "app" / "ui" / "fonts"), "app/ui/fonts"),
    (str(ROOT_DIR / "app" / "ui" / "icons"), "app/ui/icons"),
    (str(ROOT_DIR / "assets"), "assets"),
    (str(ROOT_DIR / "bin"), "bin"),
    (str(ROOT_DIR / "models"), "models"),
]

hiddenimports = [
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtPrintSupport",
    "sounddevice",
    "numpy",
    "pyperclip",
    "pynput",
    "pynput.keyboard",
    "keyring",
    "psutil",
    "dotenv",
    "sklearn",
    "librosa",
    "soundfile",
    "onnxruntime",
    "transformers",
    "huggingface_hub",
    "openwakeword",
    "edge_tts",
    "pydub",
    "num2words",
    "dateparser",
    "transliterate",
]

if is_windows:
    hiddenimports.extend([
        "keyboard",
        "ctypes",
        "ctypes.wintypes",
        "pynput.keyboard._win32",
    ])
elif is_macos:
    hiddenimports.extend([
        "AppKit",
        "Quartz",
        "objc",
        "pynput.keyboard._darwin",
    ])
else:
    hiddenimports.append("pynput.keyboard._xorg")

excludes = [
    "matplotlib",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
]

a = Analysis(
    [str(ROOT_DIR / "main.py")],
    pathex=[str(ROOT_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT_DIR / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
