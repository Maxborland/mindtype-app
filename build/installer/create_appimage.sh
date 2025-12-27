#!/bin/bash
# =============================================================================
# Create AppImage for Linux
# Works with Nuitka-compiled binaries
# =============================================================================
# Run: ./build/installer/create_appimage.sh [version]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="MindType"
APP_ID="com.mindtype.MindType"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

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

# Get version
VERSION="${1:-$(get_app_version)}"

echo -e "${CYAN}=== Creating AppImage for Linux ===${NC}"
echo "Version: $VERSION"
echo ""

# Check for compiled binary
EXEC_PATH="$DIST_DIR/$APP_NAME/$APP_NAME"
if [ ! -f "$EXEC_PATH" ]; then
    echo -e "${RED}Error: $APP_NAME not found!${NC}"
    echo "Expected: $EXEC_PATH"
    echo ""
    echo "First run the build script:"
    echo "  ./build/build_linux_nuitka.sh"
    exit 1
fi

echo -e "${GREEN}Found executable: $EXEC_PATH${NC}"

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64) ARCH_SUFFIX="x86_64" ;;
    aarch64) ARCH_SUFFIX="aarch64" ;;
    armv7l) ARCH_SUFFIX="armhf" ;;
    *) ARCH_SUFFIX="$ARCH" ;;
esac

# Paths
APPDIR="$DIST_DIR/${APP_NAME}.AppDir"
APPIMAGE_FILE="$DIST_DIR/${APP_NAME}-${VERSION}-${ARCH_SUFFIX}.AppImage"

# Clean previous AppDir
rm -rf "$APPDIR"

# Create AppDir structure
echo "Creating AppDir structure..."
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/16x16/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/32x32/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APPDIR/usr/share/metainfo"

# Copy application files
echo "Copying application files..."
cp -R "$DIST_DIR/$APP_NAME/"* "$APPDIR/usr/bin/"

# Create .desktop file
cat > "$APPDIR/usr/share/applications/${APP_ID}.desktop" << EOF
[Desktop Entry]
Type=Application
Name=MindType
GenericName=Speech to Text
Comment=Offline speech-to-text transcription using Whisper AI
Exec=$APP_NAME %F
Icon=${APP_ID}
Categories=AudioVideo;Audio;Utility;
Keywords=speech;voice;transcription;whisper;ai;dictation;
Terminal=false
StartupNotify=true
StartupWMClass=$APP_NAME
EOF

# Copy .desktop to AppDir root
cp "$APPDIR/usr/share/applications/${APP_ID}.desktop" "$APPDIR/"

# Handle icons
ICON_SRC="$ROOT_DIR/assets/icons/app.png"
if [ -f "$ICON_SRC" ]; then
    echo "Copying icons..."
    for SIZE in 16 32 64 128 256; do
        if command -v convert &> /dev/null; then
            convert "$ICON_SRC" -resize ${SIZE}x${SIZE} \
                "$APPDIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/${APP_ID}.png"
        else
            cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/${APP_ID}.png"
        fi
    done
    cp "$ICON_SRC" "$APPDIR/${APP_ID}.png"
else
    echo -e "${YELLOW}Warning: Icon not found at $ICON_SRC${NC}"
    # Create placeholder icon
    if command -v convert &> /dev/null; then
        echo "Creating placeholder icon..."
        convert -size 256x256 xc:'#1a1a2e' \
            -fill '#16213e' -draw "roundrectangle 20,20 236,236 30,30" \
            -fill '#0f3460' -draw "circle 128,100 128,50" \
            -fill '#e94560' -draw "roundrectangle 108,120 148,200 5,5" \
            "$APPDIR/${APP_ID}.png" 2>/dev/null || true

        for SIZE in 16 32 64 128 256; do
            if [ -f "$APPDIR/${APP_ID}.png" ]; then
                convert "$APPDIR/${APP_ID}.png" -resize ${SIZE}x${SIZE} \
                    "$APPDIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/${APP_ID}.png"
            fi
        done
    fi
fi

# Create AppStream metainfo
cat > "$APPDIR/usr/share/metainfo/${APP_ID}.appdata.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>${APP_ID}</id>
  <name>MindType</name>
  <summary>Offline speech-to-text transcription</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>Proprietary</project_license>
  <description>
    <p>
      MindType is a desktop application for transcribing speech to text
      using OpenAI's Whisper AI model. It works completely offline without
      sending any data to external servers.
    </p>
    <p>Features:</p>
    <ul>
      <li>Push-to-talk recording with global hotkey</li>
      <li>Support for multiple Whisper models (tiny to large)</li>
      <li>Auto-paste transcribed text to any application</li>
      <li>Multi-language support with automatic detection</li>
      <li>VAD (Voice Activity Detection) for smart recording</li>
    </ul>
  </description>
  <launchable type="desktop-id">${APP_ID}.desktop</launchable>
  <url type="homepage">https://mindtype.app</url>
  <provides>
    <binary>$APP_NAME</binary>
  </provides>
  <releases>
    <release version="$VERSION" date="$(date +%Y-%m-%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
  <categories>
    <category>AudioVideo</category>
    <category>Audio</category>
    <category>Utility</category>
  </categories>
</component>
EOF

# Create AppRun script
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
# AppRun script for MindType

SELF=$(readlink -f "$0")
HERE=${SELF%/*}

# Set environment variables
export PATH="${HERE}/usr/bin/:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib/:${HERE}/usr/bin/:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/usr/share/:${XDG_DATA_DIRS}"

# Qt platform plugin path
export QT_PLUGIN_PATH="${HERE}/usr/bin/PyQt6/Qt6/plugins:${QT_PLUGIN_PATH}"

# Run application
exec "${HERE}/usr/bin/MindType" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# Download appimagetool if needed
APPIMAGETOOL="$SCRIPT_DIR/appimagetool-${ARCH_SUFFIX}.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    echo "Downloading appimagetool..."

    APPIMAGETOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH_SUFFIX}.AppImage"

    if command -v wget &> /dev/null; then
        wget -q --show-progress "$APPIMAGETOOL_URL" -O "$APPIMAGETOOL"
    elif command -v curl &> /dev/null; then
        curl -L --progress-bar "$APPIMAGETOOL_URL" -o "$APPIMAGETOOL"
    else
        echo -e "${RED}Error: wget or curl not found!${NC}"
        echo "Install wget: sudo apt install wget"
        exit 1
    fi

    chmod +x "$APPIMAGETOOL"
    echo -e "${GREEN}appimagetool downloaded${NC}"
fi

# Create AppImage
echo ""
echo "Creating AppImage..."
rm -f "$APPIMAGE_FILE"

ARCH=$ARCH_SUFFIX "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_FILE"

# Cleanup
rm -rf "$APPDIR"

# Check result
if [ -f "$APPIMAGE_FILE" ]; then
    chmod +x "$APPIMAGE_FILE"

    SIZE=$(du -h "$APPIMAGE_FILE" | cut -f1)
    echo ""
    echo -e "${GREEN}AppImage created successfully!${NC}"
    echo "File: $APPIMAGE_FILE"
    echo "Size: $SIZE"
    echo ""
    echo -e "${CYAN}=== Done ===${NC}"
else
    echo -e "${RED}Error: AppImage was not created!${NC}"
    exit 1
fi
