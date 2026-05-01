# Fix task auto-close stale (RealStep / cafe124 case)

status: completed (F1 + F2 + F3 + F4 + cleanup, 2026-05-01)
created: 2026-05-01
profile observed: mario.alemi@cafe124.it

## Symptom

User replied in thread `<PAVPR10MB7034484AF4E54E024C85090BE648A@…>`
on 2026-04-30 18:16:39 UTC (Superhuman). The reply went `to=e.argento@realstep.it`,
`cc=ivan.marchese@cafe124milan.com + m.scacciati@realstep.it`. The
post-reply task run at 18:20:58 closed only the e.argento task (61af55e3).
Two open tasks on the same thread survived:

- de342a1d (m.scacciati@realstep.it) — created 04-21 17:00, never closed
- 5c66fa63 (ivan.marchese@cafe124milan.com) — created 04-27 12:31, never closed

Both `suggested_action` fields had been corrupted earlier with the LLM's
advisory text ("Keep existing task as-is: …", "No action needed — Ivan
is managing MareTerra…").

Suspected cause from user (timestamping): ruled out — `Date:` parsing was
fixed in v0.1.24, and the user-reply email's `date_timestamp` is correct.

## Root causes (ranked by impact on this incident)

### RC-1 — `get_tasks_by_thread` returned empty at 18:20:58 (mystery, not reproduced)

The per-thread close path at `task_creation.py:423-432` is the primary
mechanism for this scenario. It ran but `thread_tasks` was empty
(no `[TASK] dedup/close … decision=user_replied` debug line in the run,
despite DEBUG enabled). Post-hoc the same query against the live DB
returns 2 tasks. Cause not reproduced. Plausible candidates:

- Re-threading: `Email.thread_id` was different at run time vs. now
  (some `add_source_email` call later updated the linkage).
- Sources state: at run time, neither task had any `sources.emails`
  entry whose `Email.thread_id` matched PAVPR (would be surprising —
  de342a1d should have had m.scacciati's emails since 04-21 19:40).
- Read-side staleness inside the same SQLite connection (less likely
  given WAL + sequential access).

We do NOT attempt to fix RC-1 directly. RC-3 and RC-4 are compensating
controls that mask this failure mode regardless of root cause.

### RC-2 — "Forcing update on stale task" branch overwrites task description with LLM advisory

`task_creation.py:522-539`. Triggered when `task_action ∉ {update, close, create}`
(typically `"none"`) and `existing_tasks_all` is non-empty and
`result.suggested_action` is non-empty. It blindly writes `suggested_action`,
`reason`, `urgency` of `existing_tasks_all[0]` and adds the email as a
source. The LLM, given an existing task and a tangentially-related new
email, may answer `task_action="none"` with `suggested_action="Keep
existing task as-is: …"` — which then becomes the literal task body.

**Evidence in this incident:**
- 04-21 19:40:30 log shows `'task_action': 'none'` and
  `Forcing update on stale task de342a1d-… for m.scacciati`. The
  resulting `suggested_action` on de342a1d is "Keep existing task
  as-is: Coordinate with Ivan to reply to Edoardo Argento…".
- 5c66fa63 received `add_source_email` from at least 4 different
  thread runs (04-28 10:11, 04-29 16:37, 04-30 10:41, 04-30 12:11×2)
  — frankenization.

### RC-3 — Phase-2 user-reply fallback iterates only `to_email`

`task_creation.py:433-445`. The per-recipient fallback (used when the
per-thread path produces nothing) splits only `email.get("to_email")`.
`cc_email` and `bcc_email` are silently ignored. In this incident the
user replied with Ivan and Michele in CC; both their tasks would have
been closed via `get_task_by_contact` had the loop included CC.

This is the smallest, lowest-risk fix and would have rescued this exact
incident.

### RC-4 — No periodic reanalyze sweep

`process_pipeline.py:317-360` (`_run_tasks`) processes only unprocessed
emails. Once a task escapes initial closure (RC-1, RC-3), nothing
re-evaluates it. `task_reanalyze.reanalyze_task` is only triggered via
RPC `tasks.reanalyze` (single task, manual UI action).

A bounded sweep over open tasks during `_run_tasks` (e.g. tasks older
than N days OR all open tasks if count < threshold) would catch any
task that slipped past the user_reply pass — at the cost of one LLM
call per swept task per run.

### RC-5 (out of scope, fragility worth noting) — Dedup at create depends on `get_tasks_by_thread`

When `task_action == "create"`, Fix D (`task_creation.py:540-572`)
converts to update only if `existing_tasks_all` is non-empty.
`existing_tasks_all` is populated in `_collect` (326-338) only via
`get_tasks_by_thread + get_task_by_contact(from_email)`. If thread linkage
is briefly inconsistent (e.g. first email of a thread, or Message-Id chain
not yet stitched), a duplicate task on the same thread can be born. This
is how de342a1d came to exist alongside 61af55e3.

We do NOT fix this in this plan. Mitigations:
- RC-3 + RC-4 compensate at user-reply time and on the periodic sweep.
- A separate plan can revisit `_collect` to also probe by
  `Message-Id`/`References` chain or by all open tasks whose
  `sources.emails` resolve to any email in the same conversation.

## Fixes — ordered by risk × impact

### F1 (LOW risk, HIGH impact — DO FIRST) — Iterate CC + BCC in user_reply Phase 2

`task_creation.py:433-445`. After the existing `to_raw` loop, add an
identical loop for `email.get("cc_email")` and one for `email.get("bcc_email")`.
Use the same parser (split commas, strip `<…>` brackets, lowercase, skip
user_emails). Same `get_task_by_contact` + `complete_task_item` call,
same dedup against `thread_tasks`.

Rationale:
- Pure additive — no existing behaviour changes.
- Smallest possible change that resolves this exact incident.
- Cost is bounded: a few extra `get_task_by_contact` calls per user reply.

Test:
- Unit test in `tests/workers/test_task_worker_bugs.py`: build a fake
  user reply with `to=A`, `cc=B,C`, with open tasks on B and C from
  the same thread but `get_tasks_by_thread` mocked to return `[]`.
  Assert both B and C tasks are completed.

### F2 (MEDIUM risk, HIGH impact) — Stop "Forcing update on stale task" branch

`task_creation.py:522-539`. The branch's intent (mark sibling emails
as task-processed when the LLM says "none" so the thread is not
re-analyzed) is achievable without overwriting the task body.

Two options:

**F2.a (preferred)** — drop the `update_task_item` call entirely.
Keep only `_mark_thread_nonuser_processed(thread_id)` (already at line
580 outside the if/elif chain — check it still runs in this branch).
The task is left untouched; the email is marked processed.

**F2.b (more conservative)** — same as F2.a but log a warning
`[TASK] LLM returned 'none' but advisory present, NOT updating task
{stale['id']} thread_id={thread_id}`. Useful for observability during
the rollout.

Risk:
- Possible regression: any "intended" behaviour where a `none` answer
  with advisory was meant to refresh urgency or push a re-think. Audit
  call sites and LLM prompts (`agents/trainers/task_email.py`) before
  shipping. If the prompt explicitly tells the LLM to use
  `suggested_action` as a "no-op note", we need to retrain it.
- Cleanup: the corrupted `suggested_action` on de342a1d/5c66fa63 stays
  until explicit user action (`tasks.reanalyze`) or the periodic sweep
  (F4). A one-shot script can reset corrupted fields if the user wants.

Test:
- Unit test: feed `task_action="none"` with non-empty
  `suggested_action` and pre-existing task. Assert task fields unchanged
  and email marked processed.

### F3 (LOW risk, MEDIUM impact) — Defensive log when `get_tasks_by_thread` returns empty in user_reply

`task_creation.py:422-432`. Add a `logger.debug` line when
`thread_tasks` is empty: include `thread_id`, `email_id`, and the
result of a second-chance call (e.g. count of all open tasks for owner
whose `sources.emails` contains any email in this thread, computed
inline). Helps reproduce RC-1 next time.

This is observability only, no behaviour change.

### F4 (HIGHER risk, MEDIUM impact — defense in depth) — Bounded reanalyze sweep at end of `_run_tasks`

`process_pipeline.py:317-360`. After `worker.get_tasks(refresh=True)`,
sweep open tasks via `task_reanalyze.reanalyze_task`. Bound the sweep
so it doesn't blow up:

- Filter: tasks where `(now - max(analyzed_at, created_at)) >= 24h`
  AND task hasn't been re-analyzed in the last 12h. (Rough — exact
  numbers tbd.)
