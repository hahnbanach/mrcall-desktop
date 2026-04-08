#!/usr/bin/env bash
#
# Zylch installer — one-line install:
#   curl -sL https://zylchai.com/install.sh | bash
#
set -euo pipefail

echo ""
echo "  Zylch — AI-powered sales intelligence"
echo "  ======================================"
echo ""

# ── Check Python ──────────────────────────────────────

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            echo "  Found $cmd $version"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  Python 3.11+ is required but not found."
    echo ""
    echo "  Install Python:"
    echo "    macOS:   brew install python@3.12"
    echo "    Ubuntu:  sudo apt install python3.12"
    echo "    Windows: https://python.org/downloads"
    echo ""
    exit 1
fi

# ── Install pipx if missing ───────────────────────────

if ! command -v pipx &>/dev/null; then
    echo "  Installing pipx..."
    "$PYTHON" -m pip install --user pipx --quiet 2>/dev/null || {
        echo "  pip install pipx failed. Trying with apt..."
        if command -v apt &>/dev/null; then
            sudo apt install -y pipx 2>/dev/null
        elif command -v brew &>/dev/null; then
            brew install pipx 2>/dev/null
        else
            echo "  Could not install pipx. Install it manually:"
            echo "    https://pipx.pypa.io/stable/installation/"
            exit 1
        fi
    }
    "$PYTHON" -m pipx ensurepath 2>/dev/null || true
    echo "  pipx installed."
fi

# ── Install zylch ─────────────────────────────────────

echo "  Installing zylch..."
pipx install zylch --python "$PYTHON" 2>/dev/null || {
    # If already installed, upgrade
    pipx upgrade zylch 2>/dev/null || true
}

echo ""
echo "  Done! Run:"
echo ""
echo "    zylch init"
echo ""
