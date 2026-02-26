# Using Claude Flow with Claude Code

## Installation

Claude Flow is distributed as an npm package. We use `npx` to run it without global installation, ensuring we always get the latest version:

```bash
npx @claude-flow/cli@latest <command>
```

For convenience, add an alias:

```bash
alias cf='npx @claude-flow/cli@latest'
```

## Core Components

Claude Flow has three main runtime components:

| Component | Purpose | How to start |
|-----------|---------|--------------|
| **Daemon** | Background worker that manages state, tasks, and coordination | `cf daemon start` |
| **MCP Server** | Exposes tools to Claude Code via JSON-RPC | Registered with Claude Code |
| **CLI** | Direct command-line interface | `cf <command>` |

## Setting Up the Daemon

The daemon runs in the background and manages persistent state. Start it with:

```bash
cf daemon start
```

Verify it's running:

```bash
cf status
```

If status shows `[STOPPED]` but you know the daemon is running, use:

```bash
ps aux | grep claude-flow
```

The status command shows the state of all components: swarm, agents, tasks, memory, and MCP server.

## Integrating with Claude Code

To enable Claude Code to call claude-flow tools directly (instead of via Bash), register it as an MCP server:

```bash
claude mcp add claude-flow -- npx @claude-flow/cli@latest mcp start --quiet
```

This command:
1. Registers a server named "claude-flow" with Claude Code
2. When Claude Code starts, it executes the command after `--`
3. The `--quiet` flag suppresses non-JSON output that would break the protocol

**Important**: This registers the MCP server for the current project only (local scope). This is intentional: claude-flow reads its configuration from `.claude-flow/` in the current directory. Registering it globally would cause errors in projects without a `.claude-flow/` setup.

Verify registration:

```bash
claude mcp list
```

To remove the registration:

```bash
claude mcp remove claude-flow -s local
claude mcp remove claude-flow -s project
```

## Project Initialization

Initialize claude-flow in your project directory:

```bash
cf init --wizard
```

This creates the `.claude-flow/` directory with:
- `config.yaml` - Runtime configuration
- `data/` - Memory storage
- `tasks/` - Task persistence
- `daemon.log` - Daemon logs

## Common Commands

### Status and Health

```bash
cf status              # Show system status
cf status --health-check   # Run health checks
cf doctor              # Diagnose issues
```

### Memory Operations

```bash
cf memory store --key "my-key" --value "my-value"
cf memory store --key "my-key" --value "my-value" --namespace patterns
cf memory retrieve --key "my-key"
cf memory search --query "search terms"
cf memory list
```

### Task Management

```bash
cf task create --type bug-fix --description "Fix the login bug"
cf task list
cf task update --task-id <id> --status in_progress
cf task complete --task-id <id>
```

### Swarm Coordination

```bash
cf swarm init --topology hierarchical --max-agents 8
cf swarm status
cf agent spawn -t coder --name my-coder
cf agent list
```

### Daemon Control

```bash
cf daemon start    # Start background daemon
cf daemon stop     # Stop daemon
cf daemon status   # Check daemon status
```

## How MCP Integration Works

Without MCP server (CLI mode):
```
User → Claude Code → Bash("cf status") → text output → Claude parses text
```

With MCP server registered:
```
User → Claude Code → mcp__claude-flow__swarm_status({}) → structured JSON
```

Benefits of MCP integration:
- Structured data instead of text parsing
- Direct function calls without process spawning
- Better integration with Claude Code's tool system

## Using Claude Flow in Claude Code (Natural Language)

Once the MCP server is registered, you don't need to type commands. You write natural language prompts and Claude Code translates them into MCP tool calls.

### Example: Analyzing a Branch with Multiple Agents

**Step 1: Initialize coordination**

You write:
```
Initialize a swarm to coordinate the analysis. Use hierarchical topology with max 8 agents.
```

Claude Code understands this and calls `mcp__claude-flow__swarm_init` with the right parameters. You don't need to know the tool name.

**Step 2: Launch the analysis**

You write:
```
Analyze the agent orchestration changes in this branch. Check:
1. Documentation is up to date
2. Dependent features still work
3. Code follows international standards (i18n)

Spawn separate agents for each task and give me a report.
```

Claude Code understands it needs to:
- Create agents (calls `mcp__claude-flow__agent_spawn` or uses the Task tool)
- Assign tasks
- Coordinate the work
- Return a report

**Step 3: Monitor progress**

You write:
```
What's the analysis status? Show me the swarm status.
```

Claude Code calls `mcp__claude-flow__swarm_status` and shows you what's happening.

### Translation Table

