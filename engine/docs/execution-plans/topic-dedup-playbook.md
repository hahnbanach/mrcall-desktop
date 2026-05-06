# Playbook — "stesso problema, 4 task aperti, non spariscono"

status: live (deployed in commits `557e65b` + `ec61067`, 2026-05-06 evening)
owner: anyone debugging recurrent task duplication

## What this file is

A diagnostic playbook for the next session that has to debug the same
class of bug. **Read this BEFORE touching code.** The user has been
burned by 5 sessions that "fixed" something without ever testing the
real `update.run` against the live DB. Don't be the sixth.

## Symptom

User has N tasks open. Among them, M tasks all describe the same
underlying real-world problem but come from different
contacts / channels. Concrete example seen on profile
`HxiZhWEBoRUarPzqX8eRWP21FuJ3` (`mario.alemi@gmail.com`):

- email task from `carmine.salamone@cnit.it` ("Riscontro Formazione Obbligatoria")
- email task from `noreply@aifos.it` (automated platform notification)
- MrCall missed-call task from `notification@transactional.mrcall.ai` (Apr 14)
- MrCall missed-call task from `notification@transactional.mrcall.ai` (Apr 20)

User clicks `Update`. The 4 tasks remain. User clicks `Update` again.
Still 4 tasks. User loses trust. User curses the assistant.

## How to recognise it WITHOUT changing code

1. Count open tasks per contact for the affected profile. Anything
   with `n > 1` is a candidate, but don't stop there — different
   contacts on the SAME topic also count. Use:

   ```
   /home/mal/hb/mrcall-desktop/engine/.venv-debug/bin/python <<'PY'
   import sqlite3, json
   db = "/home/mal/.zylch/profiles/<UID>/zylch.db"
   c = sqlite3.connect(db); c.row_factory = sqlite3.Row
   for r in c.execute("""
     SELECT contact_email, COUNT(*) n
     FROM task_items WHERE completed_at IS NULL AND action_required=1
     GROUP BY contact_email ORDER BY n DESC LIMIT 20"""):
       print(f"  {r['n']:3d}  {r['contact_email']}")
   PY
   ```

2. Look at the `reason` / `suggested_action` text of the suspect rows
   and ask "do these describe ONE problem?". If yes → topic-dedup
   should have caught it. If F9 was supposed to run and didn't,
   move to "Diagnosis".

## Diagnosis path (in order)

### Step 1 — did F9 even fire?

Check the latest sidecar log for the affected profile:

```
grep -E "topic-dedup|update.summary" \
  ~/.zylch/profiles/<UID>/zylch.log | tail -n 20
```

Expected on every `/update` after this commit:

```
[topic-dedup] sweep complete: {'examined': N, 'clusters_with_dups': K, 'tasks_closed': M, ...}
[update.summary] sync=… tasks_pending=… open_before=… open_after=… …
```

Failure modes:

| Log line | Meaning | Fix |
|---|---|---|
| no `[topic-dedup]` line at all | F9 not wired to pipeline | Re-check `process_pipeline._run_tasks` and `_reanalyze_only` both call `_run_topic_dedup` after `_run_dedup_sweep`. |
| `'no_llm': True` | No Anthropic key + no Firebase session | User must paste `ANTHROPIC_API_KEY` in profile `.env` or sign in to Firebase. |
| `'skipped_too_few_tasks': True` | `<4` open tasks | Threshold lives in `task_topic_dedup.MIN_TASKS_FOR_TOPIC_DEDUP`. Lower if needed. |
| `'skipped_too_many_tasks': True` | `>120` open tasks | Threshold in `MAX_TASKS_FOR_TOPIC_DEDUP`. |
| `'examined': N, 'clusters_with_dups': 0` | LLM said "all distinct" | Look at the prompt. The user-visible task list IS the LLM's input; tighten the prompt in `_build_prompt` if the model is being too conservative. |

### Step 2 — is the channel column populated?

Channel-based filtering and the >30d phone auto-close BOTH depend on
`task_items.channel` being non-NULL. If a profile is fresh-migrated
from an older release, the column-add migration runs but the row
backfill might not.

```
/home/mal/hb/mrcall-desktop/engine/.venv-debug/bin/python <<'PY'
import sqlite3
c = sqlite3.connect("/home/mal/.zylch/profiles/<UID>/zylch.db")
for r in c.execute("""
  SELECT channel, COUNT(*) FROM task_items
  WHERE completed_at IS NULL AND action_required=1
  GROUP BY channel"""):
    print(r)
PY
```

If you see `(None, N)` with N > 0, the row backfill didn't run.
Symptom of the bug fixed in `557e65b`. Hard reproduction below.

### Step 3 — reproduce against the live DB (read-only-ish)

The ONLY test that counts is running the real pipeline against the
real DB. Unit tests do not count. Use:

```
ZYLCH_DB_PATH=/home/mal/.zylch/profiles/<UID>/zylch.db \
EMAIL_ADDRESS=<email> OWNER_ID=<email> \
/home/mal/hb/mrcall-desktop/engine/.venv-debug/bin/python <<'PY'
import asyncio, logging, sys
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
for n in ('anthropic._base_client','httpx','httpcore'):
    logging.getLogger(n).setLevel(logging.WARNING)
from zylch.storage.storage import Storage
from zylch.services.process_pipeline import _reanalyze_only
async def main():
    swept = await _reanalyze_only("<email>", Storage.get_instance())
    print(f"swept={swept}")
asyncio.run(main())
PY
```

