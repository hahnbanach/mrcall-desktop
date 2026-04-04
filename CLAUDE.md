# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Zylch — local AI-powered sales intelligence assistant. Python 3.11+ / SQLite / IMAP / BYOK LLM. Mono-user CLI tool, no server.

### What It Does

Multi-channel sales intelligence: connects email (IMAP), phone (MrCall/StarChat), WhatsApp (neonize/whatsmeow), and in future calendar (CalDAV). Generates tasks, maintains relationship memory, detects gaps. Also accessible via Telegram bot.

### Channels

| Channel | Protocol | Status |
|---------|----------|--------|
| Email | IMAP/SMTP | Working |
| MrCall | StarChat HTTP | Channel adapter (starchat.py) |
| WhatsApp | neonize (whatsmeow) | Implemented — local, QR code login |
| Calendar | CalDAV | Planned |

### Interfaces

| Interface | How | Status |
|-----------|-----|--------|
| CLI REPL | `zylch` (interactive chat) | Working |
| Telegram | `zylch telegram` (bot, long-polling) | Implemented |

MrCall is a **channel** (read calls, send SMS, trigger actions). Configuration is delegated to StarChat → mrcall-agent (separate repo at `~/hb/mrcall-agent`).

## Documentation

The directory ./docs/ is continuously updated. Check `docs/README.md` for the index.

After context compaction, run /doc-intrasession before resuming work!

## Quick Reference

```bash
# Install
pip install -e .                    # Dev mode
pipx install .                      # User install

# Setup
zylch init                          # Interactive wizard → ~/.zylch/.env

# Usage
zylch                               # Interactive chat (REPL)
zylch sync                          # Sync emails via IMAP
zylch tasks                         # Show actionable tasks
zylch status                        # Show sync status
zylch telegram                      # Start Telegram bot interface

# Lint & Format
black --check zylch/                # Check formatting
ruff check zylch/                   # Lint
```

## Architecture

### Flow
```
User → zylch CLI (click) or Telegram bot
  → command_handlers.py (slash) or chat_service.py (LLM)
  → tools execute (IMAP, neonize, StarChat, memory)
  → Storage (SQLite ~/.zylch/zylch.db)
  → response printed to terminal or sent to Telegram
```

### Key Layers

- **`zylch/cli/`** — Click CLI: `main.py` (entry point), `setup.py` (init wizard), `chat.py` (REPL), `commands.py` (direct shortcuts)
- **`zylch/services/`** — Business logic: `chat_service.py` (LLM orchestration), `command_handlers.py` (slash commands), `sync_service.py` (IMAP sync), `job_executor.py` (background jobs)
- **`zylch/email/`** — IMAP/SMTP client (`imap_client.py`) with auto-detect presets
- **`zylch/storage/`** — SQLAlchemy ORM with SQLite: `models.py` (17 models), `database.py` (engine), `storage.py` (Storage class)
- **`zylch/whatsapp/`** — WhatsApp client (`client.py`, QR login via neonize) and sync service (`sync.py`)
- **`zylch/telegram/`** — Telegram bot interface (`bot.py`, bridges to ChatService)
- **`zylch/tools/`** — LLM tool definitions. Split into: `gmail_tools.py`, `email_sync_tools.py`, `contact_tools.py`, `crm_tools.py`, `whatsapp_tools.py`. Registry in `factory.py`. MrCall channel in `starchat.py`.
- **`zylch/agents/`** — LLM-powered processors. `trainers/` generates prompts incrementally (task_email.py auto-runs after sync, no manual training)
- **`zylch/memory/`** — Entity-centric memory with fastembed (384-dim, ONNX). In-memory vector search via numpy. Hybrid search (text + semantic). Reconsolidation via LLM.
- **`zylch/llm/`** — Multi-provider LLM client via aisuite (Anthropic, OpenAI)

### Configuration
All config via `zylch/config.py` — Pydantic Settings loading from `~/.zylch/.env`. Key vars: `SYSTEM_LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`.

### Storage
SQLite at `~/.zylch/zylch.db`. 19 models (incl. WhatsAppMessage, WhatsAppContact). Tables created via `Base.metadata.create_all()`. No Alembic. Embeddings as BLOB, vector search in-memory. WhatsApp session in `~/.zylch/whatsapp.db` (neonize).

### Related Repositories
- `~/hb/mrcall-agent` — MrCall configurator SaaS (separate project)

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display. Show FULL values.
- **DEBUG LOGGING MANDATORY**: Every feature must log inputs, calls, and results. Pattern: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent".
- **CONCURRENT OPERATIONS**: Batch all independent operations in a single message.
- **NO ROOT FILES**: Never save working files to root. Use: `/zylch` (source), `/tests` (tests), `/docs` (docs), `/scripts` (scripts).
- **FILES < 500 LINES**: Keep modules small and focused.
- **NO HARDCODED SECRETS**: Use environment variables via Pydantic Settings.
- **SQLITE STORAGE**: All data in SQLite. Embeddings in BLOB, search in-memory.
- **Line length**: 100 chars (black + ruff configured in pyproject.toml).
