---
description: |
  Engine-side state of mrcall-desktop as of 2026-05-02. Profile-aware CLI,
  Electron desktop (validated), prompt caching in chat, user notes injection,
  memory tool pair (LLM decides update vs create), inbox/sent views, email
  archive/delete RPCs, Open-email → thread-filtered Tasks view, RealStep/
  cafe124 task auto-close fixes, optional close_note column on task_items.
  App-side state lives in ../../app/docs/active-context.md; cross-cutting
  state in ../../docs/active-context.md.
---

# Active Context

## What Is Built and Working

### Core
- **CLI**: `zylch` via click — init, update, sync, dream, tasks, status, profiles, telegram
- **Profile system**: multi-profile with `-p/--profile`, exact match, flock-based liveness (stale-lock check via flock, not PID)
- **Storage**: SQLite at `~/.zylch/profiles/<name>/zylch.db`, 19+ ORM models, WAL mode
- **Config**: Pydantic Settings from profile `.env`, `zylch init` wizard (rclone-style), DOWNLOADS_DIR with picker hint
- **LLM**: BYOK (Anthropic, OpenAI) via direct SDK calls (aisuite dropped)

### Electron Desktop (end-to-end working)
- `zylch-desktop` launches on Mac, validated by user on 2026-04-13
- 3 views (chat, tasks, emails) talk to Python sidecar via RPC
- `update.run` no longer blocks the sidecar; rough ETA + "progress is saved" notice during long updates

### Email
- IMAP client with auto-detect presets (Gmail, Outlook, Yahoo, iCloud)
- Email archive with SQLite FTS, incremental sync
- `zylch sync` does synchronous IMAP fetch
- **Inbox / Sent views**: `emails.list_inbox`, `emails.list_sent`, thread pin, read tracking (`c56634a`)
- **HTML body rendering**: `emails.list_by_thread` returns `body_html` (`65185fc`)
- Draft preview shows full body verbatim, not a summary (`108572b`)
- **Archive + Delete (this session)**: `emails.archive(thread_id)` IMAP MOVE to provider archive folder (SPECIAL-USE `\All` / `\Archive`, fallback provider names), UID MOVE with COPY+EXPUNGE fallback. `emails.delete(thread_id)` soft-delete locally only (preserves provenance for linked tasks, IMAP untouched). New columns `archived_at` / `deleted_at` on Email model, applied via existing `_apply_column_migrations` at boot. `list_inbox_threads` / `list_sent_threads` filter out flagged threads. Desktop: Archive + Delete buttons in ThreadReadingPane with optimistic removal + rollback on error. RPC lives in `zylch/rpc/email_actions.py` (not `command_handlers.py`).

### WhatsApp
- neonize (whatsmeow) client with QR code login
- Sync on demand: connect → fetch history → derive contacts from messages → disconnect
- Timestamp guard for corrupted values; contacts derived from saved messages

### Telegram / MrCall
- Telegram bot via python-telegram-bot, proactive 8am/8pm digest
- MrCall StarChat HTTP client with OAuth2 flow

### Update Pipeline (`zylch update`)
- [1/5] Email sync (IMAP, 60 days default)
- [2/5] WhatsApp sync (connect/fetch/disconnect)
- [3/5] Memory extraction (auto-trains, parallel 5x, prompt caching)
- [4/5] Task detection — LLM analyzes every non-user email; self-sent also goes through LLM (no hardcoded rules)
- [5/5] Show action items

### Tasks — view filters
- **Open-email → thread-filtered Tasks view (this session)**: clicking `✉ Open` on an Inbox thread no longer opens the thread chat. It navigates to the Tasks view with a `taskThreadFilter` applied (always, even for 0 or 1 tasks — no picker, no shortcut). Banner "Tasks for thread: <subject>" + "✕ Clear filter"; empty state when the thread has no tasks. Backend RPC `tasks.list_by_thread(thread_id)` in `zylch/rpc/task_queries.py` wraps `Storage.get_tasks_by_thread`. Desktop: `openSelected()` in `views/Email.tsx` sets the thread filter and calls `onOpenTasks` (renamed from `onOpenWorkspace`); `Tasks.tsx` supports the filter mode with live mutations (pin/skip/close/reopen/update) operating on the filtered list.

