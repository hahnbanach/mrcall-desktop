#!/usr/bin/env bash
# Launch MrCall Desktop in dev mode from this monorepo checkout.
#
# Wires the Electron app at `app/` to the local Python sidecar at
# `engine/venv/bin/zylch` via the ZYLCH_BINARY env var (the app's
# default fallback points at the legacy ~/private/zylch-standalone
# layout, which doesn't exist here).
#
# Usage:
#   scripts/dev.sh                          # current profile (whatever ZYLCH_PROFILE is, or the hardcoded default)
#   ZYLCH_PROFILE=user@example.com scripts/dev.sh
#
# Prereqs (one-time):
#   cd engine && python3.11 -m venv venv && venv/bin/pip install -e .
#   cd app && npm ci

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_BIN="$REPO_ROOT/engine/venv/bin/zylch"
APP_DIR="$REPO_ROOT/app"

if [[ ! -x "$ENGINE_BIN" ]]; then
  echo "Engine binary not found or not executable: $ENGINE_BIN" >&2
  echo "Bootstrap with:  cd engine && python3.11 -m venv venv && venv/bin/pip install -e ." >&2
  exit 1
fi

if [[ ! -d "$APP_DIR/node_modules" ]]; then
  echo "App deps not installed. Run: cd app && npm ci" >&2
  exit 1
fi

export ZYLCH_BINARY="$ENGINE_BIN"
# ZYLCH_CWD only matters if the sidecar locates anything relative to cwd
# (it doesn't — it uses ~/.zylch). Set it to the repo root for log
# clarity / future scripts that key off it.
export ZYLCH_CWD="$REPO_ROOT"

# python-magic (transitively imported by neonize) loads libmagic.dylib
# via ctypes. macOS standard search paths don't include Homebrew's, so
# add /opt/homebrew/lib (Apple Silicon) and /usr/local/lib (Intel /
# manual installs) as a fallback. Belt + suspenders alongside the
# python-magic >=0.4.27 pin in pyproject.toml; harmless if libmagic
# was installed elsewhere.
if [[ "$OSTYPE" == darwin* ]]; then
  export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
fi

echo "[dev.sh] ZYLCH_BINARY=$ZYLCH_BINARY"
echo "[dev.sh] ZYLCH_PROFILE=${ZYLCH_PROFILE:-<unset, app picks default>}"
echo "[dev.sh] cd $APP_DIR && npm run dev"

cd "$APP_DIR"
exec npm run dev
