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
- **Email**: IMAP/SMTP (bidirezionale)
- **MrCall/StarChat**: HTTP client for contacts, calls, SMS (channel, not configurator)
- **WhatsApp**: planned via neonize (whatsmeow Python wrapper, local QR code login)
- **Calendar**: planned via CalDAV

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

1. **Test `zylch init` + `zylch sync`** with real email (IMAP + app password)
2. **Test `zylch tasks`** end-to-end (requires LLM API key)
3. **Clean remaining stale code**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` — likely stale
4. **Update CLAUDE.md** to reflect standalone-only architecture
5. **Add CalDAV** calendar support
6. **Add GOWA** WhatsApp integration

## Known Issues

- `command_handlers.py` still has SaaS remnants (connect flow stubs)
- `chat_service.py` still references MrCall routing paths
- `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` may be dead code
- `tests/` directory references old architecture (needs rewrite)
- No end-to-end test of full flow (init → sync → tasks)
- `gmail_tools.py` (874 lines) above 500-line guideline
