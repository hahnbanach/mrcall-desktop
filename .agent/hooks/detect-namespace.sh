#!/bin/bash --norc --noprofile
# Claude Code Hook: Auto-detect memory namespace from file paths
# This hook runs on Read/Write/Edit operations (PostToolUse) and injects
# the appropriate memory namespace into Claude's context.

# Read JSON input from stdin
INPUT=$(cat)

# Extract file path from tool input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# If no file path, exit silently
if [[ -z "$FILE_PATH" ]]; then
  echo '{"continue": true, "hookSpecificOutput": {"hookEventName": "PostToolUse"}}'
  exit 0
fi

# Detect namespace from file path
# Add more patterns here as needed
if [[ $FILE_PATH == *"/hb/zylch-cli/"* ]]; then
  NAMESPACE="zylch-cli"
  PROJECT="Zylch CLI"
elif [[ $FILE_PATH == *"/hb/zylch/frontend/"* ]]; then
  NAMESPACE="zylch-frontend"
  PROJECT="Zylch Frontend"
elif [[ $FILE_PATH == *"/hb/zylch/zylch_memory/"* ]]; then
  NAMESPACE="zylch-memory"
  PROJECT="Zylch Memory System"
elif [[ $FILE_PATH == *"/hb/zylch/.claude/"* ]]; then
  NAMESPACE="zylch-planning"
  PROJECT="Zylch Planning/Config"
elif [[ $FILE_PATH == *"/hb/zylch/spec/"* ]]; then
  NAMESPACE="zylch-research"
  PROJECT="Zylch Research"
elif [[ $FILE_PATH == *"/hb/zylch/"* ]]; then
  NAMESPACE="zylch"
  PROJECT="Zylch Backend"
else
  # Default - try to extract folder name from /hb/<project>/
  NAMESPACE=$(echo "$FILE_PATH" | sed -n 's|.*/hb/\([^/]*\)/.*|\1|p')
  if [[ -z "$NAMESPACE" ]]; then
    NAMESPACE="default"
  fi
  PROJECT="$NAMESPACE"
fi

# Output context for Claude (PostToolUse schema)
cat <<EOF
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "[NAMESPACE: $NAMESPACE] Use this namespace for claude-flow memory operations. Project: $PROJECT"
  }
}
EOF

exit 0
