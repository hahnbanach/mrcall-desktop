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
quantity, a price change sent on WhatsApp with a decimal comma. Phone numbers
are in the fictional `+39 02 0000 0xxx` / `+44 20 0000 0xxx` ranges.

## Labels

- Rule: `{"is_durable_rule": false}` or
  `{"is_durable_rule": true, "rule_must_contain": [[alternatives], ...]}`.
- Fact: `{"is_fact_change": false}` or `{"is_fact_change": true,
  "category": "<an existing category>", "value_must_contain": [[alternatives],
  ...], "value_must_not_contain": [the old value's spellings]}`.

Every required alternative appears in what the user sent, and every forbidden
spelling in what was drafted and not in what was sent; the test holds it. The
alternatives admit other correct formats of the same value (`5:30` beside
`17:30`, `12,5` beside `12,50`).

## Scoring

A model's answer falls in one class, read from the judge's tool call. "Records"
means what the engine would write: a rule when `is_durable_rule` is true and
`rule` is non-empty; a fact when `is_fact_change` is true and `category`,
`key` and `value` are all non-empty.

- `record` — it records;
- `no_record` — it does not;
- `old_value` (fact judge, must-record cases) — it records a value that holds a
  spelling from `value_must_not_contain` and no alternative of
  `value_must_contain`: the old figure written in place of the corrected one;
- `invalid` — no call to the judge's tool. The engine writes nothing.

Correct answers:

- Labelled false: `no_record`.
- Labelled true: `record`, with every group of the label met. For a rule, the
  text contains, case-insensitively, one alternative of each group and is in
  `expect_lang`. For a fact, the value contains one alternative of each group
  (as written) and no forbidden spelling, and `category` equals the label's
  (case-insensitive, trimmed).

Any other `record` on a must-record case is an ordinary miss: missing content,
the wrong language, the wrong category, or a value that cites the old figure
beside the new one (`52 EUR + IVA (prima 45)`). `why` and `key` are not scored.

**Critical answers.** `critical_on` lists the wrong answer classes that are
critical failures for the case; `[]` means none is, and `critical` is derived
(`true` exactly when `critical_on` is not empty).

- Must-record rule cases: `[]`. A miss is the conservative error both prompts
  prefer.
- Must-record fact cases: `["old_value"]`. Writing the old figure is the
  harm; a miss, a wrong category or another value mismatch is not.
- Must-not cases: `["record"]` where the recorded rule or fact would be wrong
  for everyone: the arrangement made with one customer (-08), the personal
  wish (-09), the one-off pickup day (-11), the one-off discount (-19), and
  one order's ship date (-22). `[]` where recording would be harmless: a typo
  or grammar fix (-07, -12, -20), a tone change (-21), an order total at the
  unchanged unit price (-23), a greeting (-24), and -10. In -10 the "rule"
  would only restate a correct existing rule, which the store routes to its
  duplicate check.

**Language.** `expect_lang` is the language the measurement requires for the
scored free text; no language bar applies when it is `null`. It is the
correction's language (`lang`) on the six must-record rule cases. The judge's
prompt names no language; the bar is the brief's, so an Italian correction is
learned in Italian, which milestone 9's rejected arm failed. It is `null`
elsewhere: a fact's value and category are figures and existing names, and a
must-not case has no text to score.

The method is `text_language` in `tests/measurement/capture_support.py`:

1. Lowercase the text and split it into words on anything that is not a letter.
2. Count the words found in a fixed Italian and a fixed English function-word
   list.
3. The language with strictly more hits wins. A tie, including no hit, is
   undecided and fails the bar.

The test checks it on the memories' rules and on every must-record case's
sent text.

## Input to builder

`capture.py` boots a throwaway profile per company and seeds its memory
through `tests/memory/seeding.py`: rules into `prefs:<owner>` under the STYLE
header the harness writes, facts into `facts:<key>` under the FACT header. It
then runs `learn_from_corrections([input.correction], owner)` (the `builder`)
with the role's client routed through `MODEL_CORRECTION_LEARNING`. Both judges
are called, as in production; the harness returns the request of the case's
judge, whose prompt carries the rendered existing rules or the existing
categories. The scripted answers decline, so nothing is written; a write is
refused.

`build_requests(cases, model=...)` returns `[{"case_id", "request"}]`, the
keyword arguments the judge passed, as sent. Given the case list rather than
the document, it reads `memories` from this directory's `cases.json`. It needs
`engine/` on `sys.path`; no network, no key.
`tests/measurement/test_capture.py` runs it on every case.

## Placeholders in the captured request

The replay rebuilds each request per arm with the M10 request shape; it takes
`system`, `messages`, `tools` and `max_tokens` from the capture. Not replayed
as captured:

- `tool_choice` forcing `record_rule` / `record_fact` — the M10 shape sends
  `auto` with an explicit instruction instead.
- The model: the request carries none (the client's model, the role's
  `MODEL_CORRECTION_LEARNING`); each arm supplies its own.
