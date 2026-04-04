---
description: |
  Current state of Zylch standalone as of 2026-04-04. Dashboard, /process
  pipeline (sync-blocking), fail-fast on LLM errors, UUID fix for blob storage.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` command via click (init, sync, tasks, status, interactive chat)
- **Storage**: SQLite at `~/.zylch/profiles/<name>/zylch.db`, 17 ORM models, WAL mode
- **Config**: Pydantic Settings from profile `.env`, `zylch init` wizard
- **LLM**: BYOK multi-provider (Anthropic preferred, OpenAI supported) via aisuite
- **No server**: direct function calls, no FastAPI, no HTTP
- **Profiles**: multi-profile support with exclusive locking, profile-aware DB path

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
- **WhatsApp**: planned via GOWA (go-whatsapp-web-multidevice)
- **Calendar**: planned via CalDAV

### UX
- **Startup dashboard**: shows profile, email count, last sync age, pending processing counts, active tasks with urgency breakdown, memory entity count
- **Actionable suggestions**: dashboard tells user what to do next (`/process`, `/tasks`)
- **`/process` pipeline**: single command runs sync → memory → tasks → show results. Runs each step to completion before starting the next (no background jobs).
- **Fail-fast on LLM errors**: auth errors (401) propagate immediately and stop processing at all levels (workers, job_executor, pipeline)

### Notifications
- Deduplication (identical unread not re-created)
- Error message normalization
- Post-sync guidance

## Completed (2026-04-04)

### Startup Dashboard (`zylch/cli/chat.py`)
- Shows profile, email stats (count + newest email age as "last sync")
- Pending processing counts (memory + tasks) highlighted in yellow
- Active task count with urgency breakdown
- Memory entity count
- "Next:" section with actionable command suggestions

### `/process` Pipeline (`zylch/services/process_pipeline.py`)
- New command: `/process` runs full chain: sync → memory agent → task agent → show tasks
- **Synchronous execution**: calls `SyncService.sync_emails()` and workers directly, no background jobs
- Accepts `--days N` and `--force` flags (passed through to sync)
- Progress indicators: `[1/4]`, `[2/4]`, `[3/4]`, `[4/4]`
- Registered in `COMMAND_HANDLERS` and tab completion

### Fail-Fast on LLM Auth Errors
- `workers/memory.py`: `_extract_entities`, `_extract_calendar_facts`, `_extract_mrcall_entities` re-raise 401/auth errors instead of swallowing them
- `workers/memory.py`: `process_batch` and `process_mrcall_batch` stop after 3 consecutive failures
- `workers/task_creation.py`: `_analyze_event` re-raises auth errors; `_analyze_recent_events` stops after 3 consecutive LLM failures
- `services/job_executor.py`: memory and task processing loops re-raise auth errors to fail the job immediately

### UUID Fix (`memory/blob_storage.py`)
- `store_blob` and `update_blob` were passing `uuid.UUID()` objects to SQLite which only accepts strings
- Fixed all 3 occurrences: blob insert, sentence insert (store), sentence insert (update)

### Last Sync Fix
- Dashboard uses newest email date from DB instead of `oauth_tokens.last_sync` (which was never written)

### Linters Installed
- `black` 26.3.1 and `ruff` 0.15.8 installed in `venv/`

### QA Results (2026-04-04)
- `/process` tested end-to-end with support@mrcall.ai profile (580 emails)
- Sync: OK (+0 new, 580 total — already synced)
- Memory extraction: 43/190 emails processed successfully before manual kill (working, just slow — ~2 emails/min due to LLM calls)
- No crashes, no auth errors, no UUID errors after fixes

## Previously Completed (2026-03-31 — 2026-04-01)

### Standalone Transformation (6 streams)
- **A**: Removed MrCall configurator, Firebase, API layer (-50500 lines)
- **B**: PostgreSQL to SQLite (17 models, sqlite_insert upserts)
- **C**: Gmail OAuth to IMAP client (auto-detect, incremental sync)
- **D**: CLI integration (click, REPL, zylch init wizard)
- **E**: pgvector to numpy in-memory vector search
- **F**: Packaging (pyproject.toml, deps cleanup, .env.example)
- **Cleanup**: Fixed all broken imports, deleted stale modules

### QA (3 rounds, 2026-04-01)
- End-to-end test with support@mrcall.ai, 552 emails, IMAP cross-reference
- 10 issues found and fixed

### Tech Debt
- `SupabaseStorage` renamed to `Storage` (68 files)
- `tools/factory.py` split (2232 to 589 lines + 5 modules)

## Deployed State

- **GitHub (origin/main)**: commits up to a37cd3b pushed
- **Local**: uncommitted changes for dashboard, /process, fail-fast, UUID fix, docs

## What Is In Progress

Nothing — session work completed. ~147 emails still unprocessed for memory (processing was killed during QA).

## Immediate Next Steps

1. **Commit session changes** (dashboard, /process, fail-fast, UUID fix, docs)
2. **Run `/process` to completion** — finish memory extraction for remaining 147 emails
3. **Clean remaining stale code**: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/`
4. **Split `gmail_tools.py`** (874 lines, above 500-line guideline)
5. **Add CalDAV** calendar support
6. **Add GOWA** WhatsApp integration

## Known Issues

- `command_handlers.py` still has SaaS remnants (connect flow stubs)
- `chat_service.py` still references MrCall routing paths
- `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/` may be dead code
- `tests/` directory references old architecture (needs rewrite)
- `gmail_tools.py` (874 lines) above 500-line guideline
- `oauth_tokens.last_sync` field is never written — dashboard works around it using newest email date
- Memory extraction is slow (~2 emails/min) due to sequential LLM calls — consider batching or parallelism
