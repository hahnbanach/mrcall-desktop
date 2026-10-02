# CORRECTION_LEARNING — measurement cases

Scope: the synthetic case set and capture harness for the
`CORRECTION_LEARNING` role (milestone 10, brief D7). Inputs and labels only;
the measurement replays the captured requests on each arm.

## What the role decides

When the user edits an approval-gated message (`send_email`, `send_whatsapp`,
`send_sms`) before it is sent, `learn_from_corrections`
(`zylch/services/correction_learning.py`) judges the edit twice, independently:

- `extract_rule`, tool `record_rule` (`is_durable_rule`, `rule`, `why`): does
  the edit reveal a durable policy for every future message — not a typo, a
  one-off, a recipient-specific tweak, a personal detail, or something an
  existing rule already covers?
- `extract_fact`, tool `record_fact` (`is_fact_change`, `category`, `key`,
  `value`): did the edit correct a standard business value (price, rate, lead
  time, minimum order, hours, deliverable), reusing an existing category?

Both prompts say recording a wrong rule or fact is worse than missing one.

## Cases

24 corrections, 12 Italian and 12 English; 12 per judge, 6 that must be
recorded and 6 that must not for each. A case names its judge (`input.judge`)
and its company (`input.memory`). The two companies' memories sit once at the
file's top level (`memories`): an Italian print shop (`tipografia`) and an
English design studio (`studio`), two rules and four facts in three categories
each. Hard cases: a one-off discount, a correction that only applies an
existing rule, a typo next to a price, an order total that changed with its
quantity, a price change sent on WhatsApp with a decimal comma.

## Labels and scoring

- Rule: `{"is_durable_rule": false}` or
  `{"is_durable_rule": true, "rule_must_contain": [[alternatives], ...]}`.
- Fact: `{"is_fact_change": false}` or `{"is_fact_change": true,
  "category": "<an existing category>", "value_must_contain": [[alternatives],
  ...], "value_must_not_contain": [the old value's spellings]}`.

"Records" means what the engine would write: a rule when `is_durable_rule` is
true and `rule` is non-empty; a fact when `is_fact_change` is true and
`category`, `key` and `value` are all non-empty.

- Labelled false: correct when the model does not record.
- Labelled true: correct when it records and — rule — the rule contains,
  case-insensitively, one alternative of every group and is written in the
  case's `lang`; — fact — the value contains one alternative of every group
  (as written), none of `value_must_not_contain`, and `category` equals the
  label's (case-insensitive, trimmed).
- Critical failures: recording anything on a critical case labelled false (a
  wrong rule or fact written into memory); on a critical fact case labelled
  true, recording a value that fails `value_must_contain` or
  `value_must_not_contain` (a wrong fact written). Missing a must-record case,
  or a wrong category, is an ordinary error. `why` and `key` are not scored.

Every required alternative appears in what the user sent, and every forbidden
spelling in what was drafted and not in what was sent; the test holds it.

## Input to builder

`capture.py` boots a throwaway profile per company, seeds its memory through
`tests/memory/seeding.py` — rules into `prefs:<owner>` under the STYLE header
the harness writes, facts into `facts:<key>` under the FACT header — and runs
`learn_from_corrections([input.correction], owner)` (the `builder`) with the
role's client routed through `MODEL_CORRECTION_LEARNING`. Both judges are
called, as in production; the harness returns the request of the case's judge,
whose prompt carries the rendered existing rules or the existing categories.
The scripted answers decline, so nothing is written; a write is refused.

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments the judge passed, as sent. Given the case list rather than
the document, it reads `memories` from this directory's `cases.json`. It needs
`engine/` on `sys.path`; no network, no key.
`tests/measurement/test_capture.py` runs it on every case.
