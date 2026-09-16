# K3 reasoning and output-budget comparison

Status: complete. All 180 outputs graded; no production promotion. Maximum
reasoning improves memory semantics on this corpus but does not improve positive-
arrival task quality enough to justify a general switch.

## Question and controlled conditions

The [earlier comparison](2026-09-15-controlled-model-quality.md) evaluated an
OpenRouter adapter that explicitly disabled thinking. All 20 archived K3 arrival
wire hashes reconstruct with that setting; all report zero thinking tokens.
The current K3 catalog default therefore did not apply. This experiment asks
whether explicit maximum reasoning improves quality and at what observed cost.

| Arm | Requested reasoning | Total output ceiling |
|---|---|---:|
| off-original | Disabled | Memory 4096; tasks 2048 |
| off-8192 | Disabled | 8192 |
| max-8192 | Maximum effort | 8192 |

All three arms use K3 through OpenRouter Chat Completions, pinned to DigitalOcean,
with identical provider price ceilings, source text, tools, owner instructions
and per-case clocks. `off-original` refers to the earlier role token ceilings,
not an identical historical wire protocol. The disabled-large control separates
an output-ceiling effect from the reasoning change. No prompts are tuned here.

The corpus comprises 20 episodes selected with seed 20260916, four per original
held-out stratum, each with memory and current-state task requests, plus all 20
historical positive-arrival task requests. That gives 60 requests, 180 planned
outputs and **37 unique business clusters** because three arrival episodes overlap
the selected base. Cohorts are reported separately; repeated roles and arms do
not increase independent sample size.

These inputs are exposed diagnostic cases from one company, not a new held-out
confirmation set or an IID mailbox sample. Historical Opus grades are a semantic
reference, including the corrected 16/20 positive-task count; they are not a
contemporaneous Chat-protocol control. Each cell has one intended generation;
there is no retry to replace an incorrect model answer.

## Verified transport and accounting

The first two Messages-protocol compatibility attempts were rejected with HTTP404
before provider selection. Strict parameter filtering rejected the combination
of adaptive thinking and output effort despite the endpoint advertising reasoning.
No model response was produced. Both attempts and USD0.358544 of conservative
holds remain recorded in the same experiment ledger.

The explicit Chat protocol uses `reasoning: {effort: max}` or `{enabled: false}`.
Deterministic translation preserves system-block order, user text, captured tool
schemas and the forced function name. All arms share this translation. The adapter
reserves the larger of the source-format bound and the full translated-wire bound,
including all output tokens, before dispatch. It preserves exact decimal receipts
and raw Chat responses privately, while exposing only final text/tool blocks to
the same guarded production parser. Invalid JSON or refusal remains non-actionable;
known valid receipts can still settle without accepting the response.

The two Chat compatibility cells belong to the 180-cell matrix: the memory
response reports 531 output tokens, including 520 reasoning tokens, and the task
response reports 1574 output tokens, including 1230 reasoning tokens. Both use
DigitalOcean and complete successfully; their combined settled cost is USD0.054258.
The captured outgoing requests prove explicit maximum effort was requested, and
reported token counts prove active reasoning. They do not independently reveal
the provider's internal effort implementation.

The dedicated cap is USD10 including compatibility and uncertain holds. It does
not reset or consume the prior study's ledger. After funded compatibility, the
main run uses at most three concurrent requests, atomic reservations, durable
intents, no automatic retries and a 600-second HTTP timeout setting. The initial
sum of all worst-case Chat reservation bounds is USD31.988113, not predicted
spending; the largest single bound is USD0.342029. One reservation settles before
its unused allowance becomes available again. Admission, not a cost forecast,
determines whether remaining cells can run.

## Grading and reproducibility

Three blinded AI-agent grading partitions see only final outputs, common source requests
and frozen source-based rubrics. Arm identities, provider metadata, reasoning
text, costs and per-arm control fields are withheld. Existing policy ambiguities
remain indeterminate where appropriate. Unsupported claims, internal-entity
exclusion violations, invented completion and missed operative actions are
consequential failures regardless of which arm produced them.

Semantic quality, independent tool/schema contract, raw completion and current
parser acceptance are separate. Shared business clusters stay within one grading
partition. These source-based judgments are reviewable evaluation labels, not a
human-adjudicated gold standard or calibrated probabilities. Derived grading sources map arm-specific execution IDs back to common
source IDs with explicit one-to-one checks, exact allowed request-delta checks,
and source journal/line provenance. They are not additional paid executions.