| You write (natural language) | Claude Code does (MCP call) |
|------------------------------|----------------------------|
| "initialize hierarchical swarm" | `mcp__claude-flow__swarm_init({topology: "hierarchical"})` |
| "analyze the branch with 4 agents" | spawns agents, creates tasks, coordinates |
| "what's the status?" | `mcp__claude-flow__swarm_status()` |
| "store this pattern in memory" | `mcp__claude-flow__memory_store({key, value})` |
| "search memory for auth patterns" | `mcp__claude-flow__memory_search({query: "auth"})` |

**You speak natural language. Claude Code translates to MCP calls.**

## Memory Management

Memory is for storing concepts, decisions, and patterns - not file contents or implementation details.

### What to Store

**Store:**
- Architectural decisions ("We use JWT instead of sessions because X")
- Patterns that work ("For retries we use exponential backoff")
- Mistakes to avoid ("Don't use library X, it has bug Y")
- Project conventions ("API always in English, UI is i18n")

**Don't store:**
- File contents (they change)
- Transient implementation details
- Anything you can read from the code

### Using Namespaces

Organize memory with namespaces:

| Namespace | What goes there |
|-----------|-----------------|
| `decisions` | Architectural choices and their rationale |
| `patterns` | Reusable patterns that work |
| `avoid` | Things that don't work, mistakes to not repeat |
| `conventions` | Project standards and rules |

**In Claude Code:**
```
Store in memory (namespace: decisions): We use event-driven architecture for agent orchestration because it scales better than direct calls.
```

**CLI equivalent:**
```bash
cf memory store --namespace decisions --key "orchestration-style" --value "Event-driven via AgentBus for scalability"
```

### Updating Memory When Architecture Changes

When you change something significant, don't keep old details. Overwrite with the new state plus a note about what changed:

**In Claude Code:**
```
Search memory for everything about orchestration.
Update it: we now use AgentBus (event-driven) instead of direct calls.
Delete obsolete details, keep only the concept of what changed and why.
```

Nothing is saved automatically. You (or Claude) must explicitly save.

## Checkpoints (Git-Based Snapshots)

Checkpoints are automatic git snapshots that allow you to rollback if something goes wrong. They are **NOT** per-edit - that would be unusable.

### When Checkpoints Are Created

| Trigger | What happens | Frequency |
|---------|--------------|-----------|
| **Task completion** | When an agent finishes work, ONE checkpoint is created | Per task |
| **Session end** | When you exit Claude, ONE final checkpoint | Per session |
| **Batch edits** | Multiple edits are batched into ONE commit | Automatic |

**Example: A refactoring with 50 edits:**
- 50 edits → batched into periodic commits (NOT 50 separate commits)
- Task finishes → ONE checkpoint with tag `checkpoint-YYYYMMDD-HHMMSS`
- Session ends → ONE final checkpoint with tag `session-end-YYYYMMDD-HHMMSS`

**Result: 50 edits = 2-3 checkpoints, NOT 50**

### How It Works Technically

Checkpoints use git branches and tags:

| Type | Git object | Purpose |
|------|------------|---------|
| Pre-edit | Branch | Snapshot before changes (for recovery) |
| Post-edit | Tag | Snapshot after changes (for reference) |
| Task | Commit + metadata | Groups all work from one agent |
| Session | Tag | Final state when you exit |

The `frequency: "after-significant-change"` setting means:
- Task completion = significant change ✓
- Session end = significant change ✓
- Individual Edit = NOT significant (batched instead)

### Rolling Back

**In Claude Code:**
```
Something went wrong. Show me the recent checkpoints and rollback to before the refactoring.
```

**CLI equivalent:**
```bash
# List all checkpoints
git tag -l 'checkpoint-*' | sort -r

# View what changed in a checkpoint
git show checkpoint-20240115-143022

# Rollback to a checkpoint (keeps history)
git checkout checkpoint-20240115-143022

# Hard reset to a checkpoint (destructive, loses later work)
git reset --hard checkpoint-20240115-143022
```

### Checkpoint Metadata

Each checkpoint stores metadata in `.claude/checkpoints/`:

```json
{
  "tag": "checkpoint-20240115-143022",
  "file": "src/auth/login.ts",
  "timestamp": "2024-01-15T14:30:22Z",
  "type": "post-edit",
  "branch": "feature/auth",
  "diff_summary": "2 files changed, 45 insertions(+), 12 deletions(-)"
}
```

### Enabling Checkpoints

Checkpoints are configured in `.claude/settings.json`:

```json
{
  "checkpointManager": {
    "enabled": true,
    "autoCommit": true,
    "frequency": "after-significant-change"
  }
}
```

The hooks in `settings.json` trigger checkpoints automatically:
- `PostToolUse` for Task → calls `checkpoint-manager.sh agent-checkpoint`
- `SessionEnd` → calls `checkpoint-manager.sh session-end`

## Hooks (Automated Triggers)

