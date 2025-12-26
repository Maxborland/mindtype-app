#!/bin/bash
# =============================================================================
# macOS build script using Nuitka
# Compiles Python to native code and creates DMG
# =============================================================================
# Run: ./build/build_macos.sh [version] [--clean]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build_nuitka"

# Function to read version from app/version.py
get_app_version() {
    local version_file="$ROOT_DIR/app/version.py"
    if [ -f "$version_file" ]; then
        local version=$(grep -oP '__version__\s*=\s*"\K[^"]+' "$version_file" | head -1)
        if [ -n "$version" ]; then
            echo "$version"
            return 0
        fi
    fi
    echo "1.0.0"
}

# Determine version
if [ -n "$1" ] && [[ "$1" != "--"* ]]; then
    VERSION="$1"
else
    VERSION=$(get_app_version)
fi

echo "============================================"
echo "  MindType - macOS Build (Nuitka)           "
echo "============================================"
echo "Version: $VERSION"
echo ""

cd "$ROOT_DIR"

# Clean
if [[ "$*" == *"--clean"* ]]; then
    echo "[1/6] Cleaning previous build..."
    rm -rf "$DIST_DIR" "$BUILD_DIR"
    rm -rf MindType.build MindType.dist MindType.app
    echo "  Done"
fi

# Check dependencies
echo "[2/6] Checking dependencies..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  ERROR: python3 not found!" >&2
    exit 1
fi

# Check Nuitka
if ! python3 -c "import nuitka" 2>/dev/null; then
    echo "  - Nuitka not found. Installing..."
    pip3 install nuitka ordered-set zstandard
else
    NUITKA_VER=$(python3 -c "import nuitka; print(nuitka.__version__)" 2>/dev/null)
    echo "  - Nuitka: v$NUITKA_VER"
fi

# Check requirements
echo "  - Installing requirements..."
pip3 install -r requirements.txt

# Run Nuitka
echo ""
echo "[3/6] Compiling with Nuitka..."
echo "  This may take 10-30 minutes."

mkdir -p "$DIST_DIR"

# Убеждаемся, что whisper-cli готов для включения в сборку
BIN_DIR="$ROOT_DIR/bin/darwin-arm64"
mkdir -p "$BIN_DIR"
if [ ! -f "$BIN_DIR/whisper-cli" ]; then
    echo "  Бинарник whisper-cli не найден. Начинаем компиляцию..."
    TEMP_WHISPER=$(mktemp -d)
    git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$TEMP_WHISPER"
    cd "$TEMP_WHISPER"
    # Для Mac всегда включаем Metal
    GGML_METAL=1 make -j whisper-cli
    cp whisper-cli "$BIN_DIR/"
    cd "$ROOT_DIR"
    rm -rf "$TEMP_WHISPER"
    echo "  Бинарник успешно скомпилирован с поддержкой Metal и скопирован в $BIN_DIR"
fi

python3 -m nuitka \
    --standalone \
    --macos-create-app-bundle \
    --macos-app-icon=assets/icons/app.png \
    --enable-plugin=pyqt6 \
    --include-package=app \
    --include-data-dir=app/assets=app/assets \
    --include-package=huggingface_hub \
    --include-package=sklearn \
    --include-package=librosa \
    --include-package=soundfile \
    --include-package=psutil \
    --include-package=onnxruntime \
    --include-module=sounddevice \
    --include-module=numpy \
    --include-module=ctypes \
    --remove-output \
    --assume-yes-for-downloads \
    --output-dir="$DIST_DIR" \
    --macos-app-name="MindType" \
    --macos-app-version="$VERSION" \
    --macos-signed-app-name="com.mindtype.app" \
    main.py

# Check result
echo ""
echo "[4/6] Checking result..."

APP_PATH="$DIST_DIR/MindType.app"
if [ -d "$APP_PATH" ]; then
    echo "  Build successful!"
    echo "  App Bundle: $APP_PATH"

    # Empty models folder
    mkdir -p "$APP_PATH/Contents/MacOS/models"

    # Copy bin directory for whisper.cpp if exists
    if [ -d "bin" ]; then
        cp -r bin "$APP_PATH/Contents/MacOS/"
    fi
else
    echo "  ERROR: App Bundle not found at $APP_PATH"
    exit 1
fi

# Create DMG
echo ""
echo "[5/6] Creating DMG..."

DMG_FILE="$DIST_DIR/MindType-$VERSION.dmg"
DMG_STAGING="$DIST_DIR/dmg_staging"
rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"

cp -R "$APP_PATH" "$DMG_STAGING/"
ln -s /Applications "$DMG_STAGING/Applications"

if command -v create-dmg &> /dev/null; then
    create-dmg \
        --volname "MindType" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "MindType.app" 175 120 \
        --app-drop-link 425 120 \
        "$DMG_FILE" \
        "$DMG_STAGING"
else
    hdiutil create -volname "MindType" -srcfolder "$DMG_STAGING" -ov -format UDZO "$DMG_FILE"
fi

rm -rf "$DMG_STAGING"

echo ""
echo "============================================"
echo "  Done! DMG created: $DMG_FILE"
echo "============================================"
