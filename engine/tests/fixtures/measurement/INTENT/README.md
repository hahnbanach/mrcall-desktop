# INTENT — measurement cases

Scope: the synthetic case set and capture harness for the `INTENT` role
(milestone 10, brief D7). Inputs and labels only; the measurement replays the
captured requests on each arm.

## What the role decides

`IntentRouter.classify_intent` (`zylch/router/intent_classifier.py`) routes a
user's chat message to the skill that should handle it and answers in JSON
text: `primary_skill`, `context_skills`, `params`, `confidence`. The prompt
embeds the registry's `list_skills()`, so the classes are whatever the
registry lists. The engine has no registry and no caller of the router (the
module's docstring calls it dead, kept for a future skill router); the case
file therefore defines one at its top level, `skills`: six skills with one-line
descriptions written so that each message has one right answer —
`email_triage`, `draft_composer`, `task_manager`, `calendar`,
`contact_lookup`, `memory_notes`.

The role is measured for completeness: it is in the roster, and a role left
unmeasured blocks the table's publication (brief D7). Nothing reads its answer
today, so no case is critical (below).

## Cases

20 messages, 11 Italian and 9 English: 4 triage, 4 drafting, and 3 each for
tasks, calendar, contact lookup and memory. Near-duplicate pairs differ only in
intent: what Ferretti/Laura wrote versus replying to them, "Ricordami di"
(a to-do) versus "Ricordati che" (a fact to keep), looking up a phone number
versus saving a new one.

## Label and scoring

Label: `{"primary_skill": "<one of the registry's names>"}`. Only the primary
skill is labelled; `context_skills`, `params` and `confidence` depend on taste
and are not scored.

A model's answer falls in one class: parse its text as the router does (strip
a ```` ```json ```` fence, `json.loads`) and take `primary_skill` — the class
is that name — or `invalid` when the text does not parse or has no
`primary_skill`. The answer is correct when the name equals the label. Score
the model's raw answer, never the router's result: on any error the router
returns `email_triage`, which would count a broken answer as right on the
triage cases.

**Critical answers.** `critical_on` lists the wrong answer classes that are
critical failures for the case; `[]` means none is, and `critical` is derived
(`true` exactly when `critical_on` is not empty). Here every case has
`critical_on: []`: the router has no caller, so no wrong answer reaches anyone.

**Language.** `expect_lang` is the language the role's prompt requires for the
free text the measurement scores; no language bar applies when it is `null`.
Here it is `null` on every case: the answer is JSON holding a skill name, with
no free text to score.

## Input to builder

`input.user_input` is the message (`conversation_history` is accepted by the
method but never reaches its prompt, so cases do not carry one). `capture.py`
builds an `IntentRouter` over a registry whose `list_skills()` returns the
file's `skills` and runs `classify_intent` (the `builder`).

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments `classify_intent` passed, as sent. Given the case list rather
than the document, the harness reads `skills` from this directory's
`cases.json`. It needs `engine/` on `sys.path`; no network, no key.
`tests/measurement/test_capture.py` runs it on every case.

## Placeholders in the captured request

The replay rebuilds each request per arm with the M10 request shape; it takes
`messages` and `max_tokens` from the capture. Not replayed as captured:

- `model: "measurement/capture"` — the call site passes the client's model,
  which in the capture is the placeholder saved as `MODEL_INTENT` (or the arm
  named by `build_requests(..., model=...)`); each arm supplies its own.
- `temperature: 0` — the M10 shape sends no sampling fields.
