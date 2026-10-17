# DEDUP — measurement cases

Scope: the synthetic cases, labels, scoring rules and capture harness of
the `DEDUP` role for milestone 10 (brief D7, plan S4a). The measurement
(S4b/S4c) replays each captured request on several models and scores
every answer against its label; nothing in this directory calls a model or
needs a key.

## What the role decides

Whether open tasks are duplicates of one real-world problem for one
party, and which task survives. The role has two call sites, both routed
through `MODEL_DEDUP`, and every case names its own in `call_site`:

| `call_site` | Builder (sends the request) | Tool | The question |
|-------------|-----------------------------|------|--------------|
| `dedup.f8` | `zylch.workers.task_dedup_sweep.run_dedup_sweep` | `dedup_decision` | one cluster the engine formed (shared contact, shared thread, or blob overlap between tasks of the same party): is it one problem, and which task is the keeper? |
| `dedup.f9` | `zylch.workers.task_topic_dedup.run_topic_dedup` | `topic_dedup_decision` | all open tasks (at least four): which groups are the same problem for the same party, and the keeper of each |

`cases.json` maps each call site to its builder in `builder`.

## Files

| File | What |
|------|------|
| `cases.json` | 21 cases, `dedup-01`…`-10` at `dedup.f8`, `dedup-11`…`-21` at `dedup.f9` |
| `capture.py` | `build_requests(cases)` → `[{"case_id", "call_site", "request"}]` |
| `score.py` | `score_answer(case, answer)` → `{"passed", "critical", "outcome"}`, the reference implementation of the rules below |

## A case

`id`, `lang`, `expect_lang`, `call_site`, `input`, `label`,
`critical_on`, `critical`, `why` (what the case tests and why the label is
right).

`input`:

- `now` — `2026-10-01T09:00:00Z`. The topic sweep puts today's date in its
  prompt; the harness hands its prompt builder this date instead.
- `open_tasks` — the open tasks as stored: `id`, `contact_email`,
  `contact_phone` (phone and WhatsApp tasks), `contact_name`, `title`,
  `urgency`, `suggested_action`, `reason`, `channel`, `created_at`,
  `analyzed_at`, `sources`. The prompts show the id, the contact (and for
  F9 the party key the engine derives: phone first, else the address),
  the channel, the urgency, the creation date, the action and the reason.
  A `dedup.f8` case holds exactly one cluster.

`lang` is the language the tasks are written in. `expect_lang` is `null`
on every case: the sweeps' prompts are in English and set no output
language, so no language bar applies to the free text (`reason`, `topic`,
`rationale`; `score.FREE_TEXT` is empty).

## Label and scoring

`dedup.f8` — the answer is the input of `dedup_decision`, read as
`run_dedup_sweep` reads it:

| Outcome | When |
|---------|------|
| `merge` | `is_duplicate_group` truthy and `keeper_id` in the cluster: the sweep closes the other tasks |
| `invalid_keeper` | truthy, but the keeper is not in the cluster: the sweep skips it |
| `distinct` | anything else: nothing is closed |
| `other_keeper` | a merge around another keeper than the labelled one |
| `invalid` | the input is not an object |

The label is `is_duplicate_group`, with `keeper_id` when the group is a
duplicate; in every such case the keeper satisfies all three rules of the
prompt at once (most informative, highest urgency, most recent). It passes
with `merge` around the labelled keeper, or `distinct` on a distinct
label.

`dedup.f9` — the answer is the input of `topic_dedup_decision`, labelled
as `{"clusters": [{"keeper_id", "duplicate_ids"}]}` (an empty list when
nothing merges). Two readings:

- what the engine would close: the answer passed through the sweep's own
  filter (`_validate_decision`: unknown or reused ids dropped, pairs of
  different or unknown parties refused). Closing a task outside its
  labelled group is `wrong_close`;
- what the model decided: each answered cluster read as the group
  `{keeper_id} ∪ duplicate_ids` (one-member clusters ignored; an id in two
  groups is `wrong_groups`). Groups different from the label's are
  `wrong_groups`; the right groups with another keeper are
  `other_keeper`; otherwise `match`, which passes. `invalid`: the input is
  not an object with a `clusters` list.

`critical_on` lists the outcomes that are a critical failure on that case
(`critical` is `true` exactly when the list is not empty, never set by
hand). A wrong outcome not in the list is an ordinary miss:

- the five `dedup.f8` cases labelled distinct — the same contact with two
  different jobs (or, `-03`, two buildings of one administrator): `merge`
  closes a real task;
- `dedup-14` and `dedup-21` — one party with several distinct jobs: the
  engine's filter lets a same-party pair through, so `wrong_close` closes
  real work. The tests check that `wrong_close` is listed exactly on the
  F9 cases where such a same-party pair outside the labelled groups
  exists;
- empty elsewhere: the duplicate cases (a missed merge or another keeper
  leaves clutter), and the cross-party traps `-12`, `-16`, `-17`, `-18`,
  where the engine refuses every cross-party pair before closing anything
  — a merge there is a scored miss, not a critical failure.

Distribution: `dedup.f8` 5 duplicate / 5 distinct; `dedup.f9` 5 with one
cluster / 6 with none; `lang` it 11 / en 10; 7 cases with a non-empty
`critical_on`.

## How the harness drives the builder

For each case `capture.py` boots a disposable profile and database through
the real `init_db` (`tests/measurement/task_roles_env.py`), seeds the open
tasks exactly as given (ids, dates, sources), and calls the case's sweep
with the owner id. The sweep reads the open tasks, clusters them (F8) or
renders all of them (F9), and builds the request; a capturing client
records it (no network) and the harness checks it is the only request,
from the case's call site, routed through `MODEL_DEDUP`. The sweep then
takes its "no tool_use" path and closes nothing. Nothing of the engine is
replaced; for F9 the prompt builder receives `now`'s date as today.

## Notes for the measurement

- Usage: load `capture.py` and `score.py` by path (`capture.py` loads
  `tests/measurement/task_roles_env.py` beside it, so only `zylch` must be
  importable) and call `build_requests(cases)` with the `cases` list, from
  synchronous code. Each case gets its own profile and database; the
  environment and the storage singletons are restored afterwards, so hold
  no open engine across the call. `tests/measurement/test_capture_task_roles.py`
  and `test_scoring_task_roles.py` run them on every case.
- The captured request is what the sweep passes to `create_message`
  (`system`, `messages`, `tools`, `tool_choice`, `max_tokens`); replay it
  through the real client with its clock pinned to the case's `now`.
- The order of the tasks in the prompts is the engine's (open tasks by
  urgency, then most recently analysed), so a duplicate group's keeper is
  often listed first, as in production.
- Captures follow the engine's code: re-run `build_requests` after any
  prompt change.
- Every business is an obvious invention ("… Esempio", "Example …");
  every address is `*.example` except the product's call-notification
  relay in the phone tasks' `sources`; phone numbers are `+390200000xxx`
  (and WhatsApp ids built on them) or `+44 1632 960 xxx`. The tests
  enforce the addresses and numbers.
- Labels: reviewed independently on 2026-10-02 (ACCEPT_WITH_FIXES); this
  revision applies the review — `critical_on` per case (`-12`, `-16`, `-17`
  no longer critical), the older tasks of `-01` and `-10` naming the same
  deliverable, the same-party case `-21`, `expect_lang` `null`, invented
  business names.
