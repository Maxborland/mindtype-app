#!/bin/bash
# =============================================================================
# Create .rpm package for Fedora/RHEL/CentOS
# Works with Nuitka-compiled binaries
# =============================================================================
# Run: ./build/installer/create_rpm.sh [version]
# Requirements: rpm-build

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

echo -e "${CYAN}=== Creating RPM package ===${NC}"
echo "Version: $VERSION"
echo ""

# Check rpmbuild
if ! command -v rpmbuild &> /dev/null; then
    echo -e "${RED}Error: rpmbuild not found!${NC}"
    echo "Install it with:"
    echo "  Fedora: sudo dnf install rpm-build"
    echo "  CentOS/RHEL: sudo yum install rpm-build"
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

# Setup RPM build directories
RPM_BUILD_DIR="$HOME/rpmbuild"
mkdir -p "$RPM_BUILD_DIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

# Create source tarball
echo "Creating source tarball..."
TARBALL="$RPM_BUILD_DIR/SOURCES/$APP_NAME.tar.gz"
TARBALL_DIR="$DIST_DIR/$APP_NAME"

# Create tarball with correct structure
cd "$DIST_DIR"
tar -czf "$TARBALL" "$APP_NAME"
cd "$ROOT_DIR"

echo -e "${GREEN}Source tarball created: $TARBALL${NC}"

# Process icons
ICON_SRC="$ROOT_DIR/assets/icons/app.png"
if [ -f "$ICON_SRC" ]; then
    echo "Processing icons..."
    # Create icons directory in source
    mkdir -p "$TARBALL_DIR/icons"
    for SIZE in 16 32 48 64 128 256; do
        if command -v convert &> /dev/null; then
            convert "$ICON_SRC" -resize ${SIZE}x${SIZE} \
                "$TARBALL_DIR/icons/${APP_ID}_${SIZE}.png"
        else
            cp "$ICON_SRC" "$TARBALL_DIR/icons/${APP_ID}_${SIZE}.png"
        fi
    done

    # Update tarball with icons
    cd "$DIST_DIR"
    tar -czf "$TARBALL" "$APP_NAME"
    cd "$ROOT_DIR"
else
    echo -e "${YELLOW}Warning: Icon not found at $ICON_SRC${NC}"
fi

# Copy and prepare spec file
echo "Preparing spec file..."
SPEC_FILE="$RPM_BUILD_DIR/SPECS/$PKG_NAME.spec"

# Read the spec template and replace placeholders
cat > "$SPEC_FILE" << 'SPECEOF'
# =============================================================================
# RPM Spec file for MindType
# =============================================================================

%define app_name MindType
%define pkg_name mindtype
%define app_id com.mindtype.MindType

# Disable automatic dependency generation (we bundle everything)
%global __requires_exclude_from ^%{_libdir}/%{pkg_name}/.*$
%global __provides_exclude_from ^%{_libdir}/%{pkg_name}/.*$
AutoReqProv: no

Name:           %{pkg_name}
Version:        VERSION_PLACEHOLDER
Release:        1%{?dist}
Summary:        Offline speech-to-text transcription using Whisper AI
License:        Proprietary
URL:            https://mindtype.app
Group:          Applications/Multimedia

Source0:        %{app_name}.tar.gz

BuildArch:      x86_64

# Runtime dependencies
Requires:       glibc
Requires:       libX11
Requires:       libxcb
Requires:       libxkbcommon
Requires:       mesa-libGL
Requires:       mesa-libEGL
Requires:       pulseaudio-libs

%description
MindType is a desktop application for transcribing speech to text
using OpenAI's Whisper AI model. It works completely offline without
sending any data to external servers.

Features:
- Push-to-talk recording with global hotkey
- Support for multiple Whisper models (tiny to large)
- Auto-paste transcribed text to any application
- Multi-language support with automatic detection
- VAD (Voice Activity Detection) for smart recording

%prep
%setup -q -n %{app_name}

%install
rm -rf %{buildroot}

# Create directories
mkdir -p %{buildroot}%{_libdir}/%{pkg_name}
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/16x16/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/32x32/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/48x48/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/64x64/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/128x128/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/256x256/apps
mkdir -p %{buildroot}%{_datadir}/metainfo