### Task Detection
- **Incremental**: analyzes only unprocessed emails, preserves existing tasks
- **LLM-driven**: every non-user email (including self-sent) goes through the LLM (`958b6b5`, `c3db306`)
- **USER_NOTES + USER_SECRET_INSTRUCTIONS injected into detector prompt** (`f887f5d`) — user-specific context steers detection
- **Reopen**: `tasks.reopen` RPC + storage method — close isn't final (`843362a`). Reopen now also clears `close_note`.
- `tasks.list` honours `include_completed` (`50aa4bd`)
- **Close with optional note**: `tasks.complete(task_id, note?)` accepts a free-text reason stored on `task_items.close_note`. Display-only — never injected into detector or any LLM prompt. Auto-close paths (worker, reanalyze sweep) leave note=None so closing reasons aren't fabricated.

### Task auto-close — RealStep / cafe124 fixes (baseline since 2026-05-01)
Three coupled fixes in `zylch/workers/task_creation.py` + reanalyze sweep:

- **F1 — Cc fallback in user_reply.** Per-recipient close in user_reply iterates `to_email + cc_email` (was: `to_email` only). `storage.get_unprocessed_emails_for_task` SELECTs `cc_email`.
- **F2 — Disabled "Forcing update on stale task" branch.** When LLM returns `task_action="none"` with non-empty `suggested_action`, the worker logs WARNING and skips the update instead of overwriting existing task fields with the LLM advisory text. Email still marked task_processed via the unconditional `_mark_thread_nonuser_processed`.
- **F3 — Diagnostic log when `get_tasks_by_thread` returns empty in user_reply.** Captures `thread_id`, `email_id`, `from_email` for the next-occurrence reproducer of RC-1 (root cause not reproduced).
- **F4 — Bounded reanalyze sweep at end of `_run_tasks`.** `services/process_pipeline.py:_reanalyze_sweep` picks up to `REANALYZE_CAP=10` open tasks (oldest first) whose `analyzed_at` (or `created_at` fallback) is older than `REANALYZE_MIN_AGE_HOURS=24`. Tolerates per-task exceptions; logs `[TASK] Reanalyze sweep: N of M eligible …`. Cost: up to 10 extra LLM calls per `update`. Surfaces in the return string as `"N action items detected (M reanalyzed)"`.

Tests: `tests/workers/test_task_worker_bugs.py` (14 cases, all green) + `tests/services/test_reanalyze_sweep.py` (6 cases, all green) — 20/20 across both files.

### Chat (Assistant)
- **Prompt caching in chat**: `zylch/assistant/core.py` + `llm/client.py` mark system/tools as `cache_control: ephemeral` (`1358594`)
- **USER_NOTES injection**: user notes loaded into the chat system prompt
- **Compaction**: `zylch/services/chat_compaction.py` summarises old turns when context grows
- Three manual cache deliverable tests under `tests/manual_test_cache_deliverable*.py`

### Memory
- Entity-centric blob storage with fastembed (ONNX, 384-dim)
- In-memory vector search: numpy cosine similarity
- Hybrid search (text + semantic), reconsolidation via LLM (merge uses prompt caching)
- **Memory tool pair (this session, `0b9e4e8`)**:
  - `update_memory_tool.py`: requires exact `blob_id` + `new_content`; no internal search; errors if id missing
  - `create_memory_tool.py`: companion, stores under `user:<owner_id>` namespace
  - `SearchLocalMemoryTool` exposes `blob_id` per result, drops stale `<owner>:<assistant>:contacts` filter
  - Assistant prompt documents the save/correct workflow: search → LLM picks → update(blob_id) or create(content)

### Dream System (`zylch dream`)
- Three-gate trigger: time (4h), items (5 unprocessed), file lock
- Four phases: orient → gather → consolidate → prune
- Cron-friendly

### Settings
- `settings_io` quotes values with dotenv-style escapes, not shlex (`3117cd4`)
- `USER_SECRET_INSTRUCTIONS` unmasked in settings schema; `scripts/repair_env.py` repairs mis-quoted `.env` files (`32fc4bc`)
- `DOWNLOADS_DIR` field with directory-picker hint (`02401a4`)

## What Was Completed This Session

**Optional close-note on task completion (2026-05-02, uncommitted).**

- New nullable `task_items.close_note` column. ORM model + idempotent
  ALTER TABLE migration (`storage/database.py:_apply_column_migrations`).
- `Storage.complete_task_item(owner_id, task_id, note=None)` — kwarg
  is backwards-compatible; existing auto-close call sites (worker,
  reanalyze, task_interactive) keep `note=None` so no closing reasons
  are fabricated. `Storage.reopen_task_item` now also clears
  `close_note` so a reopened task starts fresh.
- `tasks.complete` RPC accepts optional `note` (str | null), validated
  type, length-only logged. Display-only — never injected into the
  task-detection prompt or any other LLM context.

