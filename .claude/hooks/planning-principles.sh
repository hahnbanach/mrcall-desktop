#!/usr/bin/env bash
# Claude Code Hook: Planning principles reminder
# Fires on PreToolUse for EnterPlanMode.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ "$TOOL_NAME" != "EnterPlanMode" ]]; then
  echo '{"decision": "approve"}'
  exit 0
fi

cat <<'EOF'
{
  "decision": "approve",
  "reason": "PLANNING PRINCIPLES:\n1. PREMATURE OPTIMIZATION IS THE ROOT OF ALL EVIL (Knuth). Start simple. Make it work first. Optimize only when measured.\n2. INTELLIGENCE IS WORTH THE COST. LLM over regex. Smart LLM over cheap LLM. Never downgrade the model on a critical path to save cents.\n3. No regex without user authorization.\n4. Plan must include documentation updates.\n5. The simplest thing that works is the right thing.\n6. NEVER add arbitrary limits (batch sizes, max results, truncation) that silently lose data. If a limit is needed, it must be documented and configurable."
}
EOF
exit 0
