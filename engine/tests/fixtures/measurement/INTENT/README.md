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

- Parse the model's text as the router does (strip a ```` ```json ```` fence,
  `json.loads`), read `primary_skill`, compare it exactly with the label.
- Unparseable output or a missing `primary_skill` is a failure. Score the
  model's raw answer, never the router's result: on any error the router
  returns `email_triage`, which would count a broken answer as right on the
  triage cases.
- `critical` is true where the user orders an action (write a message, create
  or close a task, book or move a meeting, save a fact): a wrong skill there
  drops the instruction. A wrong skill on a lookup is an ordinary error.

## Input to builder

`input.user_input` is the message (`conversation_history` is accepted by the
method but never reaches its prompt, so cases do not carry one). `capture.py`
builds an `IntentRouter` over a registry whose `list_skills()` returns the
file's `skills` and runs `classify_intent` (the `builder`).

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments `classify_intent` passed, as sent; the request carries
`model=` because the call site passes it (the client's model: the role's
`MODEL_INTENT`, a placeholder unless `model` names the arm). Given the case
list rather than the document, the harness reads `skills` from this directory's
`cases.json`. It needs `engine/` on `sys.path`; no network, no key.
`tests/measurement/test_capture.py` runs it on every case.
