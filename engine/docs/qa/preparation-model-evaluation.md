# Offline preparation model evaluation

This evaluator scores recorded responses against ten synthetic, human-authored
cases. It makes no API requests, initializes no worker or profile database, and
never starts mailbox processing. Model quality remains **unmeasured** until
actual model captures are supplied. A passing reference self-check validates
the evaluator, not GLM, Anthropic, or any other model.

From the repository root, using the engine development environment:

```bash
PYTHONPATH=engine python engine/scripts/evaluate_preparation.py --reference-self-check
PYTHONPATH=engine python engine/scripts/evaluate_preparation.py --captures /path/to/captures.json
PYTHONPATH=engine python -m pytest -q engine/tests/evaluation
```

The command prints a JSON report and exits with status 1 if any case fails.
Invalid or incomplete capture collections are rejected; omitted cases cannot
inflate the score. Fixtures live in
`engine/tests/evaluation/preparation_cases.json`. Their `input` contains the
synthetic source or merge pair; `expected` contains explicit review judgments;
`reference_response` is a manually written example for evaluator tests only.
Do not include expectations or reference answers in prompts sent to a model.

## Cases and scoring

- Extraction: two people with separate identifiers; a notification relay whose
  address must not be attributed to a named person; semantic `SKIP`; truncated
  output that must leave processing pending.
- Merge: the same person; two people sharing a topic; the same display name at
  different companies. Distinct people must produce `INSERT`, not a combined
  memory.
- Tasks: a direct request, an informational message, and a truncated tool
  decision that must not be accepted as complete.

Extraction uses the actual `MemoryWorker._parse_entities` and structured
identifier parser. Completion uses `complete_memory_text`; merge refusal uses
`is_no_merge_response`. Identifier sets must match exactly **per entity**, so
adding the sender to every entity fails even if all addresses exist in the
source. These are mechanical comparisons of explicit labels, not a replacement
semantic classifier. Task scoring checks the completion/tool shape and the
selected action/required flag against the case's human-authored expectation.

The report includes per-role correct/total counts, false acceptances of
incomplete responses, per-case outcomes, provider/model configurations, and
summed recorded USD cost. It does not evaluate prose completeness, tone,
real-world recall, task database writes, or production accuracy. Passing this
small suite is necessary evidence for these cases, never proof of equivalent
model quality. Existing worker integration tests cover checkpoint writes.

## Capture format and provenance

Supply one JSON list containing exactly one entry for every fixture ID:

```json
[
  {
    "id": "extract-two-people",
    "provider": "provider-name",
    "model": "exact-model-id",
    "cost_usd": "0.0012",
    "response": {
      "stop_reason": "end_turn",
      "content": [{"type": "text", "text": "recorded response text"}]
    }
  }
]
```

The example illustrates one row and is deliberately not a complete capture set.
Task responses retain their actual `tool_use` block, tool name `task_decision`,
and structured `input`. Preserve actual stop reasons; never repair truncated
responses before scoring. Record charged/settled cost, or clearly identify an
estimated cost in accompanying provenance. Never silently report an unknown
cost as zero. Keep the exact request, system prompt/version, sampling settings,
collection date, usage and cost source alongside captures so comparisons can be
reproduced. Compare identical fixture and prompt versions; split runs by model
when comparing providers. No customer mail is needed.

There is deliberately no live collection option. Future collection requires an
explicitly authorized maximum spend and the bounded engine client under a
separate capped test profile, with automatic preparation disabled. Existing
customer credentials or mailbox work must not be used as an implicit benchmark.
