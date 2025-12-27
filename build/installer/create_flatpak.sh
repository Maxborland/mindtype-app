#!/bin/bash
# =============================================================================
# Create Flatpak bundle for Linux
# Works with Nuitka-compiled binaries
# =============================================================================
# Run: ./build/installer/create_flatpak.sh [version]
# Requirements: flatpak, flatpak-builder

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

echo -e "${CYAN}=== Creating Flatpak bundle ===${NC}"
echo "Version: $VERSION"
echo ""

# Check flatpak-builder
if ! command -v flatpak-builder &> /dev/null; then
    echo -e "${RED}Error: flatpak-builder not found!${NC}"
    echo "Install it with:"
    echo "  Fedora: sudo dnf install flatpak-builder"
    echo "  Ubuntu: sudo apt install flatpak-builder"
    echo "  Arch: sudo pacman -S flatpak-builder"
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

# Install Flatpak runtime if needed
echo "Checking Flatpak runtime..."
if ! flatpak info org.freedesktop.Platform//23.08 &>/dev/null; then
    echo -e "${YELLOW}Installing Flatpak runtime (org.freedesktop.Platform 23.08)...${NC}"
    flatpak install -y flathub org.freedesktop.Platform//23.08 org.freedesktop.Sdk//23.08
fi

# Prepare Flatpak sources
echo "Preparing Flatpak sources..."
FLATPAK_DIR="$SCRIPT_DIR/flatpak"
mkdir -p "$FLATPAK_DIR/icons"

# Handle icons
ICON_SRC="$ROOT_DIR/assets/icons/app.png"
if [ -f "$ICON_SRC" ]; then
    echo "Processing icons..."
    for SIZE in 16 32 48 64 128 256; do
        if command -v convert &> /dev/null; then
            convert "$ICON_SRC" -resize ${SIZE}x${SIZE} \
                "$FLATPAK_DIR/icons/${SIZE}x${SIZE}.png"
        else
            cp "$ICON_SRC" "$FLATPAK_DIR/icons/${SIZE}x${SIZE}.png"
        fi
    done
else
    echo -e "${YELLOW}Warning: Icon not found at $ICON_SRC${NC}"
    # Create placeholder icons
    if command -v convert &> /dev/null; then
        for SIZE in 16 32 48 64 128 256; do
            convert -size ${SIZE}x${SIZE} xc:'#1a1a2e' \
                "$FLATPAK_DIR/icons/${SIZE}x${SIZE}.png" 2>/dev/null || true
        done
    fi
fi

# Update metainfo with current version
sed -i "s/version=\"[^\"]*\"/version=\"$VERSION\"/" "$FLATPAK_DIR/$APP_ID.metainfo.xml"
sed -i "s/date=\"[^\"]*\"/date=\"$(date +%Y-%m-%d)\"/" "$FLATPAK_DIR/$APP_ID.metainfo.xml"

# Build directory
BUILD_DIR="$DIST_DIR/flatpak-build"
REPO_DIR="$DIST_DIR/flatpak-repo"
BUNDLE_FILE="$DIST_DIR/${APP_ID}-${VERSION}.flatpak"

# Clean previous builds
rm -rf "$BUILD_DIR"
rm -rf "$REPO_DIR"
rm -f "$BUNDLE_FILE"

# Create temporary manifest with correct paths
MANIFEST="$SCRIPT_DIR/$APP_ID.yml"
TEMP_MANIFEST="$DIST_DIR/$APP_ID.yml"

# Generate manifest with absolute paths
cat > "$TEMP_MANIFEST" << EOF
app-id: $APP_ID
runtime: org.freedesktop.Platform
runtime-version: '23.08'
sdk: org.freedesktop.Sdk
command: mindtype

finish-args:
  - --share=ipc
  - --socket=x11
  - --socket=wayland
  - --socket=pulseaudio
  - --device=dri
  - --share=network
  - --filesystem=home
  - --filesystem=xdg-config
  - --filesystem=xdg-data
  - --filesystem=xdg-cache
  - --talk-name=org.freedesktop.Notifications
  - --talk-name=org.kde.StatusNotifierWatcher
  - --env=QT_QPA_PLATFORM=xcb

modules:
  - name: mindtype
    buildsystem: simple
    build-commands:
      - mkdir -p /app/bin
      - mkdir -p /app/lib/mindtype
      - mkdir -p /app/share/applications
      - mkdir -p /app/share/icons/hicolor/16x16/apps
      - mkdir -p /app/share/icons/hicolor/32x32/apps
      - mkdir -p /app/share/icons/hicolor/48x48/apps
      - mkdir -p /app/share/icons/hicolor/64x64/apps
      - mkdir -p /app/share/icons/hicolor/128x128/apps
      - mkdir -p /app/share/icons/hicolor/256x256/apps
      - mkdir -p /app/share/metainfo
      - cp -R MindType/* /app/lib/mindtype/
      - |
        cat > /app/bin/mindtype << 'LAUNCHER'
        #!/bin/bash
        export LD_LIBRARY_PATH="/app/lib/mindtype:\$LD_LIBRARY_PATH"
        export QT_PLUGIN_PATH="/app/lib/mindtype/PyQt6/Qt6/plugins:\$QT_PLUGIN_PATH"
        exec /app/lib/mindtype/MindType "\$@"
        LAUNCHER
      - chmod +x /app/bin/mindtype
      - cp $APP_ID.desktop /app/share/applications/
      - |
        for SIZE in 16 32 48 64 128 256; do
          if [ -f "icons/\${SIZE}x\${SIZE}.png" ]; then
            cp "icons/\${SIZE}x\${SIZE}.png" "/app/share/icons/hicolor/\${SIZE}x\${SIZE}/apps/$APP_ID.png"
          fi
        done
      - cp $APP_ID.metainfo.xml /app/share/metainfo/

    sources:
      - type: dir
        path: $DIST_DIR/$APP_NAME
        dest: MindType
      - type: file
        path: $FLATPAK_DIR/$APP_ID.desktop
      - type: file
        path: $FLATPAK_DIR/$APP_ID.metainfo.xml
      - type: dir
        path: $FLATPAK_DIR/icons
        dest: icons
EOF

# Build Flatpak
echo ""
echo "Building Flatpak..."
flatpak-builder --force-clean "$BUILD_DIR" "$TEMP_MANIFEST"

# Export to repository
echo ""
echo "Exporting to repository..."
flatpak-builder --repo="$REPO_DIR" --force-clean "$BUILD_DIR" "$TEMP_MANIFEST"

# Create bundle
echo ""
echo "Creating bundle..."
flatpak build-bundle "$REPO_DIR" "$BUNDLE_FILE" "$APP_ID"

# Cleanup
rm -rf "$BUILD_DIR"
rm -rf "$REPO_DIR"
rm -f "$TEMP_MANIFEST"

# Check result
if [ -f "$BUNDLE_FILE" ]; then
    SIZE=$(du -h "$BUNDLE_FILE" | cut -f1)
    echo ""
    echo -e "${GREEN}Flatpak bundle created successfully!${NC}"
    echo "File: $BUNDLE_FILE"
    echo "Size: $SIZE"
    echo ""
    echo "Install with:"
    echo "  flatpak install $BUNDLE_FILE"
    echo ""
    echo "Or publish to Flathub:"
    echo "  https://github.com/flathub/flathub/wiki/App-Submission"
    echo ""
    echo -e "${CYAN}=== Done ===${NC}"
else
    echo -e "${RED}Error: Flatpak bundle was not created!${NC}"
    exit 1
fi












