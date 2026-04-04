---
description: |
  CLI command reference for Zylch standalone. Click commands (zylch sync, tasks, status)
  and slash commands in interactive chat (/sync, /tasks, /email, /memory).
  Semantic command matching via fastembed (no LLM API calls for routing).
---

# CLI Commands Reference

## Terminal Commands

```bash
zylch              # Start interactive chat (REPL)
zylch init         # Setup wizard (writes ~/.zylch/.env)
zylch sync         # Sync emails via IMAP
zylch tasks        # Show actionable tasks
zylch status       # Show sync status
```

## Interactive Chat (REPL)

Start with `zylch` (no arguments). Supports slash commands and natural language.

### Semantic Command Matching

Natural language is matched to commands using fastembed (no LLM API calls):

| Natural Language | Command | Score |
|-----------------|---------|-------|
| "sync" | `/sync` | 0.93 |
| "synchronize with the past 2 days" | `/sync 2` | 0.85 |
| "my tasks" | `/tasks` | 0.92 |
| "email stats" | `/stats` | 0.95 |

Threshold: 0.65 minimum confidence. Falls back to LLM for complex queries.

## Slash Commands

### Pipeline

| Command | Description |
|---------|-------------|
| `/process` | Full pipeline: sync → memory → tasks → show results |
| `/process --days N` | Sync last N days, then process |
| `/process --force` | Reprocess all emails |

### Data

| Command | Description |
|---------|-------------|
| `/sync [days]` | Sync emails via IMAP (default: incremental) |
| `/stats` | Email statistics (count, threads) |
| `/email search <query>` | Search email archive (FTS) |
| `/email list` | List recent email drafts |
| `/email create` | Create email draft |
| `/email send` | Send email draft |

### Tasks

| Command | Description |
|---------|-------------|
| `/tasks` | List actionable tasks (4-level urgency) |
| `/gaps` | Analyze relationship gaps |

### Memory

| Command | Description |
|---------|-------------|
| `/memory search <query>` | Search entity memory (hybrid) |
| `/memory store <content>` | Store new memory blob |
| `/memory stats` | Memory statistics |
| `/memory list` | List all memory blobs |

### MrCall/StarChat

| Command | Description |
|---------|-------------|
| `/mrcall` | MrCall/StarChat phone integration |
| `/call <number>` | Initiate outbound call |

### Utility

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/status` | Show sync and system status |

## Configuration

All config via `~/.zylch/.env`, set up by `zylch init`:

```bash
# Required
EMAIL_ADDRESS=user@gmail.com
EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx
SYSTEM_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Auto-detected from email domain
IMAP_SERVER=imap.gmail.com
SMTP_SERVER=smtp.gmail.com
```

## Related

- [Architecture](../ARCHITECTURE.md) - System overview
- [Email Archive](../features/email-archive.md) - Email sync details
- [Task Management](../features/task-management.md) - Task system
