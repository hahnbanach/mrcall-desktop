# COMPACTION — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
COMPACTION role (milestone 10, decision D7: "about five mechanical smokes"),
and the label rules adopted after their independent review. Everything here
is invented: people, companies, ids, prices.

## What the role decides

COMPACTION summarizes the middle of a long chat so the conversation fits the
model's window (`zylch/services/chat_compaction.py`). `ChatService` runs
`compact_if_needed` on a restored history before every turn; past 80,000
estimated tokens it keeps the first turn and the last ten verbatim, renders the
turns between as prose (tool calls and results become one-line narrations)
and asks the role's model for one summary, which replaces them. Whatever the
summary drops, the assistant has forgotten: its prompt asks for the user's
intents, decisions, drafts, tool results and every identifier (task, email,
draft ids), in the conversation's language, as prose, without invented facts.

## Files

- `cases.json` — five smoke cases.
- `capture.py` — `build_requests(cases)` returns, per case,
  `{"case_id", "request", "capture_now"}`: the summarizer's request as
  `_summarize` passed it to `create_message`, and the moment it was captured
  at; `run_case(case, client)` compacts the case's history with any client and
  returns the new history, the summary spliced in.

## How a case drives the builder

Builder: `zylch.services.chat_compaction.compact_if_needed`, in a throwaway
profile. `input.history` is the restored conversation (first turn, middle,
ten closing turns); `input.soft_limit` is 0 so a short history takes the path
production takes past 80,000 tokens. Head, tail and rendering are production's,
so only the length of the middle differs from a real compaction. The harness
checks that the summary was spliced in. The request carries `model`: the call
site passes the client's own, recorded as the placeholder `<role model>` that
a measurement replaces with the arm's model. On replay the client appends its
datetime line, set to the entry's `capture_now` (label review G5), as it is
inside `run_case`'s profile.

The middles carry the facts among low-information turns — interruptions,
acknowledgements, "ok" — as a real 80,000-token middle does, so a faithful
summary has room under `max_chars` (label review: a limit equal to a middle
of facts alone left none).

## A case

`id`, `lang` (the conversation's language), `expect_lang`, `input`, `label`,
`critical`, `critical_on`, `why` (what the summary must keep and why).

## Label schema and scoring

```json
"label": {"contains": [["d-4c1e9a"], ["250"], ["1.790", "1790", "1,790"]],
          "max_chars": 1447, "no_headings": true, "complete": true}
```

Scored on the model's answer (the summary text), normalised first by the
measurement (Markdown emphasis stripped, non-breaking and thin spaces made
plain — review G3):

- non-empty — an empty summary fails every case (the engine discards it);
- `contains` — every group matched by one alternative (case-insensitive
  substring): the identifiers and the decided facts — corrected quantities,
  totals, the agreed day, a send held until accounts confirm — the assistant
  must still know after compaction. Each group accepts the fact in either
  language (`lunedì`, `lunedi`, `monday`), so a language slip stays a
  language failure;
- `max_chars` — the summary is shorter than the rendered middle it replaces
  (the label carries that length);
- `no_headings` — no line starts with `#` (the prompt asks for prose);
- `complete` — the response did not stop at `max_tokens`.

**Language.** `expect_lang` is the case's `lang`: the prompt keeps the
conversation's language (compaction-03 is Italian with an English quotation,
and expects Italian).

**Critical.** `critical_on` lists the kinds of failure that are critical in
the case; `critical` is derived (`true` exactly when the list is not empty).
Every case has `critical_on: ["contains"]`: a summary that loses a draft id
or keeps a superseded price makes the next turn act on a wrong fact. Language,
length and form are mechanical bars, never critical.
`tests/measurement/conversation_judge.py` is the reference reading;
`test_labels_agent_and_smoke_roles.py` holds it on the cases.

## Distribution

| Case | Language | Must keep |
|---|---|---|
| compaction-01 | it | draft d-4c1e9a, the corrected 250 pieces, the 1.790 € total |
| compaction-02 | en | invoice NW-2026-0917, draft d-90aa13, held until accounts confirm |
| compaction-03 | it (English quoted) | task t-5521, draft d-77b0e5, the 1.810 € total |
| compaction-04 | en (tool calls in the middle) | task t-8830, the moodboard task t-8831 closed (its id or its name), the 3 pm call |
| compaction-05 | it | the corrected 1.250 € price, Monday delivery, draft d-2f8b40 |
