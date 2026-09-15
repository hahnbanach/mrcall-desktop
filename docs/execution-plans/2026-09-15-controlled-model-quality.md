---
status: completed
---
# Controlled model quality delivery

Brief: [controlled comparison](../briefs/2026-09-15-controlled-model-quality.md).

## Frozen design before inference

- 50 distinct real threads: 10 development (including the three already exposed),
  40 held-out. Original memory and task requests for Opus 5, Kimi K3, GLM 5.2:
  300 cells. Earlier outputs remain historical; old six requests also get their
  missing Opus control using their original frozen date (six additional calls).
- Strata target: 10 commercial inquiries/qualification, 10 delivery/payment/
  invoicing, 10 waiting/acknowledgement/closure, 10 corrected or multi-party
  commitments, 10 noise/routine notifications. Each stratum contributes 2 dev,
  8 held-out where source availability permits. Document any source-driven
  substitution before inference; never select based on model performance.
- Selection uses a fixed seed and recorded candidate inventory; distinct thread
  IDs and full source evidence are checked. Cover both short and long eligible
  threads and language variation present in the inventory, not only convenient
  short examples. No message truncation to obtain cheap successes. Preserve
  exact worker context, trained prompts and tools. Historical controls retain
  1024/500 output caps; the expanded comparison uses uniformly reviewed
  4096 memory / 2048 task caps for all models, as amended below.
- Preregister per-thread source-grounded facts, forbidden inferences and allowed
  task lifecycle decisions. Existing model-generated memory is context, not truth.
  A reviewer audits the rubric before outputs. A thread with contradictory owner
  instructions is explicitly marked as such, not silently scored against one.
- Fix a single memory-prompt candidate using only development evidence, before
  held-out outputs are opened. Run candidate on development first; promote to
  held-out comparison only if it removes consequential errors without new ones.
  The single memory candidate is tested on all three models: 30 development
  calls and, only if supported, 120 held-out calls. Task requests stay original
  in this experiment. Any later task/cap/wire variant requires a separately
  reviewed design and budget allocation; it is not an implicit extra arm.
- Preselect 10 threads (two per stratum) for one repeat of original requests for
  all models/roles (60 cells). Repeats estimate observed instability, not extra
  independent sample size. Freeze candidate/split/repeat manifests with hashes.
- Maximum scope: 300 original cells + 60 repeats + six historical Opus controls
  + at most six compatibility probes + at most 150 candidate memory calls =
  522 new calls. Earlier attempts remain recorded in the same ledger and their
  costs/holds count against USD20. This is a ceiling, not a spending target.
  Before dispatch, inventory actual request reservation bounds and a conservative
  expected-cost forecast, including existing settled usage and uncertain holds.

## Delivery gates and ownership

1. Brief review APPROVED. Fresh plan review before implementation/inference.
2. Dataset worker captures private source + exact requests/rubric. Routing worker
   investigates metadata and prepares a safe diagnostic harness. Root owns all
   paid dispatch and the single scratch ledger. Review data/protocol before calls.
3. Diagnose existing 429/incomplete responses using free metadata and at most
   six explicit paid compatibility probes with private error bodies. No blind
   retries. Stop an unavailable model/role after three consecutive comparable
   failures and diagnose before spending the rest of its matrix.
4. Run missing historical Opus control, then development matrix. Freeze prompt
   candidate and held-out matrix before viewing held-out model outputs. Root
   runs bounded, interleaved model scheduling, at most four concurrent calls per
   model, with atomic engine reservations and a cumulative experiment USD20 cap.
   Preserve every failure/hold and stop at cap; no resets on UTC rollover.
   Prioritize the historical control and complete original 50-thread matrix
   before spending on optional candidate calls or repeats. Original held-out
   outputs may be collected first for budget priority, but remain sealed and
   unavailable to prompt developers until the candidate is frozen. Optional
   work uses only remaining allowance; report any omitted arms explicitly.
5. Independent blinded grading partitions by thread; all model/prompt identities,
   costs and latencies masked. Report parser/schema/completion separately from
   consequential source errors and minor unsupported detail. All returned outputs
   graded, all attempts reported. Resolve rubric ambiguity without model identity.
