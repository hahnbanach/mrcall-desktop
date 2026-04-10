# CLAUDE.md

Zylch — local AI-powered sales intelligence CLI. Python 3.11+ / SQLite / IMAP / WhatsApp (neonize) / BYOK LLM. Mono-user, no server.

## Documentation

All knowledge lives in `./docs/`. This file is the index.

| Doc | What |
|-----|------|
| [system-rules.md](docs/system-rules.md) | Tech stack, coding standards, dependency rules, imperatives |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System map, data flow, module boundaries |
| [CONVENTIONS.md](docs/CONVENTIONS.md) | Code style, patterns, logging, security |
| [active-context.md](docs/active-context.md) | Current state, in-progress work, known issues |
| [quality-grades.md](docs/quality-grades.md) | Per-module quality assessment |
| [guides/cli-commands.md](docs/guides/cli-commands.md) | CLI and slash command reference |
| [guides/quick-start.md](docs/guides/quick-start.md) | Install, setup, first use |
| [agents/README.md](docs/agents/README.md) | Agent system (memory, tasks, emailer) |

After context compaction, run /doc-intrasession before resuming work!

## Quick Reference

```bash
# Install
pip install -e .                    # Dev mode
pipx install .                      # User install

# Setup
zylch init                          # Profile wizard (LLM → Email → WhatsApp → Telegram → MrCall)

# Usage
zylch -p user@example.com update    # Sync + analyze + detect tasks (cron-friendly)
zylch -p user@example.com sync      # Fetch only (email + WhatsApp, no AI)
zylch -p user@example.com tasks     # Show action items
zylch -p user@example.com status    # Show sync stats
zylch -p user@example.com           # Interactive chat (REPL)
zylch profiles                      # List profiles
zylch telegram                      # Start Telegram bot + proactive digest

# Lint
black --check zylch/
ruff check zylch/
```

## Channels

| Channel | Protocol | Status |
|---------|----------|--------|
| Email | IMAP/SMTP | Working |
| WhatsApp | neonize (whatsmeow) | Working — QR code login, sync on demand |
| MrCall | StarChat HTTP + OAuth2 | Channel adapter |
| Telegram | python-telegram-bot | Bot interface |
| Calendar | CalDAV | Planned |

## Critical Rules

- **NO OUTPUT TRUNCATION**: Never use `[:8]`, `[:50]`, `[:100]` slicing for display
- **DEBUG LOGGING MANDATORY**: `logger.debug(f"[/cmd] func(param={param}) -> result={result}")`
- **NEVER log secrets**: Only "present"/"absent"
- **FILES < 500 LINES**: Keep modules small and focused
- **SQLITE STORAGE**: All data in SQLite. Embeddings in BLOB, search in-memory
- **NO HARDCODED SECRETS**: Pydantic Settings from profile `.env`
- **NO ROOT FILES**: Use `/zylch`, `/tests`, `/docs`, `/scripts`
- **PROFILE MATCH**: Exact match only, no substring/fuzzy