`_reanalyze_only` is exactly what `update.run` calls when there are no
new emails — so this exercises F4 (reanalyze sweep) + F8 (deterministic
dedup) + F9 (topic dedup) + Fase 3.3 (phone>30d auto-close) without
hitting IMAP. Watch the stdout for the same log lines you'd see in
the sidecar.

If you must touch the DB destructively (reopening tasks to test a
fix), use `/tmp/HxiZh-test.db` instead of the live file. The user said
"il db lo puoi far esplodere" but be sane about it. Always `cp` first.

### Step 4 — final-mile check via the actual JSON-RPC

Even if the SQL says "30 open", the app might still render 57. Check
that `tasks.list` (the call the renderer issues) returns what you
expect:

```
HOME=/tmp/zylch-test-home  # so the sidecar binds to a sandbox profile
/home/mal/hb/mrcall-desktop/engine/.venv-debug/bin/zylch -p HxiZh-test rpc
```

Then send `{"jsonrpc":"2.0","id":1,"method":"tasks.list","params":{}}`
on stdin and parse the result. The Python harness used during the
2026-05-06 fix is preserved in this file's git history — search for
the `subprocess.Popen(...zylch...rpc...)` invocation in commit
`ec61067`'s log if you need a copy.

## What F9 covers and what it doesn't

**Covers:**
- Cross-channel duplication (email + phone notification + automated
  platform notification all about one issue).
- Cross-contact duplication (Salamone person + AiFOS company + MrCall
  notification address all about the safety course).
- Repeated callbacks from the same caller (Pietro Giana 5→1 case).
- Repeated low-balance / quota alerts (Tiscali Store 10→1 case).

**Does not cover:**
- LLM-driven CLOSE of a single task because the user replied. That
  is F4's job (`task_reanalyze`). F9 only deduplicates; it never
  closes a singleton.
- Cluster size > 120 open tasks. F9 skips the whole sweep at that
  size (prompt becomes a haystack). If the user genuinely accumulates
  >120 open tasks, the right answer is to figure out why creation is
  out of control, not to crank the cap.
- Newly created tasks in the same `update` run that haven't yet been
  written to the DB at the moment F9 runs. F9 runs at the end of the
  pipeline so this is mostly fine, but a task created during F9's
  read could in theory be missed. Next `update` catches it.

## Cost

One Opus 4.6 message per `/update` at most. Empirical: 13k input + 1.5k
output tokens on the gmail profile (57 open tasks). At list price
~$0.30 per call. The user has accepted this cost — see commit message
on `ec61067`.

## Knobs

All in `engine/zylch/workers/task_topic_dedup.py`:

| Constant | Default | What |
|---|---|---|
| `MIN_TASKS_FOR_TOPIC_DEDUP` | 4 | Skip the sweep entirely below this. |
| `MAX_TASKS_FOR_TOPIC_DEDUP` | 120 | Skip the sweep entirely above this. |
| `DEDUP_SKIP_DAYS` | 7 | Reopen-protection window (matches F8). |
| `TOPIC_DEDUP_NOTE_TEMPLATE` | `"Duplicate of {keeper_id} (auto-merged by topic dedup: {topic})"` | Stamped on `close_note` of every closed duplicate. |

Pipeline ordering lives in `engine/zylch/services/process_pipeline.py`:
F4 → F8 → F9 → Fase 3.3 → `[update.summary]` log.

## What I changed in the 2026-05-06 evening session

Two commits, both pushed to `origin/main`:

- `557e65b fix(storage): unblock Fase 3.1/3.2 backfills (split early-return)`
  — `_apply_data_backfills` had its first backfill (`sources.thread_id`)
  inlined with `if not needs_lookup: return`. That `return` killed the
  whole dispatcher, so the Fase 3.1 (`email_blobs` index) and Fase 3.2
  (`task_items.channel`) backfills appended below it never ran on any
  install whose tasks already had `thread_id`. Lifted the inlined body
  into `_backfill_task_thread_id()` so the early-out is local.
- `ec61067 feat(tasks): F9 cross-contact topic dedup`
  — new worker, hooked into both `_run_tasks` and `_reanalyze_only`,
  with `tasks.topic_dedup_now` RPC for a manual trigger.

## What I didn't fix and why

- **Reanalyze (F4) keeps the Salamone email task open even though
  the user replied to a sibling thread.** The reason is the
  Opus 4.6 model itself: shown a clear thread + sibling thread with
  the user's "Se lo riattivate vedo di finirlo" reply, the model
  still chose `KEEP` because "compliance obligation" is interpreted
  as "user must complete the course, not just reply". I did not
  change the F4 prompt — F9 closes the duplicates around it, so
  the user sees ONE row instead of FOUR, which is what they asked
  for. If a future session wants to push for an outright CLOSE of
  the keeper too, the lever is `_build_user_content` in
  `engine/zylch/workers/task_reanalyze.py`.

- **The `_backfill_email_blobs_index` in `database.py` has a
  `if existing_links is not None: return` guard.** That guard skips
  the backfill if even ONE `email_blobs` row exists. On the gmail
  profile this means 9 / 607 blobs are indexed, the rest aren't.
  F7's deterministic-lookup gets reduced coverage. This is a smaller
  bug and orthogonal to the topic-dedup work. Left for a focused
  follow-up.
