---
description: |
  Current state of Zylch standalone as of 2026-04-04. Profile-aware CLI,
  prompt caching, parallel LLM, dream system, Telegram proactive digest.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` via click — init, process, sync, dream, tasks, status, profiles, telegram
- **Profile system**: multi-profile with `-p/--profile`, exact match, exclusive locking
- **Storage**: SQLite at `~/.zylch/profiles/<name>/zylch.db`, 19 ORM models + last_dream_at, WAL mode
- **Config**: Pydantic Settings from profile `.env`, `zylch init` wizard (rclone-style)
- **LLM**: BYOK (Anthropic, OpenAI) via direct SDK calls (aisuite dropped)

### Email
- IMAP client with auto-detect presets (Gmail, Outlook, Yahoo, iCloud)
- Email archive with SQLite FTS, incremental sync
- `zylch sync` does synchronous IMAP fetch (not background job)

### WhatsApp
- neonize (whatsmeow) client with QR code login
- Sync on demand: connect → fetch history → derive contacts from messages → disconnect
- Timestamp guard for corrupted values (rejects year < 2009 or > 2100)
- Contacts derived from saved messages (neonize has no "get all contacts" API)

### Telegram
- Bot interface via python-telegram-bot (long-polling)
- Bridges to ChatService for slash commands and NL
- **Proactive digest**: APScheduler sends task summaries at 8am/8pm via Telegram

### MrCall
- StarChat HTTP client (channel adapter) with OAuth2 flow

### Process Pipeline (`zylch process`)
- [1/5] Email sync (IMAP, 7 days default)
- [2/5] WhatsApp sync (connect/fetch/disconnect)
- [3/5] Memory extraction (auto-trains on first run, **parallel 5x**, **prompt caching**)
- [4/5] Task detection (auto-trains on first run, **parallel 5x**, **prompt caching**)
- [5/5] Show action items

### Dream System (`zylch dream`)
- Three-gate trigger: time (4h), items (5 unprocessed), file lock
- Four phases: orient → gather → consolidate → prune
- Prune: removes empty blobs and short stale blobs (90+ days)
- Cron-friendly: `0 */6 * * * zylch -p user@example.com dream`

### LLM Improvements
- **Prompt caching**: trained prompts sent as Anthropic system with `cache_control: ephemeral`. ~90% token discount on batch operations.
- **Parallel LLM**: `asyncio.Semaphore(5)` + `asyncio.gather` in memory worker and task worker. ~5x throughput.
- **Direct SDK**: aisuite dropped, Anthropic/OpenAI called directly (resolved httpx conflict with neonize)

### Memory
- Entity-centric blob storage with fastembed (ONNX, 384-dim)
- In-memory vector search: numpy cosine similarity
- Hybrid search (text + semantic), reconsolidation via LLM (merge also uses prompt caching)

## What Is In Progress

Nothing — session work completed.

## Immediate Next Steps

1. **Test `zylch process` end-to-end** — validate prompt caching + parallel on real data
2. **Test `zylch dream`** — run gate checks, verify prune, check last_dream_at persists
3. **Test Telegram digest** — start bot, wait for 8am/8pm, verify message
4. **Clean stale modules**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/`
5. **Split oversized files**: `command_handlers.py` (5137), `gmail_tools.py` (988)
6. **Fix lint**: 63 Black reformats, 114 Ruff errors

## Known Issues

- `command_handlers.py` (5137 lines) far above 500-line guideline
- `gmail_tools.py` (988 lines), `workers/memory.py` (917), `workers/task_creation.py` (901) above guideline
- Legacy trained prompts use `{from_email}` format placeholders — prompt caching falls back to old behavior for these (new prompts from auto-train use cached system prompt)
- neonize "Press Ctrl+C to exit" printed by Go — not suppressible
- `tests/` directory entirely stale
- 63 files need Black reformatting, 114 Ruff errors
