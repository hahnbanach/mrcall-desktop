# NARRATION — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
NARRATION role (milestone 10, decision D7: "about five mechanical smokes").
Everything here is invented.

## What the role decides

NARRATION writes the one line the desktop shows while a chat turn runs
(`zylch/rpc/methods.py`). Two RPCs, one role:

- `narration.predict` — the first placeholder, from the user's message: one
  Italian sentence of at most 80 characters starting with "Sto " (otherwise
  the RPC falls back to "Sto pensando alla tua richiesta.").
  `max_tokens` 40.
- `narration.summarize` — every few seconds, from the sidecar's latest log
  lines: one Italian, first-person, present-tense sentence of at most 80
  characters about the concrete action under way; an important error said
  briefly and kindly. `max_tokens` 60.

## Files

- `cases.json` — five smoke cases.
- `capture.py` — `build_requests(cases)` returns, per case,
  `{"case_id", "request", "capture_now"}`: the request of its RPC as it
  passed it to `create_message_sync`, and the moment it was captured at;
  `run_case(case, client)` calls the RPC with any client and returns its
  result.

## How a case drives the builder

The document's `builder` is the module both RPCs live in;
`input.builder` names the case's RPC (`zylch.rpc.methods.narration_summarize`
or `zylch.rpc.methods.narration_predict`); `input.params` are its parameters as
the renderer sends them (`lines` and `context`; `message` and `context`). The
log lines use the sidecar's stderr format (`HH:MM:SS logger LEVEL message`).
`narration_summarize` drops lines it judges noise before calling the model;
the harness fails a case whose lines would all be dropped rather than capture
nothing. On replay the client appends its datetime line, set to the entry's
`capture_now` (label review G5).

## A case

`id`, `lang` (the language of the input), `expect_lang`, `input`, `label`,
`critical`, `critical_on`, `why`.

## Label schema and scoring

```json
"label": {"contains": [["cerc", "email", "ferretti"]], "max_chars": 80,
          "single_line": true, "starts_with_any": ["Sto "], "not_equal": ["Sto pensando alla tua richiesta."]}
```

Scored on the model's answer, stripped of surrounding whitespace and quotes,
and normalised by the measurement (Markdown emphasis stripped, non-breaking
and thin spaces made plain — review G3):

- non-empty;
- `max_chars` — the prompts' 80 characters;
- `single_line` — no line break;
- `starts_with_any` (predict only) — begins with "Sto " (case-insensitive);
- `not_equal` (predict only) — not the ambiguity fallback: both requests are
  unambiguous;
- `contains` — names the action under way: every group matched by one
  alternative (case-insensitive substring; stems such as `cerc`, `scaric`
  cover the verb's forms).

**Language.** `expect_lang` is `it` on every case, the two English inputs
included: both prompts fix Italian whatever language the user writes in.
`lang` is the input's language. A line of fewer than about eight words is too
short for reliable detection, and the measurement skips the bar there (review
G3).

**Critical.** No case is critical (`critical_on: []`, `critical: false`): a
weak narration costs a moment of the user's attention, nothing else. Every
check is a mechanical bar.

## Distribution

| Case | RPC | Input language | The line must name |
|---|---|---|---|
| narration-01 | summarize | it | the search of Ferretti's email |
| narration-02 | summarize | en | the attachment downloaded and read |
| narration-03 | summarize | it | the mail server timing out (a warning) |
| narration-04 | predict | en | looking for Kestrel's invoice |
| narration-05 | predict | it | the WhatsApp to Laura |