**Test fix — `TestUserReplyClosesCcRecipientTask` (3 cases).** These
F1 tests were failing on HEAD (verified via `git stash`): `_collect`
re-imports `get_session` lazily so the fixture-level patch is already
exited when `user_reply` runs, and the fixture's `user_email =
"user@example.com"` didn't match the test data's `from_email =
mario.alemi@cafe124.it`, so `_collect` routed to LLM instead of
user_reply. Two coupled fixes in `tests/workers/test_task_worker_bugs.py`:

- Wrap each test's `await worker.get_tasks(...)` in
  `patch("zylch.storage.database.get_session")` +
  `patch("zylch.workers.task_creation.build_thread_history")` (same
  pattern already used by `TestForcingUpdateBranch` and
  `TestColleagueEmailCreatesTask`).
- Align `from_email` to `user@example.com` and the self-cc address to
  match the fixture's `user_email`. The test's assertion is about
  Cc-recipient closure semantics — the user's own address is
  incidental.

Tests: 20/20 green across `tests/workers/test_task_worker_bugs.py` +
`tests/services/`.

---

**v0.1.24 — Email timezone fix (2026-04-21).** RFC 2822 `Date:` headers carry
a timezone offset (e.g. `-0600` for Missive-relayed mail, `+0100` for CET
senders). Two call sites stripped the offset via `dt.replace(tzinfo=None)`
instead of converting to UTC, so `emails.date` stored the sender-timezone
wall-clock as if it were UTC. Example: a support reply sent at 14:42 CET was
stored as `07:42`, making the task detector treat the customer's 13:00
message as the most recent in the thread and keep the task falsely open.

Fix details:
- New helper `zylch/utils/dates.parse_email_date_to_utc_naive`
- Two consumer fixes: `zylch/storage/storage.py:160-170`,
  `zylch/tools/email_sync.py:_parse_email_date_for_sort`
- Regression tests `tests/utils/test_dates.py` (7 cases: positive/negative/
  zero offsets, ISO `Z` suffix, empty/garbage)
- Historical backfill `scripts/backfill_email_date_utc.py --all --apply`
  rebuilt 666 mis-timestamped rows (400 on support@mrcall.ai, 266 on
  user@example.com) using the already-correct `date_timestamp`
  column — no IMAP re-fetch required.
- Open `task_items` cleared on both profiles; task detector regenerated
  from corrected chronology (support@mrcall.ai went from 60 false opens
  to 49 real opens; Tentacools false-positive no longer reproduces).

Impact: silent in production for ~3 months. Any thread with participants
in different timezones could have had its chronology inverted.

**Email archive + delete (uncommitted at time of writing)**
- Backend: `zylch/rpc/email_actions.py` NEW — `emails.archive`, `emails.delete`. `storage/models.py` + `storage/database.py` gained `archived_at` / `deleted_at` with idempotent ALTER. `storage/storage.py` gained `set_thread_archived` / `set_thread_deleted` / `get_thread_message_id_headers` and inbox/sent filter clauses. `email/imap_client.py` gained `find_archive_folder` (SPECIAL-USE `\All` then `\Archive`, fallback Gmail/Outlook/iCloud names) + `move_message_by_message_id` (UID MOVE, COPY+EXPUNGE fallback).
- Desktop: Archive + Delete buttons in `views/Email.tsx` ThreadReadingPane, optimistic removal with rollback; Delete tooltip spells out "local-only".
- Tested: `emails.delete` end-to-end over JSON-RPC stdin/stdout (`zylch -p … rpc`); migration across 4 existing profiles; Gmail archive-folder discovery returns `[Gmail]/All Mail`. IMAP MOVE live path (real thread) NOT tested — pending Mac validation.

**Open-email → thread-filtered Tasks view (uncommitted at time of writing)**
- Backend: `zylch/rpc/task_queries.py` NEW — `tasks.list_by_thread`.
- Desktop: `views/Email.tsx` `openSelected()` rewired; `views/Tasks.tsx` gained filter mode with banner + clear button; `store/thread.ts` gained `taskThreadFilter`; prop `onOpenWorkspace` → `onOpenTasks`; `App.tsx` wired.
- Tested: RPC for known/unknown thread + missing param over sidecar; `npm run typecheck` + `npm run build` clean. Click-flow in Electron NOT exercised — pending Mac validation.

**Primary: `0b9e4e8` — memory tool rewrite (LLM decides update vs create)**
- `update_memory_tool.py` rewritten: takes exact `blob_id` + `new_content` only; no internal semantic search, no fuzzy match
- `create_memory_tool.py` NEW: companion for fresh blobs under `user:<owner_id>`
- `contact_tools.py` `SearchLocalMemoryTool`: exposes `blob_id` per hit, drops stale namespace filter
- `services/task_executor.py` approval preview uses `blob_id`
- `assistant/prompts.py` documents the "save/correct memory" workflow
- Motivation: old `update_memory` searched internally and clobbered the Joel blob when user asked to save a different contact ("Café 124"). The LLM must choose which blob to update.
- Tested at Python level; end-to-end Electron chat validation pending on Mac.

**Other commits since 2026-04-10 (13), by theme:**

- Chat intelligence
  - `1358594` prompt cache + user notes + compaction (`assistant/core.py`, `llm/client.py`, `services/chat_compaction.py`)
  - `108572b` draft preview shows full body verbatim
- Tasks
  - `843362a` reopen: `tasks.reopen` RPC + storage method
  - `f887f5d` inject USER_NOTES + USER_SECRET_INSTRUCTIONS into task detector
  - `50aa4bd` `tasks.list` honours `include_completed`
- Emails
  - `c56634a` inbox/sent list + thread pin + read tracking
  - `65185fc` `emails.list_by_thread` returns `body_html`
- Settings / env
  - `32fc4bc` unmask `USER_SECRET_INSTRUCTIONS` + `scripts/repair_env.py`
  - `3117cd4` `settings_io` uses dotenv-style quoting, not shlex
  - `02401a4` `DOWNLOADS_DIR` + directory-picker hint
- Ops / scripts
  - `a7f9c59` `scripts/diag_custom124.py` — read-only inspection of Custom124 state
  - `5bf67c7` one-shot cleanup script for merged Custom124 tasks
- RPC / release
  - `2e96365` `update.run` no longer blocks the sidecar
  - `e6125c4` rough ETA + "progress is saved" notice during update
  - `53b6146` bump to 0.1.23

## What Is In Progress

- **Mac validation: IMAP archive (Task 2)** — archive a disposable thread from the Inbox view, confirm it appears in Gmail's "All Mail" and disappears from INBOX. Outlook/iCloud/Fastmail archive-folder discovery also only smoke-tested on Gmail so far.
- **Mac validation: Open → Tasks filter (Task 3)** — Inbox → Open → lands on Tasks view with banner; exercise 0-task thread, N-task thread, Clear filter, sidebar back-nav while filter is set.
- **Electron chat validation of the new memory flow on Mac** — user to exercise search → update/create round-trip in the desktop app
- **Custom124 cleanup follow-up** — now that `USER_NOTES` feeds the task detector (`f887f5d`), run `scripts/diag_custom124.py` (`a7f9c59`) to confirm duplicates stop recurring after the one-shot cleanup (`5bf67c7`). Related memory file: `project_task_detection_fixes.md`.
- Remaining: .docx/.pptx native parsing (current fallback is `run_python`)

## Immediate Next Steps

1. Validate the close-note UI on Mac: open task → Close → leave note empty → confirm closure; reopen → confirm note cleared; close with text → switch to Closed view → confirm note appears in subdued box.
2. Validate the two prior UI flows (archive/delete + Open→Tasks filter) on Mac, then commit alongside the close-note feature.
3. Exercise the memory tools end-to-end in mrcall-desktop on Mac (search → update/create round-trip).
4. Re-run Custom124 diagnosis after a few update cycles to confirm USER_NOTES guidance takes effect.
5. Split oversized files: `command_handlers.py` (5427), `workers/task_creation.py` (1149), `tools/gmail_tools.py` (1002), `workers/memory.py` (916).
6. Keep `tests/` directory renewal slow-burn — current live tests are the manual cache deliverables + `tests/workers/test_task_worker_bugs.py` + `tests/services/test_reanalyze_sweep.py`.

## Known Issues

- `services/command_handlers.py` (5427 lines) — 10x over 500-line guideline
- `tools/gmail_tools.py` (1002), `workers/task_creation.py` (1149), `workers/memory.py` (916) — all above guideline
- `services/sync_service.py` (574) — slightly over
- Legacy trained prompts with `{from_email}` placeholders fall back to old behavior (new prompts use cached system prompt)
- neonize "Press Ctrl+C to exit" line printed by Go runtime — not suppressible from Python
- Most tests in `tests/` are stale (except `tests/workers/test_task_worker_bugs.py` and the manual cache deliverables)
- WhatsApp session DB (`~/.zylch/whatsapp.db`) is global, not per-profile — multi-profile with different WA accounts not supported
- `oauth_tokens.last_sync` still never written by any code path