Private evidence and reproduction helpers live under
`~/.local/share/mrcall/evaluations/2026-09-16-k3-reasoning/`, outside Git.
The [brief](../briefs/2026-09-16-k3-reasoning-quality.md) and
[execution plan](../execution-plans/2026-09-16-k3-reasoning-quality.md) record the
frozen design, protocol repair, reviews and scheduling amendment.

Official protocol references: [reasoning controls](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens),
[Messages API](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-a-message),
[K3 endpoint metadata](https://openrouter.ai/api/v1/models/moonshotai/kimi-k3/endpoints).

## Results and decision

All 180 Chat generations returned from the pinned provider and were graded
exactly once. Maximum reasoning is a promising memory configuration, but it is
**not an acceptable blanket replacement** for disabled reasoning or historical
Opus. On positive arrival tasks, maximum reasoning corrects four determinate
errors and introduces five relative to the equal-ceiling disabled control.
No production default is promoted.

Counts below retain all 20 planned requests per cohort. `Usable` requires an
acceptable semantic judgment, acceptable independent contract judgment and parser
acceptance. An indeterminate answer is not counted as successful.

| Cohort | Arm | Acceptable | Unacceptable | Indeterminate | Parser accepted | Usable |
|---|---|---:|---:|---:|---:|---:|
| Memory | off-original | 10 | 7 | 3 | 17 | 9 |
| Memory | off-8192 | 9 | 8 | 3 | 18 | 9 |
| Memory | max-8192 | 14 | 2 | 4 | 16 | 11 |
| Current-state tasks | off-original | 17 | 3 | 0 | 20 | 17 |
| Current-state tasks | off-8192 | 14 | 6 | 0 | 20 | 11 |
| Current-state tasks | max-8192 | 18 | 2 | 0 | 20 | 18 |
| Positive arrival tasks | off-original | 9 | 10 | 1 | 20 | 9 |
| Positive arrival tasks | off-8192 | 13 | 6 | 1 | 20 | 13 |
| Positive arrival tasks | max-8192 | 12 | 7 | 1 | 20 | 12 |

The equal-ceiling paired comparison is more informative than aggregate totals:

| max-8192 versus off-8192 | Corrected errors | New errors | Both acceptable | Both unacceptable | Indeterminate pairs |
|---|---:|---:|---:|---:|---:|
| Memory | 6 | 1 | 8 | 1 | 4 |
| Current-state tasks | 5 | 1 | 13 | 1 | 0 |
| Positive arrival tasks | 4 | 5 | 7 | 2 | 2 |

Memory's semantic improvement is reduced by output-shape failures: only 11/20
maximum-reasoning outputs are directly usable versus 9/20 for either disabled
arm. Bare FACT values instead of the required envelope remain a contract/parser
problem. Current-state tasks improve to 18/20, but the original-ceiling disabled
arm already reaches 17/20. The large-ceiling disabled arm has three additional
contract failures despite parser acceptance; parser success is not proof that the
whole required contract is satisfied.

Concrete equal-ceiling transitions, traced to private source and output IDs:

- Maximum reasoning correctly excludes an internal colleague from external
  memory and avoids inventing a company legal identity. It also preserves quoted
  quantities as feasible quantities rather than incorrectly calling them minima.
- It correctly creates a task for an incoming NDA-addendum review that the
  disabled control dismisses. It also avoids updating a nonexistent task when
  captured task context is empty.
- It introduces an unsupported ambient-storage assurance, a categorical
  no-glass/exclusive-coffee refusal, and an unsupported private-label product
  assignment in arrival replies where the disabled control remains grounded.
- It invents payment confirmation in a current-state task from a payment-method
  field without evidence that payment completed.

These examples explain the decision: additional reasoning does not reliably
prevent invented business facts. Maximum memory reasoning merits confirmation
with a corrected output contract on fresh cases; current-state task gains need
repeatability checks. Positive-arrival task generation still needs grounded
capability/policy handling and validation before any promotion. A model's own
confidence would not resolve the observed unsupported assertions.

## Observed cost, latency and reasoning

Costs are exact provider receipts for each cohort's 20 calls; these are observed
costs, not stable tariff multipliers or a production-volume forecast.

| Cohort | off-original USD | off-8192 USD | max-8192 USD | Historical Opus USD |
|---|---:|---:|---:|---:|
| Memory | 0.128960 | 0.224098 | 0.541189 | 1.285235 |
| Current-state tasks | 0.273042 | 0.342320 | 0.601415 | 1.921725 |
| Positive arrival tasks | 0.249357 | 0.170028 | 0.688665 | 1.306355 |

On arrival tasks, maximum reasoning costs about **4.05 times** the equal-ceiling
disabled control. It remains about **47% cheaper** than historical Opus on those
same inputs; the earlier disabled-K3 saving does not carry over unchanged.
Caching differs across arms despite fixed inputs and interleaving: observed
cached-input fractions across all roles are approximately 77.7% (off-original),
68.6% (off-8192) and 46.9% (max-8192). Cost ratios therefore include cache effects;
they must not be attributed entirely to effort. Historical Opus uses a different
protocol, serving time and cache state.

| Cohort | Median seconds, off-original | off-8192 | max-8192 | Maximum arm p95 seconds |
|---|---:|---:|---:|---:|
| Memory | 7.56 | 8.08 | 25.05 | 98.44 |
| Current-state tasks | 8.06 | 8.90 | 20.66 | 41.47 |
| Positive arrival tasks | 13.24 | 11.77 | 51.97 | 102.29 |

All 60 maximum-effort responses report positive reasoning use: 63,756 tokens in
total, split 22,509 memory / 10,027 current-state tasks / 31,220 arrival tasks.
All 120 disabled responses report zero. All 180 responses pass completion checks;
none reaches its output ceiling or ends because of length. The largest maximum-
effort response uses 7,134 of 8,192 total output tokens, including reasoning.

Exact receipts sum to **USD3.21907330**. Per-call upward rounding to microdollars
produces **USD3.219159** settled in the ledger. The two unresolved initial404
attempts retain **USD0.358544**, giving **USD3.577703** accounted exposure against
the USD10 cap. No hold was released to make the experiment fit.

## Historical reference and uncertainty

On these exact selected inputs, canonical historical Opus semantic counts are
8 acceptable / 9 unacceptable / 3 indeterminate for memory, 15/5/0 for current-
state tasks and 16/4/0 for arrivals. These are reference labels, not truth or a
contemporaneous control. On determinate arrival pairs, maximum K3 has zero wins,
three losses, twelve joint passes and four joint failures versus that reference;
one pair is excluded as indeterminate.

An independent blinded cross-group consistency review changed one new maximum-
reasoning arrival answer from acceptable to indeterminate: the source requests
cappuccino flavour but never establishes milk ingredients, so an unconditional
milk-policy refusal rests on an unresolved premise. The initial judgment and
adjudication are both archived; all three new variants were reviewed under the
same rule, without revealing their arm identities. The historical Opus answer
shares that uncertain premise. Leaving its canonical archive intact, applying
the same sensitivity gives **15 acceptable / 4 unacceptable / 1 indeterminate**.
The determinate paired result above is unchanged. Other ambiguities include
conflicting automated-order instructions and an unclear sample/shipping price.

Every arm has one generation per input, on exposed cases from one company.
No disabled output hits its ceiling, so differences between the two disabled
arms do not demonstrate that a larger output allowance improves reasoning;
sampling and serving variability remain explanations. There are 37 business
clusters, not 180 independent examples. These results justify rejecting a global
promotion, not estimating production error rates or proving equivalence.

## Validation and evidence

The evaluation transport and runner changes pass 330 relevant engine tests and
Ruff. Independent review verifies all 180 unique Chat generations, exact source
bindings and arm controls, provider identity, receipts and reservations. Final
aggregation verifies coverage, canonical grades, contract/parser distinctions,
paired denominators and exact historical subsets. The two compatibility answers
appear once in the 180-cell total. Source-based grading includes a separate blind
cross-group consistency review; it is not a human-certified gold standard.

Private `summary.json`, canonical grades, adjudication, manifests, wire requests,
raw responses, source mappings, execution code and reproduction helpers preserve
the evidence outside Git. The public report contains no mailbox credentials or
raw customer correspondence.

## Deployment boundary

This is an evaluation-only opt-in transport. No engine/provider defaults, saved
models, trained prompts, billing-server behavior or GUI controls change. The four
Café124 accounts remain paused on their pinned release. Any production adoption
must separately carry the proven transport, bounded accounting and relevant
quality limitations; passing an HTTP compatibility probe alone is insufficient.
