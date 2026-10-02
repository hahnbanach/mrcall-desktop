# COMPACTION — measurement cases

Scope: the synthetic smoke cases, labels and capture harness that measure the
COMPACTION role (milestone 10, decision D7: "about five mechanical smokes").
Everything here is invented: people, companies, ids, prices.

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
- `capture.py` — `build_requests(cases)` returns the summarizer's request per
  case as `_summarize` passed it to `create_message`; `run_case(case, client)`
  compacts the case's history with any client and returns the new history.

## How a case drives the builder

Builder: `zylch.services.chat_compaction.compact_if_needed`, in a throwaway
profile. `input.history` is the restored conversation (first turn, middle,
ten closing turns); `input.soft_limit` is 0 so a short history takes the path
production takes past 80,000 tokens. Head, tail and rendering are production's,
so only the length of the middle differs from a real compaction. The harness
checks that the summary was spliced in. The request carries `model`: the call
site passes the client's own, recorded as the placeholder `<role model>` that
a measurement replaces with the arm's model.

## Label schema and scoring

```json
"label": {"language": "it", "contains": [["d-4c1e9a"], ["250"], ["1.790", "1790"]],
          "max_chars": 786, "no_headings": true, "complete": true}
```

Scored on the model's answer (the summary text):

- non-empty — an empty summary fails every case (the engine discards it);
- `language` — the language of the summary: the conversation's (compaction-03
  is Italian with an English quotation, and the prompt keeps the
  conversation's language);
- `contains` — every group matched by one alternative (case-insensitive
  substring): the identifiers and the decided facts — corrected quantities,
  totals, the agreed day — the assistant must still know after compaction;
- `max_chars` — the summary is shorter than the rendered middle it replaces
  (the label carries that length);
- `no_headings` — no line starts with `#` (the prompt asks for prose);
- `complete` — the response did not stop at `max_tokens`.

**Critical.** All five cases are critical: a summary that loses a draft id or
keeps a superseded price makes the next turn act on a wrong fact. A failed
`contains` is a critical failure; language, length and form are mechanical
bars.

## Distribution

| Case | Language | Must keep |
|---|---|---|
| compaction-01 | it | draft d-4c1e9a, the corrected 250 pieces, the 1.790 € total |
| compaction-02 | en | invoice NW-2026-0917, draft d-90aa13 (held until accounts confirm) |
| compaction-03 | it (English quoted) | task t-5521, draft d-77b0e5, the 1.810 € total |
| compaction-04 | en (tool calls in the middle) | tasks t-8830 and t-8831, the 3 pm call |
| compaction-05 | it | the corrected 1.250 € price, Monday delivery, draft d-2f8b40 |
