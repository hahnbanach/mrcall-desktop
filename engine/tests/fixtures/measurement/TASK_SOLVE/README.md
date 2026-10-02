# TASK_SOLVE — measurement cases

Scope: the synthetic scenarios, labels and capture harness that measure the
TASK_SOLVE role (milestone 10, decision D7: "about eight scripted tool-use
scenarios"), and the label rules adopted after their independent review.
Everything here is invented: people, companies (Brentagrigia Costruzioni at
"via Inesistente 1" included), `.example` domains, `+39 0x 0000 0xxx` and
`+44 20 7946 0xxx` numbers, prices, invoices.

## What the role decides

TASK_SOLVE is the agent behind "Open" on a task (`tasks.solve`): the
`SOLVE_SYSTEM_PROMPT` with the user's personal data, learned OPERATING RULES
and language directive, a user turn holding the task context (the task, the
original email, the linked memory blobs, the user's typed instructions), the
twelve `SOLVE_TOOLS`, and the `TaskExecutor` loop. Its prompt fixes a
workflow: read the context first and search only for what is missing; when
the next action is sendable, call the send tool straight away with the full
payload (the approval card is the confirmation); load business facts with
`list_fact_categories` then `get_facts_by_category` before any quote, never
mixing categories; when only the user can decide, answer in prose with one
closing question; reply in the original message's language. The cases test
each of these decisions.

## Files

- `cases.json` — eleven cases over eight scenarios: the quote scenario is
  captured at its three decision points (task_solve-02/03/04), the invoice
  scenario at two (task_solve-07/08), the later ones after replayed rounds.
  `write_tools` (top level) lists the solve's write and send tools, for the
  critical rule.
- `capture.py` — `build_requests(cases)` returns, per case,
  `{"case_id", "request", "capture_now"}`: the request at its decision point
  as the executor passed it to `create_message_sync`, and the moment it was
  captured at; `run_case(case, client)` runs the whole solve with any client.

## How a case drives the builder

Builder: `zylch.rpc.methods.tasks_solve`, called as the desktop calls it, in a
throwaway profile (`tests/measurement/conversation_capture.py`). The harness
seeds what the RPC reads, under the owner the RPC uses:

| `input` field | Becomes |
|---|---|
| `profile` | The persona's environment, read into USER PERSONAL DATA and the user's name. `USER_LANGUAGE` is unset, so the language directive is "match the original message". |
| `email` (optional) | The synced email the task's `event_id` points at (the ORIGINAL EMAIL block). |
| `memory` | Company memory blobs, linked from the task (`sources.blobs`; the CONTACT MEMORY block). |
| `rules` (optional) | Learned rules in `template:<owner>`, the family the OPERATING RULES block is built from. |
| `task` | The task row (`contact_*`, `title`, `urgency`, `reason`, `suggested_action`; `event_type` and `event_id` for a WhatsApp task). |
| `instructions` (optional) | What the user typed in the solve box. |
| `replay` (optional) | Tool calls already made in this solve; the request captured is the next one. |
| `tool_results` | The string each solve tool returns (`execute_tool` answers from here). A tool whose answer depends on an argument is `{"by_arg": "category", "results": {...}, "default": ...}`. An unscripted tool answers "No results.". |

A captured request is the executor's arguments (`system`, `messages`,
`tools`, `max_tokens`). `run_clock`, with which the loop fixes the datetime
line the client appends for all its requests, is the client's own and is not
recorded (`CLIENT_ONLY`): a replay passes its own, set to the entry's
`capture_now` (label review G5), so "Thursday" in task_solve-01 and "this
Saturday" in task_solve-05 read against 5 October 2026 on any later day. The
client adds admission and transport. The follow-up reanalysis a mutating
solve triggers is another role (REANALYZE) and never runs here.

## A case

`id`, `lang` (the original message's language), `expect_lang`, `input`,
`label`, `critical`, `critical_on`, `why` (what the case tests and why the
label is right).

## Label schema and scoring

```json
"label": {
  "first_call": null | {"any_of": [{"name": "<tool>", "args": {"<argument>": <matcher>}}]},
  "never_call": ["<tool>", ...],
  "answer": {} | {"contains": [["<alternative>", ...], ...]}
}
```

A model's turn is scored as `run_case` returns it (`turn`): `first`, the tool
calls of its response to the captured request; `later`, the calls of every
response after it; `text`, all the text it wrote in the turn. The executor
shows every text block to the user, so a recap written next to a send counts
even when the last response is empty (label review G4).

- **`first_call`** is scored on `first`. `null`: no tool call. Otherwise at
  least one call must match one spec of `any_of`: the same tool name, and
  every listed argument present and satisfying its matcher —
  `{"contains": [[...], ...]}` (every group matched by one alternative, a
  case-insensitive substring), `{"equals": "x"}` (case-insensitive, trimmed)
  or `{"digits_contain": "2079460344"}` (the argument's digits contain these).
  Arguments the spec does not list are not scored.
- **`never_call`** fails the case if any response of the turn calls one of
  these tools.
- **`answer`** is scored on `text`: non-empty, and `contains` as above. For
  task_solve-05, whose `first_call` is `null`, that is the response to the
  captured request; for the others it comes after the turn is continued.
- **Language** — `expect_lang` is the case's `lang` on every case: the solve
  prompt fixes the rule ("Match the language of the original email … mixed or
  unclear, default to Italian"), so task_solve-06 (a WhatsApp question, no
  email) and task_solve-10 (an English bounce around an Italian reminder)
  expect Italian. The measurement skips the bar on a text too short to detect
  reliably, and normalises the text before matching — Markdown emphasis
  stripped, non-breaking and thin spaces made plain (review G3).

`tests/measurement/conversation_judge.py` is the reference reading of these
checks and of the critical rule; `test_labels_agent_and_smoke_roles.py` holds
it on the cases.

## What is critical

`critical_on` lists the kinds of failure that are critical in the case;
`critical` is derived (`true` exactly when the list is not empty). A failure
whose kind is not listed is an ordinary miss. The kinds:

- `never_call` — a tool the label forbids, in any response of the turn;
- `unmatched_write` — the response to the captured request calls a write or
  send tool (`write_tools`: the engine's approval-gated tools,
  `task_executor.APPROVAL_TOOLS`, among `SOLVE_TOOLS`) that no `first_call`
  spec names;
- `wrong_arguments` — it calls a tool a spec names with arguments no spec for
  that tool accepts, also when a matching call stands next to it (a parallel
  `get_facts_by_category("white-label")` beside the private-label one);
- `contains` — the answer misses a fact the label requires.

No call, a read-only call the label does not forbid (a search for past
quotes first), or a question asked instead is an ordinary failure.

| Case | `critical_on` | The harm |
|---|---|---|
| task_solve-02 | `unmatched_write`, `wrong_arguments` | a quote sent before the prices are loaded, or the wrong category's facts |
| task_solve-03 | `unmatched_write`, `wrong_arguments` | a quote sent, or white-label terms loaded (alone or beside private-label's) |
| task_solve-04 | `unmatched_write`, `wrong_arguments` | a quote without 6,80 € or the 90 € logo fee, or to someone else |
| task_solve-05 | `never_call`, `unmatched_write` | a message to Daniel committing Sarah to Saturday |
| task_solve-08 | `unmatched_write`, `wrong_arguments` | a reply with another invoice number or amount |

task_solve-05's closing question is a form check: missing, it is an ordinary
failure.

## Continuing a turn

Sending only the captured request scores `first_call`, `never_call` and the
answer of task_solve-05. For the other answers run
`capture.run_case(case, client)` with the arm's client: replayed rounds are
answered by the script, every tool answers from `tool_results`, approval
cards are approved, and the result carries the RPC's result (`result`), the
final answer (`answer`), the tool calls of every response (`calls`), the
replayed rounds (`replayed`) and the turn to score (`turn`).

## Distribution

| Expected first call | Cases |
|---|---|
| `send_email` | task_solve-01, task_solve-04 (after two replayed rounds), task_solve-08 (after a replayed search) |
| `list_fact_categories` (or the right category directly) | task_solve-02 |
| `get_facts_by_category` with `private-label` (after a replayed round) | task_solve-03 |
| no tool, a closing question to the user | task_solve-05 |
| `send_whatsapp` | task_solve-06 |
| `search_emails` | task_solve-07 |
| `update_memory` (or `search_memory` first) | task_solve-09 |
| `web_search` for the PEC address | task_solve-10 |
| `send_sms` | task_solve-11 |

Six Italian, five English; five critical (task_solve-02, -03, -04, -05,
-08).
