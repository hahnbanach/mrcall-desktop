---
description: |
  Current state of Zylch standalone as of 2026-04-10 evening. Profile-aware CLI,
  prompt caching, parallel LLM, dream system, Telegram proactive digest.
  12 task detection fixes in 0.1.20. ~90% task accuracy (up from 56%).
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
- [1/5] Email sync (IMAP, 60 days default)
- [2/5] WhatsApp sync (connect/fetch/disconnect)
- [3/5] Memory extraction (auto-trains on first run, **parallel 5x**, **prompt caching**)
- [4/5] Task detection (incremental — creates/updates/closes tasks without deleting existing ones)
- [5/5] Show action items

### Task Detection (fixed in 0.1.16)
- **Incremental**: `get_tasks(refresh=True)` analyzes only unprocessed emails, preserves existing tasks
- **Exact user match**: only the user's own email address is treated as "self" — same-domain colleagues generate tasks normally
- **Reply detection**: user's sent emails close tasks for each recipient (parses comma-separated to_email)
- **is_auto_reply** stored in DB

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

## What Was Completed This Session (2026-04-10 evening)

Bumped to **v0.1.20**. 12 fixes to task detection across `task_creation.py`, `task_interactive.py`, `process_pipeline.py`, `task_email.py`, `solve_tools.py`:

1. **Self-sent emails = always task** — bypass LLM, self-sent is always actionable
2. **Notification sender filter** — no-reply, notification@, etc. filtered out
3. **Task dedup by title similarity** — SequenceMatcher >50% prevents near-duplicates
4. **Post-discuss default changed** — from "done" to "back"
5. **Hard-coded invoice reminder rule** — 2+ reminders = MEDIUM priority task
6. **Hard-coded meeting decline rule** — 2+ declines = LOW priority task
7. **Case-insensitive DB queries** — ilike fix
8. **Sync default changed** — from 7 to 60 days
9. **Prompt trainer no longer blanket-filters** invoices/declines
10. **Force-update stale tasks** — new email for same contact triggers update
11. **Full thread context passed to LLM** — no longer truncated
12. **Thread context instruction added** to LLM user message

Other fixes:
- **download_attachment ID mismatch** — UUID vs gmail_id resolved
- **read_document hardcoded macOS paths** — now platform-aware defaults

New docs:
- Created `docs/qa/testing-live.md` (live testing methodology)

Task detection accuracy: from 7 tasks (56% recall) to 12+ tasks (~90% accuracy).

## What Is In Progress

- Background tests running: pitch deck task execution, comodato attachment download
- Remaining: .docx/.pptx reading capability (Zylch finds files but can't parse binary formats natively)
- Task description staleness partially fixed (thread context helps but LLM interpretation varies)

## Immediate Next Steps

1. **Run `zylch process` end-to-end** — validate that tasks persist and colleague emails generate tasks
2. **Clean stale modules**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/`
3. **Split oversized files**: `command_handlers.py` (5137), `gmail_tools.py` (988)
4. **Lint clean** (2026-04-17): `make lint` exits 0 — Black and Ruff pass on `zylch/` and `tests/`
5. **Test `zylch dream`** — run gate checks, verify prune, check last_dream_at persists
6. **Test Telegram digest** — start bot, wait for 8am/8pm, verify message

## Known Issues

- `command_handlers.py` (5137 lines) far above 500-line guideline
- `gmail_tools.py` (988 lines), `workers/memory.py` (917) above guideline
- `workers/task_creation.py` (1170+ lines) — grew from 901, needs splitting
- Legacy trained prompts use `{from_email}` format placeholders — prompt caching falls back to old behavior for these (new prompts from auto-train use cached system prompt)
- neonize "Press Ctrl+C to exit" printed by Go — not suppressible
- Most tests in `tests/` directory are stale (except `tests/workers/` which is current)
- Duplicate tasks still appear occasionally (invoice reminders, cross-contact same thread)
- No .docx/.pptx parser — relies on run_python fallback
- Lint clean as of 2026-04-17: `make lint` exits 0 (Black + Ruff pass on `zylch/` and `tests/`)
