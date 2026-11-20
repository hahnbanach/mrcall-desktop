# TASK_DETECTION — measurement cases

Scope: the synthetic cases, labels, scoring rules and capture harness of
the `TASK_DETECTION` role for milestone 10 (brief D7, plan S4a). The
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
| `cases.json` | 22 cases: `{"schema": 1, "role", "builder", "cases": [...]}` |
| `capture.py` | `build_requests(cases)` → `[{"case_id", "call_site", "request"}]` |
| `score.py` | `score_answer(case, answer)` → `{"passed", "critical", "outcome"}`, the reference implementation of the rules below |
| `profiles.json`, `trained_prompt.it.txt`, `trained_prompt.en.txt` | the two synthetic profile owners and the task prompt the trainer would have stored for each; `REANALYZE` uses them too, because both roles send that prompt |

## A case

`id`, `lang`, `expect_lang`, `call_site` (`task.detect`), `input`,
`label`, `critical_on`, `critical`, `why` (what the case tests and why the
label is right).

`input`:

- `profile` — `it`: Giulia Ferraris, Serramenti Esempio s.r.l., windows
  and doors near Bergamo; `en`: Tom Hale, Example Design Ltd, a branding
  and web studio in Bristol.
- `now` — when the case happens, `2026-10-01T09:00:00Z` (a Thursday). The
  harness pins the clock the builder reads to it.
- `emails` — the mailbox: `id`, `thread_id`, `from`, `from_name`, `to`,
  `subject`, `date`, `body`, `auto_reply` when set. Exactly one email is
  `pending` (not yet task-processed): the one the detector analyses. The
  others were processed when they arrived; they still appear in the thread
  history, which renders every email of the thread.
- `open_tasks` — open tasks as stored (`id`, contact, `suggested_action`,
  `reason`, `urgency`, `created_at`, `sources` with the source email and
  `thread_id`). In every case the detector is shown all of them (the
  tests check their ids reach the request).
- `memory` — the sender's memory blob (`contact`, `blob_id`, `content` in
  the `#IDENTIFIERS / #ABOUT / #HISTORY` envelope), what the hybrid search
  returns for the sender's address.

`lang` is the language of the pending email. `expect_lang` is the language
the role's prompt requires for the free text of the answer (`title`,
`suggested_action`, `reason`: `score.FREE_TEXT`): the owner's language,
because the trained prompt says "Write suggested actions, titles and
reasons in Italian/English" and the tool asks for the title "in the user's
language". They differ in `task_detection-17`, an English email to the
Italian owner: `lang` `en`, `expect_lang` `it`. The tests check that
`expect_lang` is the language the captured prompt names.

## Label and scoring

The answer is the input of the model's `task_decision` call. `score.py`
reads it as the engine would and reduces it to one outcome:

| Outcome | When |
|---------|------|
| `invalid` | `_analyze_event` drops it (a required field missing, a wrong type or enum value): the email stays pending and is retried |
| `create` | `create` with `action_required: true` and a suggested action of five characters or more |
| `none` | `none`; or `create` with `action_required: false` (the engine creates nothing); or `create`/`update` with a suggested action under five characters (the email branch drops it); or `update`/`close` with no target the engine can resolve |
| `update`, `close` | applied to a target: the given `target_task_id` when it is an open task, else the only open task when there is exactly one (Fix B) |
| `other_target` | the labelled `update`/`close`, applied to another open task |

The label: `task_action`; `target_task_id` when an `update` or `close` is
labelled or accepted; `action_required: true` on `create` labels only —
the engine reads it only there, so it is scored only there; `also_accept`
lists the other actions that also pass (`-21`: `update`; `-22`: `none`). An
answer passes when its outcome is the labelled or an accepted action, with
the labelled target for `update` and `close`. Urgency, title, suggested
action, reason and the relay contact fields are not scored: they are
matters of taste or belong to the mechanical bars (the tool called, a
valid answer in `expect_lang`).

`critical_on` lists the outcomes that are a critical failure on that case
(`critical` is `true` exactly when the list is not empty, never set by
hand). A wrong outcome not in the list is an ordinary miss:

- `create` cases — an explicit request (a new lead, an angry client, a
  colleague's approval due today, a callback, a customs form) with no task
  tracking it: `none` loses it; in `-18`, where the client's only open task
  is unrelated, `update` and `close` corrupt that task too;
- `update` cases — the new email changes what the open task states
  (quantities, size, dates, scope, budget): `none` leaves it stale and
  `close` drops pending work; in `-20`, `other_target` rewrites or closes
  the client's other task. `create` is only a miss: on the task's own
  thread the engine turns it into this same update
  (`_pick_force_update_target`);
- `-21` (a courtesy thank-you) and `-22` (a chaser) — a quote is still
  owed: `close` drops it;
- `close` and `none` cases have an empty list: their errors leave clutter.

Distribution: create 7, none 7 (one also accepting `update`), update 5
(one also accepting `none`), close 3; `lang` it 11 / en 11, `expect_lang`
it 12 / en 10; 13 cases with a non-empty `critical_on`.

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

- Usage: load `capture.py` and `score.py` by path (`capture.py` loads
  `tests/measurement/task_roles_env.py` beside it, so only `zylch` must be
  importable) and call `build_requests(cases)` with the `cases` list, from
  synchronous code. Each case gets its own profile and database; the
  environment and the storage singletons are restored afterwards, so hold
  no open engine across the call. `tests/measurement/test_capture_task_roles.py`
  and `test_scoring_task_roles.py` run them on every case.
- The captured request is what the worker passes to `create_message`
  (`system`, `messages`, `tools`, `tool_choice`, `max_tokens`). The client
  adds the datetime line and applies the request shape when it sends it:
  replay through the real client with its clock pinned to the case's
  `now`, or the datetime line contradicts `Date: 2026-10-01`.
- Captures follow the engine's code: re-run `build_requests` after any
  prompt change. The same case renders byte-identically on any day.
- Every business is an obvious invention ("… Esempio", "Example …");
  every address is `*.example` except the product's own call-notification
  relay (`notification@transactional.mrcall.ai`, case `-13`); every phone
  number is `+39 02 0000 0xxx` or `+44 1632 960 xxx`. The tests enforce
  the addresses and numbers.
- Labels: reviewed independently on 2026-10-02 (ACCEPT_WITH_FIXES); this
  revision applies the review — `critical_on` per case, `action_required`
  scored on `create` only, the two pending-work cases `-21` and `-22`,
  `expect_lang`, invented business names.
