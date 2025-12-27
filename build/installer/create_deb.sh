#!/bin/bash
# =============================================================================
# Create .deb package for Debian/Ubuntu
# Works with Nuitka-compiled binaries
# =============================================================================
# Run: ./build/installer/create_deb.sh [version]
# Requirements: dpkg-deb

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
DIST_DIR="$ROOT_DIR/dist"
APP_NAME="MindType"
PKG_NAME="mindtype"
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

echo -e "${CYAN}=== Creating DEB package ===${NC}"
echo "Version: $VERSION"
echo ""

# Check dpkg-deb
if ! command -v dpkg-deb &> /dev/null; then
    echo -e "${RED}Error: dpkg-deb not found!${NC}"
    echo "Install it with: sudo apt install dpkg"
    exit 1
fi

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
ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")

# Package paths
PKG_DIR="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
DEB_FILE="$DIST_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"

# Clean previous
rm -rf "$PKG_DIR"
rm -f "$DEB_FILE"

# Create package structure
echo "Creating package structure..."
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/lib/$PKG_NAME"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/16x16/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/32x32/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$PKG_DIR/usr/share/metainfo"
mkdir -p "$PKG_DIR/usr/share/doc/$PKG_NAME"

# Copy application files
echo "Copying application files..."
cp -R "$DIST_DIR/$APP_NAME/"* "$PKG_DIR/usr/lib/$PKG_NAME/"

# Create launcher symlink
ln -sf "/usr/lib/$PKG_NAME/$APP_NAME" "$PKG_DIR/usr/bin/$PKG_NAME"

# Calculate installed size (in KB)
INSTALLED_SIZE=$(du -sk "$PKG_DIR" | cut -f1)

# Create control file
cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: $PKG_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: MindType Team <support@mindtype.app>
Homepage: https://mindtype.app
Description: Offline speech-to-text transcription
 MindType is a desktop application for transcribing speech to text
 using OpenAI's Whisper AI model. It works completely offline without
 sending any data to external servers.
 .
 Features:
  - Push-to-talk recording with global hotkey
  - Support for multiple Whisper models
  - Auto-paste transcribed text
  - Multi-language support
Depends: libc6, libx11-6, libxcb1, libxkbcommon0, libgl1, libegl1, libpulse0 | libasound2
Recommends: libportaudio2
EOF

# Create postinst script
cat > "$PKG_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

# Update icon cache
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

exit 0
EOF
chmod 755 "$PKG_DIR/DEBIAN/postinst"

# Create postrm script
cat > "$PKG_DIR/DEBIAN/postrm" << 'EOF'
#!/bin/bash
set -e

# Update icon cache
if command -v gtk-update-icon-cache &> /dev/null; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

# Remove config on purge
if [ "$1" = "purge" ]; then
    rm -rf /home/*/.config/MindType 2>/dev/null || true
    rm -rf /home/*/.local/share/MindType 2>/dev/null || true
fi

exit 0
EOF
chmod 755 "$PKG_DIR/DEBIAN/postrm"

# Create .desktop file
cat > "$PKG_DIR/usr/share/applications/${APP_ID}.desktop" << EOF
[Desktop Entry]
Type=Application
Name=MindType
GenericName=Speech to Text
Comment=Offline speech-to-text transcription using Whisper AI
Exec=$PKG_NAME %F
Icon=${APP_ID}
Categories=AudioVideo;Audio;Utility;
Keywords=speech;voice;transcription;whisper;ai;dictation;
Terminal=false
StartupNotify=true
StartupWMClass=$APP_NAME
EOF

# Handle icons
ICON_SRC="$ROOT_DIR/assets/icons/app.png"
if [ -f "$ICON_SRC" ]; then
    echo "Installing icons..."
    for SIZE in 16 32 48 64 128 256; do
        if command -v convert &> /dev/null; then
            convert "$ICON_SRC" -resize ${SIZE}x${SIZE} \
                "$PKG_DIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/${APP_ID}.png"
        else
            cp "$ICON_SRC" "$PKG_DIR/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps/${APP_ID}.png"
        fi
    done
else
    echo -e "${YELLOW}Warning: Icon not found at $ICON_SRC${NC}"
fi

# Create AppStream metainfo
cat > "$PKG_DIR/usr/share/metainfo/${APP_ID}.metainfo.xml" << EOF
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
    <binary>$PKG_NAME</binary>
  </provides>
  <releases>
    <release version="$VERSION" date="$(date +%Y-%m-%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF

# Create copyright file
cat > "$PKG_DIR/usr/share/doc/$PKG_NAME/copyright" << EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: MindType
Source: https://mindtype.app

Files: *
Copyright: $(date +%Y) MindType Team
License: Proprietary
 This software is proprietary.
 See https://mindtype.app/license for details.
EOF

# Build .deb package
echo ""
echo "Building .deb package..."
dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_FILE"

# Cleanup
rm -rf "$PKG_DIR"

# Check result
if [ -f "$DEB_FILE" ]; then
    SIZE=$(du -h "$DEB_FILE" | cut -f1)
    echo ""
    echo -e "${GREEN}DEB package created successfully!${NC}"
    echo "File: $DEB_FILE"
    echo "Size: $SIZE"
    echo ""
    echo "Install with:"
    echo "  sudo dpkg -i $DEB_FILE"
    echo "  sudo apt install -f  # if dependencies are missing"
    echo ""
    echo -e "${CYAN}=== Done ===${NC}"
else
    echo -e "${RED}Error: DEB package was not created!${NC}"
    exit 1
fi












