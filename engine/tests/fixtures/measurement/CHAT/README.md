# CHAT — measurement cases

Scope: the synthetic scenarios, labels and capture harness that measure the
CHAT role (milestone 10, decision D7: "about eight scripted tool-use
scenarios"). Everything here is invented: people, companies, `.example`
domains, `+39 0x 0000 0xxx` and `+44 20 7946 0xxx` numbers, prices.

## What the role decides

CHAT is the desktop chat agent (`zylch/assistant/core.py`, `ZylchAIAgent`):
one system prompt (`assistant/prompts.py` plus the user's personal data and
learned rules), the thirty tools of `ToolFactory.create_all_tools`, and a tool
loop. At each request it decides whether to call a tool — which one, with which
arguments — or to answer, and in which language. The cases test the decisions
its prompt makes explicit: memory first for a person (`search_local_memory`),
`get_tasks` for anything about to-dos, the send tools called directly (their
approval card is the confirmation), `read_email` when a preview is cut, a web
search only when asked, a behaviour rule saved as `behavioral_rule` after a
search, a reply drafted in the thread (`in_reply_to`) and never sent when the
user said "save", and the draft the user approved sent by its id.

## Files

- `cases.json` — twelve cases over ten scenarios: two scenarios are captured
  at both of their decision points (chat-08/09, chat-10/11), the second after
  a replayed tool round, and chat-04 too starts after a replayed search.
- `capture.py` — `build_requests(cases)` returns, per case, the request at
  its decision point as the agent passed it to `create_message`;
  `run_case(case, client)` runs the whole turn with any client (see
  "Continuing a turn").

## How a case drives the builder

Builder: `zylch.assistant.core.ZylchAIAgent.process_message`, built as
`ChatService._initialize_agent` builds it, in a throwaway profile
(`tests/measurement/conversation_capture.py: disposable_profile`).

| `input` field | Becomes |
|---|---|
| `profile` | The persona's environment (`EMAIL_ADDRESS`, `USER_FULL_NAME`, `USER_COMPANY`, `USER_PHONE`), read into the USER CONTEXT block of the system prompt. |
| `channels` (optional) | Which channels the live channel block marks ready; all ready by default. |
| `history` (optional) | Earlier turns, restored with `set_history` as `ChatService` does. |
| `user_message` | The new user turn. |
| `replay` (optional) | Tool calls the model already made in this turn. The harness answers them, the agent runs them against the scripted tools, and the request captured is the next one. |
| `tool_results` | Each tool's scripted answer, a `ToolResult` as a dict (`status`, `data`, `message`); the agent formats it exactly as a real one. A tool the case does not script answers "No results.". |

The agent's clock reads `CAPTURE_NOW` (Monday 5 October 2026, 09:30), so the
date/time line of the turn is the same in every capture; no label depends on
the date (the dates the cases mention are facts to report, not deadlines to
compare with today). A captured request is the call site's arguments
(`system`, `messages`, `tools`, `max_tokens`): the real client adds its own
datetime line, admission and transport when a measurement replays it.

## Label schema and scoring

```json
"label": {
  "first_call": null | {"any_of": [{"name": "<tool>", "args": {"<argument>": <matcher>}}]},
  "never_call": ["<tool>", ...],
  "answer": null | {"language": "it" | "en", "contains": [["<alternative>", ...], ...]}
}
```

- **`first_call`** is scored on the model's response to the captured request.
  `null`: the response must call no tool. Otherwise at least one `tool_use`
  block must match one spec of `any_of`: the same tool name, and every listed
  argument present and satisfying its matcher —
  `{"contains": [[alternatives], ...]}` (every group matched by one
  alternative, a case-insensitive substring of the argument's text),
  `{"equals": "x"}` (case-insensitive, trimmed) or `{"digits_contain": "0200000187"}`
  (the argument's digits, everything else removed, contain these digits).
  Arguments the spec does not list are not scored.
- **`never_call`** fails the case if any response of the turn calls one of
  these tools.
- **`answer`** is scored on the turn's final text: an empty answer fails;
  `language` is the language of the answer text; `contains` works as above.
  For a case whose `first_call` is `null` the final text is the response to
  the captured request; otherwise it comes after the turn is continued.
  `null` means nothing to score (`get_tasks` hands its own list to the user).
- **Critical.** In a case marked `critical`, a failed `first_call`,
  `never_call` or `contains` is a critical failure (a wrong or duplicate
  email, a send the user did not ask for, a rule written to the wrong memory).
  The language check is a mechanical bar, never critical.

## Continuing a turn

A measurement that sends only the captured request can score `first_call`,
`never_call`, and the `answer` of the cases whose `first_call` is `null`. To
score the other answers, run `capture.run_case(case, client)` with the arm's
client: replayed rounds are answered by the script, every tool answers from
`tool_results`, approval-gated tools are approved, and the result carries the
final answer and the tool calls of every response the model gave.

## Distribution

| Expected first call | Cases |
|---|---|
| `search_local_memory` | chat-01, chat-08 |
| a search (`search_emails`, `search_local_emails` or `search_local_memory`) | chat-10 |
| `get_tasks` | chat-02 |
| `send_whatsapp_message` | chat-03 |
| `read_email` (after a replayed search) | chat-04 |
| no tool, a text answer | chat-05 |
| `send_sms` | chat-06 |
| `web_search` | chat-07 |
| `create_memory` as `behavioral_rule` (after a replayed search) | chat-09 |
| `create_draft` threaded (after a replayed search) | chat-11 |
| `send_draft` of the draft in history | chat-12 |

Six Italian, six English; four critical (chat-09 to chat-12); three with a
replayed round (chat-04, chat-09, chat-11) and one continuing an earlier turn
from `history` (chat-12).

## Known conflict in the prompt

The chat system prompt says, in its drafting section, "LANGUAGE: Always
respond in English. Zylch is designed for the US market." The labels follow
the measurement's bar (D7: an answer "in the source's language"), so an
Italian request expects an Italian answer. A model that obeys the English rule
fails the language bar of the Italian cases until the prompt is aligned.
