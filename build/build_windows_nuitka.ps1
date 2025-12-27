# =============================================================================
# Windows build script using Nuitka
# Compiles Python to native code for reverse engineering protection
# =============================================================================
# Run: .\build\build_windows_nuitka.ps1
# With params: .\build\build_windows_nuitka.ps1 -Version "1.1.0" -Clean

param(
    [switch]$Clean,
    [switch]$NoInstaller,
    [switch]$Onefile,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$DistDir = Join-Path $RootDir "dist"
$BuildDir = Join-Path $RootDir "build_nuitka"

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
            Write-Warning "Could not read version from app/version.py: $_"
        }
    }
    return "1.0.0"
}

# If version not specified, read from app/env.py
if ([string]::IsNullOrEmpty($Version)) {
    $Version = Get-AppVersion
    Write-Host "Version read from app/env.py: $Version" -ForegroundColor Gray
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MindType - Windows Build (Nuitka)        " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Version: $Version"
Write-Host "Mode: $(if ($Onefile) { 'Single file (--onefile)' } else { 'Folder (--standalone)' })"
Write-Host ""

# Change to root directory
Set-Location $RootDir

# Activate venv if exists (check both .venv and venv)
$VenvPaths = @(
    (Join-Path $RootDir "venv\Scripts\Activate.ps1"),
    (Join-Path $RootDir ".venv\Scripts\Activate.ps1")
)
foreach ($VenvPath in $VenvPaths) {
    if (Test-Path $VenvPath) {
        Write-Host "Activating virtual environment: $VenvPath" -ForegroundColor Gray
        . $VenvPath
        break
    }
}

# Clean previous build
if ($Clean) {
    Write-Host "[1/5] Cleaning previous build..." -ForegroundColor Yellow
    if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }
    if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
    if (Test-Path "MindType.build") { Remove-Item -Recurse -Force "MindType.build" }
    if (Test-Path "MindType.dist") { Remove-Item -Recurse -Force "MindType.dist" }
    if (Test-Path "MindType.onefile-build") { Remove-Item -Recurse -Force "MindType.onefile-build" }
}

# Check dependencies
Write-Host "[2/5] Checking dependencies..." -ForegroundColor Yellow

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  - Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  - ERROR: Python not found!" -ForegroundColor Red
    Write-Host "    Install Python 3.8+ and add it to PATH" -ForegroundColor Yellow
    exit 1
}

# Check pip
try {
    $pipVersion = pip --version 2>&1
    Write-Host "  - pip: OK" -ForegroundColor Green
} catch {
    Write-Host "  - ERROR: pip not found!" -ForegroundColor Red
    exit 1
}

# Check Nuitka
try {
    $null = python -c "import nuitka" 2>&1
    $nuitkaVersion = python -c "import nuitka; print(nuitka.__version__)" 2>&1
    Write-Host "  - Nuitka: v$nuitkaVersion" -ForegroundColor Green
} catch {
    Write-Host "  - Nuitka not found. Installing..." -ForegroundColor Yellow
    try {
        pip install nuitka ordered-set zstandard
        if ($LASTEXITCODE -ne 0) {
            throw "Nuitka installation error"
        }
        Write-Host "  - Nuitka installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "  - ERROR: Could not install Nuitka!" -ForegroundColor Red
        Write-Host "    Try installing manually: pip install nuitka ordered-set zstandard" -ForegroundColor Yellow
        exit 1
    }
}

# Models will be downloaded by user on first run
Write-Host "  - Models: will be downloaded on first run" -ForegroundColor Gray

# Build Nuitka command
Write-Host ""
Write-Host "[3/5] Compiling with Nuitka..." -ForegroundColor Green
Write-Host "  This may take 10-30 minutes depending on your computer."
Write-Host ""