6. Pair results by thread and role against Opus, report wins/ties/losses, error
   categories, uncertainty and repeat instability. Acceptance: no new consequential
   errors versus Opus on held-out threads, no unresolved availability/contract
   failures, and lower observed cost for that role. Any worse case rejects an
   automatic switch; an observed pass supports only a monitored pilot, never an
   equivalence or zero-error assertion. Preserve unknowns rather than impute passes.
7. Implement only supported generic fixes; independent code review and focused
   regression checks. Final separate review checks source-to-result traceability,
   cost totals, no hidden exclusions, and recommendation/configuration consistency.
   Save sanitized report and reproducible harness, reconcile docs, commit/push main.

## Boundaries

No production mail/memory/task/settings/schedule writes, no secret logging or
customer messages, no Anthropic fallback or backlog restart. Existing production
holds remain a distinct issue. The scratch cap extends the same previous USD1
ledger to USD20 for the newly authorized broader experiment; earlier settled
usage and uncertain holds count against it. Raw data is private and never Git.
Role-local availability circuit breaking can leave a matrix incomplete; report
exact coverage and reason, and do not infer semantic quality from failed calls.

## Explicit compatibility amendment before expanded inference

Instrumented GLM probe1 returned HTTP429 with DeepInfra `engine_overloaded`,
`upstream_provider_shared_pool`, and `available=1`. Free endpoint metadata shows
Baidu/Ambient under the original ceiling reject both required and named tool
selection. Changing named choice to `any` would not solve it. K3 probe2 succeeded.

Approve one additional, separately labelled GLM compatibility probe at verified
DigitalOcean prices USD0.70 input / USD2.20 output per million tokens, pinned to
that provider. Both the admission reservation rate and wire price ceiling must
increase together; all content, output caps and named mandatory tools remain
identical. Keep no automatic retries/fallbacks and the same cumulative USD20.
If supported, use this explicitly disclosed repaired GLM transport in the expanded
quality matrix; previous failed baseline attempts remain reported. This does not
alter stored production settings, deploy a release or waive future code review.
The initial comparison describes executable model/provider configurations, not
isolated model weights independent of serving infrastructure.

The dataset review also checks independent business episodes: different thread
IDs for the same order must be clustered or replaced before inference. Selection
revisions are recorded with their source-based reason, never informed by outputs.


## Explicit completion-limit amendment before expanded inference

Historical equal-input Opus control completed only three of six requests: one
memory response reached 1024 output tokens and two task responses reached 500.
These remain documented current-configuration completion failures, not semantic
errors or evidence that another model is better. Historical requests/results and
their exact caps are retained; they are not overwritten by calibration attempts.

The 50-thread matrix is a distinct calibrated-configuration arm: original prompts,
owner context, messages and task tool contract, but the SAME larger output caps
for Opus, K3 and GLM: memory 4096 and tasks 2048. Freeze new request hashes and
label this distinction in manifests and results. Apply these caps consistently to
original/candidate/repeat comparisons so a model never receives extra answer
space relative to its comparator. No runtime production limits change here.

Use already allocated diagnostic slots 4 and 5 for explicitly labelled Opus
calibration on the historically truncated second memory case and second task
case, respectively, with those larger caps. They remain within six total probes
and the same USD20 ledger including prior holds. Recompute exact admission bounds
and the conservative expected-cost forecast for all mandatory expanded cells
before paid matrix execution; optional candidate/repeats cannot displace the
original 50-thread comparison. Larger maximum reservations are not assumed actual
costs, and no estimated completion savings may bypass the real admission guard.

If either calibration still truncates, inspect its stop reason/usage and review a
new common cap or scope amendment BEFORE launching the expanded matrix. At most
the sixth diagnostic slot remains; do not loop, silently retry, change a cap for
one model, release uncertain holds, or expand the cumulative allowance. Keep
current-configuration reliability and calibrated-model quality verdicts separate.

## Historical arrival replay supplement — reviewed before capture

