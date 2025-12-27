# =============================================================================
# Main build script for all platforms
# Automates MindType build for Windows, Linux and macOS
# =============================================================================
# Run: .\build\build_all.ps1
# With params: .\build\build_all.ps1 -Platform all -Clean -Version "1.1.0"

param(
    [ValidateSet('windows','linux','macos','all')]
    [string]$Platform = 'windows',
    [switch]$Clean,
    [string]$Version = "",
    [switch]$NoInstaller,
    [switch]$Onefile
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

# Function to read version from app/env.py
function Get-AppVersion {
    $EnvFile = Join-Path $RootDir "app\env.py"
    if (Test-Path $EnvFile) {
        try {
            $content = Get-Content $EnvFile -Raw
            if ($content -match 'APP_VERSION:\s*str\s*=\s*"([^"]+)"') {
                return $matches[1]
            }
        } catch {
            Write-Warning "Could not read version from app/env.py: $_"
        }
    }
    return "1.0.0"
}

# If version not specified, read from app/env.py
if ([string]::IsNullOrEmpty($Version)) {
    $Version = Get-AppVersion
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  MindType - Universal Build Script        " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Version: $Version"
Write-Host "Platform: $Platform"
Write-Host "Clean: $(if ($Clean) { 'Yes' } else { 'No' })"
Write-Host ""

# Build results
$BuildResults = @()

# Function to build Windows
function Build-Windows {
    Write-Host "=== Building for Windows ===" -ForegroundColor Green
    Write-Host ""

    $BuildScript = Join-Path $ScriptDir "build_windows_nuitka.ps1"
    if (-not (Test-Path $BuildScript)) {
        Write-Host "ERROR: Windows build script not found: $BuildScript" -ForegroundColor Red
        return $false
    }

    try {
        $params = @{
            Version = $Version
        }
        if ($Clean) { $params.Clean = $true }
        if ($NoInstaller) { $params.NoInstaller = $true }
        if ($Onefile) { $params.Onefile = $true }

        & $BuildScript @params
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "[OK] Windows build completed successfully" -ForegroundColor Green
            return $true
        } else {
            Write-Host ""
            Write-Host "[ERROR] Windows build failed" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host ""
        Write-Host "[ERROR] Windows build error: $_" -ForegroundColor Red
        return $false
    }
}

# Function to build Linux (via WSL or Docker)
function Build-Linux {
    Write-Host "=== Building for Linux ===" -ForegroundColor Green
    Write-Host ""

    # Check for WSL
    if (Get-Command wsl -ErrorAction SilentlyContinue) {
        Write-Host "WSL detected, starting build via WSL..." -ForegroundColor Yellow
        Write-Host ""

        $wslPath = $RootDir.Replace("\", "/").Replace(":", "").ToLower()
        $BuildScript = "/mnt/$wslPath/build/build_linux.sh"
        $buildArgs = @()
        if ($Clean) { $buildArgs += "--clean" }
        $buildArgs += $Version

        try {
            wsl bash $BuildScript $buildArgs
            if ($LASTEXITCODE -eq 0) {
                Write-Host ""
                Write-Host "[OK] Linux build completed successfully" -ForegroundColor Green
                return $true
            } else {
                Write-Host ""
                Write-Host "[ERROR] Linux build failed" -ForegroundColor Red
                return $false
            }
        } catch {
            Write-Host ""
            Write-Host "[ERROR] Linux build error: $_" -ForegroundColor Red
            return $false
        }
    } else {
        Write-Host "WARNING: WSL not found. Linux build skipped." -ForegroundColor Yellow
        Write-Host "To build for Linux, install WSL or build on a Linux system." -ForegroundColor Yellow
        Write-Host ""
        return $false
    }
}

# Function to build macOS (via SSH or Docker)
function Build-macOS {
    Write-Host "=== Building for macOS ===" -ForegroundColor Green
    Write-Host ""

    Write-Host "WARNING: macOS build requires a Mac with Xcode installed." -ForegroundColor Yellow
    Write-Host "To build for macOS, run on Mac:" -ForegroundColor Yellow
    $cleanFlag = ""
    if ($Clean) { $cleanFlag = "--clean" }
    Write-Host "  ./build/build_macos.sh $Version $cleanFlag" -ForegroundColor Cyan
    Write-Host ""
    return $false
}

# Determine which platforms to build
$PlatformsToBuild = @()
switch ($Platform) {
    'windows' { $PlatformsToBuild = @('windows') }
    'linux' { $PlatformsToBuild = @('linux') }
    'macos' { $PlatformsToBuild = @('macos') }
    'all' { $PlatformsToBuild = @('windows', 'linux', 'macos') }
}

# Run build for each platform
foreach ($plat in $PlatformsToBuild) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan

    $success = $false
    switch ($plat) {
        'windows' { $success = Build-Windows }
        'linux' { $success = Build-Linux }
        'macos' { $success = Build-macOS }
    }

    $BuildResults += @{
        Platform = $plat
        Success = $success
    }

    Write-Host ""
}

# Summary
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "           Build Summary                   " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$successCount = ($BuildResults | Where-Object { $_.Success }).Count
$totalCount = $BuildResults.Count

foreach ($result in $BuildResults) {
    $status = "Skipped/Error"
    if ($result.Success) { $status = "Success" }
    $color = "Yellow"
    if ($result.Success) { $color = "Green" }
    Write-Host "  $($result.Platform.PadRight(10)) : $status" -ForegroundColor $color
}

Write-Host ""
$summaryColor = "Yellow"
if ($successCount -eq $totalCount) { $summaryColor = "Green" }
Write-Host "Success: $successCount / $totalCount" -ForegroundColor $summaryColor
Write-Host ""

# Show results location
$DistDir = Join-Path $RootDir "dist"
if (Test-Path $DistDir) {
    Write-Host "Build results are in: $DistDir" -ForegroundColor Cyan
    Write-Host ""

    Get-ChildItem -Path $DistDir -File -ErrorAction SilentlyContinue | ForEach-Object {
        $size = [math]::Round($_.Length / 1MB, 2)
        Write-Host "  - $($_.Name) ($size MB)" -ForegroundColor Gray
    }

    Get-ChildItem -Path $DistDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $size = [math]::Round((Get-ChildItem -Recurse $_.FullName | Measure-Object -Property Length -Sum).Sum / 1MB, 2)
        Write-Host "  - $($_.Name)/ ($size MB)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "              Done!                        " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Return exit code
if ($successCount -eq $totalCount -and $totalCount -gt 0) {
    exit 0
} else {
    exit 1
}
