#!/usr/bin/env bash
#
# Zylch uninstaller
#   curl -sL https://raw.githubusercontent.com/malemi/zylch/main/scripts/uninstall.sh | bash
#
set -euo pipefail

echo ""
echo "  Zylch — Uninstall"
echo "  =================="
echo ""

# ── Remove binary ────────────────────────────────────

BINARY="/usr/local/bin/zylch"
if [ -f "$BINARY" ]; then
    if [ -w "$BINARY" ]; then
        rm "$BINARY"
    else
        sudo rm "$BINARY"
    fi
    echo "  Removed $BINARY"
else
    # Try pipx
    if command -v pipx &>/dev/null && pipx list 2>/dev/null | grep -q zylch; then
        pipx uninstall zylch
        echo "  Removed via pipx"
    elif command -v pip &>/dev/null && pip show zylch &>/dev/null 2>&1; then
        pip uninstall -y zylch
        echo "  Removed via pip"
    else
        echo "  Binary not found at $BINARY"
    fi
fi

# ── Ask about data ───────────────────────────────────

DATA_DIR="$HOME/.zylch"
if [ -d "$DATA_DIR" ]; then
    echo ""
    echo "  Data directory: $DATA_DIR"
    echo "  Contains: profiles, databases, WhatsApp sessions"
    echo ""
    read -p "  Delete all data? This cannot be undone. [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$DATA_DIR"
        echo "  Deleted $DATA_DIR"
    else
        echo "  Kept $DATA_DIR"
    fi
fi

echo ""
echo "  Done."
echo ""
