# Complete selected-case source review — Opus and K3

**Status: post-hoc review of all 60 selected cases and all 240 outputs.**
There are 37 distinct business clusters, three K3 arms and historical Opus.
This replaces the earlier semantic interpretation for this selected comparison.
It does not regrade the entire earlier 360-output study or GLM, and is not a new
blinded holdout. Original responses, numerical snapshots and costs are preserved.

## What is being judged

- **Task decision:** whether the requested create/update/no-action follows the
  supplied context and policy. It includes invalid task targets, not just the
  correct natural-language intention.
- **Source/policy adequacy:** whether the whole output respects supplied facts,
  explicit instructions and known business constraints. An unverified explanation
  can make this indeterminate while its task decision is acceptable.
- **Integration:** captured parser acceptance and independent task-schema checks.
  These do not establish truth; parser acceptance can still discard malformed
  entity blocks.

A/U/I below means acceptable / unacceptable / indeterminate. These are review
judgments, not observed real-world error probabilities. An explicit policy breach
is not automatically a commercially harmful action or a false business fact.
Unknown facts are not classified as false. Later owner evidence is recorded
separately from original model inputs.

## Task decisions, all 20 cases per cohort

| Arm | Current-state tasks A/U/I | Arrival tasks A/U/I |
|---|---:|---:|
| Historical Opus | 15/3/2 | 19/0/1 |
| K3 off, original ceiling | 17/2/1 | 17/2/1 |
| K3 off, 8192 | 15/2/3 | 17/2/1 |
| K3 max, 8192 | 19/0/1 | 19/0/1 |

Opus and maximum K3 make acceptable task decisions on the same 19 arrival
cases; SCASO remains indeterminate for both. This does not certify every sentence
in their proposed replies. Maximum K3 makes more unverified explanatory assertions
in this sample. Current-state Opus failures include explicit old-email/own-sent
policy violations; they do not prove that reconnecting with those leads would be
commercially harmful. The automated-form policy conflict remains explicit.

## Whole source/policy adequacy, all 20 cases per cohort

| Arm | Memory A/U/I | Current-state A/U/I | Arrival A/U/I |
|---|---:|---:|---:|
| Historical Opus | 9/7/4 | 14/3/3 | 17/1/2 |
| K3 off, original ceiling | 11/4/5 | 16/2/2 | 10/2/8 |
| K3 off, 8192 | 8/7/5 | 13/2/5 | 14/2/4 |
| K3 max, 8192 | 14/1/5 | 18/0/2 | 14/0/6 |

Four memory cases have unresolved Shopify-notification extraction policy.
Domain-derived company/order association is another uncertainty, not a proven
false identity. Memory instruction failures include extracting excluded internal
colleagues and learning a reusable style without the required repeated examples.

## Concrete errors and non-errors

| Case | Captured source or constraint | Observed output | Assessment and comparator |
|---|---|---|---|
| Mancini follow-up | Latest customer asks “giusto?” after the prior brochure | K3 off-original returns “No action needed - Riccardo already responded with detailed product info” | Drops the newer question. K3 off-8192, max and Opus create the reply task. Catalogue naming disagreement is not the asserted failure. |
| Renato meeting | Customer proposes “mercoledì 1 alle 10:30”; no existing task supplied | K3 off-8192 selects `update`, provides no target, says “Non creare nuovo task separato.” | Invalid lifecycle operation cannot persist the needed task in this empty context. Opus and max create it. |
| NDA follow-up | “Se per voi è tutto in ordine, siamo pronti a procedere.” | K3 off-8192 returns no action because no urgent intervention is required | Recipient review is still needed. Low urgency can be true; it does not remove the obligation. Opus and max create review/confirmation work. |
| Stow memory | STYLE requires 3+ Ivan replies; captured source is one Riccardo reply | K3 max emits “Entity type: STYLE” / “Production inquiry reply — white label vs private label options” | Unjustified reusable style extraction. Opus does not add that style, but extracts excluded internal Riccardo; neither is wholly clean on this case. Commercial prices and ambient shelf life are not the error. |
| Rod shipment memory | Shared-company instruction excludes its people from external contacts | Opus emits a PERSON for “Giada”, “Company: Café 124” | Explicit own-company exclusion violated. K3 max excludes Giada but derives a company/order association from the sender domain, which remains unverified rather than proven false. |
| Cappuccino reply | Later exact-project owner note says “non facciamo cappuccino”; supplied policy forbids MOQ/price detail when declining | K3 off-original advances pricing, cost inclusions and timing; Opus proposes a decline/alternative with “white label da 600 lattine” | Off-original handling conflicts with established intended refusal. Opus has the right task disposition but violates the no-MOQ instruction. Unknown milk ingredients, costs and actual timing are not declared false. |

