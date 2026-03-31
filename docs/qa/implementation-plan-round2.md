# QA Implementation Plan - Round 2

Date: 2026-03-31

---

## Finding 1: `/email search` deprecated with no working alternative

### Problem

`/email search sorvillo` returns a deprecation message pointing to `/agent email run`,
which requires an LLM API key. A simple DB search should not need LLM.

### Root Cause

The `search` subcommand in `handle_email()` was replaced wholesale with a deprecation
string (line ~2103 of `command_handlers.py`). The `emails` table already has a
`fts_document` TSVECTOR column (weighted: subject=A, body_plain=B, from_email=C) with
a GIN index (`idx_emails_fts_document`), so PostgreSQL full-text search is ready to use.

### Plan

**Files to modify:**

1. `zylch/services/command_handlers.py` -- replace the deprecation block for `search`

**Changes:**

- Remove the deprecation return (lines 2103-2113).
- Implement a direct PostgreSQL FTS query against `emails.fts_document`:
  ```
  plainto_tsquery('english', query) matched against fts_document
  ```
- Support existing flags: `--from <sender>` (ILIKE on `from_email`), `--days N`
  (filter on `date`), `--limit N` (default 10, max 50).
- Return formatted results: date, from, subject, snippet (first 120 chars).
  Include `ts_headline()` for query term highlighting in snippet.
- Also add ILIKE fallback on `from_email` and `from_name` when query looks like
  a person name (no spaces, single token) -- covers the "sorvillo" case where
  the name may not appear in subject/body.
- Follow the existing pattern in `handle_email()` for session handling and
  owner_id filtering.

**Complexity:** Low. Single file change, uses existing DB infrastructure.

**Dependencies:** None. The `fts_document` column and GIN index already exist.

**Testing:**

- `python -m pytest tests/ -k email` (existing tests still pass)
- Manual: `/email search sorvillo`, `/email search contratto --days 30`,
  `/email search invoice --from mario --limit 5`

---

## Finding 2: New emails from sync don't generate tasks automatically

### Problem

After syncing 307 new emails, task count stays at 11. The "Cancellare abbonamento"
email from Antonio Sorvillo is in the DB but no task was created.

### Root Cause

Task detection is a separate step (`/agent task process`) that must be run manually.
However, the infrastructure for auto-chaining already exists:
`job_executor._chain_processing_after_sync()` (line ~871) chains memory_process and
then task_process after sync -- but only when a trained memory agent exists. When
the memory agent is not trained, it checks for a task agent and chains task_process
directly. The chain requires an LLM API key (passed through the job params).

The real gap: when sync runs without an API key (or without trained agents), no
chaining happens and the user gets no indication that tasks were not processed.

### Plan

**Files to modify:**

1. `zylch/services/job_executor.py` -- improve chaining logic and notification
2. `zylch/services/command_handlers.py` -- add post-sync guidance in `/sync` output

**Changes in `job_executor.py`:**

- In `_chain_processing_after_sync()`: when neither memory agent nor task agent is
  trained, create an info notification telling the user:
  "New emails synced but task detection is not configured. Run `/agent task train email`
  to enable automatic task creation."
- When agents ARE trained but API key is missing, create a notification:
  "New emails synced but task processing skipped: no API key. Run `/connect <provider>`."
- Add debug logging at each decision branch (per CLAUDE.md rules).

**Changes in `command_handlers.py`:**

- In the `/sync` response formatter: if the sync result includes new emails and the
  user has no trained task agent, append a one-line hint:
  "Tip: run `/agent task train email` to auto-detect tasks from new emails."
- Only show this hint once (check if task agent prompt exists via
  `storage.get_agent_prompt(owner_id, 'task_email')`).

**Complexity:** Medium. Two files, logic changes in the chaining flow. Must not
break the existing chain when agents ARE trained and API key IS present.

**Dependencies:** Finding 3 (notification dedup) should ideally land first or
together, since this adds new notifications.

**Testing:**

- Manual: run `/sync` without trained agents, verify hint appears.
- Manual: train task agent, run `/sync`, verify tasks are auto-created.
- `python -m pytest tests/ -v` (regression check)

---

## Finding 3: "API key required" error banner repeats every message

### Problem

The notification "Background job failed: API key required for memory extraction"
appears on every single message. It gets created once in `job_executor.py` (line 143)
as a `UserNotification` row, then `get_unread_notifications` fetches it, and
`mark_notifications_read` marks it read. But every failed background job creates a
NEW notification row with the same message, so the user sees it repeatedly.

### Root Cause

Two issues:
1. **Duplicate creation:** Each failed job creates a new notification via
   `create_notification()` without checking if an identical unread notification
   already exists for the same user.
2. **No dedup on read:** Even if creation is fixed, the pattern of "create error
   notification per job failure" means repeated failures produce repeated banners.

### Plan

**Files to modify:**

1. `zylch/storage/storage.py` -- add dedup to `create_notification()`
2. `zylch/services/job_executor.py` -- normalize error messages before creating
   notifications

**Changes in `storage.py`:**

- In `create_notification()`: before inserting, check if an unread notification with
  the same `owner_id`, `notification_type`, and `message` already exists. If so, skip
  the insert and return the existing row. This is a simple SELECT before INSERT,
  acceptable because notification creation is low-frequency.
  ```python
  existing = session.query(UserNotification).filter(
      UserNotification.owner_id == owner_id,
      UserNotification.message == message,
      UserNotification.read == False,
  ).first()
  if existing:
      logger.debug(f"Notification dedup: identical unread exists for {owner_id}")
      return existing.to_dict()
  ```

**Changes in `job_executor.py`:**

- In the generic exception handler (line 140-147): normalize the error message to
  remove job-specific UUIDs before passing to `create_notification()`. For example,
  strip the job_id prefix so "API key required for memory extraction" always produces
  the same message string regardless of which job failed.
- Group related failures: if the error contains "API key required", use a single
  canonical message: "Background jobs require an API key. Run `/connect <provider>` to
  configure." This prevents slight message variations from bypassing dedup.

**Complexity:** Low. Two small changes, no schema migration needed.

**Dependencies:** None. Should land before or with Finding 2.

**Testing:**

- Manual: trigger two background jobs without API key, verify only one banner appears.
- Manual: dismiss the banner (read it), trigger another failure, verify it appears
  once more (not suppressed permanently).
- `python -m pytest tests/ -v` (regression check)

---

## Implementation Order

| Order | Finding | Complexity | Reason |
|-------|---------|------------|--------|
| 1     | F3 (notification dedup) | Low | Foundation for F2; standalone fix |
| 2     | F1 (email search FTS)   | Low | Standalone fix, no dependencies |
| 3     | F2 (auto-task after sync) | Medium | Depends on F3 for clean notifications |

Estimated total effort: ~2-3 hours of implementation + manual QA.