$NuitkaArgs = @(
    "-m"
    "nuitka"
    "--standalone"
    "--msvc=latest"
    "--windows-console-mode=disable"
    "--windows-icon-from-ico=assets/icons/app.ico"
    "--enable-plugin=pyqt6"
    "--include-package=app"
    "--include-data-dir=app/assets=app/assets"
    "--include-package=huggingface_hub"
    "--include-package=sklearn"
    "--include-package=librosa"
    "--include-package=soundfile"
    "--include-package=psutil"
    "--include-package=onnxruntime"
    "--include-module=sounddevice"
    "--include-module=numpy"
    "--include-module=ctypes"
    "--noinclude-pytest-mode=nofollow"
    "--noinclude-setuptools-mode=nofollow"
    "--noinclude-custom-mode=setuptools:nofollow"
    "--remove-output"
    "--assume-yes-for-downloads"
    "--output-dir=`"$DistDir`""
    "--output-filename=MindType.exe"
    "--company-name=MindType"
    "--product-name=MindType"
    "--file-version=$Version"
    "--product-version=$Version"
    "`"--file-description=MindType - Offline Voice Transcription`""
    "`"--copyright=Copyright 2024 MindType`""
    "--lto=yes"
)

# Add --onefile if flag is set
if ($Onefile) {
    $NuitkaArgs += "--onefile"
}

# Add main file
$NuitkaArgs += "main.py"

# Use python from venv if available
$PythonCmd = "python"
if (Test-Path "venv\Scripts\python.exe") {
    $PythonCmd = ".\venv\Scripts\python.exe"
} elseif (Test-Path ".venv\Scripts\python.exe") {
    $PythonCmd = ".\.venv\Scripts\python.exe"
}

# Run Nuitka
Write-Host "  Command: $PythonCmd $($NuitkaArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

# Build command as single string for proper execution
$NuitkaCmd = "$PythonCmd " + ($NuitkaArgs -join " ")

try {
    # Use Invoke-Expression for proper argument handling
    Invoke-Expression $NuitkaCmd

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERROR: Nuitka compilation failed!" -ForegroundColor Red
        Write-Host "Exit code: $LASTEXITCODE" -ForegroundColor Red
        Write-Host ""
        Write-Host "Possible causes:" -ForegroundColor Yellow
        Write-Host "  - Missing dependencies" -ForegroundColor Yellow
        Write-Host "  - Not enough disk space" -ForegroundColor Yellow
        Write-Host "  - C++ compiler issues" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Check logs above for details." -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host ""
    Write-Host "ERROR: Could not start Nuitka!" -ForegroundColor Red
    Write-Host "Details: $_" -ForegroundColor Red
    exit 1
}

# Check result
Write-Host ""
Write-Host "[4/5] Checking result..." -ForegroundColor Yellow

$ExePath = if ($Onefile) {
    Join-Path $DistDir "MindType.exe"
} else {
    Join-Path $DistDir "main.dist\MindType.exe"
}

# Rename folder if needed
if (-not $Onefile) {
    $OldDist = Join-Path $DistDir "main.dist"
    $NewDist = Join-Path $DistDir "MindType"
    if (Test-Path $OldDist) {
        if (Test-Path $NewDist) { Remove-Item -Recurse -Force $NewDist }
        Rename-Item $OldDist $NewDist
        $ExePath = Join-Path $NewDist "MindType.exe"
    }
}

if (Test-Path $ExePath) {
    Write-Host ""
    Write-Host "Build successful!" -ForegroundColor Green
    Write-Host "Executable: $ExePath"

    # Exe size
    $Size = (Get-Item $ExePath).Length / 1MB
    Write-Host "Exe size: $([math]::Round($Size, 2)) MB"

    if (-not $Onefile) {
        # Folder size
        $FolderPath = Split-Path $ExePath -Parent
        $FolderSize = (Get-ChildItem -Recurse $FolderPath | Measure-Object -Property Length -Sum).Sum / 1MB
        Write-Host "Folder size: $([math]::Round($FolderSize, 2)) MB"

        # Create empty models folder (models will be downloaded on first run)
        $DestModels = Join-Path $FolderPath "models"
        New-Item -ItemType Directory -Force -Path $DestModels | Out-Null
        Write-Host ""
        Write-Host "Models folder created (empty). User will download on first run." -ForegroundColor Gray
    }
} else {
    Write-Host ""
    Write-Host "ERROR: Executable not found!" -ForegroundColor Red
    Write-Host "Expected: $ExePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  - Compilation failed with error" -ForegroundColor Yellow
    Write-Host "  - Insufficient permissions to write to dist/" -ForegroundColor Yellow
    Write-Host "  - Antivirus blocked file creation" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Check compilation logs above." -ForegroundColor Yellow
    exit 1
}

# Create installer
if (-not $NoInstaller -and -not $Onefile) {
    Write-Host ""
    Write-Host "[5/5] Creating Inno Setup installer..." -ForegroundColor Green

    $InnoSetup = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $InnoSetup)) {
        $InnoSetup = "C:\Program Files\Inno Setup 6\ISCC.exe"
    }

    if (Test-Path $InnoSetup) {
        $IssFile = Join-Path $ScriptDir "installer\windows.iss"
        if (Test-Path $IssFile) {
            & $InnoSetup "/DAppVersion=$Version" "/DAppName=MindType" $IssFile
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Installer created successfully!" -ForegroundColor Green
            } else {
                Write-Host "Installer creation error" -ForegroundColor Red
            }
        } else {
            Write-Host "windows.iss file not found: $IssFile" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Inno Setup not found. Skipping installer creation." -ForegroundColor Yellow
        Write-Host "Install Inno Setup: https://jrsoftware.org/isinfo.php"
    }
} else {
    Write-Host ""
    Write-Host "[5/5] Skipping installer creation" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "              Done!                        " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Application compiled to native code."
Write-Host "Source Python code is protected from decompilation."
Write-Host ""