The complete private inventory contains every adverse and uncertain finding,
the exact output and source quotations, the review rationale and peer corrections.
These examples are not a substitute for the full 240-output review.

Withdrawn allegations remain withdrawn: 12-month ambient shelf life and cans-only
cold brew are confirmed company facts. Dominique’s ready artwork/preference makes
the old “workflow reversal” claim unsound; fastest route and designer responsibility
remain unknown. Payment processor wording does not prove paid or unpaid. SCASO
has a later internal intention to block the same sender, without independently
proving fraud or human authorship. See the [detailed disputed cases](2026-09-16-disputed-case-review.md).

## Integration defects are separate

| Arm | Memory parser accepted /20 | Current task schema without recorded violations /20 | Arrival task schema without recorded violations /20 |
|---|---:|---:|---:|
| Historical Opus | 20 | 20 | 20 |
| K3 off, original ceiling | 17 | 20 | 20 |
| K3 off, 8192 | 18 | 17 | 19 |
| K3 max, 8192 | 16 | 20 | 20 |

All captured task outputs passed the current parser, including Renato’s invalid
update, which the independent schema/lifecycle check rejects. Three current-task
off-8192 responses have too-short `suggested_action` values despite adequate
semantic decisions. These are additional integration failures, not rewritten
semantic labels.

The saved memory prompt simultaneously asks for flat FACT records without
sections and shows a header-based FACT format. The engine extraction parser
requires `#IDENTIFIERS`. Following one of our contradictory instructions can
therefore lose facts or fail integration. The model must not be blamed for an
invented business fact merely because this serialization contract is broken.
The recorded parser results above are unchanged; this review does not repair or
deploy that runtime path.

## Observed costs for the same selected inputs

| 20 requests | K3 off original | K3 off 8192 | K3 max 8192 | Historical Opus |
|---|---:|---:|---:|---:|
| Memory | $0.1290 | $0.2241 | $0.5412 | $1.2852 |
| Current-state tasks | $0.2730 | $0.3423 | $0.6014 | $1.9217 |
| Arrival tasks | $0.2494 | $0.1700 | $0.6887 | $1.3064 |

Maximum K3 costs approximately 58% less for memory, 69% less for current-state
tasks and 47% less for arrival tasks than these historical Opus responses.
On arrival tasks, maximum K3 costs about four times the equal-ceiling disabled
arm. Cache-hit rates, transport/provider and serving time differ; these are
observed bills, not normalized price promises. Arrival median latency is 51.965s
for maximum K3 versus 11.765s for off-8192 and 6.49s for historical Opus.
No paid requests were made during this source review.

## Reproduction and limits

The private directory is
`~/.local/share/mrcall/evaluations/2026-09-16-k3-reasoning/evidence-repair/comparative-review/`.
It contains all 60 complete cases, 240 original outputs, per-role first-pass
reviews, explicit peer-review overlays and `consolidated-review.json`.
Each case’s four semantic input hashes match. Full shared system/tool sections
are retained; compact views use explicit hashed references rather than dropping
context. Original grades are not overwritten. Exact quotation validation checks
traceability, not reviewer comprehension or real-world truth.

The new offline grading code additionally creates per-label evidence bundles,
validates version 2 quote/coverage bindings, separates four review dimensions
and requires actual parser acceptance for usable counts. Nine focused reviews
exercise that complete version 2 contract. The full comparative source review
above retains its separate documented review schema and peer adjudications;
it is not silently relabeled as 240 version 2 validations.

These are exposed diagnostic cases with one captured generation per arm/case,
not independent business outcomes or a population error estimate. No Haiku
comparison is made. GLM and unselected historical cases are not newly regraded.
Maximum K3 is promising for task disposition in this sample; uncertainty in
draft assertions and the memory integration defect still prevent a claim of
equivalence or a general unattended-rollout guarantee. Production remains unchanged.
