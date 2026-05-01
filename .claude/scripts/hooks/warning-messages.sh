#!/usr/bin/env bash
# Warning-messages hook for mrcall-desktop.
# Adapted from ~/hb/.claude/scripts/hooks/warning-messages.sh — scoped to this monorepo
# (Python engine at engine/, Electron app at app/, JSON-RPC stdio between them).
#
# Hooks invoking this script are notification-only. We never block tool use:
# all paths exit 0 even on parse errors, and the hooks in settings.json wrap
# the call with `|| true` defensively.
#
# Usage:
#   warning-messages.sh tdd-reminder <file-path>
#   warning-messages.sh push-quality
#   warning-messages.sh release-gate
#   warning-messages.sh file-written <file-path>

set -u  # NOT -e — never die on a soft error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${SCRIPT_DIR}/../../config"
MESSAGES_FILE="${CONFIG_DIR}/messages.toml"

# Default messages — used if config file or key is missing.
declare -A DEFAULT_MESSAGES=(
    ["tdd_reminder_python"]="No test file found for this Python module. Consider TDD — write a test under engine/tests/ first."
    ["tdd_reminder_ts"]="No test file found for this TypeScript module. Smoke-test the change in 'npm run dev' before declaring done."
    ["push_quality"]="Quality check before push: run 'cd engine && make lint' and 'cd app && npm run typecheck' as relevant. Don't bypass with --no-verify."
    ["release_gate"]="Release / notarize / publish detected. Run /release-checklist (Six Gates) before tagging. Notarize via afterSign, not mac.notarize."
    ["file_written"]="File written: %s"
    ["ipc_reminder"]="This file lives on the JSON-RPC boundary. If you changed a method name, payload shape, or error envelope, both engine/ and app/ must move together — pull in ipc-contract-reviewer."
)

# Look up a key from messages.toml, fall back to default.
get_config_message() {
    local key="$1"
    local default="${DEFAULT_MESSAGES[$key]:-}"

    if [[ -f "$MESSAGES_FILE" ]]; then
        local value
        value=$(grep -E "^${key}[[:space:]]*=" "$MESSAGES_FILE" 2>/dev/null \
                | head -1 \
                | sed -E 's/^[^=]+=[[:space:]]*"?([^"]*)"?[[:space:]]*$/\1/')
        if [[ -n "$value" ]]; then
            echo "$value"
            return 0
        fi
    fi

    echo "$default"
}

# Is this an engine Python source file under engine/zylch/ ?
is_engine_python() {
    local path="$1"
    [[ "$path" == *"/engine/zylch/"* || "$path" == "engine/zylch/"* ]] && [[ "$path" == *.py ]]
}

# Is this an app TypeScript source file under app/src/ ?
is_app_ts() {
    local path="$1"
    [[ "$path" == *"/app/src/"* || "$path" == "app/src/"* ]] && [[ "$path" == *.ts || "$path" == *.tsx ]]
}

# Does this file likely live on the IPC boundary?
is_ipc_boundary() {
    local path="$1"
    case "$path" in
        */app/src/main/rpc*|app/src/main/rpc*)         return 0 ;;
        */app/src/main/sidecar*|app/src/main/sidecar*) return 0 ;;
        */app/src/preload/*|app/src/preload/*)         return 0 ;;
        */engine/zylch/rpc/*|engine/zylch/rpc/*)       return 0 ;;
        */engine/zylch/rpc.py|engine/zylch/rpc.py)     return 0 ;;
    esac
    return 1
}

tdd_reminder() {
    local file_path="${1:-}"
    [[ -z "$file_path" ]] && return 0

    if is_engine_python "$file_path"; then
        # engine convention: tests/test_<module>.py mirrors zylch/<module>.py
        local module
        module="$(basename "$file_path" .py)"
        local test_candidate="engine/tests/test_${module}.py"
        if [[ ! -f "$test_candidate" ]]; then
            local msg
            msg=$(get_config_message "tdd_reminder_python")
            echo "[mrcall-desktop hook] $msg"
        fi
    elif is_app_ts "$file_path"; then
        # The app does not (yet) have a unit test harness. Just remind on smoke-test.
        local msg
        msg=$(get_config_message "tdd_reminder_ts")
        echo "[mrcall-desktop hook] $msg"
    fi

    # Independent of TDD: if this is the IPC boundary, surface the contract reminder.
    if is_ipc_boundary "$file_path"; then
        local msg
        msg=$(get_config_message "ipc_reminder")
        echo "[mrcall-desktop hook] $msg"
    fi

    return 0
}

push_quality() {
    local msg
    msg=$(get_config_message "push_quality")
    echo "[mrcall-desktop hook] $msg"
}

release_gate() {
    local msg
    msg=$(get_config_message "release_gate")
    echo "[mrcall-desktop hook] $msg"
}

file_written() {
    local file_path="${1:-}"
    [[ -z "$file_path" ]] && return 0
    local fmt
    fmt=$(get_config_message "file_written")
    # shellcheck disable=SC2059
    printf "[mrcall-desktop hook] $fmt\n" "$file_path"
}

main() {
    local cmd="${1:-}"
    shift || true
    case "$cmd" in
        tdd-reminder)  tdd_reminder "$@" ;;
        push-quality)  push_quality ;;
        release-gate)  release_gate ;;
        file-written)  file_written "$@" ;;
        "")            return 0 ;;
        *)             return 0 ;;  # unknown command — silent, never block
    esac
    return 0
}

main "$@" || true
exit 0
