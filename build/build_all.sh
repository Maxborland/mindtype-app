#!/bin/bash
# =============================================================================
# Universal build script for MindType (Linux/macOS)
# Supports all installer formats with Nuitka code obfuscation
# =============================================================================
# Usage: ./build/build_all.sh [options]
#
# Options:
#   --platform <linux|macos>    Target platform (default: current)
#   --version <X.Y.Z>           Version number (default: from app/env.py)
#   --format <format>           Installer format (see below)
#   --clean                     Clean previous builds
#   --help                      Show this help
#
# Formats:
#   all         Build all formats (default)
#   appimage    AppImage only (universal Linux)
#   deb         Debian/Ubuntu package only
#   rpm         Fedora/RHEL package only
#   flatpak     Flatpak bundle only
#   dmg         macOS DMG only
#   none        Binary only (no installer)
#
# Examples:
#   ./build/build_all.sh                           # All formats for current platform
#   ./build/build_all.sh --format appimage         # AppImage only
#   ./build/build_all.sh --format deb --clean      # DEB with clean build
#   ./build/build_all.sh --version 1.1.0           # Specific version

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$ROOT_DIR/dist"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
NC='\033[0m'

# Default values
PLATFORM=""
VERSION=""
FORMAT="all"
CLEAN=false

# Detect current platform
detect_platform() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "macos" ;;
        *)       echo "unknown" ;;
    esac
}

# Read version from app/env.py
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

# Show help
show_help() {
    head -40 "$0" | tail -35 | sed 's/^# //' | sed 's/^#//'
    exit 0
}

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --platform|-p)
            PLATFORM="$2"
            shift 2
            ;;
        --version|-v)
            VERSION="$2"
            shift 2
            ;;
        --format|-f)
            FORMAT="$2"
            shift 2
            ;;
        --clean|-c)
            CLEAN=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            # Legacy support: positional arguments
            if [ -z "$PLATFORM" ] && [[ "$1" =~ ^(linux|macos)$ ]]; then
                PLATFORM="$1"
            elif [ -z "$VERSION" ] && [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
                VERSION="$1"
            elif [ "$1" = "--clean" ]; then
                CLEAN=true
            else
                echo -e "${RED}Unknown argument: $1${NC}" >&2
                echo "Use --help for usage information"
                exit 1
            fi
            shift
            ;;
    esac
done

# Set defaults
CURRENT_PLATFORM=$(detect_platform)
[ -z "$PLATFORM" ] && PLATFORM="$CURRENT_PLATFORM"
[ -z "$VERSION" ] && VERSION=$(get_app_version)

# Validate format
case "$FORMAT" in
    all|appimage|deb|rpm|flatpak|dmg|none) ;;
    *)
        echo -e "${RED}Invalid format: $FORMAT${NC}" >&2
        echo "Valid formats: all, appimage, deb, rpm, flatpak, dmg, none"
        exit 1
        ;;
esac

# Header
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  MindType - Universal Build Script        ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "Current platform: $CURRENT_PLATFORM"
echo "Target platform:  $PLATFORM"
echo "Version:          $VERSION"
echo "Format:           $FORMAT"
echo "Clean build:      $(if $CLEAN; then echo 'Yes'; else echo 'No'; fi)"
echo ""

# Check platform compatibility
if [ "$PLATFORM" != "$CURRENT_PLATFORM" ]; then
    echo -e "${YELLOW}WARNING: Cross-platform build requested${NC}"
    echo ""

    case "$PLATFORM" in
        windows)
            echo "For Windows build, use PowerShell:"
            echo "  .\\build\\build_all.ps1 -Platform windows"
            ;;
        linux)
            echo "For Linux build on macOS, use Docker:"
            echo "  docker run --rm -v \"\$PWD:/workspace\" -w /workspace python:3.11 bash build/build_all.sh"
            ;;
        macos)
            echo "macOS build requires a Mac with Xcode."
            ;;
    esac
    echo ""
    exit 1
fi

# Track results
declare -A BUILD_RESULTS
BUILD_SUCCESS=true

# Function to run build step
run_step() {
    local step_name="$1"
    local script="$2"
    shift 2

    echo ""
    echo -e "${GREEN}=== $step_name ===${NC}"

    if [ -f "$script" ]; then
        chmod +x "$script"
        if "$script" "$@"; then
            BUILD_RESULTS["$step_name"]="Success"
            return 0
        else
            BUILD_RESULTS["$step_name"]="Failed"
            BUILD_SUCCESS=false
            return 1
        fi
    else
        echo -e "${RED}Script not found: $script${NC}"
        BUILD_RESULTS["$step_name"]="Script not found"
        BUILD_SUCCESS=false
        return 1
    fi
}

