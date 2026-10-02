# TASK_SOLVE — measurement cases

Scope: the synthetic scenarios, labels and capture harness that measure the
TASK_SOLVE role (milestone 10, decision D7: "about eight scripted tool-use
scenarios"). Everything here is invented: people, companies, `.example`
domains, `+39 0x 0000 0xxx` and `+44 20 7946 0xxx` numbers, prices, invoices.

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
- `capture.py` — `build_requests(cases)` returns, per case, the request at
  its decision point as the executor passed it to `create_message_sync`;
  `run_case(case, client)` runs the whole solve with any client.

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
`tools`, `max_tokens`): the real client adds its datetime line, admission and
transport when a measurement replays it. Pending appointments and deliveries
are named by weekday, not by calendar date, so a replay on a later day reads
the case the same way. The follow-up reanalysis a mutating solve triggers is
another role (REANALYZE) and never runs here.

## Label schema and scoring

```json
"label": {
  "first_call": null | {"any_of": [{"name": "<tool>", "args": {"<argument>": <matcher>}}]},
  "never_call": ["<tool>", ...],
  "answer": {"language": "it" | "en", "contains": [["<alternative>", ...], ...]}
}
```

- **`first_call`** is scored on the model's response to the captured request.
  `null`: the response must call no tool. Otherwise at least one `tool_use`
  block must match one spec of `any_of`: the same tool name, and every listed
  argument present and satisfying its matcher — `{"contains": [[...], ...]}`
  (every group matched by one alternative, a case-insensitive substring),
  `{"equals": "x"}` (case-insensitive, trimmed) or
  `{"digits_contain": "2079460344"}` (the argument's digits contain these).
  Arguments the spec does not list are not scored.
- **`never_call`** fails the case if any response of the turn calls one of
  these tools.
- **`answer`** is scored on the turn's final text (non-empty; `language` is the
  language of the text; `contains` as above). For task_solve-05, whose
  `first_call` is `null`, that is the response to the captured request; for
  the others it comes after the turn is continued.
- **Critical.** In a case marked `critical`, a failed `first_call`,
  `never_call` or `contains` is a critical failure: a quote at a wrong price
  or from the wrong category, a wrong invoice number sent to a customer, a
  commitment the user reserved to herself. The language check is a mechanical
  bar, never critical.

## Continuing a turn

Sending only the captured request scores `first_call`, `never_call` and the
answer of task_solve-05. For the other answers run
`capture.run_case(case, client)` with the arm's client: replayed rounds are
answered by the script, every tool answers from `tool_results`, approval
cards are approved, and the result carries the RPC's result, the final answer
and the tool calls of every response the model gave.

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
| `web_search` | task_solve-10 |
| `send_sms` | task_solve-11 |

Six Italian, five English; five critical (task_solve-02, -03, -04, -05,
-08).