Current additional account inventories lack saved trained task prompts and do not
supply twenty independent, currently actionable positive episodes. Do not invent
a trained fallback or describe retrospective cases as today's pending workload.
Instead, add twenty historical arrival replays from the existing production
mail corpus, using its actual saved task prompt and worker prompt construction.
This is a separately labelled cold-start task-ability supplement.

Each case ends at a real external actionable request before the owner's reply.
Keep source text and timestamps unchanged; freeze evaluation time at that incoming
timestamp plus one minute with consistent timezone normalization. Both the worker
builder's date and the LLM adapter's datetime injection use that frozen time.
Include only the chronological thread prefix available then. Existing tasks,
retrieved company memory and calendar context are explicitly empty; no later
reply or live context may leak into the replay. Saved trained prompts and owner
rules are current policy applied retrospectively, not claimed historical policy.

Source reviewers verify that this current policy permits the proposed action:
form notifications explicitly marked NO ACTION cannot manufacture positive cases.
Preregister required/forbidden decisions using only the visible source prefix.
Do not use subsequent replies as rubric evidence. With an empty task store,
there is no valid target for closing or updating an existing task. A task to
change a business order is still a newly created task, not an invented task ID.

All three models receive the same twenty frozen task cases with 2048 output
tokens: sixty additional cells. Review source/rubrics and verify both clocks
before any paid supplement dispatch. Cluster business-episode overlap with the
base fifty and within the supplement; report independent episode counts rather
than claiming seventy independent threads. Selection uses source evidence only,
without reading model outputs.

The maximum becomes 582 new calls (previous ceiling 522 plus 60 replay cells),
not a spending target. The unchanged cumulative USD20 includes all earlier usage
and uncertain holds. After completing the original fifty-thread matrix, prioritize
this positive-task supplement before optional prompt candidates or repeats.
Recompute its exact reservation bounds and cost forecast against remaining
allowance before execution. No production writes, prompt/model replacements,
backlog restart or release deployment follow from this supplemental experiment.

## Dispatch observations and completion handling

All six historical Opus controls were attempted. Original caps truncated three
responses; reviewed calibration completed at 1327 memory output tokens and 549
task output tokens under uniform 4096/2048 evaluation caps. Probe3 at the reviewed
GLM DigitalOcean ceiling returned a mandatory tool response. Probe count is five.

The reviewed base manifests freeze 60 development cells and 240 held-out cells.
Preflight sum of conservative reservation bounds is USD55.968442, not permission
to spend that amount; admission remains individually atomic under USD20. A
planning forecast (JSON chars/3 input tokens, 1500/900 role output tokens, 2x Opus
input allowance) is USD17.629585 including prior liabilities. It is not an upper
bound or a promise that every optional cell fits; actual settlement frees holds.

Development returned 57 of 60 planned responses; three remaining GLM task cells
were skipped by the completion circuit. Three returned GLM task responses were
ordinary NO_ACTION text despite mandatory tool choice. Private body inspection
identifies a prompt/tool-contract issue, not an upstream outage. Held-out uses
new unique requests (no retries), and its unchanged-request results are retained
to measure this failure across cases. Completion and contract failures remain
visible; no plain text is silently converted into a successful task decision.
Held-out raw content remains sealed from prompt developers.

## Reviewed implementation and grading progress

- Candidate `memory-grounding-v1` frozen from development-only grades and
  independently approved before held-out semantic access. Its source patch SHA256
  is `59bf60581e34225bf0aa7526fa83714414377fb8637614ebabe7b01d15908a81`.
  Candidate held-out dispatch remains conditional on development results.
- Runner safety review and 16 tests pass, including actual SQLite reservation
  equality, request-clock isolation, durable intents and concurrency limits.
- Scoped completion-cap milestone approved: only both email memory extraction
  paths and task detection change to named 4096/2048 ceilings. Forty-two focused
  tests cover complete long output and rejected truncation/checkpoint behavior.
  No model/prompt/profile deployment or other worker-cap expansion is included.
