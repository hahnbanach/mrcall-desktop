# Claude Code Configuration

This document explains the Claude Code hooks and settings configured for this project.

## Configuration Files

- `.claude/settings.json` - Main configuration (hooks, permissions, MCP servers)
- `.claude/hooks/wrap-hook.sh` - Centralized hook wrapper script
- `.claude/hooks/detect-namespace.sh` - Auto-detects memory namespace from file paths

## Hooks Architecture

All hooks are routed through a single wrapper script (`wrap-hook.sh`) that:

1. Receives hook type as argument
2. Reads JSON input from stdin (provided by Claude Code)
3. Parses relevant fields based on hook type
4. Executes the appropriate `claude-flow` command
5. Returns correctly-formatted JSON for each hook type

### Why a Wrapper?

- **Centralized JSON parsing** - Instead of duplicating `jq` parsing in every hook command in settings.json, the wrapper handles it once
- **Correct schema per hook type** - Different hooks (PreToolUse, PostToolUse, Stop) require different JSON response schemas
- **Clean shell execution** - Uses `bash --noprofile --norc` to avoid loading user shell profiles

### Hook Types Configured

| Hook | Trigger | Purpose |
|------|---------|---------|
| pre-bash | Before Bash commands | Safety validation, resource preparation |
| post-bash | After Bash commands | Metrics tracking, result storage |
| pre-edit | Before Write/Edit/MultiEdit | Auto-assign agents, load context |
| post-edit | After Write/Edit/MultiEdit | Format code, update memory |
| pre-read | Before Read | Load context |
| detect-namespace | After Read/Write/Edit | Injects memory namespace context |
| session-end | On Stop | Generate summary, persist state, export metrics |

### JSON Response Schemas

Each hook type requires a specific JSON response format:

**PreToolUse hooks:**
```json
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse"
  }
}
```

**PostToolUse hooks:**
```json
{
  "continue": true,
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "[HOOK: hook-name] output here"
  }
}
```

**Stop hooks:**
```json
{
  "continue": true
}
```

## Namespace Detection Hook

The `detect-namespace.sh` hook automatically injects the correct claude-flow memory namespace based on file paths. This runs as a PostToolUse hook on Read/Write/Edit operations.

### Namespace Mappings

| Path Pattern | Namespace | Project |
|--------------|-----------|---------|
| `/hb/zylch-cli/` | `zylch-cli` | Zylch CLI |
| `/hb/zylch/frontend/` | `zylch-frontend` | Zylch Frontend |
| `/hb/zylch/zylch_memory/` | `zylch-memory` | Zylch Memory System |
| `/hb/zylch/.claude/` | `zylch-planning` | Zylch Planning/Config |
| `/hb/zylch/spec/` | `zylch-research` | Zylch Research |
| `/hb/zylch/` (other) | `zylch` | Zylch Backend |
| `/hb/<folder>/` | `<folder>` | Auto-detected |
| Other | `default` | Default |

The hook outputs `additionalContext` reminding Claude to use the detected namespace for memory operations.

## Shell Profile Loading

**Important:** Claude Code's Bash tool executes commands using your default shell with profile loading enabled. This means you'll see output from `.bashrc`/`.zshrc` (e.g., "Reading pCloud profile") before command output.

This is Claude Code behavior, not controllable from configuration. The hooks themselves use `bash --noprofile --norc` to avoid this overhead, but the Bash tool does not.

## Permissions

The `permissions` section in settings.json defines allowed and denied commands:

```json
{
  "allow": [
    "Bash(npx claude-flow:*)",
    "Bash(git status)",
    "Bash(git diff:*)",
    // ... etc
  ],
  "deny": [
    "Bash(rm -rf /)"
  ]
}
```

## MCP Servers

Enabled MCP servers:
- `claude-flow` - Swarm orchestration, memory, task management
- `ruv-swarm` - Additional swarm capabilities

## Environment Variables

Set in `settings.json` under `env`:

| Variable | Value | Purpose |
|----------|-------|---------|
| `CLAUDE_FLOW_AUTO_COMMIT` | false | Don't auto-commit changes |
| `CLAUDE_FLOW_AUTO_PUSH` | false | Don't auto-push to remote |
| `CLAUDE_FLOW_HOOKS_ENABLED` | true | Enable claude-flow hooks |
| `CLAUDE_FLOW_TELEMETRY_ENABLED` | true | Enable telemetry |
| `CLAUDE_FLOW_REMOTE_EXECUTION` | true | Allow remote execution |
| `CLAUDE_FLOW_CHECKPOINTS_ENABLED` | true | Enable checkpoints |

## Modifying Hooks

To add a new hook:

1. Add the hook type handling in `.claude/hooks/wrap-hook.sh` (in the `case` statement)
2. Add the matcher and command in `.claude/settings.json`
3. Ensure the JSON response matches the expected schema for that hook type

Example for adding a new PreToolUse hook:

```json
{
  "matcher": "ToolName",
  "hooks": [
    {
      "type": "command",
      "command": "bash --noprofile --norc .claude/hooks/wrap-hook.sh 'pre-toolname' 'pre-toolname'"
    }
  ]
}
```

Then add handling in wrap-hook.sh:
```bash
pre-toolname)
  FIELD=$(echo "$INPUT" | jq -r '.tool_input.field // empty')
  HOOK_CMD="npx claude-flow@alpha hooks pre-toolname --field '$FIELD'"
  ;;
```
