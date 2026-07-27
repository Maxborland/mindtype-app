# =============================================================================
# Windows build script with PyInstaller
# =============================================================================
# Run: .\build_windows.ps1
# With params: .\build_windows.ps1 -Version "0.9.2" -Clean

param(
    [switch]$Clean,
    [switch]$NoInstaller,
    [string]$Version = "",
    [string]$PythonExe = "python"
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
    return "0.9.3"
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
} else {
    Write-Host "[1/4] Skipping clean (use -Clean to clean)" -ForegroundColor Gray
}

# Verify the release interpreter and synchronize deterministic build inputs.
Write-Host "[2/4] Preparing hashed Python 3.11 build environment..." -ForegroundColor Yellow
$BuildPythonVersion = & $PythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
if ($LASTEXITCODE -ne 0 -or $BuildPythonVersion.Trim() -ne "3.11") {
    throw "Windows release builds require Python 3.11; got '$BuildPythonVersion'"
}
$IsVirtualEnvironment = & $PythonExe -c "import sys; print('1' if sys.prefix != sys.base_prefix else '0')"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the Python 3.11 build environment"
}
$BuildPythonExe = $PythonExe
if ($IsVirtualEnvironment.Trim() -ne "1") {
    $BuildVenv = Join-Path $RootDir ".venv-build"
    $BuildVenvPython = Join-Path $BuildVenv "Scripts\python.exe"
    if (-not (Test-Path $BuildVenvPython)) {
        & $PythonExe -m venv $BuildVenv
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create isolated Windows build environment"
        }
    }
    $BuildPythonExe = $BuildVenvPython
}
$BaseLock = Join-Path $RootDir "requirements\base.lock"
$DevLock = Join-Path $RootDir "requirements\dev.lock"
foreach ($LockFile in @($BaseLock, $DevLock)) {
    if (-not (Test-Path $LockFile)) {
        throw "Hashed dependency lock not found: $LockFile"
    }
}
& $BuildPythonExe -m pip install --require-hashes -r $BaseLock -r $DevLock
if ($LASTEXITCODE -ne 0) {
    throw "Could not install hashed Windows build dependencies"
}
$pyinstallerVersion = & $BuildPythonExe -m PyInstaller --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is unavailable after installing hashed build dependencies"
}
Write-Host "  PyInstaller: $pyinstallerVersion" -ForegroundColor Green

# Build with PyInstaller using spec file
Write-Host "[3/4] Building with PyInstaller (using mindtype.spec)..." -ForegroundColor Yellow

$SpecFile = Join-Path $RootDir "mindtype.spec"
if (-not (Test-Path $SpecFile)) {
    throw "Spec file not found: $SpecFile"
}

& $BuildPythonExe -m PyInstaller $SpecFile --noconfirm --clean

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
