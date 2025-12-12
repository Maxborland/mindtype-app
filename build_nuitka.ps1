# MindType Nuitka Build Script
# Запуск: .\build_nuitka.ps1
# С очисткой: .\build_nuitka.ps1 -Clean

param(
    [switch]$Clean,
    [switch]$Debug,
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MindType Nuitka Build" -ForegroundColor Cyan
Write-Host "  Version: $Version" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Переходим в директорию приложения
Set-Location $ScriptDir
Write-Host "[1/4] Working directory: $ScriptDir" -ForegroundColor Yellow

# Очистка если нужно
if ($Clean) {
    Write-Host "[2/4] Cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path "dist") {
        Remove-Item -Recurse -Force "dist"
    }
    if (Test-Path "main.build") {
        Remove-Item -Recurse -Force "main.build"
    }
} else {
    Write-Host "[2/4] Skipping clean (use -Clean to clean)" -ForegroundColor Gray
}

# Активируем venv
Write-Host "[3/4] Activating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv\Scripts\Activate.ps1") {
    . .\venv\Scripts\Activate.ps1
} else {
    Write-Host "ERROR: venv not found! Create it first: python -m venv venv" -ForegroundColor Red
    exit 1
}

# Проверяем зависимости
$required = @("nuitka", "pyqt6", "faster_whisper", "huggingface_hub", "sounddevice", "numpy", "pyperclip")
foreach ($pkg in $required) {
    $check = pip show $pkg 2>$null
    if (-not $check) {
        Write-Host "Installing missing package: $pkg" -ForegroundColor Yellow
        pip install $pkg
    }
}

# Собираем аргументы Nuitka
Write-Host "[4/4] Starting Nuitka compilation..." -ForegroundColor Yellow
Write-Host "This may take 10-20 minutes..." -ForegroundColor Gray
Write-Host ""

$NuitkaArgs = @(
    "--standalone"
    "--msvc=latest"
    "--windows-icon-from-ico=assets/icons/app.ico"
    "--enable-plugin=pyqt6"
    "--include-package=app"
    "--include-package=faster_whisper"
    "--include-package=huggingface_hub"
    "--include-module=sounddevice"
    "--include-module=numpy"
    "--include-module=pyperclip"
    "--include-module=webbrowser"
    "--include-module=ctranslate2"
    "--noinclude-pytest-mode=nofollow"
    "--noinclude-setuptools-mode=nofollow"
    "--remove-output"
    "--assume-yes-for-downloads"
    "--output-dir=dist"
    "--output-filename=MindType.exe"
    "--company-name=MindType"
    "--product-name=MindType"
    "--file-version=$Version"
    "--product-version=$Version"
    "--lto=yes"
)

# Ensure Silero VAD ONNX is bundled (required when vad_filter=True)
$VadOnnx = Join-Path $ScriptDir "venv\Lib\site-packages\faster_whisper\assets\silero_vad_v6.onnx"
if (-not (Test-Path $VadOnnx)) {
    Write-Host "ERROR: VAD ONNX not found: $VadOnnx" -ForegroundColor Red
    Write-Host "Make sure dependencies are installed in venv (venv\\Lib\\site-packages\\faster_whisper\\assets\\silero_vad_v6.onnx)." -ForegroundColor Yellow
    exit 1
}
$NuitkaArgs += "--include-data-files=$VadOnnx=faster_whisper/assets/silero_vad_v6.onnx"

# Debug или Release режим
if ($Debug) {
    Write-Host "Building in DEBUG mode (with console)" -ForegroundColor Yellow
} else {
    $NuitkaArgs += "--windows-console-mode=disable"
}

$NuitkaArgs += "main.py"

# Запуск Nuitka
python -m nuitka @NuitkaArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host "  Output: dist\main.dist\MindType.exe" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green

    # Показываем размер
    $exePath = "dist\main.dist\MindType.exe"
    if (Test-Path $exePath) {
        $size = (Get-Item $exePath).Length / 1MB
        Write-Host "  Size: $([math]::Round($size, 2)) MB" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  BUILD FAILED!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    exit 1
}


