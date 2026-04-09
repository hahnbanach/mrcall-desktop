#!/usr/bin/env bash
#
# Zylch installer — one-line install:
#   curl -sL https://zylchai.com/install.sh | bash
#
set -euo pipefail

echo ""
echo "  Zylch — Sales Intelligence"
echo "  ======================================"
echo ""

# ── Detect OS and architecture ────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)  PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *)      echo "  Unsupported OS: $OS"; exit 1 ;;
esac

case "$ARCH" in
    x86_64|amd64)  ARCH="x64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *)             echo "  Unsupported architecture: $ARCH"; exit 1 ;;
esac

BINARY="zylch-${PLATFORM}-${ARCH}"
INSTALL_DIR="/usr/local/bin"
URL="https://github.com/malemi/zylch/releases/latest/download/${BINARY}"

echo "  Platform: ${PLATFORM} ${ARCH}"

# Get latest version
VERSION=$(curl -sfL "https://api.github.com/repos/malemi/zylch/releases/latest" 2>/dev/null | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"//;s/".*//')
if [ -n "$VERSION" ]; then
    echo "  Version:  ${VERSION}"
else
    echo "  Version:  latest"
fi

# ── Download binary ───────────────────────────────────

echo "  Downloading zylch..."
TMP="$(mktemp)"
if command -v curl &>/dev/null; then
    curl -sfL -o "$TMP" "$URL" || {
        echo "  Download failed. No release found for ${BINARY}."
        echo "  Check: https://github.com/malemi/zylch/releases"
        echo ""
        echo "  Alternative install (requires Python 3.11+):"
        echo "    pip install zylch"
        rm -f "$TMP"
        exit 1
    }
elif command -v wget &>/dev/null; then
    wget -q -O "$TMP" "$URL" || {
        echo "  Download failed. Check https://github.com/malemi/zylch/releases"
        rm -f "$TMP"
        exit 1
    }
else
    echo "  curl or wget required"
    exit 1
fi

# ── Install ───────────────────────────────────────────

chmod +x "$TMP"

# Detect install vs upgrade
ACTION="Installed"
if [ -f "$INSTALL_DIR/zylch" ]; then
    ACTION="Updated"
fi

if [ -w "$INSTALL_DIR" ]; then
    mv "$TMP" "$INSTALL_DIR/zylch"
else
    echo "  Installing to $INSTALL_DIR (needs sudo)..."
    sudo mv "$TMP" "$INSTALL_DIR/zylch"
fi

echo ""
echo "  $ACTION! Run:"
echo ""
if [ "$ACTION" = "Installed" ]; then
    echo "    zylch init"
else
    echo "    zylch --help"
fi
echo ""
