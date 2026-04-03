---
description: |
  Current state of Zylch standalone as of 2026-04-01. Fully transformed
  from shared SaaS codebase to local CLI tool. SQLite, IMAP, no server.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` command via click (init, sync, tasks, status, interactive chat)
- **Storage**: SQLite at `~/.zylch/zylch.db`, 17 ORM models, WAL mode
- **Config**: Pydantic Settings from `~/.zylch/.env`, `zylch init` wizard
- **LLM**: BYOK multi-provider (Anthropic preferred, OpenAI supported) via aisuite
- **No server**: direct function calls, no FastAPI, no HTTP

### Email
- IMAP client (`zylch/email/imap_client.py`): fetch, search, send via SMTP
- Auto-detect IMAP/SMTP servers (Gmail, Outlook, Yahoo, iCloud presets)
- Email archive with SQLite FTS (LIKE fallback)
- Auto-sync on first message if last sync >24h
- `/email search` via FTS with ILIKE fallback for person names

### Task System
- 4-level urgency: CRITICAL, HIGH, MEDIUM, LOW
- Incremental task prompt: auto-generated after sync, no manual training
- Prompt reconsolidation pattern (update existing, don't recreate)
- `user_email` from oauth_tokens, not env vars

### Memory
- Entity-centric blob storage with fastembed (ONNX, 384-dim)
- In-memory vector search: numpy brute-force cosine similarity
- Embeddings stored as BLOB in SQLite, loaded into RAM on first search
- Hybrid search (text LIKE + semantic cosine), reconsolidation via LLM
- Prioritizes PERSON and COMPANY extraction over TEMPLATEs

### Channels
- **Email**: IMAP/SMTP (bidirectional)
- **MrCall/StarChat**: HTTP client for contacts, calls, SMS (channel, not configurator)
- **WhatsApp**: neonize (whatsmeow) — local QR login, sync, search, send, gap analysis
- **Calendar**: planned via CalDAV

### Interfaces
- **CLI REPL**: `zylch` — interactive chat with slash commands
- **Telegram bot**: `zylch telegram` — same ChatService, accessible from phone

### WhatsApp (implemented)
- `zylch/whatsapp/client.py`: QR code login, session in `~/.zylch/whatsapp.db`
- `zylch/whatsapp/sync.py`: HistorySyncEv + MessageEv → whatsapp_messages table
- `zylch/tools/whatsapp_tools.py`: 5 LLM tools (search, conversation, send, gap, timeline)
- `zylch/services/unified_conversation.py`: merges email + WhatsApp + calls per contact
- `zylch/workers/memory.py`: WhatsApp message → memory extraction pipeline
- `/connect whatsapp`: inline QR code display, 60s scan timeout
- `/sync whatsapp`: sync contacts + messages to SQLite
- Models: `WhatsAppMessage`, `WhatsAppContact`

### Telegram bot (implemented)
- `zylch/telegram/bot.py`: bridges Telegram → ChatService (same engine as REPL)
- Long-polling (no webhook/server needed), secured by `TELEGRAM_ALLOWED_USER_ID`
- Markdown → Telegram HTML conversion, message splitting (>4096 chars)
- Config: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` in `~/.zylch/.env`

### Notifications
- Deduplication (identical unread not re-created)
- Error message normalization
- Post-sync guidance

## Completed This Session (2026-03-31 / 2026-04-01)

### QA (3 rounds)
- End-to-end test with support@mrcall.ai, 500 emails, IMAP cross-reference
- 10 issues found and fixed (providers seed, /gaps, priorities, memory, auto-sync, OAuth, search, dedup, training, fastembed)

### Tech Debt
- `SupabaseStorage` → `Storage` (68 files)
- `tools/factory.py` split (2232 → 589 lines + 5 modules)

### Standalone Transformation (6 streams)
- **A**: Removed MrCall configurator, Firebase, API layer (-50500 lines)
- **B**: PostgreSQL → SQLite (17 models, sqlite_insert upserts)
- **C**: Gmail OAuth → IMAP client (auto-detect, incremental sync)
- **D**: CLI integration (click, REPL, zylch init wizard)
- **E**: pgvector → numpy in-memory vector search
- **F**: Packaging (pyproject.toml, deps cleanup, .env.example)
- **Cleanup**: Fixed all broken imports, deleted stale modules

## Deployed State

- **GitHub (origin/main)**: all commits pushed
- **Local**: `pip install -e .` works, `zylch --help` and `zylch status` verified

## What Is In Progress

Nothing — all streams completed.

## Immediate Next Steps

1. **Test WhatsApp end-to-end**: QR login → sync → search → send
2. **Test Telegram bot**: token setup → message routing → command handling
3. **Test `zylch init` + `zylch sync`** with real email (IMAP + app password)
4. **Clean remaining stale code**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` — likely stale
5. **Add CalDAV** calendar support

## Known Issues

- `command_handlers.py` still has SaaS remnants (connect flow stubs)
- `chat_service.py` still references MrCall routing paths
- `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` may be dead code
- `tests/` directory references old architecture (needs rewrite)
- No end-to-end test of full flow (init → sync → tasks)
- `gmail_tools.py` (874 lines) above 500-line guideline
