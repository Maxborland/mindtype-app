# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir build for the current MindType desktop application."""

from pathlib import Path

from comtypes.client import GetModule
from PyInstaller.utils.hooks import collect_data_files


ROOT = Path(SPECPATH)

datas = []
for source, destination in [
    (ROOT / "app" / "ui" / "fonts", "app/ui/fonts"),
    (ROOT / "assets", "assets"),
]:
    if source.exists():
        datas.append((str(source), destination))

for filename in [
    "whisper-cli.exe",
    "whisper-server.exe",
    "whisper.dll",
    "ggml-base.dll",
    "ggml-cpu.dll",
    "ggml-vulkan.dll",
    "ggml.dll",
]:
    source = ROOT / "bin" / "win-x64" / filename
    if source.exists():
        datas.append((str(source), "bin/win-x64"))

datas += collect_data_files("certifi")

# Generate UI Automation type-library wrappers while the build environment is
# writable, then include them in the frozen application.
GetModule("UIAutomationCore.dll")

hiddenimports = [
    "app.llm.anthropic",
    "app.llm.gemini",
    "app.llm.mindtype_cloud",
    "app.llm.ollama",
    "app.llm.openai",
    "app.llm.openrouter",
    "app.providers.mindtype_cloud",
    "app.platform.windows",
    "keyboard",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "sounddevice",
    "webrtcvad",
    "_webrtcvad",
    "PyQt6.QtPdf",
    "PyQt6.QtSvg",
    "comtypes.gen.UIAutomationClient",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",
        # Optional local ML and assistant packs are deliberately not part of
        # the laptop-friendly base installer.
        "torch",
        "transformers",
        "optimum",
        "onnxruntime",
        "openwakeword",
        "edge_tts",
        "pydub",
        "librosa",
        "sklearn",
        "scipy",
        "numba",
        "llvmlite",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MindType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icons" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MindType",
)
