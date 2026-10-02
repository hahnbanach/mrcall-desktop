# CHAT — measurement cases

Scope: the synthetic scenarios, labels and capture harness that measure the
CHAT role (milestone 10, decision D7: "about eight scripted tool-use
scenarios"), and the label rules adopted after their independent review.
Everything here is invented: people, companies, `.example` domains,
`+39 0x 0000 0xxx` and `+44 20 7946 0xxx` numbers, prices.

## What the role decides

CHAT is the desktop chat agent (`zylch/assistant/core.py`, `ZylchAIAgent`):
one system prompt (`assistant/prompts.py` plus the user's personal data and
learned rules), the thirty tools of `ToolFactory.create_all_tools`, and a tool
loop. At each request it decides whether to call a tool — which one, with which
arguments — or to answer. The cases test the decisions its prompt makes
explicit: memory first for a person (`search_local_memory`), `get_tasks` for
anything about to-dos, the send tools called directly (their approval card is
the confirmation), `read_email` when a preview is cut, a web search only when
asked, a behaviour rule saved as a rule after a search, a reply drafted in the
thread and never sent when the user said "save", the draft the user approved
sent by its id, a channel that is not connected named instead of used, and a
question when two contacts fit ("When uncertain, ask for clarification").

## Files

- `cases.json` — fourteen cases over twelve scenarios: two scenarios are
  captured at both of their decision points (chat-08/09, chat-10/11), the
  second after a replayed tool round; chat-04 and chat-14 too start after a
  replayed search. `write_tools` (top level) lists the chat's write and send
  tools, for the critical rule.
- `capture.py` — `build_requests(cases)` returns, per case,
  `{"case_id", "request", "capture_now"}`: the request at its decision point
  as the agent passed it to `create_message`, and the moment it was captured
  at; `run_case(case, client)` runs the whole turn with any client (see
  "Continuing a turn").

## How a case drives the builder

Builder: `zylch.assistant.core.ZylchAIAgent.process_message`, built as
`ChatService._initialize_agent` builds it, in a throwaway profile
(`tests/measurement/conversation_capture.py: disposable_profile`).

| `input` field | Becomes |
|---|---|
| `profile` | The persona's environment (`EMAIL_ADDRESS`, `USER_FULL_NAME`, `USER_COMPANY`, `USER_PHONE`), read into the USER CONTEXT block of the system prompt. |
| `channels` (optional) | Which channels the live channel block marks ready; all ready by default. The WhatsApp probe is pinned to the same answer, so an install without the WhatsApp library cannot turn "ready" into "NOT connected". |
| `history` (optional) | Earlier turns, restored with `set_history` as `ChatService` does. |
| `user_message` | The new user turn. |
| `replay` (optional) | Tool calls the model already made in this turn. The harness answers them, the agent runs them against the scripted tools, and the request captured is the next one. |
| `tool_results` | Each tool's scripted answer, a `ToolResult` as a dict (`status`, `data`, `message`, `error`); the agent formats it exactly as a real one. A tool the case does not script answers "No results.". |

The profile's clock reads `CAPTURE_NOW` (Monday 5 October 2026, 09:30): the
turn's date line, and the datetime line a real client appends to the system
prompt. A captured request is the call site's arguments (`system`,
`messages`, `tools`, `max_tokens`); `run_clock`, with which the loop fixes
that datetime line for all its requests, is the client's own and is not
recorded (`CLIENT_ONLY`). A replay passes its own run clock set to the
entry's `capture_now` (label review G5), so the two lines agree on any later
day; the client adds admission and transport.

## A case

