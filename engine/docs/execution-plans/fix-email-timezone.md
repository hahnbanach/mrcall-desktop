# Fix Email Timezone Parsing Bug
status: completed (2026-04-21, v0.1.24)

## Goal

Stop silently corrupting the `Date:` header of every email sent from a non-UTC timezone. Currently the naive-datetime column `emails.date` stores the wall-clock value of the sender's timezone as if it were UTC, shifting chronology by the offset. Task detection reasons on wrong timestamps, producing false "unanswered" tasks.

## Root Cause (confirmed)

RFC 2822 `Date:` header example: `Fri, 27 Feb 2026 07:42:27 -0600`. Real UTC is `13:42:27`. Zylch stores `07:42:27`.

Two points in code drop the offset instead of converting to UTC:

1. **`zylch/storage/storage.py:164`** — `parsedate_to_datetime(raw_date)` returns a tz-aware datetime; it is then passed directly to SQLAlchemy's naive `DateTime` column (`models.py:92`). SQLAlchemy/SQLite stores the wall-clock portion and discards tzinfo.
2. **`zylch/tools/email_sync.py:596`** — `return dt.replace(tzinfo=None)` explicitly strips the offset "for comparison". This is wrong: `replace(tzinfo=None)` does NOT convert; it just chops the tz, leaving local wall-clock.

`emails.date_timestamp` (integer epoch, `models.py:93`) is **correct** — `email_archive.py:244` uses `int(dt.timestamp())` on the tz-aware datetime, which produces true UTC epoch seconds. This is the lifeline for migration (no IMAP re-fetch needed).

## Fix Strategy

### Parser fixes (forward-going)

- `storage.py:164`: replace with
  ```python
  raw_date = parsedate_to_datetime(raw_date).astimezone(timezone.utc).replace(tzinfo=None)
  ```
  Stores naive UTC — preserves existing column type, matches `_utcnow` convention used elsewhere in the model (`models.py:101, 102`).

- `email_sync.py:595–596` and `:600–601`: same treatment — `.astimezone(timezone.utc).replace(tzinfo=None)` instead of `.replace(tzinfo=None)`.

- `imap_client.py:421`: consider parsing at source (return tz-aware datetime instead of raw string) so every consumer gets the same correct value. **Decision required from user**: small refactor risk vs. leaving the raw-string contract intact and only fixing consumers.

### Column type — decision required from user

Keep `Email.date` as naive `DateTime` (current) or migrate to `DateTime(timezone=True)`?
- **Keep naive**: simplest, no model change, every insert stores UTC as naive.
- **Make tz-aware**: correct by construction, but every query/comparison site (`workers/task_creation.py`, `workers/memory.py`, CLI formatters) must audit for tz-aware-vs-naive comparison bugs (~20 sites per grep).

Recommendation: **keep naive UTC** for the fix. Revisit tz-aware migration as a separate task.

## Data Migration for Existing ~920 Rows

Because `date_timestamp` is already correct UTC epoch, no IMAP re-fetch needed. One-shot SQL backfill:

```sql
UPDATE emails
SET date = datetime(date_timestamp, 'unixepoch')
WHERE date_timestamp IS NOT NULL;
```

- Run per-profile against `~/.zylch/profiles/*/zylch.db`.
- Rows where `date_timestamp IS NULL` (should be rare/none) get hand-reviewed or left alone.
- Ship as `scripts/backfill_email_date_utc.py` that iterates profiles, prints before/after counts, and exits 0.
- Dry-run flag mandatory; default is dry-run.

**User confirmation required** before running the non-dry version.

## Task Re-analysis

Open tasks were computed from wrong chronology. Options:

- **A (destructive)**: `DELETE FROM task_items WHERE completed_at IS NULL;` then `zylch -p <profile> process` to rebuild. Fast, clean, but loses any manual task edits. **User confirmation required.**
- **B (gentle)**: clear `emails.task_processed_at` for affected threads only, re-run task worker. Preserves existing tasks; detector updates/closes them based on corrected dates. Slower, risk of duplicates.

Recommendation: **B for production profiles**, **A for the support@mrcall.ai profile** where the user is actively testing and has seen fewer than a dozen tasks.

## Test Plan (user-facing, per project rules)

Use the product as a user would.

1. **Pre-fix snapshot** (read-only, already confirmed):
   ```
   sqlite3 ~/.zylch/profiles/support@mrcall.ai/zylch.db \
     "SELECT date, date_timestamp FROM emails WHERE message_id_header LIKE '%CAECLDjt9-OHBwsCzvjaMjPWM%';"
   ```
   Expected current (buggy) output: `2026-02-27 07:42:27 | 1740663747` (timestamp is already correct; naive date is wrong).

2. **Apply parser fix + lint**:
   ```
   make lint
   ```
   Must exit 0.

3. **Fresh-sync test**: delete one known row, re-sync, verify correct date.
   ```
   # delete the Tentacools 14:42 reply row (by gmail_id), then:
   zylch -p support@mrcall.ai sync
   sqlite3 ... "SELECT date FROM emails WHERE message_id_header LIKE '%CAECLDjt9-OHBwsCzvjaMjPWM%';"
   ```
   Expected: `2026-02-27 13:42:27`.

4. **Run backfill dry-run** on support@mrcall.ai profile. Verify printed before/after for 3–5 known rows.

5. **Apply backfill (real)**. Re-query the Tentacools row. Must now read `13:42:27`.

6. **Re-run task detection** on support@mrcall.ai (strategy A: delete open tasks + `zylch process`). Verify the Tentacools task is now auto-closed (support replied after the customer's last message).

7. **Regression guard**: add `tests/email/test_date_parsing.py` with three cases:
   - `Fri, 27 Feb 2026 07:42:27 -0600` → stored value `2026-02-27 13:42:27` naive UTC.
   - `Thu, 20 Nov 2025 10:30:59 +0100` → stored `2025-11-20 09:30:59`.
   - `Wed, 01 Jan 2025 00:00:00 +0000` → stored `2025-01-01 00:00:00`.
   Cheap unit test, no IMAP needed — tests `storage.py` insertion path directly.

## Rollout Order

1. Write failing unit test (step 7) — verifies bug before fix.
2. Patch `storage.py:164` and `email_sync.py:595-601`.
3. Confirm test passes. `make lint`.
4. Manual sync test (step 3 above) on support@mrcall.ai.
5. Write `scripts/backfill_email_date_utc.py` (dry-run default).
6. User runs backfill dry-run, reviews output.
7. User runs backfill for real (per-profile).
8. User re-runs task detection per profile (strategy A or B).
9. User verifies Tentacools task auto-closes — then this plan is done.

No deploy step. Local CLI.

## Open Questions (require user input)

- Parse at source (imap_client return tz-aware datetime) vs fix only at storage? → **Recommendation: fix only at storage**, leave raw-string contract.
- Column type change `DateTime` → `DateTime(timezone=True)`? → **Recommendation: no**, separate task.
- Task cleanup strategy A vs B? → **Recommendation: A for support@mrcall.ai, B elsewhere**.
- Is the project OK depending on `date_timestamp` always being populated? Any code path that inserts without setting it? A quick audit of `storage.py` insertion sites is a prerequisite for the backfill SQL above.
