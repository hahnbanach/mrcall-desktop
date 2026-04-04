---
description: |
  Current state of Zylch standalone as of 2026-04-04. Fully transformed
  from shared SaaS codebase to local CLI tool. SQLite, IMAP, no server.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` command via click (init, sync, tasks, status, interactive chat)
- **Storage**: SQLite at `~/.zylch/zylch.db`, 19 ORM models, WAL mode
- **Config**: Pydantic Settings from `~/.zylch/.env`, `zylch init` 5-step wizard (LLM → Email → WhatsApp → Telegram → MrCall)
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
- **MrCall/StarChat**: HTTP client for contacts, calls, SMS + OAuth2 PKCE connection flow
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
- Default-deny when `TELEGRAM_ALLOWED_USER_ID` not set
- Markdown → Telegram HTML conversion, message splitting (>4096 chars)
- Config: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` in `~/.zylch/.env`

### MrCall OAuth2 (implemented)
- `zylch/tools/mrcall/oauth.py`: OAuth2 authorization code flow with PKCE
- Local HTTP callback server on port 19274, browser-based consent
- Token exchange + encrypted storage in SQLite `oauth_tokens` table
- Token refresh support via `refresh_mrcall_token()`
- Step 5 in `zylch init` wizard, re-run support (shows existing connection)
- Config: `MRCALL_CLIENT_ID`, `MRCALL_CLIENT_SECRET` in `~/.zylch/.env`

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

## Completed This Session (2026-04-03 / 2026-04-04)

### WhatsApp + Telegram + MrCall OAuth (PR #2)
- WhatsApp channel: neonize client, sync, 5 LLM tools, memory pipeline, unified timeline
- Telegram bot: ChatService bridge, long-polling, markdown→HTML, default-deny auth
- MrCall OAuth2: PKCE flow, local callback server, token storage/refresh
- `zylch init` rewritten as 5-step multi-channel wizard
- Code review: 14 issues found and fixed (broken memory worker, datetime bugs, security)

## What Is In Progress

Nothing — all streams completed.

## Immediate Next Steps

1. **Test WhatsApp end-to-end**: QR login → sync → search → send
2. **Test Telegram bot**: token setup → message routing → command handling
3. **Test MrCall OAuth**: client_id setup → browser consent → token storage
4. **Test `zylch init`** full 5-step wizard with real credentials
5. **Clean remaining stale code**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` — likely stale
6. **Add CalDAV** calendar support

## Known Issues

- `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` may be dead code
- `tests/` directory references old architecture (needs rewrite)
- No end-to-end test of full flow (init → sync → tasks)
- `gmail_tools.py` (874 lines) above 500-line guideline
- `README.md` and `docs/guides/integrations.md` have SaaS-era content that needs cleanup
