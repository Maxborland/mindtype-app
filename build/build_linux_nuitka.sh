#!/bin/bash
# =============================================================================
# Linux build script using Nuitka
# Compiles Python to native code for reverse engineering protection
# =============================================================================
# Run: ./build/build_linux_nuitka.sh
# With params: ./build/build_linux_nuitka.sh --version 1.1.0 --clean

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build_nuitka"
APP_NAME="MindType"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Default values
CLEAN=false
VERSION=""
ONEFILE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --clean|-c)
            CLEAN=true
            shift
            ;;
        --version|-v)
            VERSION="$2"
            shift 2
            ;;
        --onefile|-o)
            ONEFILE=true
            shift
            ;;
        *)
            # If argument doesn't start with -, treat as version
            if [[ ! "$1" =~ ^- ]]; then
                VERSION="$1"
            fi
            shift
            ;;
    esac
done

# Function to read version from app/env.py
get_app_version() {
    local env_file="$ROOT_DIR/app/env.py"
    if [ -f "$env_file" ]; then
        local version=$(grep -oP 'APP_VERSION:\s*str\s*=\s*"\K[^"]+' "$env_file" 2>/dev/null | head -1)
        if [ -n "$version" ]; then
            echo "$version"
            return 0
        fi
    fi
    echo "1.0.0"
}

# If version not specified, read from app/env.py
if [ -z "$VERSION" ]; then
    VERSION=$(get_app_version)
    echo -e "${GRAY}Version read from app/env.py: $VERSION${NC}"
fi

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  MindType - Linux Build (Nuitka)          ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "Version: $VERSION"
echo "Mode: $(if $ONEFILE; then echo 'Single file (--onefile)'; else echo 'Folder (--standalone)'; fi)"
echo ""

cd "$ROOT_DIR"

# Activate venv if exists
if [ -f ".venv/bin/activate" ]; then
    echo -e "${GRAY}Activating virtual environment...${NC}"
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    echo -e "${GRAY}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# Clean previous build
if $CLEAN; then
    echo -e "${YELLOW}[1/5] Cleaning previous build...${NC}"
    rm -rf "$DIST_DIR"
    rm -rf "$BUILD_DIR"
    rm -rf "main.build"
    rm -rf "main.dist"
    rm -rf "main.onefile-build"
    rm -rf "$APP_NAME.build"
    rm -rf "$APP_NAME.dist"
    echo "  Cleaned"
fi

# Check dependencies
echo -e "${YELLOW}[2/5] Checking dependencies...${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  - ERROR: python3 not found!${NC}"
    echo -e "${YELLOW}    Install Python 3.8+ and add it to PATH${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "${GREEN}  - Python: $PYTHON_VERSION${NC}"

# Check pip
if ! command -v pip3 &> /dev/null; then
    echo -e "${RED}  - ERROR: pip3 not found!${NC}"
    exit 1
fi
echo -e "${GREEN}  - pip3: OK${NC}"

# Check GCC
if ! command -v gcc &> /dev/null; then
    echo -e "${RED}  - ERROR: GCC not found!${NC}"
    echo -e "${YELLOW}    Install GCC: sudo apt install build-essential${NC}"
    exit 1
fi
GCC_VERSION=$(gcc --version | head -1)
echo -e "${GREEN}  - GCC: $GCC_VERSION${NC}"

# Check patchelf (required for Nuitka on Linux)
if ! command -v patchelf &> /dev/null; then
    echo -e "${YELLOW}  - patchelf not found. Installing...${NC}"
    if command -v apt &> /dev/null; then
        sudo apt install -y patchelf
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y patchelf
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm patchelf
    else
        pip3 install patchelf
    fi
fi
echo -e "${GREEN}  - patchelf: OK${NC}"

# Check Nuitka
if ! python3 -c "import nuitka" 2>/dev/null; then
    echo -e "${YELLOW}  - Nuitka not found. Installing...${NC}"
    pip3 install nuitka ordered-set zstandard
    if [ $? -ne 0 ]; then
        echo -e "${RED}  - ERROR: Could not install Nuitka!${NC}"
        echo -e "${YELLOW}    Try installing manually: pip3 install nuitka ordered-set zstandard${NC}"
        exit 1
    fi
    echo -e "${GREEN}  - Nuitka installed successfully${NC}"
else
    NUITKA_VERSION=$(python3 -c "import nuitka; print(nuitka.__version__)" 2>/dev/null || echo "unknown")
    echo -e "${GREEN}  - Nuitka: v$NUITKA_VERSION${NC}"
fi

# Check ccache (optional, speeds up rebuilds)
if command -v ccache &> /dev/null; then
    echo -e "${GREEN}  - ccache: OK (faster rebuilds)${NC}"
else
    echo -e "${GRAY}  - ccache: not installed (optional, speeds up rebuilds)${NC}"
fi

echo -e "${GRAY}  - Models: will be downloaded on first run${NC}"

# Build Nuitka command
echo ""
echo -e "${GREEN}[3/5] Compiling with Nuitka...${NC}"
echo "  This may take 10-30 minutes depending on your computer."
echo ""

# Create dist directory
mkdir -p "$DIST_DIR"