# Build binary with Nuitka
build_binary() {
    local build_script=""
    local args=()

    if [ "$PLATFORM" = "linux" ]; then
        build_script="$SCRIPT_DIR/build_linux_nuitka.sh"
    elif [ "$PLATFORM" = "macos" ]; then
        build_script="$SCRIPT_DIR/build_macos.sh"
    fi

    args+=("--version" "$VERSION")
    $CLEAN && args+=("--clean")

    run_step "Building binary (Nuitka)" "$build_script" "${args[@]}"
}

# Build installers based on format
build_installers() {
    local formats=()

    if [ "$FORMAT" = "all" ]; then
        if [ "$PLATFORM" = "linux" ]; then
            formats=("appimage" "deb" "rpm" "flatpak")
        elif [ "$PLATFORM" = "macos" ]; then
            formats=("dmg")
        fi
    elif [ "$FORMAT" != "none" ]; then
        formats=("$FORMAT")
    fi

    for fmt in "${formats[@]}"; do
        case "$fmt" in
            appimage)
                run_step "Creating AppImage" "$SCRIPT_DIR/installer/create_appimage.sh" "$VERSION" || true
                ;;
            deb)
                run_step "Creating DEB package" "$SCRIPT_DIR/installer/create_deb.sh" "$VERSION" || true
                ;;
            rpm)
                if command -v rpmbuild &> /dev/null; then
                    run_step "Creating RPM package" "$SCRIPT_DIR/installer/create_rpm.sh" "$VERSION" || true
                else
                    echo -e "${YELLOW}Skipping RPM: rpmbuild not installed${NC}"
                    BUILD_RESULTS["Creating RPM package"]="Skipped (no rpmbuild)"
                fi
                ;;
            flatpak)
                if command -v flatpak-builder &> /dev/null; then
                    run_step "Creating Flatpak" "$SCRIPT_DIR/installer/create_flatpak.sh" "$VERSION" || true
                else
                    echo -e "${YELLOW}Skipping Flatpak: flatpak-builder not installed${NC}"
                    BUILD_RESULTS["Creating Flatpak"]="Skipped (no flatpak-builder)"
                fi
                ;;
            dmg)
                run_step "Creating DMG" "$SCRIPT_DIR/installer/create_dmg.sh" "$VERSION" || true
                ;;
        esac
    done
}

# Main build process
echo -e "${CYAN}Starting build process...${NC}"

# Step 1: Build binary
if ! build_binary; then
    echo ""
    echo -e "${RED}Binary build failed! Aborting.${NC}"
    exit 1
fi

# Step 2: Build installers
if [ "$FORMAT" != "none" ]; then
    build_installers
fi

# Summary
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}           Build Summary                   ${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

for step in "${!BUILD_RESULTS[@]}"; do
    result="${BUILD_RESULTS[$step]}"
    if [ "$result" = "Success" ]; then
        echo -e "  ${GREEN}✓${NC} $step"
    elif [[ "$result" == Skipped* ]]; then
        echo -e "  ${YELLOW}○${NC} $step ($result)"
    else
        echo -e "  ${RED}✗${NC} $step ($result)"
    fi
done

echo ""

# List artifacts
if [ -d "$DIST_DIR" ]; then
    echo -e "${CYAN}Build artifacts:${NC}"
    echo ""

    # List files
    for file in "$DIST_DIR"/*.{exe,AppImage,deb,rpm,flatpak,dmg} 2>/dev/null; do
        if [ -f "$file" ]; then
            size=$(du -h "$file" | cut -f1)
            echo -e "  ${GREEN}•${NC} $(basename "$file") ($size)"
        fi
    done

    # List directories
    for dir in "$DIST_DIR"/MindType "$DIST_DIR"/OfflineWhisper.app 2>/dev/null; do
        if [ -d "$dir" ]; then
            size=$(du -sh "$dir" | cut -f1)
            echo -e "  ${GREEN}•${NC} $(basename "$dir")/ ($size)"
        fi
    done
fi

echo ""

# Final status
if $BUILD_SUCCESS; then
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}              Build Complete!              ${NC}"
    echo -e "${GREEN}============================================${NC}"
    exit 0
else
    echo -e "${YELLOW}============================================${NC}"
    echo -e "${YELLOW}     Build completed with some failures    ${NC}"
    echo -e "${YELLOW}============================================${NC}"
    exit 1
fi
