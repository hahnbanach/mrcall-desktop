# K3 and GLM with actual engine prompts

Model-selection conclusions are superseded by the
[controlled 360-response comparison](2026-09-15-controlled-model-quality.md).
This three-case record remains historical diagnostic evidence.


This evaluation does not justify a production model switch. K3 produced two
acceptable task decisions but one request failed; GLM produced no task decisions
because all three requests returned HTTP429. Both models made consequential
memory errors. A successful parser check is insufficient evidence of quality.

## Method and limits

Three short real threads cover an acknowledged declined proposal, a confirmed
sample delivery/invoice workflow, and a substantive technical inquiry. Expected
facts and task dispositions were recorded and independently reviewed before paid
calls. Mail and company identifiers, trained prompts, retrieved context and raw
outputs remain in private scratch storage, outside Git.

Requests were captured from actual memory/task worker construction at source
`67866c2`, including saved trained prompts, owner rules, company self-notion,
retrieval and existing tasks. Memory receives the individual message (including
its quoted content); task detection receives the chronological thread. Both
models receive identical requests and the same engine-generated current-date
line. Captured runtime caps were 1024 output tokens for memory and 500 for tasks, with
real task tools and forced `task_decision`. No context was shortened. This differs
from the [earlier synthetic test](2026-09-13-openrouter-models.md), whose extraction
and task prompts were simplified and whose output allowance was 4096 tokens.

Only the engine API path was tested, through its OpenRouter adapter. Claude Code
headless operation, kernel classifiers, memory merging and draft quality were not
tested. Results from three selected short threads cannot establish comparative
quality on the full mailbox, large threads, attachments or repeat runs. Anthropic
was not rerun on this dataset, so this is not an equal-input Anthropic comparison.
Temperature remains the production value of 1; a single paired response cannot
isolate prompt effects from sampling or provider variation.

## Requests and measured costs

| Prompt | Model / role | Usable responses / attempts | Reported cost of usable responses | Response time, seconds |
|---|---|---:|---:|---|
| Original | K3 memory | 3 / 3 | $0.03088800 | 5.08–81.74 |
| Original | K3 tasks | 2 / 3 | $0.03947010 | 71.20–82.81 |
| Original | GLM 5.2 memory | 3 / 3 | $0.00325083 | 1.02–8.18 |
| Original | GLM 5.2 tasks | 0 / 3 | — | No usable response |
| Candidate | K3 memory | 1 / 3 | $0.01479690 | 44.16 |
| Candidate | GLM 5.2 memory | 3 / 3 | $0.00231655 | 2.08–9.50 |

Five requests returned HTTP429; another returned an incomplete response after
121.99 seconds. These are availability failures, not semantic grades. The adapter
does not retain detailed upstream error bodies, so their root cause is unproven.
Free key metadata showed available credit. Failed requests were not repeated;
independent, previously unattempted cases continued. All 12 usable responses
passed the actual worker response parsers; semantic checks are separate below.

One isolated USD1 engine ledger covered all 18 attempts. It records **$0.090729
settled usage, $0.297063 uncertain reservations, $0.612208 remaining**. Uncertain
holds were retained; settled usage is not a claim about the final cost of failed
requests. Reported costs are direct provider costs, without MrCall markup or
StarChat rounding. GLM responses include provider cache-read tokens; this is not
a cold-cache tariff comparison. K3 and GLM were run sequentially under current
price caps without automatic retry, fallback or tariff increases.

## Prompt and parser correction

The output-blind candidate only changes memory system instructions: use the
sectioned FACT envelope required by the actual parser and remove an unrelated IT
consulting example that invented names, roles, company facts and prices. Owner
rules, self-notion, messages, output limits and all task requests are unchanged.
The system prompt shrinks from 13,151 to 11,920 characters. Three candidate memory
requests per model were attempted; unchanged tasks were not repeated.

The generic source fix applies to future prompt training. A related parser fix
stops FACT values at exact protocol section headers, preserving multiline values
and legacy flat FACTs. Otherwise even correctly sectioned output could save
`#ABOUT` and `#HISTORY` inside the business value. This is structural protocol
parsing; semantic classification remains LLM-driven.

Both changes passed independent implementation review and 49 focused tests,
including the real trainer FACT example through extraction and fact-value parsing.
Existing saved prompts were not rewritten, models were not switched, and hosted
engines remain pinned to their previous release with affected processing paused.

## Blinded semantic outcome and decision

An independent reviewer graded shuffled opaque output IDs without model, prompt
variant, cost or timing information. Mapping was joined only after grading.

| Prompt | Model / role | Semantically acceptable / returned |
|---|---|---:|
| Original | K3 memory | 2 / 3 |
| Original | K3 tasks | 2 / 2 |
| Original | GLM 5.2 memory | 1 / 3 |
| Original | GLM 5.2 tasks | Not measured: none returned |
| Candidate | K3 memory | 0 / 1 |
| Candidate | GLM 5.2 memory | 1 / 3 |

Six of twelve returned outputs were acceptable; all eighteen attempts remain in
the availability denominator above. Acceptable does not mean flawless: one K3
task leaves sender/signature implicit, and one memory output infers a full name
from an email address. Consequential failures include treating a planned invoice
as issued, attributing one contact's office phone to a different contact,
extracting own-company people despite explicit exclusions, promoting a customer
address to a general business FACT, creating an unidentified placeholder company,
and inferring a reusable writing STYLE without the required owner examples.

The candidate shows no observed semantic improvement and is **not promoted to
stored prompts**. The generic format/grounding correction is justified by the
parser contract and the fabricated instructional example, not by an unsupported
claim of higher semantic accuracy. Future generated prompts still need evaluation.

K3 remains the more promising task candidate on this sample, with insufficient
coverage and availability to recommend automatic backlog processing. GLM memory
is cheaper here but fails important identity/business-context checks; GLM tasks
cannot be judged until the 429 path is diagnosed. Next work should investigate
routing availability without paid retries and strengthen/evaluate identity,
source attribution and planned-versus-completed rules on held-out cases. No
blanket cheap-model switch, automatic Anthropic fallback or backlog restart is
justified by this experiment. Existing production holds are a separate unresolved
billing-reconciliation issue, untouched by this scratch ledger.

Focused verification (from repository root, using an environment with engine
test dependencies installed):

```bash
PYTHONPATH=engine python -m pytest -q \
  engine/tests/agents/test_memory_message_trainer.py \
  engine/tests/services/test_facts_store.py \
  engine/tests/workers/test_memory_spend_safety.py --disable-warnings
```

Result: 49 passed, 13 warnings. Independent final review approved the code,
report, no-promotion decision and deployment boundaries. New report/work-trace
links resolve and `git diff --check` passes.