- Three independent blinded grading partitions retain stable labels across
  incremental inference. Post-freeze source-only adjudication may corroborate
  supplied memory against original cross-profile mail; keep initial grades and
  supplemental evidence hashes without modifying frozen requests or candidate.
- Operational aggregation reconciles every phase with the ledger. Semantic
  aggregation distinguishes missing responses, ungraded responses, indeterminate
  cases, both-pass/both-fail pairs, and task-disposition/stratum denominators.
  A usable response after explicit gateway recovery is not first-attempt success.

## Bounded provider recovery amendment

Independent review approved exactly eight additional base calls: four K3 calls
with no generated output (three provider shared-pool HTTP429 errors with explicit
retry delay, one provider internal error) and four cells never dispatched after
the task availability circuit opened. Freeze their provenance, response hashes
and unchanged request identity before dispatch. Wait at least 120 seconds, use
global concurrency one, retain every uncertain hold and the cumulative USD20
cap. No completed, malformed or truncated model answer is eligible. These calls
remain separate operational attempts; this approval does not extend to later
arrival-cohort failures or another recovery of the same cell.

## K3 serving and completion compatibility amendment

Repeated Makora shared-pool errors persisted at global concurrency one. The final
sixth diagnostic used an independently reviewed DigitalOcean pin at the existing
K3 price ceilings; current endpoint metadata supports forced functions. It
returned HTTP200 and a valid task tool block, but labelled the complete response
`end_turn` rather than `tool_use`. That is a frozen-parser completion failure,
not missing inference or an excuse to regenerate the answer.

The previous unused eight-cell recovery manifest is superseded, subject to independent manifest review, by exact
DigitalOcean manifests: ten remaining base cells and eighteen arrival cells with
no model-produced response. The diagnostic itself supplies the eleventh missing
base answer, explicitly imported for grading without inventing another paid
intent; its cost stays in the diagnostic ledger category. Preserve every old
attempt, raw stop reason and uncertain hold. Both input and output price ceilings,
content, tools and clocks remain unchanged. Use global concurrency one and the
same cumulative cap. Any protocol normalization is a separate source milestone
with separate counterfactual usability results; it cannot overwrite frozen grades.

## Protocol normalization milestone

Independent review approved a source-only OpenRouter compatibility fix. Expose
`tool_use` for a complete `end_turn` response only when tool invocation blocks
are fully formed (nonempty string IDs/names and object inputs), all such blocks
are valid and no refusal/malformed blocks are present. Preserve the original
stop reason and raw response. Truncation, refusal and every other stop reason
remain unchanged; no retry, provider/model switch or profile migration is added.

Before adopting the fix in offline replay, preserve a frozen parser mode and
record normalization source hashes. A regression must prove that original
`end_turn` plus valid-tool output still fails the frozen parser after the live
adapter improves. Counterfactual repaired-parser usability is reported separately
and cannot alter original semantic/contract grades. Integration review and focused
malformed/truncated/refused/complete response tests precede completion.

Repeated originals intentionally retain their original routing policy, including
K3's price-sorted provider choice. The DigitalOcean amendment applies only to
explicitly enumerated missing cells and the sixth diagnostic. Candidate memory
calls also preserve original routing for the development comparison. Provider
outages in repeats remain operational failures, not semantic stability evidence.

## Completion

All 360 main responses are collected and graded with source-bound, blinded
rubrics. Candidate coverage is 20/30 (plus 30 regraded original controls), and
repeat coverage is 50/60; missing outputs and operational failures remain explicit.
No candidate held-out promotion or automatic model replacement passes the full
gate. The [final report](../evaluations/2026-09-15-controlled-model-quality.md)
contains paired quality, cost, compatibility replay and repeatability outcomes.

Source changes comprise named email/task ceilings, guarded complete-tool response
normalization, and the bounded/offline evaluation tools. Independent reviews
approve these milestones, all main grade bindings, immutable baseline replay and
final spending reconciliation. The combined affected suites pass 281 tests.
Settled cost is USD13.473667, with USD3.963280 retained in uncertain holds against
the same cumulative USD20 cap. No additional paid inference remains necessary.
No hosted release, model, saved prompt or processing state changes are included.