Hooks are shell commands that run automatically at specific events. They enable:
- Checkpoint creation
- Learning from successes/failures
- Agent routing optimization
- Session state persistence

### Hook Types

| Hook | When it fires | Use case |
|------|---------------|----------|
| `PreToolUse` | Before Edit, Bash, Task, etc. | Guidance, risk assessment |
| `PostToolUse` | After successful tool use | Learning, checkpoints, metrics |
| `PostToolUseFailure` | After failed tool use | Learn from failures |
| `SessionStart` | When Claude starts | Restore context, start daemon |
| `SessionEnd` | When Claude exits | Save state, create checkpoint |
| `UserPromptSubmit` | When you send a message | Route to optimal agent |

### Configuring Hooks

Hooks are defined in `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Task",
        "hooks": [
          {
            "type": "command",
            "timeout": 4000,
            "command": "cf hooks post-task --task-id \"$TOOL_INPUT_prompt\" --success true"
          }
        ]
      }
    ]
  }
}
```

### Background Workers

Claude-flow has 12 background workers that can be triggered via hooks:

| Worker | What it does |
|--------|--------------|
| `map` | Creates codebase structure map |
| `optimize` | Performance optimization |
| `audit` | Security analysis |
| `testgaps` | Find missing test coverage |
| `document` | Auto-documentation |
| `deepdive` | Deep code analysis |
| `consolidate` | Memory consolidation |

**In Claude Code:**
```
Run the security audit worker on this codebase.
```

**CLI equivalent:**
```bash
cf hooks worker dispatch --trigger audit
```

## Full Project Sync with Swarm

Periodically, you may want to sync documentation and memory with the actual codebase. Use a swarm for parallel analysis:

**In Claude Code:**
```
Initialize a hierarchical swarm and do a full project sync:

Spawn these agents:
1. Researcher: analyze all code in the project
2. Documenter: update the files in docs/ based on the analysis
3. Memory-manager: extract key concepts and save them to memory

Coordinate them and give me a report of what changed.
```

This will:
1. Create the swarm (`mcp__claude-flow__swarm_init`)
2. Spawn 3 parallel agents (`mcp__claude-flow__agent_spawn` x3)
3. Create tasks for each
4. Coordinate their work
5. Return a consolidated report

### When to Use Swarm vs Single Claude

| Situation | Use |
|-----------|-----|
| Large parallelizable task (analyze 10 modules) | Swarm |
| Need specialization (one analyzes, one writes, one reviews) | Swarm |
| Sequential task | Single Claude |
| Small task | Single Claude |
| Want direct control | Single Claude |

## Codebase Map

The "map" worker creates a high-level representation of the codebase structure. Agents use this to understand where things are without reading every file.

**What the map contains:**
- Directory structure
- Entry points
- Key modules and their responsibilities
- Dependencies between modules

**What it doesn't contain:**
- File contents
- Specific implementations

### Generating the Map

**In Claude Code:**
```
Generate a codebase map and save it to memory.
```

**CLI equivalent:**
```bash
cf hooks worker dispatch --trigger map
```

### When to Update the Map

Update after significant structural changes:
- New modules added
- Directories reorganized
- Major refactoring

**In Claude Code:**
```
The codebase structure changed. Update the codebase map.
```

## Troubleshooting

### Status shows STOPPED but daemon is running

This is a known bug in alpha versions. The status command may fail if any MCP tool returns an error.

1. Check if daemon process exists: `ps aux | grep claude-flow`
2. Restart daemon: `cf daemon stop --force && cf daemon start`

### MCP server fails to connect

1. Verify registration: `claude mcp list`
2. Check error log: `cat /tmp/claude-flow-errors.log`
3. Re-register: remove and add again

### Kill all processes and start fresh

```bash
pkill -f "claude-flow"
cf daemon start
```

### Checkpoints not being created

1. Verify git is initialized in your project
2. Check `.claude/settings.json` has `checkpointManager.enabled: true`
3. Ensure hooks are configured for `PostToolUse` and `SessionEnd`

## Quick Reference

| Task | Natural Language | CLI |
|------|------------------|-----|
| Start daemon | "Start the claude-flow daemon" | `cf daemon start` |
| Check status | "What's the system status?" | `cf status` |
| Store pattern | "Store in memory: we use X for Y" | `cf memory store --key x --value y` |
| Search memory | "Search memory for auth patterns" | `cf memory search --query "auth"` |
| Spawn swarm | "Initialize swarm with 4 agents" | `cf swarm init --max-agents 4` |
| Run worker | "Run the security audit" | `cf hooks worker dispatch --trigger audit` |
| List checkpoints | "Show recent checkpoints" | `git tag -l 'checkpoint-*' \| sort -r` |
| Rollback | "Rollback to before the refactoring" | `git checkout checkpoint-YYYYMMDD-HHMMSS` |
