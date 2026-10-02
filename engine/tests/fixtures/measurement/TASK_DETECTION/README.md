# TASK_DETECTION — measurement cases

Scope: the synthetic cases, labels and capture harness of the
`TASK_DETECTION` role for milestone 10 (brief D7, plan S4a). The
measurement (S4b/S4c) replays each captured request on several models and
scores every answer against its label; nothing in this directory calls a
model or needs a key.

## What the role decides

For one email the engine has not analysed yet (the newest of its thread),
the detector decides through the `task_decision` tool whether the profile
owner has something to do, and what happens to the task list: `create` a
task, `update` or `close` one of the open tasks it is shown
(`target_task_id`), or `none`. Call site `task.detect` in
`zylch/workers/task_creation.py` (`TaskWorker._analyze_event`, the method
that builds and sends the request), model key `MODEL_TASK_DETECTION`.

## Files

| File | What |
|------|------|
| `cases.json` | 20 cases: `{"schema": 1, "role", "builder", "cases": [...]}` |
| `capture.py` | `build_requests(cases)` → `[{"case_id", "call_site", "request"}]` |
| `profiles.json`, `trained_prompt.it.txt`, `trained_prompt.en.txt` | the two synthetic profile owners and the task prompt the trainer would have stored for each; `REANALYZE` uses them too, because both roles send that prompt |

## A case

`id`, `lang`, `call_site` (`task.detect`), `input`, `label`, `critical`,
`why` (what the case tests and why the label is right).

`input`:

- `profile` — `it`: Giulia Ferraris, Serramenti Ferraris s.r.l., windows
  and doors near Bergamo; `en`: Tom Hale, Harbour Lane Design Ltd, a
  branding and web studio in Bristol.
- `now` — when the case happens, `2026-10-01T09:00:00Z` (a Thursday). The
  harness pins the clock the builder reads to it.
- `emails` — the mailbox: `id`, `thread_id`, `from`, `from_name`, `to`,
  `subject`, `date`, `body`, `auto_reply` when set. Exactly one email is
  `pending` (not yet task-processed): the one the detector analyses. The
  others were processed when they arrived; they still appear in the thread
  history, which renders every email of the thread.
- `open_tasks` — open tasks as stored (`id`, contact, `suggested_action`,
  `reason`, `urgency`, `created_at`, `sources` with the source email and
  `thread_id`). The engine shows the detector those of the same thread or
  the same contact.
- `memory` — the sender's memory blob (`contact`, `blob_id`, `content` in
  the `#IDENTIFIERS / #ABOUT / #HISTORY` envelope), what the hybrid search
  returns for the sender's address.

`lang` is the profile owner's language: the language the answer's free
text (title, suggested action, reason) is expected in, as the trained
prompt asks. `task_detection-17` is an English email to the Italian
owner, so its `lang` is `it`.

## Label and scoring

The answer is the input of the model's `task_decision` call.

| Field | Compared | Label |
|-------|----------|-------|
| `task_action` | exactly | always |
| `action_required` | exactly | always: `true` for `create` and `update` (the owner still has work), `false` for `close` and `none` |
| `target_task_id` | exactly | only for `update` and `close` |

A case passes when every labelled field matches. Urgency, title,
suggested action, reason and the relay contact fields are not scored:
they are matters of taste or belong to the mechanical bars (the tool
called, a valid non-empty answer in `lang`).

`critical: true` marks the cases where every wrong answer causes real
harm, so a failed critical case is a critical failure:

- the `create` cases — an explicit request (a new lead, an angry client, a
  colleague's approval due today, a callback, a customs form) with no task
  tracking it: any other action, or `action_required: false`, leaves no
  task; in `-18` an `update`/`close` would also corrupt the client's
  unrelated open task;
- the `update` cases — the new email changes facts the open task states
  (quantities, size, dates, scope, budget): keeping it leaves a wrong
  task, `create` duplicates it, `close` drops pending work, and in `-20`
  the other open task of the same client must not be touched.

`close` and `none` cases are not critical: their errors leave clutter.

Distribution: create 7, none 6, update 4, close 3; `it` 10, `en` 10;
11 critical.

## How the harness drives the builder

For each case `capture.py`:

1. boots a disposable profile and database through the real `init_db`
   (`tests/measurement/task_roles_env.py`), with the profile owner's
   identity (`EMAIL_ADDRESS`, `USER_FULL_NAME`, `USER_COMPANY`) in the
   environment, so the engine appends the owner's personal-data section;
2. pins the clock of `task_creation`, `thread_presenter` and
   `storage.storage` to `now`;
3. seeds the trained prompt (agent type `task_email`), the emails and the
   open tasks;
4. runs `TaskWorker(...).get_tasks(refresh=True)`, the pipeline's own
   entry: its email branch builds the thread history (quoted text
   stripped), the existing-task context and the memory context and calls
   `_analyze_event`, which builds the request;
5. records it with a capturing client (no network) and checks it is the
   only request, from `task.detect`, routed through
   `MODEL_TASK_DETECTION`; the worker then takes its "no decision" path.

Replaced, because they need the embedding model: the embedding engine and
the hybrid search, which answers with the case's `memory` entry for the
sender's address. Everything else is the engine's code.

## Notes for the measurement

- Usage: load `capture.py` by path (it loads `tests/measurement/task_roles_env.py`
  beside it, so only `zylch` must be importable) and call
  `build_requests(cases)` with the `cases` list, from synchronous code. Each
  case gets its own profile and database; the environment and the storage
  singletons are restored afterwards, so hold no open engine across the call.
  `tests/measurement/test_capture_task_roles.py` runs it on every case.
- The captured request is what the worker passes to `create_message`
  (`system`, `messages`, `tools`, `tool_choice`, `max_tokens`). The client
  adds the datetime line and applies the request shape when it sends it:
  replay through the real client with its clock pinned to the case's
  `now`, or the datetime line contradicts `Date: 2026-10-01`.
- Captures follow the engine's code: re-run `build_requests` after any
  prompt change. The same case renders byte-identically on any day.
- Every address is `*.example` except the product's own call-notification
  relay (`notification@transactional.mrcall.ai`, case `-13`); every phone
  number is `+39 02 0000 0xxx` or `+44 1632 960 xxx`. The tests enforce it.
- Labels are awaiting the independent label review of S4a.
