# SYNC_ANALYSIS — measurement cases

Scope: the synthetic case set and capture harness for the `SYNC_ANALYSIS`
role (milestone 10, brief D7). Inputs and labels only; the measurement replays
the captured requests on each arm.

## What the role decides

For each email thread the sync analyses, `EmailSyncManager._agent_analyze`
(`zylch/tools/email_sync.py`, prompt `zylch/prompts/email_thread_classify.txt`)
asks through the `classify_thread` tool whether the user has a task:
`expected_action` — `"answer"` (someone waits for the user's reply),
`"reminder"` (the user promised something) or `null` (nothing to do) — `open`
(a task is pending) and an English `summary`. The engine records
`requires_action = expected_action is not None`.

The role's other call sites make no decision to label: `calendar_sync.py`
builds a client and never sends a request; `process_pipeline.py` sends a
one-token preflight ping (which S1 replaces with a free check).

## Cases

20 threads, 10 Italian and 10 English (one mixes both): 7 `answer` (questions,
requests for documents or a quote, a meeting proposal, a damaged delivery, a
request without a question mark), 4 `reminder` (the prompt's examples 2 and 4
in both languages: the user promised, the customer only thanked), 1 action
whose class the prompt leaves open, 8 with no action (automated notices, a
newsletter, a calendar acceptance, concluded courtesies, an explicit
"No need to reply"). The newest message always comes from the other party;
the user's promises are visible in what it quotes. Cases 08 and 15 are the
same shape (the customer thanks the user) with opposite labels.

## Label and scoring

Label: `{"needs_action": true, "expected_action": "answer" | "reminder"}`,
`{"needs_action": true}` where the class is not decidable from the prompt's
rules, or `{"needs_action": false, "expected_action": null}`.

A model's answer falls in one class, read from its `classify_thread` call:
`answer`, `reminder`, `none` (`expected_action` null), or `invalid` (no call;
the engine then falls back to the snippet, `open: true`, no action).

- Correct: on a no-action case, `none`; on an action case, `answer` or
  `reminder` — the labelled one where the label names a class. `open` must
  equal `needs_action` (the prompt's examples tie them).
- `summary` is not scored: the tool asks for English whatever the thread's
  language.

**Critical answers.** `critical_on` lists the wrong answer classes that are
critical failures for the case; `[]` means none is, and `critical` is derived
(`true` exactly when `critical_on` is not empty).

- `["none", "invalid"]` on every action case: a missed customer request or a
  forgotten promise. `invalid` lands on the same fallback, no action.
- `[]` on the no-action cases: marking such a thread open is an ordinary
  error, as is the other class on an action case.

**Language.** `expect_lang` is the language the role's prompt requires for the
free text the measurement scores; no language bar applies when it is `null`.
Here it is `null` on every case: the only free text, `summary`, is asked in
English and not scored.

## Input to builder

`input.messages` is the thread: `from_name`, `from_email`, `to_email`,
`subject`, `date` (ISO 8601 with offset) and `body_plain`. `capture.py`
writes them into the throwaway profile's `emails` table, builds
`EmailSyncManager` over a real `EmailArchiveManager`, and runs `sync_emails`
with a window that holds the thread whenever it runs; the manager orders the
thread by date and `_agent_analyze` (the `builder`) builds the request for the
newest message: subject, sender, message count and body. One thread per case,
so one request; the table is emptied between cases.

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments `_agent_analyze` passed, as sent, from a client built for
the role's `MODEL_SYNC_ANALYSIS`. It needs `engine/` on `sys.path`; no
network, no key. `tests/measurement/test_capture.py` runs it on every case.

## Placeholders in the captured request

The replay rebuilds each request per arm with the M10 request shape; it takes
`messages`, `tools` and `max_tokens` from the capture. Not replayed as
captured:

- `tool_choice` forcing `classify_thread` — the M10 shape sends `auto` with an
  explicit instruction instead.
- The model: the request carries none (the client's model, the role's
  `MODEL_SYNC_ANALYSIS`); each arm supplies its own.

## Engine behaviour found while building the set

- `clean_html` parses any body containing `<`, so a plain-text reply whose
  quoted attribution carries `Name <address>` is read as HTML: the address is
  dropped and every newline collapses into a space. The content survives, and
  the cases are labelled on what the model receives.
- The analysis is not kept. `_save_analyzed_threads` and `_save_cache` are
  no-ops, and every reader of the thread cache (`search_threads`, `get_stats`,
  closing a thread) starts from `_load_cache`, which returns an empty cache.
  So the role's answers reach no one today (the chat's `sync_emails` tool
  reports counts only). The critical answers above are the role's own
  semantics, as reviewed.
