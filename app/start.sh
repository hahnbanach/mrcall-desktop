#!/usr/bin/env bash
# Start Zylch Desktop in dev mode.
# Expects zylch and zylch-desktop repos side by side:
#   parent/
#   ├── zylch/           (the CLI repo)
#   └── zylch-desktop/   (this repo)
#
# Usage:
#   ./start.sh                              # auto-selects profile if only one
#   ./start.sh mario.alemi@cafe124.it       # explicit profile

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ZYLCH_DIR="$(cd "$DIR/../zylch" && pwd)"

if [ ! -f "$ZYLCH_DIR/venv/bin/zylch" ]; then
    echo "Error: $ZYLCH_DIR/venv/bin/zylch not found."
    echo "Run: cd $ZYLCH_DIR && python3 -m venv venv && source venv/bin/activate && pip install -e ."
    exit 1
fi

echo ">> git pull $(basename "$ZYLCH_DIR")"
git -C "$ZYLCH_DIR" pull --ff-only
echo ">> git pull $(basename "$DIR")"
git -C "$DIR" pull --ff-only

PROFILE="${1:-}"

cd "$DIR"
ZYLCH_CWD="$ZYLCH_DIR" \
ZYLCH_BINARY="$ZYLCH_DIR/venv/bin/zylch" \
LOG_LEVEL="${LOG_LEVEL:-DEBUG}" \
${PROFILE:+ZYLCH_PROFILE="$PROFILE"} \
npm run dev