`id`, `lang` (the user's language), `expect_lang`, `input`, `label`,
`critical`, `critical_on`, `why` (what the case tests and why the label is
right).

## Label schema and scoring

```json
"label": {
  "first_call": null | {"any_of": [{"name": "<tool>", "args": {"<argument>": <matcher>}}]},
  "never_call": ["<tool>", ...],
  "answer": null | {} | {"contains": [["<alternative>", ...], ...]}
}
```

A model's turn is scored as `run_case` returns it (`turn`): `first`, the tool
calls of its response to the captured request; `later`, the calls of every
response after it; `text`, all the text it wrote in the turn (review G4).

- **`first_call`** is scored on `first`. `null`: no tool call. Otherwise at
  least one call must match one spec of `any_of`: the same tool name, and
  every listed argument present and satisfying its matcher —
  `{"contains": [[alternatives], ...]}` (every group matched by one
  alternative, a case-insensitive substring of the argument's text),
  `{"equals": "x"}` (case-insensitive, trimmed) or `{"digits_contain": "0200000187"}`
  (the argument's digits, everything else removed, contain these digits).
  Arguments the spec does not list are not scored.
- **`never_call`** fails the case if any response of the turn calls one of
  these tools.
- **`answer`** is scored on `text`: `{}` asks only for a non-empty text;
  `contains` works as above; `null` means nothing to score (`get_tasks` hands
  its own list to the user). For a case whose `first_call` is `null` the text
  is the response to the captured request; otherwise it comes after the turn
  is continued.
- **Language** is not scored: `expect_lang` is `null` on every case (below).
- The measurement normalises the text before matching — Markdown emphasis
  stripped, non-breaking and thin spaces made plain (review G3) — and the
  alternatives are written for that text.

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
  `task_executor.APPROVAL_TOOLS`, among the chat's) that no `first_call` spec
  names;
- `wrong_arguments` — it calls a tool a spec names with arguments no spec for
  that tool accepts, also when a matching call stands next to it;
- `contains` — the answer misses a fact the label requires.

No call, a read-only call the label does not forbid, or a question asked
instead is an ordinary failure.

| Case | `critical_on` | The harm |
|---|---|---|
| chat-09 | `never_call`, `unmatched_write`, `wrong_arguments` | a rule overwritten, or saved without the 10% or the one-year condition |
| chat-11 | `never_call`, `unmatched_write`, `wrong_arguments` | the reply sent, or drafted to the wrong address or thread or without the date |
| chat-12 | `never_call`, `unmatched_write`, `wrong_arguments` | another draft sent, or a second quote written |
| chat-13 | `never_call` | a text or a call to Tom nobody asked for (a WhatsApp attempt fails harmlessly) |
| chat-14 | `never_call`, `unmatched_write` | a message sent to a guessed Marco |

chat-10 is not critical: which search to run, or composing the reply at once
with `compose_email` (which saves an unsent draft), is not a decision that
can harm; chat-11 keeps the no-send check.

## Language

The chat prompt contradicts itself: `assistant/prompts.py:155` says
"LANGUAGE: Always respond in English. Zylch is designed for the US market.",
and `:182` says `Then ask "Shall I send it?" (or in Italian if that's the
user's language)`. The prompt is not changed in this milestone and the conflict is recorded for
the CTO; until it is aligned, CHAT's language is unscored (`expect_lang`
`null`), and `lang` only says which language the user writes in.

## Continuing a turn

A measurement that sends only the captured request can score `first_call`,
`never_call`, and the `answer` of the cases whose `first_call` is `null`. To
score the rest, run `capture.run_case(case, client)` with the arm's client:
replayed rounds are answered by the script, every tool answers from
`tool_results`, approval-gated tools are approved, and the result carries the
final answer (`answer`), the tool calls of every response (`calls`), the
replayed rounds (`replayed`) and the turn to score (`turn`).

## Distribution

| Expected first call | Cases |
|---|---|
| `search_local_memory` | chat-01, chat-08 |
| a search (`search_emails`, `search_local_emails`, `search_local_memory`, `search_provider_emails`) or `compose_email` with the date | chat-10 |
| `get_tasks` | chat-02 |
| `send_whatsapp_message` | chat-03 |
| `read_email` (after a replayed search) | chat-04 |
| no tool, a text answer | chat-05 |
| `send_sms` | chat-06 |
| `web_search` | chat-07 |
| `create_memory` as a rule — `behavioral_rule`, or the `template`/`prefs` namespace (after a replayed search) | chat-09 |
| `create_draft` threaded, or `compose_email` (after a replayed search) | chat-11 |
| `send_draft` of the draft in history | chat-12 |
| no tool: WhatsApp is not connected, say how to pair it | chat-13 |
| no tool: two contacts are called Marco, ask which (after a replayed search) | chat-14 |

Seven Italian, seven English; five critical (chat-09, chat-11 to chat-14);
four with a replayed round (chat-04, chat-09, chat-11, chat-14), one
continuing an earlier turn from `history` (chat-12), one with a channel not
ready (chat-13).
