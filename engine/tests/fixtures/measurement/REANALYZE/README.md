# REANALYZE — measurement cases

Scope: the synthetic cases, labels and capture harness of the `REANALYZE`
role for milestone 10 (brief D7, plan S4a). The measurement (S4b/S4c)
replays each captured request on several models and scores every answer
against its label; nothing in this directory calls a model or needs a key.

## What the role decides

For one existing open task, given the latest history of its thread (and
of related threads with the same contact), the reanalysis decides through
the `reanalyze_decision` tool whether the task is still accurate (`keep`),
resolved or no longer actionable (`close`), or still open but stale
(`update`, with a fresh suggested action). Call site `f4.reanalyze` in
`zylch/workers/task_reanalyze.py` (`reanalyze_task`, shared by the F4
sweep, the `tasks.reanalyze` RPC and the CLI `/update <task_id>`; it builds
and sends the request), model key `MODEL_REANALYZE`.

## Files

| File | What |
|------|------|
| `cases.json` | 20 cases: `{"schema": 1, "role", "builder", "cases": [...]}` |
| `capture.py` | `build_requests(cases)` → `[{"case_id", "call_site", "request"}]` |

The profile owners and their trained task prompt — the reanalysis system
prompt in production — are the ones of `../TASK_DETECTION/profiles.json`.

## A case

`id`, `lang`, `call_site` (`f4.reanalyze`), `input`, `label`, `critical`,
`why` (what the case tests and why the label is right).

`input`:

- `profile` — `it` (Giulia Ferraris, Serramenti Ferraris s.r.l.) or `en`
  (Tom Hale, Harbour Lane Design Ltd).
- `now` — `2026-10-01T09:00:00Z` (a Thursday); the harness pins the clock
  the builder reads to it, so "today", "N days ago" and the 60-day window
  of related threads are the same on any day.
- `task` — the open task under review, as stored: `id`, contact,
  `title`, `urgency`, `suggested_action`, `reason`, `channel`,
  `created_at`, `analyzed_at`, `sources` (source email and `thread_id`).
- `emails` — its thread, and in `reanalyze-14` a related thread with the
  same contact: `id`, `thread_id`, `from`, `to`, `subject`, `date`, `body`,
  `auto_reply` when set (`reanalyze-03`: the owner's mailbox acknowledged
  automatically).

`lang` is the profile owner's language, the language an `update`'s new
suggested action is expected in.

## Label and scoring

The answer is the input of the model's `reanalyze_decision` call. One
field is labelled and compared exactly: `action` (`keep`, `close`,
`update`), after the engine's own lower-casing. A case passes when it
matches. Not scored: `urgency`, `suggested_action`, `title`, `reason`
(taste), and `waiting_on`, which the engine checks against its own
deterministic reading of the thread and logs; it could serve as a
diagnostic.

The labels follow the user message's own rules: the owner replied with
the next step and the ball is in the contact's court → `close`; the
request was fulfilled, withdrawn, or its deadline passed → `close` (the
contact may have written last: "WAITING ON US" does not keep a resolved
task open); the ask, the quantities or the deadline changed → `update`;
otherwise → `keep`, and an urgency may not be lowered while the contact
waits on us (`reanalyze-05`, "no rush").

`critical: true` marks the cases where every wrong answer causes real
harm, so a failed critical case is a critical failure:

- the `update` cases — the contact changed what the task states
  (quantities, languages and end date, a different request, an earlier
  deadline, new questions with a deadline, a cancelled deliverable
  replaced by another): `keep` leaves the owner working from wrong facts,
  `close` drops the request;
- `reanalyze-03` — the only message after the warranty request is the
  mailbox's automatic acknowledgment, made before the task: nothing
  changed, and closing drops the claim.

The other `keep` and the `close` cases are not critical: their likely
errors (an unneeded update, a resolved task left open) are not harmful.

Distribution: keep 7, close 7, update 6; `it` 10, `en` 10; 7 critical.

## How the harness drives the builder

For each case `capture.py`:

1. boots a disposable profile and database through the real `init_db`
   (`tests/measurement/task_roles_env.py`), with the profile owner's
   identity in the environment, so the engine appends the owner's
   personal-data section to the trained prompt;
2. pins the clock of `task_reanalyze`, `thread_presenter` and
   `storage.storage` to `now`;
3. seeds the trained prompt (agent type `task_email`), the emails and the
   task;
4. calls `reanalyze_task(task_id, owner_id)`, which loads the task,
   renders the thread history and the related threads, resolves who is
   waiting and builds the request;
5. records it with a capturing client (no network) and checks it is the
   only request, from `f4.reanalyze`, routed through `MODEL_REANALYZE`;
   the function returns its "no decision" result and the task is
   untouched.

Nothing of the engine is replaced.

## Notes for the measurement

- Usage: load `capture.py` by path (it loads `tests/measurement/task_roles_env.py`
  beside it, so only `zylch` must be importable) and call
  `build_requests(cases)` with the `cases` list, from synchronous code. Each
  case gets its own profile and database; the environment and the storage
  singletons are restored afterwards, so hold no open engine across the call.
  `tests/measurement/test_capture_task_roles.py` runs it on every case.
- The captured request is what `reanalyze_task` passes to
  `create_message` (`system`, `messages`, `tools`, `tool_choice`,
  `max_tokens`). Replay it through the real client with its clock pinned
  to the case's `now`, or the datetime line the client appends
  contradicts `Today's date: 2026-10-01`.
- Captures follow the engine's code: re-run `build_requests` after any
  prompt change.
- Every address is `*.example`; every phone number is `+39 02 0000 0xxx`
  or `+44 1632 960 xxx`. The tests enforce it.
- Labels are awaiting the independent label review of S4a.
