# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec файл для Offline Whisper.
Кросс-платформенная сборка для Windows, macOS и Linux.
"""

import sys
import os
from pathlib import Path

# Определяем платформу
is_windows = sys.platform == 'win32'
is_macos = sys.platform == 'darwin'
is_linux = sys.platform.startswith('linux')

# Пути
ROOT_DIR = Path(SPECPATH).parent
APP_DIR = ROOT_DIR / 'app'
MODELS_DIR = ROOT_DIR / 'models'
ASSETS_DIR = ROOT_DIR / 'assets'

# Имя приложения
APP_NAME = 'OfflineWhisper'

# Определяем иконку
if is_windows:
    ICON_FILE = str(ASSETS_DIR / 'icons' / 'app.ico')
elif is_macos:
    ICON_FILE = str(ASSETS_DIR / 'icons' / 'app.icns')
else:
    ICON_FILE = str(ASSETS_DIR / 'icons' / 'app.png')

# Проверяем существование иконки
if not os.path.exists(ICON_FILE):
    ICON_FILE = None

# Собираем данные для включения
datas = [
    # Включаем модель tiny (базовая)
    (str(MODELS_DIR / 'tiny'), 'models/tiny'),
]

# Скрытые импорты для faster-whisper и других библиотек
hiddenimports = [
    'faster_whisper',
    'ctranslate2',
    'huggingface_hub',
    'tokenizers',
    'sounddevice',
    'numpy',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'pyperclip',
    'pynput',
    'pynput.keyboard',
    'pynput.keyboard._win32' if is_windows else 'pynput.keyboard._darwin' if is_macos else 'pynput.keyboard._xorg',
]

# Платформо-специфичные импорты
if is_windows:
    hiddenimports.extend([
        'keyboard',
        'ctypes',
        'ctypes.wintypes',
    ])
elif is_macos:
    hiddenimports.extend([
        'AppKit',
        'Quartz',
        'objc',
    ])

# Исключаем ненужные модули для уменьшения размера
excludes = [
    'tkinter',
    'matplotlib',
    'scipy',
    'pandas',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'wheel',
    'pkg_resources',  # Полностью исключаем
]

# Бинарные файлы для ctranslate2/faster-whisper
binaries = []

# Анализ
a = Analysis(
    [str(ROOT_DIR / 'main.py')],
    pathex=[str(ROOT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT_DIR / 'build' / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],  # Убрали runtime hook
    excludes=excludes,
    noarchive=False,
)

# Удаляем runtime hook pkg_resources если он был добавлен автоматически
# PyInstaller 6+ добавляет pyi_rth_pkgres автоматически
new_scripts = []
for script in a.scripts:
    if 'pyi_rth_pkgres' not in script[0] and 'pyi_rth_pkgutil' not in script[0]:
        new_scripts.append(script)
a.scripts = new_scripts

# Удаляем дубликаты
pyz = PYZ(a.pure, a.zipped_data)

# Исполняемый файл
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
    console=False,  # GUI приложение
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
)

# Сборка в папку
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)

# macOS .app bundle
if is_macos:
    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon=ICON_FILE,
        bundle_identifier='com.offlinewhisper.app',
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': 'Offline Whisper',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'NSMicrophoneUsageDescription': 'Offline Whisper needs microphone access for speech-to-text.',
            'LSMinimumSystemVersion': '10.15',
        },
    )