- Cap: at most `N=10` tasks per run, ordered by `analyzed_at ASC`
  (oldest first).
- Skip if no LLM credentials (already handled by `reanalyze_task`).
- Concurrency: serial (reanalyze already does its own LLM call;
  parallelizing risks rate limits). Optional: `asyncio.Semaphore(2)`.

Cost: up to 10 extra LLM calls per `update` run. With prompt caching
on the trained system, marginal cost is ~the user content (thread
history) per task.

Risk:
- Could close a task that the user genuinely wanted open (LLM
  decision). Mitigated by the same prompt the manual reanalyze uses
  — it's not new behaviour, just more frequent.
- Could update a task in unexpected ways. Same mitigation.
- User notes / preferences not exposed to reanalyze prompt today —
  if F2 reveals that the "advisory becomes task body" pattern was
  load-bearing for some signal, F4's reanalyze must cover the same.

Test:
- Unit test: insert N=15 stale tasks, run `_run_tasks`, assert exactly
  10 reanalyzed and the remaining 5 are the newest.
- Integration smoke: run `zylch -p user@example.com update` on a
  test profile with a known stale task and confirm it gets closed.

## Sequencing

1. **F1** — implement, test, commit alone. Smallest blast radius.
2. **F3** — implement, commit alone. Pure observability. Helps next
   incident.
