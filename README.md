# Zylch — Local AI-Powered Sales Intelligence

Zylch is a local CLI tool that connects your email (IMAP), detects tasks, maintains relationship memory, and helps you write emails. Runs on your machine, no server needed.

## Design Philosophy

- **Task-focused**: Answers one question — "What do I need to do?"
- **Person-centric**: Tasks aggregated by person, analyzing entire relationships
- **Local-first**: All data in SQLite on your machine, BYOK for LLM keys
- **Multi-profile**: Manage multiple email accounts, each with isolated data and config
- **Multi-channel**: Email (IMAP), phone (MrCall/StarChat), WhatsApp and calendar planned

## Features

### Email Intelligence
- IMAP/SMTP with auto-detect (Gmail, Outlook, Yahoo, iCloud)
- Email archive with SQLite full-text search
- Thread analysis, AI-generated email detection
- Draft management with threading headers
- Auto-sync on first chat if last sync >24h

### Task Detection
- 4-level urgency: CRITICAL, HIGH, MEDIUM, LOW
- Person-centric view combining all threads per contact
- Incremental prompt auto-generated after sync
- Prompt reconsolidation (update existing, don't recreate)

### Entity Memory
- Person/company/template entities in natural-language blobs
- Hybrid search: text LIKE + fastembed cosine similarity (384-dim)
- Memory reconsolidation via LLM (update, not duplicate)
- In-memory vector search with numpy (no external DB)

### Channels
- **Email**: IMAP/SMTP (bidirectional, INBOX + Sent)
- **WhatsApp**: neonize/whatsmeow (QR code login, sync on demand)
- **MrCall/StarChat**: Contacts, calls, SMS (channel adapter + OAuth2)
- **Telegram**: Bot interface (long-polling + proactive digest)
- **Calendar**: Planned (CalDAV)

## Install

```bash
# One-line install (no Python needed — downloads standalone binary)
curl -sL https://raw.githubusercontent.com/malemi/zylch/main/scripts/install.sh | bash

# Or via pip / pipx (requires Python 3.11+)
pipx install zylch
```

## Setup

```bash
zylch init
```

The wizard walks through: LLM provider, email, WhatsApp, Telegram, MrCall, personal data, document folders.
Each profile is stored in `~/.zylch/profiles/<email>/` with its own `.env` and database.
Run `zylch init` again to add more profiles or edit existing ones.

## Usage

```bash
zylch              # Interactive chat (REPL) — shows dashboard on startup
zylch sync         # Sync emails via IMAP
zylch tasks        # Show actionable tasks
zylch status       # Show sync status
```

On startup, the dashboard shows your profile, email stats, pending processing, and active tasks — plus what to do next.

### Interactive Chat

```
/process           # Full pipeline: sync + memory + tasks (recommended)
/sync              # Sync emails only
/tasks             # Show tasks needing action
/email search <q>  # Search email archive
/memory search <q> # Search entity memory
/memory list       # List memory blobs
/memory stats      # Memory statistics
/help              # All commands
```

Natural language works too — "my tasks", "sync emails", "who is mario@example.com?"

## Configuration

Each profile has its own config in `~/.zylch/profiles/<email>/.env`:

```bash
# Required
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx   # App password
SYSTEM_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Optional
MY_EMAILS=you@gmail.com,you@company.com
LOG_LEVEL=INFO
```

## Architecture

```
User -> zylch CLI (click)
  -> command_handlers.py (slash) or chat_service.py (LLM)
  -> tools execute (IMAP, StarChat, memory)
  -> Storage (SQLite ~/.zylch/profiles/<email>/zylch.db)
  -> response printed to terminal
```

- **13 SQLAlchemy models**, SQLite with WAL mode
- **fastembed** (ONNX, 384-dim) for embeddings, numpy for vector search
- **aisuite** for multi-provider LLM (Anthropic, OpenAI)
- No server, no Docker, no external database

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full system map.

## Documentation

See [docs/README.md](docs/README.md) for the complete index:

- [Quick Start](docs/guides/quick-start.md)
- [CLI Commands](docs/guides/cli-commands.md)
- [Email Archive](docs/features/email-archive.md)
- [Entity Memory](docs/features/entity-memory-system.md)
- [Task Management](docs/features/task-management.md)
- [Relationship Intelligence](docs/features/relationship-intelligence.md)

## Requirements

- Python 3.11+
- Email account with IMAP access + app password
- LLM API key (Anthropic or OpenAI)

## License

Proprietary
