# K3 reasoning and output-budget comparison

Status: inference complete; grades revised after confirmed reviewer errors.
The original quality recommendation and failure examples are withdrawn. Revised
labels below are post-hoc calibration, not independent business-quality validation.
See the [correction and concrete evidence](2026-09-16-grading-correction.md).

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
reference, using the revised labels and explicit indeterminate cases; they are not a
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
remain indeterminate where appropriate. Source-contradicted actions, internal-entity exclusion violations and missed
operative actions are task failures. An unverified business fact is not thereby
false. Later CTO evidence and full-input review revise initial judgments uniformly
across arms; the correction is recorded separately from the frozen model inputs.

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

## Revised results and interpretation

All 180 Chat generations returned and were graded exactly once. Subsequent review
corrected business-fact penalties, overlooked supplied instructions, and the
conflation of unverified explanations with operational failures. The original
claim that maximum reasoning introduced five consequential arrival errors is
withdrawn: the revised equal-ceiling comparison has two corrections, one new
source-contradicted workflow error and four indeterminate pairs.

The CTO confirms 12-month ambient shelf life and cans-only cold-brew production.
These are accurate company facts. The model's Brazil/private-label distinction
also follows the FAQ already present in its input. Neither should have been
presented as an invented business fact. These grading errors affect multiple
arms and historical models, not only maximum K3.

All 20 planned requests remain in each cohort. `Usable` is the conservative
conjunction of acceptable whole-response judgment, acceptable independent
contract and parser acceptance. It is not the number of correct task decisions:
a correct no-action with an unverified payment explanation remains indeterminate
as a whole response, even though its operational decision is acceptable.

| Cohort | Arm | Acceptable | Unacceptable | Indeterminate | Parser accepted | Usable |
|---|---|---:|---:|---:|---:|---:|
| Memory | off-original | 10 | 7 | 3 | 17 | 9 |
| Memory | off-8192 | 9 | 8 | 3 | 18 | 9 |
| Memory | max-8192 | 14 | 2 | 4 | 16 | 11 |
| Current-state tasks | off-original | 17 | 2 | 1 | 20 | 17 |
| Current-state tasks | off-8192 | 14 | 6 | 0 | 20 | 11 |
| Current-state tasks | max-8192 | 18 | 1 | 1 | 20 | 18 |
| Positive arrival tasks | off-original | 10 | 8 | 2 | 20 | 10 |
| Positive arrival tasks | off-8192 | 16 | 3 | 1 | 20 | 16 |
| Positive arrival tasks | max-8192 | 15 | 2 | 3 | 20 | 15 |

Paired outcomes exclude a pair if either whole-response judgment is indeterminate.
Counts can therefore differ from subtraction of marginal acceptable totals.

| max-8192 versus off-8192 | Corrected failures | New failures | Both acceptable | Both unacceptable | Indeterminate pairs |
|---|---:|---:|---:|---:|---:|
| Memory | 6 | 1 | 8 | 1 | 4 |
| Current-state tasks | 5 | 0 | 13 | 1 | 1 |
| Positive arrival tasks | 2 | 1 | 12 | 1 | 4 |

Memory remains 14/20 semantically acceptable at maximum effort, but only 11/20
passes semantics, contract and parser together; either disabled arm has 9/20
usable. Current-state tasks have 18/20 acceptable at maximum effort versus 17/20
with original disabled ceilings. Correct no-action decisions with uncertain
payment explanations are disclosed separately, not described as financial or
task failures.

Two defensible arrival-task problems remain in the maximum arm:

- A concrete follow-up supplies named products after the owner explicitly offers
  founder review of payment terms. The output dismisses it as a scam and returns
  no action, contrary to the operative thread and the narrow generic-spam rule.
  Whether the correspondent actually is fraudulent is unknown.
- The owner says applying labels in Paris avoids delays from supplier-side label
  production/application. The output calls supplier-side printing/application
  the fastest route, reversing the supplied workflow comparison. Who should add
  mandatory artwork text is a separate unknown, not a proven false assertion.

Maximum effort also fixes genuine errors: it creates the pending NDA-review task
and creates a new meeting-invitation task instead of updating a nonexistent task.
The earlier shelf-life, glass and payment examples are not evidence of new
operational failures; the correction note preserves their exact distinctions.

These revised labels do not establish that K3 is commercially unreliable or that
maximum effort is generally worse. They also do not establish equivalence or an
automatic replacement. Model selection needs a company-validated fact reference,
explicit instruction precedence and a representative memory-enabled evaluation
before another independent confirmation. No production configuration changes.

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

## Revised historical reference and uncertainty

The historical comparator is corrected under the same business-fact and
uncertainty rules. On the exact selected 20 inputs per cohort, Opus is8 acceptable /
9 unacceptable / 3 indeterminate for memory, 15/4/1 for current-state tasks and
17/1/2 for arrivals. Maximum K3 versus historical Opus on arrivals has zero wins,
one loss, 15 joint passes,one joint failure and 3 indeterminate pairs. This is a
historical comparison under different transport/cache conditions, not a fresh
control or human-certified ground truth.

The [correction note](2026-09-16-grading-correction.md) distinguishes initial
reviewer mistakes from new authoritative CTO evidence. Old labels, revised
labels, captured input hashes and rationales are retained. Inputs, responses,
prices and clocks are unchanged; no answer was regenerated to improve a score.

The 20 arrival replays deliberately contain no retrieved company-memory snippets,
existing tasks or calendar context. They do include the saved trained task prompt
and owner instructions, including learned product facts. All 40 original heldout
task requests contain retrieved memory snippets. A cold-start arrival replay is
not a measurement of the complete live memory-enabled product.

Every arm has one generation per input, on exposed cases from one company.
No disabled output hits its ceiling, so differences between disabled arms do
not demonstrate an output-budget effect. Sampling, serving and grader variability
remain explanations. There are 37 business clusters, not 180 independent examples.
Post-hoc repaired labels are calibration evidence, not production error rates.

## Validation and evidence

The evaluation transport and runner changes pass 330 relevant engine tests and
Ruff. Independent review verifies all 180 unique Chat generations, exact source
bindings and arm controls, provider identity, receipts and reservations. Final
aggregation verifies coverage, canonical grades, contract/parser distinctions,
paired denominators and exact historical subsets. The two compatibility answers
appear once in the 180-cell total. Initial blind grading and cross-group review missed substantive errors in the
evaluation itself. The later full-input and CTO-evidence correction is explicit;
passing code tests and arithmetic review does not validate business judgments.

The [sanitized table snapshot](2026-09-16-k3-reasoning-quality-tables.json)
contains the revised aggregate counts. Private `summary.json`, canonical grades,
adjudication, manifests, wire requests,
raw responses, source mappings, execution code and reproduction helpers preserve
the evidence outside Git. The public report contains no mailbox credentials or
raw customer correspondence.

## Deployment boundary

This is an evaluation-only opt-in transport. No engine/provider defaults, saved
models, trained prompts, billing-server behavior or GUI controls change. The four
Café124 accounts remain paused on their pinned release. Any production adoption
must separately carry the proven transport, bounded accounting and relevant
quality limitations; passing an HTTP compatibility probe alone is insufficient.
