#!/usr/bin/env -S bash --norc --noprofile
# =============================================================================
# Claude Code Hook Wrapper
# =============================================================================
#
# PURPOSE:
# Claude Code hooks can return JSON with "additionalContext" to inject text
# into Claude's context. The existing claude-flow hooks just run commands
# without returning this JSON, so Claude never sees their output.
#
# This wrapper:
# 1. Runs any hook command passed to it
# 2. Captures its output
# 3. Returns proper JSON with additionalContext so Claude sees what happened
#
# WHY WE NEED THIS:
# We wanted to know when hooks fire and what they do. Without this wrapper,
# hooks run silently - Claude has no visibility into whether they executed.
# By wrapping hooks with this script, every hook execution becomes visible
# in Claude's context via the additionalContext field.
#
# USAGE:
#   wrap-hook.sh <hook-name> <command-to-run>
#
# EXAMPLE:
#   wrap-hook.sh "pre-edit" "npx claude-flow@alpha hooks pre-edit --file foo.py"
#
# =============================================================================

HOOK_NAME="$1"
HOOK_TYPE="$2"  # pre-bash, post-bash, pre-edit, post-edit, pre-read, session-end
shift 2

# Read stdin (JSON input from Claude Code)
INPUT=$(cat)

# Parse JSON based on hook type - centralized here instead of in settings.json
case "$HOOK_TYPE" in
  pre-bash|post-bash)
    CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    HOOK_CMD="npx claude-flow@alpha hooks ${HOOK_TYPE//-bash/}-command --command '$CMD' --validate-safety true --prepare-resources true"
    ;;
  pre-edit|post-edit)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')
    if [ "$HOOK_TYPE" = "pre-edit" ]; then
      HOOK_CMD="npx claude-flow@alpha hooks pre-edit --file '$FILE' --auto-assign-agents true --load-context true"
    else
      HOOK_CMD="npx claude-flow@alpha hooks post-edit --file '$FILE' --format true --update-memory true"
    fi
    ;;
  pre-read)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    HOOK_CMD="npx claude-flow@alpha hooks pre-read --file '$FILE' --load-context true"
    ;;
  session-end)
    HOOK_CMD="npx claude-flow@alpha hooks session-end --generate-summary true --persist-state true --export-metrics true"
    ;;
  *)
    # Fallback: use remaining args as command
    HOOK_CMD="$@"
    ;;
esac

# Run the actual hook command, capture both stdout and stderr
OUTPUT=$(eval "$HOOK_CMD" 2>&1)
EXIT_CODE=$?

# Return JSON based on hook type - different schemas for different hooks
case "$HOOK_TYPE" in
  session-end)
    # Stop hooks only support: continue, suppressOutput, stopReason
    cat <<EOF
{
  "continue": true
}
EOF
    ;;
  pre-bash|pre-edit|pre-read)
    # PreToolUse hooks
    cat <<EOF
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse"
  }
}
EOF
    ;;
  post-bash|post-edit)
    # PostToolUse hooks
    cat <<EOF
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "[HOOK: $HOOK_NAME] $OUTPUT"
  }
}
EOF
    ;;
  *)
    cat <<EOF
{
  "continue": true
}
EOF
    ;;
esac
