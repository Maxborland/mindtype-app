# Скрипт сборки для Windows
# Запуск: .\build\build_windows.ps1

param(
    [switch]$Clean,
    [switch]$NoInstaller,
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build_temp"

Write-Host "=== Сборка Offline Whisper для Windows ===" -ForegroundColor Cyan
Write-Host "Версия: $Version"
Write-Host ""

# Переходим в корневую директорию
Set-Location $RootDir

# Очистка предыдущей сборки
if ($Clean) {
    Write-Host "Очистка предыдущей сборки..." -ForegroundColor Yellow
    if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
}

# Проверяем наличие PyInstaller
Write-Host "Проверка зависимостей..." -ForegroundColor Yellow
try {
    python -c "import PyInstaller" 2>$null
} catch {
    Write-Host "PyInstaller не найден. Устанавливаем..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Проверяем наличие модели tiny
$TinyModelDir = Join-Path $RootDir "models\tiny"
if (-not (Test-Path $TinyModelDir)) {
    Write-Host "ВНИМАНИЕ: Модель tiny не найдена в $TinyModelDir" -ForegroundColor Red
    Write-Host "Сборка будет без встроенной модели." -ForegroundColor Yellow
}

# Запускаем PyInstaller
Write-Host ""
Write-Host "Запуск PyInstaller..." -ForegroundColor Green
$SpecFile = Join-Path $ScriptDir "offline_whisper.spec"

pyinstaller --clean --noconfirm $SpecFile

if ($LASTEXITCODE -ne 0) {
    Write-Host "Ошибка сборки PyInstaller!" -ForegroundColor Red
    exit 1
}

# Проверяем результат
$ExePath = Join-Path $DistDir "OfflineWhisper\OfflineWhisper.exe"
if (Test-Path $ExePath) {
    Write-Host ""
    Write-Host "Сборка успешна!" -ForegroundColor Green
    Write-Host "Исполняемый файл: $ExePath"

    # Размер
    $Size = (Get-Item $ExePath).Length / 1MB
    Write-Host "Размер exe: $([math]::Round($Size, 2)) MB"

    # Размер папки
    $FolderSize = (Get-ChildItem -Recurse (Join-Path $DistDir "OfflineWhisper") | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "Размер папки: $([math]::Round($FolderSize, 2)) MB"
} else {
    Write-Host "Ошибка: исполняемый файл не найден!" -ForegroundColor Red
    exit 1
}

# Создание установщика
if (-not $NoInstaller) {
    Write-Host ""
    Write-Host "Создание установщика Inno Setup..." -ForegroundColor Green

    $InnoSetup = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $InnoSetup)) {
        $InnoSetup = "C:\Program Files\Inno Setup 6\ISCC.exe"
    }

    if (Test-Path $InnoSetup) {
        $IssFile = Join-Path $ScriptDir "installer\windows.iss"
        if (Test-Path $IssFile) {
            & $InnoSetup "/DAppVersion=$Version" $IssFile
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Установщик создан успешно!" -ForegroundColor Green
            } else {
                Write-Host "Ошибка создания установщика" -ForegroundColor Red
            }
        } else {
            Write-Host "Файл windows.iss не найден: $IssFile" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Inno Setup не найден. Пропускаем создание установщика." -ForegroundColor Yellow
        Write-Host "Установите Inno Setup: https://jrsoftware.org/isinfo.php"
    }
}

Write-Host ""
Write-Host "=== Готово ===" -ForegroundColor Cyan







