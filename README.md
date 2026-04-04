# Zylch — Local AI Sales Intelligence

Zylch is a local AI-powered sales intelligence assistant. Connects email (IMAP), WhatsApp (neonize), phone (MrCall/StarChat), and generates tasks, relationship memory, and gap analysis. Mono-user CLI tool, no server. Also accessible via Telegram bot.

## Quick Start

```bash
# Install
pip install -e .

# Setup (interactive 5-step wizard)
zylch init

# Interactive chat
zylch

# Sync emails
zylch sync

# Show tasks
zylch tasks

# Start Telegram bot
zylch telegram
```

## Design Philosophy

- **Task-focused**: Answers "What do I need to do?" — no unnecessary classifications
- **Person-centric**: Tasks aggregated by contact, analyzing entire relationships
- **Multi-channel**: Email + WhatsApp + phone calls unified per contact
- **Local-first**: All data in SQLite, no cloud dependencies, BYOK LLM

## Channels

| Channel | Protocol | How to connect |
|---------|----------|---------------|
| Email | IMAP/SMTP | App password via `zylch init` |
| WhatsApp | neonize (whatsmeow) | QR code scan via `zylch init` or `/connect whatsapp` |
| MrCall | StarChat HTTP + OAuth2 | OAuth2 consent via `zylch init` |
| Calendar | CalDAV | Planned |

## Interfaces

| Interface | How to start | Description |
|-----------|-------------|-------------|
| CLI REPL | `zylch` | Interactive chat with slash commands |
| Telegram bot | `zylch telegram` | Same engine, accessible from phone |

## Features

### Email Intelligence
- IMAP sync with auto-detect presets (Gmail, Outlook, Yahoo, iCloud)
- Email archive with SQLite full-text search (FTS5)
- Smart search by sender, subject, or content
- Draft management and email composition

### WhatsApp
- Local connection via neonize (QR code login, no cloud API)
- Message sync, contact search, send messages
- Gap analysis: detect unanswered conversations
- Unified timeline: see email + WhatsApp + calls per contact

### Task Management
- Person-centric: all threads per contact in one view
- 4-level urgency (CRITICAL, HIGH, MEDIUM, LOW)
- Incremental task prompt, auto-generated after sync
- Prompt reconsolidation (updates existing, doesn't recreate)

### Entity Memory
- Entity-centric blob storage with fastembed (ONNX, 384-dim)
- Hybrid search: text LIKE + semantic cosine similarity
- LLM-powered reconsolidation (merges new info with existing knowledge)
- Extracts PERSON and COMPANY entities from all channels

### MrCall/StarChat
- Phone call history and contact info
- SMS sending
- OAuth2 PKCE connection flow via `zylch init`

### Telegram Bot
- Long-polling (no server/webhook needed)
- Secured by `TELEGRAM_ALLOWED_USER_ID` (default-deny)
- All slash commands and natural language queries work
- Markdown → Telegram HTML conversion

## Configuration

All config lives in `~/.zylch/.env`, created by `zylch init`:

```bash
# LLM (required)
SYSTEM_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Email (IMAP)
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=your-app-password

# Telegram (optional)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ALLOWED_USER_ID=your-numeric-id

# MrCall (optional)
MRCALL_CLIENT_ID=your-client-id
MRCALL_CLIENT_SECRET=your-client-secret
```

## CLI Commands

```bash
# Core
/help              Show help
/quit              Exit Zylch
/clear             Clear conversation history

# Sync & Tasks
/sync              Sync emails via IMAP
/sync whatsapp     Sync WhatsApp contacts + messages
/sync status       Show sync counts
/tasks             Show detected tasks

# Connections
/connect whatsapp  Connect WhatsApp (QR code)

# Memory
/memory --list     List behavioral memories
/memory --add      Add new rule
/memory --stats    Show memory stats
```

## Architecture

```
User → zylch CLI (click) or Telegram bot
  → command_handlers.py (slash) or chat_service.py (LLM)
  → tools execute (IMAP, neonize, StarChat, memory)
  → Storage (SQLite ~/.zylch/zylch.db)
  → response printed to terminal or sent to Telegram
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full system design.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System design and module map
- [Integrations Guide](docs/guides/integrations.md) — Channel setup details
- [CLI Commands](docs/guides/cli-commands.md) — Command reference
- [Entity Memory](docs/features/entity-memory-system.md) — Memory system design
- [WhatsApp Integration](docs/features/WHATSAPP_INTEGRATION_TODO.md) — Implementation details

## Development

```bash
# Lint & Format
black --check zylch/
ruff check zylch/
```

## License

Proprietary — MrCall SRL
