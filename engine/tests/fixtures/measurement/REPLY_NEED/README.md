# REPLY_NEED — measurement cases

Scope: the synthetic case set and capture harness for the `REPLY_NEED` role
(milestone 10, brief D7). Inputs and labels only; the measurement replays the
captured requests on each arm.

## What the role decides

For a customer's message on a thread our side has already answered, whether we
still owe a reply (`zylch/utils/reply_need.py`). The model answers through the
`reply_need_decision` tool, one verdict per message index: `needs_reply`
(boolean) and a short `reason`. The two errors are not equal: calling a real
request a closing courtesy silences the customer and nothing downstream catches
it; calling a thank-you "needs a reply" costs one line on a list.

## Cases

20 messages, one per case, 11 Italian and 9 English (two mix both):

- 10 need a reply: a request wrapped in thanks, a problem not solved, a new day
  proposed for an appointment, a new delivery address, a quote we owe, a
  complaint, a missing contract page, an order change — none with a question
  mark, which the engine's screen would settle without a model.
- 10 pure closing courtesies: with a signature block, a legal confidentiality
  footer full of request words, a quoted trailer of our own mail, a bare
  "Ok, grazie", an explicit "No need to reply".

## Label and scoring

Label: `{"needs_reply": true | false}`.

A model's answer falls in one class, read from the `reply_need_decision` call's
`verdicts` entry with `index` 0:

- `needs_reply` — `needs_reply` is `true`;
- `no_reply` — `needs_reply` is `false`;
- `invalid` — no tool call, no verdict for index 0, or a value that is not a
  boolean. The engine degrades this to "needs a reply"; the model did not
  decide, so it never counts as correct (a mechanical failure).

The answer is correct when its class matches the label. `reason` is not scored.

**Critical answers.** `critical_on` lists the wrong answer classes that are
critical failures for the case; `[]` means no wrong answer on it is critical,
and `critical` is derived (`true` exactly when `critical_on` is not empty).
Here: `["no_reply"]` on every case labelled `needs_reply: true`, because
silencing a request is the harm; `invalid` is not critical, because the engine
answers it with "needs a reply". `[]` on the courtesies, where a wrong answer
costs a line on a list.

**Language.** `expect_lang` is the language the role's prompt requires for the
free text the measurement scores; no language bar applies when it is `null`.
Here it is `null` on every case: the only free text, `reason`, is optional,
asked in English, and not scored.

## Input to builder

`input.message` holds `from_email`, `subject` and `body_plain`. `capture.py`
hands it to `classify()` in the shape `emails.needs_reply` builds
(`zylch/rpc/reply_queries.py`): not ours, not an autoresponder, no attachment,
`answered_before: true`. `classify` screens it first; every case passes the
screen (typed text short, no question mark, no link), reaches `adjudicate`
(the `builder`), and yields its one request. The harness refuses a case the
screen settles alone. Production batches up to 40 messages per request; the
measurement sends one.

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments `adjudicate` passed, as sent, from a client built for the
role's `MODEL_REPLY_NEED` (`model`, default a placeholder). It needs `engine/`
on `sys.path` (it imports `tests.memory` helpers); no network, no key.
`tests/measurement/test_capture.py` runs it on every case.

## Placeholders in the captured request

The replay rebuilds each request per arm with the M10 request shape; it takes
`system`, `messages`, `tools` and `max_tokens` from the capture. Not replayed
as captured:

- `temperature: 0` — the call site picks it against the client's model (`1`
  only for `moonshotai/kimi-k3`), and the capture's model is a placeholder;
  the M10 shape sends no sampling fields.
- `tool_choice` forcing `reply_need_decision` — the M10 shape sends `auto`
  with an explicit instruction instead.
- The model: the request carries none (the client's model, the role's
  `MODEL_REPLY_NEED`); each arm supplies its own.

## Engine behaviour found while building the set

`visible_text` cuts at the first line whose three-line window ends in a reply
attribution. With the attribution on one line after a blank line
(`"Thanks.\nPlease cancel the second pallet.\n\nOn …, X <x@…> wrote:"`), the
window starting two lines above already matches, so the last typed line is
dropped and the model sees only `"Thanks."` — the silencing direction the
module forbids. Case 13 therefore uses the two-line wrapped attribution the
engine handles; the defect is reported, not worked around in the labels.