# Find VAD ONNX file
VAD_ONNX=""
for candidate in ".venv/lib/python"*"/site-packages/faster_whisper/assets/silero_vad_v6.onnx" \
                 "venv/lib/python"*"/site-packages/faster_whisper/assets/silero_vad_v6.onnx" \
                 "/usr/local/lib/python"*"/dist-packages/faster_whisper/assets/silero_vad_v6.onnx" \
                 "/usr/lib/python"*"/site-packages/faster_whisper/assets/silero_vad_v6.onnx"; do
    expanded=$(ls $candidate 2>/dev/null | head -1)
    if [ -f "$expanded" ]; then
        VAD_ONNX="$expanded"
        break
    fi
done

if [ -z "$VAD_ONNX" ]; then
    echo -e "${RED}ERROR: VAD ONNX not found in venv: faster_whisper/assets/silero_vad_v6.onnx${NC}"
    echo -e "${YELLOW}Make sure faster_whisper is installed: pip install faster-whisper${NC}"
    exit 1
fi
echo -e "${GRAY}  Found VAD ONNX: $VAD_ONNX${NC}"

# Build Nuitka arguments
NUITKA_ARGS=(
    "-m" "nuitka"
    "--standalone"
    "--enable-plugin=pyqt6"
    "--include-package=app"
    "--include-package=faster_whisper"
    "--include-package=huggingface_hub"
    "--include-module=sounddevice"
    "--include-module=numpy"
    "--include-module=ctypes"
    "--noinclude-pytest-mode=nofollow"
    "--noinclude-setuptools-mode=nofollow"
    "--noinclude-custom-mode=setuptools:nofollow"
    "--remove-output"
    "--assume-yes-for-downloads"
    "--output-dir=$DIST_DIR"
    "--output-filename=$APP_NAME"
    "--lto=yes"
    "--include-data-files=$VAD_ONNX=faster_whisper/assets/silero_vad_v6.onnx"
)

# Add onefile if requested
if $ONEFILE; then
    NUITKA_ARGS+=("--onefile")
    NUITKA_ARGS+=("--onefile-tempdir-spec=/tmp/mindtype_%PID%")
fi

# Add main file
NUITKA_ARGS+=("main.py")

# Use python from venv if available
PYTHON_CMD="python3"
if [ -f ".venv/bin/python" ]; then
    PYTHON_CMD=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
fi

# Show command
echo -e "${GRAY}  Command: $PYTHON_CMD ${NUITKA_ARGS[*]}${NC}"
echo ""

# Run Nuitka
if ! $PYTHON_CMD "${NUITKA_ARGS[@]}"; then
    echo ""
    echo -e "${RED}ERROR: Nuitka compilation failed!${NC}"
    echo ""
    echo -e "${YELLOW}Possible causes:${NC}"
    echo -e "${YELLOW}  - Missing dependencies${NC}"
    echo -e "${YELLOW}  - Not enough disk space${NC}"
    echo -e "${YELLOW}  - GCC compiler issues${NC}"
    echo ""
    echo -e "${YELLOW}Check logs above for details.${NC}"
    exit 1
fi

# Check result
echo ""
echo -e "${YELLOW}[4/5] Checking result...${NC}"

if $ONEFILE; then
    EXEC_PATH="$DIST_DIR/$APP_NAME"
else
    EXEC_PATH="$DIST_DIR/main.dist/$APP_NAME"
fi

# Rename folder if needed
if ! $ONEFILE; then
    OLD_DIST="$DIST_DIR/main.dist"
    NEW_DIST="$DIST_DIR/$APP_NAME"
    if [ -d "$OLD_DIST" ]; then
        rm -rf "$NEW_DIST"
        mv "$OLD_DIST" "$NEW_DIST"
        EXEC_PATH="$NEW_DIST/$APP_NAME"
    fi
fi

if [ -f "$EXEC_PATH" ]; then
    chmod +x "$EXEC_PATH"
    echo ""
    echo -e "${GREEN}Build successful!${NC}"
    echo "Executable: $EXEC_PATH"

    # Exe size
    SIZE=$(du -h "$EXEC_PATH" | cut -f1)
    echo "Executable size: $SIZE"

    if ! $ONEFILE; then
        # Folder size
        FOLDER_PATH=$(dirname "$EXEC_PATH")
        FOLDER_SIZE=$(du -sh "$FOLDER_PATH" | cut -f1)
        echo "Folder size: $FOLDER_SIZE"

        # Create empty models folder
        DEST_MODELS="$FOLDER_PATH/models"
        mkdir -p "$DEST_MODELS"
        echo ""
        echo -e "${GRAY}Models folder created (empty). User will download on first run.${NC}"
    fi
else
    echo ""
    echo -e "${RED}ERROR: Executable not found!${NC}"
    echo -e "${RED}Expected: $EXEC_PATH${NC}"
    echo ""
    echo -e "${YELLOW}Possible causes:${NC}"
    echo -e "${YELLOW}  - Compilation failed with error${NC}"
    echo -e "${YELLOW}  - Insufficient permissions to write to dist/${NC}"
    echo ""
    echo -e "${YELLOW}Check compilation logs above.${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[5/5] Post-build steps...${NC}"
echo -e "${GRAY}  Installers can be created separately with:${NC}"
echo -e "${GRAY}    ./build/installer/create_appimage.sh $VERSION${NC}"
echo -e "${GRAY}    ./build/installer/create_deb.sh $VERSION${NC}"
echo -e "${GRAY}    ./build/installer/create_rpm.sh $VERSION${NC}"
echo -e "${GRAY}    ./build/installer/create_flatpak.sh $VERSION${NC}"

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}              Done!                        ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "Application compiled to native code."
echo "Source Python code is protected from decompilation."
echo ""
echo "Build output: $DIST_DIR/$APP_NAME/"
echo ""












