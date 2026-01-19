# =============================================================================
# Windows build script with PyArmor obfuscation + PyInstaller
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
$ObfuscatedDir = Join-Path $RootDir "dist_obfuscated"
$BuildDir = Join-Path $RootDir "build_pyarmor"

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
Write-Host "  MindType Windows Build (PyArmor)" -ForegroundColor Cyan
Write-Host "  Version: $Version" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Clean if requested
if ($Clean) {
    Write-Host "[1/6] Cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $ObfuscatedDir) { Remove-Item -Recurse -Force $ObfuscatedDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    if (Test-Path "*.spec") { Remove-Item -Force "*.spec" }
} else {
    Write-Host "[1/6] Skipping clean (use -Clean to clean)" -ForegroundColor Gray
}

# Check PyArmor
Write-Host "[2/6] Checking PyArmor..." -ForegroundColor Yellow
try {
    $pyarmorVersion = & pyarmor --version 2>&1
    Write-Host "  PyArmor: $pyarmorVersion" -ForegroundColor Green
} catch {
    Write-Host "  PyArmor not found. Installing..." -ForegroundColor Yellow
    pip install pyarmor
}

# Check PyInstaller
Write-Host "[3/6] Checking PyInstaller..." -ForegroundColor Yellow
try {
    $pyinstallerVersion = & pyinstaller --version 2>&1
    Write-Host "  PyInstaller: $pyinstallerVersion" -ForegroundColor Green
} catch {
    Write-Host "  PyInstaller not found. Installing..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Obfuscate with PyArmor
Write-Host "[4/6] Obfuscating with PyArmor..." -ForegroundColor Yellow
Write-Host "  This may take a few minutes..." -ForegroundColor Gray

# Create obfuscated directory
if (Test-Path $ObfuscatedDir) { Remove-Item -Recurse -Force $ObfuscatedDir }
New-Item -ItemType Directory -Force -Path $ObfuscatedDir | Out-Null

# Copy non-Python files first
Write-Host "  Copying assets..." -ForegroundColor Gray
Copy-Item -Path "app" -Destination $ObfuscatedDir -Recurse -Force
Copy-Item -Path "main.py" -Destination $ObfuscatedDir -Force

# Obfuscate Python files
Write-Host "  Obfuscating Python code..." -ForegroundColor Gray
Push-Location $ObfuscatedDir
try {
    # Obfuscate main.py and app/ directory
    & pyarmor gen --output . main.py
    & pyarmor gen --output ./app --recursive ./app

    if ($LASTEXITCODE -ne 0) {
        throw "PyArmor obfuscation failed"
    }
} finally {
    Pop-Location
}

Write-Host "  Obfuscation complete!" -ForegroundColor Green

# Build with PyInstaller
Write-Host "[5/6] Building with PyInstaller..." -ForegroundColor Yellow

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
    "--collect-all=pyarmor_runtime",
    "--noconfirm",
    "--clean",
    "$ObfuscatedDir\main.py"
)

& pyinstaller @PyInstallerArgs

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

Write-Host "  Build complete!" -ForegroundColor Green

# Create installer with Inno Setup (if available)
if (-not $NoInstaller) {
    Write-Host "[6/6] Creating installer..." -ForegroundColor Yellow

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
    Write-Host "[6/6] Skipping installer (use without -NoInstaller to create)" -ForegroundColor Gray
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