3. **F2** — audit prompts, implement (F2.a), test, commit. Document
   in `active-context.md` that "Forcing update on stale task" is
   removed.
4. **F4** — implement, test, commit. Probably bump version (defensive
   but user-visible: more LLM calls per `update`).

Steps 1-3 can ship together if confident. Step 4 should be its own
PR with explicit version bump.

## Status — 2026-05-01

**F1 (CC fallback) — DONE.** `task_creation.py` user_reply branch now
iterates `to_email + cc_email` via a single `_split_addrs` helper, with
deduping. `storage.get_unprocessed_emails_for_task` was missing
`cc_email` in its SELECT; added. Three new tests in
`tests/workers/test_task_worker_bugs.py::TestUserReplyClosesCcRecipientTask`:
contact-in-Cc closes, user-self-in-Cc skipped, dedup To+Cc.

**F2 (kill "Forcing update") — DONE (variant F2.b: warning log,
no update).** Trainer `agents/trainers/task_email.py` is a
meta-prompt (it generates the per-user task prompt at training
time); no static prompt audit possible. Decision: keep the
log-and-skip variant rather than silent-drop, so we get a signal
in `zylch.log` if any deployment was relying on this branch. The
existing per-user trained prompts in storage will need to be
re-trained eventually if they tell the LLM to use
`suggested_action` as a no-op note (no evidence they do).
New test
`TestForcingUpdateBranchDoesNotCorruptTask::test_none_with_advisory_does_not_update_existing_task`
asserts no `update_task_item` call when LLM returns `task_action=none`
+ advisory text.

**F3 (diagnostic log) — DONE.** When `get_tasks_by_thread` returns
empty in the user_reply branch, we log
`[TASK] user_reply thread_tasks=EMPTY thread_id=… email_id=…
from_email=… — falling back to recipients`. Next time RC-1
recurs there will be a reproducer line in `zylch.log`.

**F4 (periodic reanalyze sweep) — DONE.**
`zylch/services/process_pipeline.py:_reanalyze_sweep` runs at the end
of `_run_tasks`. Bounded by `REANALYZE_MIN_AGE_HOURS=24` (skip
fresh tasks) and `REANALYZE_CAP=10` (oldest first). Operates on
the in-memory tasks list returned by `worker.get_tasks(refresh=True)`,
so no extra `get_task_items` query. Calls `reanalyze_task` serially
to avoid LLM rate limits. Tolerates per-task exceptions. Logs an
INFO line `[TASK] Reanalyze sweep: N of M eligible (cap=…, min_age_h=…)`.
Cost: up to 10 extra LLM calls per `update` run; with prompt caching
on the trained system, marginal cost is the user content per task.
Tests: `tests/services/test_reanalyze_sweep.py` (6 cases — empty,
oldest-first cap, completed-skip, exception-tolerance, created_at
fallback, action_required-skip).

**Pre-existing test fix (bonus).**
`TestColleagueEmailCreatesTask::test_colleague_email_not_skipped`
was broken on main (deferred `from zylch.storage.database import
get_session` in `_collect` re-imports the un-patched module).
Patched the test to re-apply `patch("zylch.storage.database.get_session")`
inside the test body alongside `build_thread_history`. 14/14 tests
green now.

**Manual cleanup — DONE.** de342a1d and 5c66fa63 on
`mario.alemi@cafe124.it` were closed via direct SQL UPDATE on the
profile DB at 2026-05-01 10:49:32 UTC (Mario had already replied to
the thread on 04-30, so closing is correct). The corrupted
`suggested_action` strings remain on the rows but the tasks are no
longer surfaced. If anyone wants to re-open with a corrected
description, `tasks.reanalyze` from the UI will produce a clean
update.

## Manual cleanup (one-shot)

After F2 ships, the corrupted `suggested_action` fields on de342a1d
and 5c66fa63 remain. Options:

- Manually `tasks.reanalyze` each from the desktop UI.
- Manually `tasks.complete` each from the desktop UI (user knows the
  underlying issue is resolved).
- Wait for F4's sweep to pick them up.

No automated cleanup script is proposed — these are two specific
tasks on one profile.

## Out of scope (separate plans)

- RC-5 (dedup-at-create fragility). Needs a deeper look at threading
  in `_collect` — possibly probe by Message-Id/References chain or
  by union of open-task source threads. Defer.
- Why `get_tasks_by_thread` returned empty at 18:20:58 (RC-1).
  F3's diagnostic log will give us a reproducer the next time.

## Acceptance

- F1 unit test passes.
- F2 unit test passes; `task_email` prompt audit committed alongside.
- F3 produces a debug line on the next "missed close" event.
- F4 unit + smoke tests pass; observed cost increase per `update` run
  documented.
- A re-run of the RealStep scenario on a fresh profile (mock or
  real) closes all three tasks (Argento, Michele, Ivan) in a single
  user-reply pass.
