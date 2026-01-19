# =============================================================================
# Windows build script with PyInstaller
# =============================================================================
# Run: .\build_windows.ps1
# With params: .\build_windows.ps1 -Version "0.9.1" -Clean

param(
    [switch]$Clean,
    [switch]$NoInstaller,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = $ScriptDir
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build"

# Function to read version from app/version.py
function Get-AppVersion {
    $VersionFile = Join-Path $RootDir "app\version.py"
    if (Test-Path $VersionFile) {
        try {
            $content = Get-Content $VersionFile -Raw
            if ($content -match '__version__\s*=\s*"([^"]+)"') {
                return $matches[1]
            }
        } catch {
            Write-Host "Warning: Could not read version from app/version.py" -ForegroundColor Yellow
        }
    }
    return "0.9.1"
}

if ([string]::IsNullOrEmpty($Version)) {
    $Version = Get-AppVersion
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MindType Windows Build" -ForegroundColor Cyan
Write-Host "  Version: $Version" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Clean if requested
if ($Clean) {
    Write-Host "[1/4] Cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    if (Test-Path "*.spec") { Remove-Item -Force "*.spec" }
} else {
    Write-Host "[1/4] Skipping clean (use -Clean to clean)" -ForegroundColor Gray
}

# Check PyInstaller
Write-Host "[2/4] Checking PyInstaller..." -ForegroundColor Yellow
try {
    $pyinstallerVersion = & pyinstaller --version 2>&1
    Write-Host "  PyInstaller: $pyinstallerVersion" -ForegroundColor Green
} catch {
    Write-Host "  PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Build with PyInstaller
Write-Host "[3/4] Building with PyInstaller..." -ForegroundColor Yellow

$PyInstallerArgs = @(
    "--name=MindType",
    "--windowed",
    "--icon=assets/icons/app.ico",
    "--add-data=assets;assets",
    "--add-data=bin;bin",
    "--add-data=models;models",
    "--add-data=app/assets;app/assets",
    "--hidden-import=PyQt6",
    "--hidden-import=PyQt6.QtCore",
    "--hidden-import=PyQt6.QtGui",
    "--hidden-import=PyQt6.QtWidgets",
    "--hidden-import=sounddevice",
    "--hidden-import=numpy",
    "--hidden-import=scipy",
    "--hidden-import=keyring",
    "--hidden-import=keyring.backends",
    "--hidden-import=keyring.backends.Windows",
    "--noconfirm",
    "--clean",
    "main.py"
)

& pyinstaller @PyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

Write-Host "  Build complete!" -ForegroundColor Green

# Create installer with Inno Setup (if available)
if (-not $NoInstaller) {
    Write-Host "[4/4] Creating installer..." -ForegroundColor Yellow

    $InnoSetup = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    $IssFile = Join-Path $RootDir "installer\windows.iss"

    if ((Test-Path $InnoSetup) -and (Test-Path $IssFile)) {
        & $InnoSetup "/DAppVersion=$Version" $IssFile

        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Installer created!" -ForegroundColor Green
        } else {
            Write-Host "  Installer creation failed" -ForegroundColor Red
        }
    } else {
        Write-Host "  Inno Setup not found, skipping installer" -ForegroundColor Yellow
    }
} else {
    Write-Host "[4/4] Skipping installer (use without -NoInstaller to create)" -ForegroundColor Gray
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Output:" -ForegroundColor White
Write-Host "  Executable: $DistDir\MindType\MindType.exe" -ForegroundColor Gray
if (Test-Path "$DistDir\MindType-$Version-Setup.exe") {
    Write-Host "  Installer:  $DistDir\MindType-$Version-Setup.exe" -ForegroundColor Gray
}
Write-Host ""