# Copy application files (excluding icons subdir we created)
find . -maxdepth 1 -mindepth 1 ! -name 'icons' -exec cp -R {} %{buildroot}%{_libdir}/%{pkg_name}/ \;

# Install icons if they exist
if [ -d "icons" ]; then
    for SIZE in 16 32 48 64 128 256; do
        if [ -f "icons/%{app_id}_${SIZE}.png" ]; then
            cp "icons/%{app_id}_${SIZE}.png" \
                "%{buildroot}%{_datadir}/icons/hicolor/${SIZE}x${SIZE}/apps/%{app_id}.png"
        fi
    done
fi

# Create launcher symlink
ln -sf %{_libdir}/%{pkg_name}/%{app_name} %{buildroot}%{_bindir}/%{pkg_name}

# Desktop file
cat > %{buildroot}%{_datadir}/applications/%{app_id}.desktop << EOF
[Desktop Entry]
Type=Application
Name=MindType
GenericName=Speech to Text
Comment=Offline speech-to-text transcription using Whisper AI
Exec=%{pkg_name} %%F
Icon=%{app_id}
Categories=AudioVideo;Audio;Utility;
Keywords=speech;voice;transcription;whisper;ai;dictation;
Terminal=false
StartupNotify=true
StartupWMClass=%{app_name}
EOF

# AppStream metainfo
cat > %{buildroot}%{_datadir}/metainfo/%{app_id}.metainfo.xml << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>%{app_id}</id>
  <name>MindType</name>
  <summary>Offline speech-to-text transcription</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>Proprietary</project_license>
  <description>
    <p>
      MindType is a desktop application for transcribing speech to text
      using OpenAI's Whisper AI model. It works completely offline.
    </p>
  </description>
  <launchable type="desktop-id">%{app_id}.desktop</launchable>
  <url type="homepage">https://mindtype.app</url>
  <provides>
    <binary>%{pkg_name}</binary>
  </provides>
  <content_rating type="oars-1.1"/>
</component>
EOF

%post
# Update icon cache
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
fi

# Update desktop database
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database %{_datadir}/applications &>/dev/null || :
fi

%postun
# Update icon cache
if [ -x /usr/bin/gtk-update-icon-cache ]; then
    /usr/bin/gtk-update-icon-cache -f -t %{_datadir}/icons/hicolor &>/dev/null || :
fi

# Update desktop database
if [ -x /usr/bin/update-desktop-database ]; then
    /usr/bin/update-desktop-database %{_datadir}/applications &>/dev/null || :
fi

%files
%defattr(-,root,root,-)
%{_libdir}/%{pkg_name}
%{_bindir}/%{pkg_name}
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/metainfo/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{app_id}.png

%changelog
SPECEOF

# Replace version placeholder
sed -i "s/VERSION_PLACEHOLDER/$VERSION/g" "$SPEC_FILE"

# Add changelog entry
CHANGELOG_DATE=$(date "+%a %b %d %Y")
echo "* $CHANGELOG_DATE MindType Team <support@mindtype.app> - $VERSION-1" >> "$SPEC_FILE"
echo "- Release version $VERSION" >> "$SPEC_FILE"

# Build RPM
echo ""
echo "Building RPM package..."
rpmbuild -bb "$SPEC_FILE"

# Find the built RPM
RPM_FILE=$(find "$RPM_BUILD_DIR/RPMS" -name "${PKG_NAME}-${VERSION}*.rpm" -type f | head -1)

if [ -f "$RPM_FILE" ]; then
    # Copy to dist directory
    cp "$RPM_FILE" "$DIST_DIR/"
    FINAL_RPM="$DIST_DIR/$(basename "$RPM_FILE")"

    SIZE=$(du -h "$FINAL_RPM" | cut -f1)
    echo ""
    echo -e "${GREEN}RPM package created successfully!${NC}"
    echo "File: $FINAL_RPM"
    echo "Size: $SIZE"
    echo ""
    echo "Install with:"
    echo "  Fedora: sudo dnf install $FINAL_RPM"
    echo "  CentOS/RHEL: sudo yum install $FINAL_RPM"
    echo ""
    echo -e "${CYAN}=== Done ===${NC}"
else
    echo -e "${RED}Error: RPM package was not created!${NC}"
    echo "Check rpmbuild output above for errors."
    exit 1
fi












