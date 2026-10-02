# DEDUP — measurement cases

Scope: the synthetic cases, labels and capture harness of the `DEDUP`
role for milestone 10 (brief D7, plan S4a). The measurement (S4b/S4c)
replays each captured request on several models and scores every answer
against its label; nothing in this directory calls a model or needs a key.

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
| `cases.json` | 20 cases, `dedup-01`…`-10` at `dedup.f8`, `dedup-11`…`-20` at `dedup.f9` |
| `capture.py` | `build_requests(cases)` → `[{"case_id", "call_site", "request"}]` |

## A case

`id`, `lang`, `call_site`, `input`, `label`, `critical`, `why` (what the
case tests and why the label is right).

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

`lang` is the language the tasks are written in.

## Label and scoring

`dedup.f8` — the answer is the input of `dedup_decision`:

- `is_duplicate_group`, compared exactly;
- `keeper_id`, compared exactly, labelled only when the group is a
  duplicate. In every such case the keeper satisfies all three rules of
  the prompt at once (most informative, highest urgency, most recent).

`dedup.f9` — the answer is the input of `topic_dedup_decision`, labelled
as `{"clusters": [{"keeper_id", "duplicate_ids"}]}` (an empty list when
nothing merges). Read every answered cluster as the group
`{keeper_id} ∪ duplicate_ids`, ignoring a cluster whose only member is its
keeper; an id in two groups fails the case. The set of groups must equal
the label's, and each group's keeper must equal the labelled keeper (the
clearly most informative task). Score the model's answer itself, before
the engine's safety filter (`_validate_decision` drops cross-party
pairs): the filter is a backstop, not the role's job.

A case passes when everything labelled matches.

`critical: true` marks the cases where every wrong answer causes real
harm, so a failed critical case is a critical failure:

- the five `dedup.f8` cases labelled distinct — the same contact with two
  different jobs (or, `-03`, two buildings of one administrator):
  answering duplicate closes a real task;
- four `dedup.f9` cases labelled with no cluster — different customers
  with the same kind of request (`-12`, `-16`, `-17`) or one client with
  several distinct jobs (`-14`): any cluster closes someone's task.

Not critical: the duplicate cases (a missed merge leaves clutter), and
`dedup-18`, where two people of the same company write about the same
meeting — merging them breaks the prompt's party rule but loses little.

Distribution: `dedup.f8` 5 duplicate / 5 distinct; `dedup.f9` 5 with one
cluster / 5 with none; `it` 10, `en` 10; 9 critical.

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

- Usage: load `capture.py` by path (it loads `tests/measurement/task_roles_env.py`
  beside it, so only `zylch` must be importable) and call
  `build_requests(cases)` with the `cases` list, from synchronous code. Each
  case gets its own profile and database; the environment and the storage
  singletons are restored afterwards, so hold no open engine across the call.
  `tests/measurement/test_capture_task_roles.py` runs it on every case.
- The captured request is what the sweep passes to `create_message`
  (`system`, `messages`, `tools`, `tool_choice`, `max_tokens`); replay it
  through the real client with its clock pinned to the case's `now`.
- The order of the tasks in the prompts is the engine's (open tasks by
  urgency, then most recently analysed), so a duplicate group's keeper is
  often listed first, as in production.
- Captures follow the engine's code: re-run `build_requests` after any
  prompt change.
- Every address is `*.example` except the product's call-notification
  relay in the phone tasks' `sources`; phone numbers are
  `+390200000xxx` (and WhatsApp ids built on them) or `+44 1632 960 xxx`.
  The tests enforce it.
- Labels are awaiting the independent label review of S4a.
