#!/bin/bash
# =============================================================================
# Linux build script using Nuitka
# Compiles Python to native code and creates AppImage
# =============================================================================
# Run: ./build/build_linux.sh [version] [--clean]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build_nuitka"

# Function to read version from app/version.py
get_app_version() {
    local version_file="$ROOT_DIR/app/version.py"
    if [ -f "$version_file" ]; then
        local version=$(grep -E '__version__\s*=\s*"[^"]+"' "$version_file" | sed 's/.*"\([^"]*\)".*/\1/' | head -1)
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

# Remove 'v' from version for Nuitka (must be numeric tuple)
VERSION="${VERSION#v}"

echo "============================================"
echo "  MindType - Linux Build (Nuitka)           "
echo "============================================"
echo "Version: $VERSION"
echo ""

cd "$ROOT_DIR"

# Clean
if [[ "$*" == *"--clean"* ]]; then
    echo "[1/6] Cleaning previous build..."
    rm -rf "$DIST_DIR" "$BUILD_DIR"
    rm -rf MindType.build MindType.dist
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
    NUITKA_VER=$(python3 -m nuitka --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
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
BIN_DIR="$ROOT_DIR/bin/linux-x64"
mkdir -p "$BIN_DIR"
if [ ! -f "$BIN_DIR/whisper-cli" ]; then
    echo "  Бинарник whisper-cli не найден. Начинаем компиляцию..."
    TEMP_WHISPER=$(mktemp -d)
    git clone --depth 1 https://github.com/ggerganov/whisper.cpp "$TEMP_WHISPER"
    cd "$TEMP_WHISPER"
    GGML_VULKAN=1 make -j whisper-cli
    cp whisper-cli "$BIN_DIR/"
    cd "$ROOT_DIR"
    rm -rf "$TEMP_WHISPER"
    echo "  Бинарник успешно скомпилирован и скопирован в $BIN_DIR"
fi

python3 -m nuitka \
    --standalone \
    --linux-onefile-icon=assets/icons/app.png \
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
    --output-filename=MindType \
    main.py

# Check result
echo ""
echo "[4/6] Checking result..."

# Nuitka creates main.dist folder
OLD_DIST="$DIST_DIR/main.dist"
NEW_DIST="$DIST_DIR/MindType"

if [ -d "$OLD_DIST" ]; then
    rm -rf "$NEW_DIST"
    mv "$OLD_DIST" "$NEW_DIST"
fi

EXEC_PATH="$NEW_DIST/MindType"
if [ -f "$EXEC_PATH" ]; then
    echo "  Build successful!"
    echo "  Executable: $EXEC_PATH"

    # Empty models folder
    mkdir -p "$NEW_DIST/models"

    # Copy bin directory for whisper.cpp if exists
    if [ -d "bin" ]; then
        cp -r bin "$NEW_DIST/"
    fi
else
    echo "  ERROR: Executable not found at $EXEC_PATH"
    exit 1
fi

# Create AppImage
echo ""
echo "[5/6] Creating AppImage..."

APPDIR="$DIST_DIR/MindType.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy files
cp -R "$NEW_DIST/"* "$APPDIR/usr/bin/"

# .desktop file
cat > "$APPDIR/usr/share/applications/mindtype.desktop" << EOF
[Desktop Entry]
Type=Application
Name=MindType
GenericName=Speech to Text
Comment=Offline speech-to-text transcription
Exec=MindType
Icon=mindtype
Categories=AudioVideo;Audio;Utility;
Terminal=false
StartupNotify=true
StartupWMClass=MindType
EOF

cp "$APPDIR/usr/share/applications/mindtype.desktop" "$APPDIR/"

# Icon
ICON_SRC="$ROOT_DIR/assets/icons/app.png"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/mindtype.png"
    cp "$ICON_SRC" "$APPDIR/mindtype.png"
fi

# AppRun
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin/:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib/:${HERE}/usr/bin/:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/usr/share/:${XDG_DATA_DIRS}"
exec "${HERE}/usr/bin/MindType" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# appimagetool
APPIMAGETOOL="$SCRIPT_DIR/appimagetool-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" -O "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# Generate AppImage
APPIMAGE_FILE="$DIST_DIR/MindType-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_FILE"
chmod +x "$APPIMAGE_FILE"

echo ""
echo "============================================"
echo "  Done! AppImage created: $APPIMAGE_FILE"
echo "============================================"
