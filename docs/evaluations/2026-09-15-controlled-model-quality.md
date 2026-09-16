# Controlled engine model comparison

Current selected-case interpretation: [complete 60-case / 240-output source review](2026-09-16-reviewed-model-comparison.md).
The historical tables below remain unchanged; unselected historical outputs and GLM
are not newly regraded.

Status: all 360 main responses present. Categorical semantic scores and paired
quality conclusions are superseded pending full evidence-based regrading.
Tables remain historical snapshots, **not counts of proven decision errors**.
Exhaustive regrading is not complete; no replacement scores are asserted.
The original model-selection recommendation is withdrawn. See the
[disputed-case review](2026-09-16-disputed-case-review.md) and
[earlier grading correction](2026-09-16-grading-correction.md).

This study concerns engine API calls for email memory extraction and task
detection. It does not evaluate the separately authenticated headless operator.

## Interpretation after grading correction

The original recommendation to retain Opus for task quality overstates what this
experiment establishes. Initial graders penalized correct company facts and
misapplied supplied instructions. The earlier revisions did not resolve all grading defects. Tables preserve
whole-response labels whose factual and operational interpretation is disputed;
they are not a validated production error-rate or model-equivalence estimate. No production model is promoted or rejected solely
on these counts; company-validated reference facts and representative retrieval
must precede an independent confirmation.

K3 and GLM are cheaper in the recorded serving conditions. Memory extraction,
positive task creation, output contracts and retrieval need separate assessment.
The supplied source improvements (completion ceilings, guarded normalization and
bounded evaluation tooling) remain independently tested. Haiku and Sonnet were
not evaluated in this comparison. The memory-prompt candidate is not promoted.

## Main quality results

Each entry is **acceptable / unacceptable / indeterminate**. All planned main
responses are present; indeterminate means conflicting instructions or unresolved
evidence, not a missing output. A response passes only if it contains required
operative information and no consequential error. These are whole-response
judgments, not the fraction of individual facts that are wrong.

| Model | Held-out memory, 40 | Held-out current-state tasks, 40 | Historical positive tasks, 20 |
|---|---:|---:|---:|
| Opus 5 | 20 / 17 / 3 | 29 / 8 / 3 | 17 / 1 / 2 |
| Kimi K3 | 26 / 10 / 4 | 30 / 7 / 3 | 15 / 4 / 1 |
| GLM 5.2 | 23 / 13 / 4 | 32 / 5 / 3 | 11 / 7 / 2 |

The current-state task cohort often legitimately requires no new action. Judging
only that cohort would omit arrival-time behavior; the archived labels do not
establish how many cheaper-model actions were actually incorrect.
The separate positive cohort is deliberately enriched and must not be pooled
with current-state tasks to estimate a natural mailbox error rate.

Paired semantic comparison against Opus, excluding pairs with either verdict
indeterminate:

| Role/cohort | Model | Wins | Losses | Both pass | Both fail | Indeterminate pairs |
|---|---|---:|---:|---:|---:|---:|
| Memory | Kimi K3 | 6 | 1 | 19 | 9 | 5 |
| Memory | GLM 5.2 | 5 | 3 | 17 | 10 | 5 |
| Current-state tasks | Kimi K3 | 3 | 2 | 26 | 5 | 4 |
| Current-state tasks | GLM 5.2 | 3 | 0 | 27 | 5 | 5 |
| Positive arrival tasks | Kimi K3 | 0 | 3 | 14 | 1 | 2 |
| Positive arrival tasks | GLM 5.2 | 0 | 6 | 9 | 1 | 4 |

The archived failure categories include allegations of violating explicit owner/contact exclusions, converting
one-off quantities into minimum quantities, assigning prices to different products,
learning STYLE from insufficient examples, and missing a pending action or
contradicting the source workflow. A correct no-action with an unverified payment
or shipment explanation is indeterminate as a whole response, not demonstrated
nonpayment, nonshipment or wrong task handling. Unsupported durable memory writes
remain a separate extraction-contract concern; factual truth and source grounding
must not be conflated.

## Design and limits

The frozen base contains 50 distinct business episodes, with two role requests
per episode: 10 development and 40 held-out. Five source-based strata each
contribute ten episodes. Exact captured worker inputs are compared across
Anthropic Opus 5, Kimi K3 and GLM 5.2, through OpenRouter. Opus is a comparator,
not a source of ground truth. Source messages and owner instructions determine
the rubric. Old generated memory is context, not verified evidence by itself.
After the freeze, a blinded source-only adjudication checked a later update
against original messages from another company mailbox. It corroborated facts
already supplied in shared memory; those outputs were not hallucinations. The
supplemental evidence and initial/revised grades are preserved separately.
Frozen requests, case selection and candidate prompts were not changed.
A separate blinded policy adjudication identified a conflict between ignoring
automated notifications and retaining substantive customer/order information.
Abstentions on automated customer-order memory are therefore indeterminate,
uniformly across platforms and models. Later payment/task adjudication separates
unverified explanatory claims from operationally correct no-action decisions.
Initial grades and the exact conflicting instructions are retained privately.

The current-state base contains only three clear positive task cases. Therefore
a separate cohort reconstructs 20 real incoming requests at their arrival time,
before later responses or completed work can conceal the need for action. Both
the prompt builder and transport clock use that historical time. Current trained
owner policies are applied retrospectively. Ten episodes overlap the base;
the combined data contains 60 episode clusters, not 70 independent observations.
The arrival cohort measures creation from an empty task context, not update or
closure accuracy.

Development-only evidence produced one frozen memory candidate before held-out
outputs were opened. Its changes repair the FACT envelope contradiction and
add source attribution, owner exclusion, scoped business terms, lifecycle and
STYLE evidence instructions. All owner business policies remain intact. The
candidate must pass its development comparison before any held-out candidate
calls. Original task prompts remain unchanged throughout this experiment.

Eligibility and strata were chosen from source evidence before seeded within-stratum
selection. Two long-input cases were deliberately included before inference.
This is a stratified evaluation from one business with correlated communication
patterns, not an IID sample of all customers. Repeated outputs do not increase
the number of independent episodes. No observed result proves zero errors or
model equivalence.

## Reasoning configuration clarification (2026-09-16)

The original OpenRouter adapter explicitly sends `thinking: disabled` for all
models. K3's advertised default effort therefore did not apply. Reconstruction
of all 20 arrival wire hashes confirms this setting, and their reported thinking
token counts are zero. These results compare the engine's non-thinking request
configuration, not maximum-effort K3. The
[explicit reasoning experiment](../execution-plans/2026-09-16-k3-reasoning-quality.md)
is a separate controlled comparison; its results must not be inferred from this
report's quality or cost figures.

## Serving conditions and diagnosed failures

Historical equal-input Opus controls retained the actual 1024-token memory and
500-token task ceilings. Three of six responses truncated: one memory and two
task responses. Two explicit calibration calls completed at 4096/2048 ceilings.
All three models use those same expanded role ceilings in the main comparison.
The historical failures remain completion failures, not semantic grades.

GLM routing under the original price ceiling selected an overloaded DeepInfra
endpoint. The reviewed comparison pins GLM to DigitalOcean at USD0.70 input and
USD2.20 output per million tokens, supporting the required named task tool.
This is an explicitly changed serving configuration, not evidence isolating
model weights from provider infrastructure.

K3's original price-sorted routing repeatedly encountered provider shared-pool
failures. Its sixth compatibility diagnostic and 28 exact missing-response
recoveries use DigitalOcean, at unchanged ceilings of USD2.648138063 input and
USD13.28272425 output per million tokens. The base includes that one diagnostic
response plus ten recoveries; arrivals include eighteen recoveries. The diagnostic
is imported for grading without another paid call. Every original error and
uncertain hold remains recorded; no cell with a model-produced answer is retried
for a better grade. K3 candidate and repeat arms retain original routing. Main
quality and latency therefore describe these repaired serving conditions, not
an unchanged first-attempt route or a controlled isolation of model weights.

An early concurrent batch received 21 OpenRouter HTTP402 pre-dispatch admission
errors. Raw error metadata identifies in-flight credit exhaustion, attempt zero,
and no selected provider. These attempts remain in operational results. Each
has one explicitly authorized recovery, with identical input and lower global
concurrency; completed but incorrect answers are never retried for a better grade.

A separate reviewed reconciliation settled those 21 demonstrably unbilled errors
at zero, releasing USD5.223035 of reserved allowance. Exact response hashes,
reservation bindings and settlement receipts are retained privately. Older
uncertain holds of USD0.318187 remain charged against the same cumulative USD20
experiment ceiling. This is not a budget reset. OpenRouter documents zero-output
inference charge waivers; auxiliary charges are excluded from that guarantee,
and these requests used no auxiliary services. See its
[zero-completion policy](https://openrouter.ai/docs/guides/features/zero-completion-insurance).

## Cost and response latency

Observed provider cost for the selected first model-produced response per cell,
including cache effects; these figures exclude earlier transport failures,
diagnostics and optional arms. They are empirical sample costs, not list-price
quotes or forecasts of an entire mailbox. Latencies cover the successful HTTP
attempt only, excluding time lost to outages and recovery scheduling.

| Role/cohort | Model | Total USD | Mean USD/request | Median / p95 seconds |
|---|---|---:|---:|---:|
| Memory, held-out | Opus | 2.489835 | 0.062246 | 5.81 / 26.04 |
| Memory, held-out | K3 | 0.515217 | 0.012880 | 8.84 / 75.73 |
| Memory, held-out | GLM | 0.129716 | 0.003243 | 16.01 / 77.67 |
| Tasks, current state | Opus | 3.591035 | 0.089776 | 4.28 / 7.81 |
| Tasks, current state | K3 | 0.867378 | 0.021684 | 10.14 / 38.97 |
| Tasks, current state | GLM | 0.200168 | 0.005004 | 18.02 / 56.55 |
| Tasks, positive arrivals | Opus | 1.306355 | 0.065318 | 6.49 / 8.88 |
| Tasks, positive arrivals | K3 | 0.289977 | 0.014499 | 15.86 / 31.27 |
| Tasks, positive arrivals | GLM | 0.045626 | 0.002281 | 18.78 / 57.58 |

K3 costs about 79% less for held-out memory and 76–78% less for tasks in these
serving conditions. GLM costs about 94–97% less. The historical positive-task labels are superseded. These labels
are not independently validated business-quality estimates. None of these percentages includes the cost of human
correction or downstream mistakes.

The cumulative isolated experiment ledger, including earlier tests, controls,
probes, failed attempts and optional arms, records **USD13.473667 settled plus
USD3.963280 still reserved**, a conservative **USD17.436947** against the USD20
cap. There are 502 reservations, 473 usage rows and 29 open holds. A hold is an
uncertain exposure retained for safety, not a claim that the provider billed it.
All paid processes are finished. No further calls are needed to reproduce the
offline tables. The sixth diagnostic's grading import is derived data: its cost
is counted once under diagnostics, never as a second paid request.

## Completion, contract and usable output

Semantic grades above remain unchanged by the compatibility fix. Usable means
semantically acceptable, independently contract-acceptable, and accepted by the
production response guard/parser. These are results after the explicitly logged
transport recoveries, not first-attempt availability statistics.

| Role/cohort | Model | Raw parser accepts | Usable, frozen adapter | Usable, compatibility replay |
|---|---|---:|---:|---:|
| Memory (40) | Opus 5 | 37 | 20 | 20 |
| Memory (40) | Kimi K3 | 40 | 26 | 26 |
| Memory (40) | GLM 5.2 | 39 | 22 | 22 |
| Current-state tasks (40) | Opus 5 | 40 | 29 | 29 |
| Current-state tasks (40) | Kimi K3 | 30 | 24 | 29 |
| Current-state tasks (40) | GLM 5.2 | 32 | 24 | 24 |
| Positive arrival tasks (20) | Opus 5 | 20 | 17 | 17 |
| Positive arrival tasks (20) | Kimi K3 | 0 | 0 | 15 |
| Positive arrival tasks (20) | GLM 5.2 | 20 | 11 | 11 |

K3 returned complete tool payloads labelled `end_turn` on ten held-out tasks and
nineteen arrival tasks. The frozen adapter rejects them; compatibility replay
accepts those 29 payloads. One arrival response remains truncated and incoherent.
Independent schema validation still catches a missing or too-short required
value in one otherwise parser-accepted arrival output and one held-out task. The fix does not
repair schema or content. GLM returns plain `NO_ACTION` rather than the mandatory
tool on eight held-out tasks; these remain failures even when the decision is
semantically appropriate. Parsing alone is therefore an inadequate quality test.

## Prompt candidate and repeatability

The optional-arm judgments below retain their historical exploratory status.
They were not a new company-fact-validated confirmation after the grading repair
and must not be used to restore the withdrawn quality recommendation.

The single frozen development candidate produces 20 of 30 planned responses:
Opus 10, GLM 10, K3 zero. K3 has three provider HTTP429 errors followed by seven
unattempted calls after its availability circuit opens. All 20 responses and
30 original controls receive fresh blinded paired grading; original frozen
control grades are retained, not overwritten.

| Candidate model | Acceptable / unacceptable / indeterminate | Paired semantic wins / losses | Contract-acceptable |
|---|---:|---:|---:|
| Opus, 10 | 9 / 1 / 0 | 3 / 0 | 10 |
| GLM, 10 | 5 / 4 / 1 | 1 / 0 | 8 |
| K3, 10 planned | No responses | Not measurable | Not measurable |

The archived grading recorded no new consequential loss against its controls;
that judgment has not received exhaustive evidence-based regrading. Nevertheless, K3 coverage is absent and
GLM still has consequential and schema errors. The complete candidate gate is
not met; **no candidate held-out calls were made and no saved prompt was changed**.
Opus's development improvement is promising, not held-out evidence of a general
improvement. The earlier generic trainer FACT correction is already separate
source work; it does not retroactively rewrite these saved prompts.

Of 60 preselected original repeats, 50 return and are graded: Opus 14, K3 17,
GLM 19. Missing responses comprise six HTTP402 failures (three Opus, three K3),
three unattempted Opus calls after the circuit opens, and one GLM timeout.
Original routing is retained for this arm. Among 44 pairs determinate on both
runs, seven semantic verdicts change: five acceptable-to-unacceptable and two
unacceptable-to-acceptable. Six further observed pairs are indeterminate on at
least one run. The ten missing outputs provide no semantic stability evidence.

| Model/role | Returned / planned | Determinate pairs | Pass → fail | Fail → pass |
|---|---:|---:|---:|---:|
| Opus memory | 10 / 10 | 10 | 2 | 0 |
| Opus tasks | 4 / 10 | 4 | 0 | 0 |
| K3 memory | 8 / 10 | 7 | 1 | 1 |
| K3 tasks | 9 / 10 | 8 | 1 | 0 |
| GLM memory | 9 / 10 | 7 | 0 | 0 |
| GLM tasks | 10 / 10 | 8 | 1 | 1 |

These are observed grade transitions, not a clean estimate of sampling variance:
there are incomplete pairs, possible grader variability and provider differences.
The small strata and selected single-business corpus do not justify population
confidence claims. Any conditional bootstrap emitted by the summary tool is
descriptive for this frozen set, not proof of equivalence or a zero-error rate.

## Delivered source changes and validation

- Email memory extraction uses a named 4096-token ceiling in both email paths;
  task detection uses 2048. Other worker caps are unchanged. Completion guards
  continue rejecting truncated output, preserving pending work without writes.
  Larger ceilings can increase per-request reservations and spending; existing
  admission limits still apply. These ceilings are not a cost optimization.
- `LLMResponse` normalizes only complete `end_turn` responses containing valid
  tool blocks with nonempty IDs/names and object inputs, with valid accompanying
  text and no refusal or unknown block. The raw response and original stop reason
  remain available. This shared Anthropic-compatible wrapper includes OpenRouter;
  truncation and malformed payloads are not repaired.
- Versioned runner, parser replay, blinded-pack preparation and aggregation
  separate paid execution from offline analysis, verify source bindings, preserve
  failed attempts, and distinguish missing, indeterminate and ungraded outputs.
  The memory candidate is a separate evaluation patch, not a production default.

The combined LLM, evaluation and affected-worker suites pass: **281 tests** with
13 existing Pydantic deprecation warnings. After lint-only cleanup, all 86
evaluation and compatibility tests pass again; explicit engine-config lint and
the documentation mechanical gate pass. Independent reviews cover runner
safety, source changes, frozen-parser preservation, all 360 main grade bindings,
compatibility provenance and final financial reconciliation.
The hosted four-profile release remains pinned to `10477fd`, with unchanged
saved presets, daily caps and paused automatic processing. Source delivery does
not deploy a provider pin, resume a backlog, or certify unattended task quality.

## Reproducibility and privacy

Protocol: [blinded grading](controlled-quality-grading.md).
Delivery: [execution plan](../execution-plans/2026-09-15-controlled-model-quality.md).
The versioned runner requires explicit execution, an isolated ledger, atomic
reservations, a fixed accounting day, durable attempt intents and a matching
manifest. It never retries a dispatched cell on restart. Raw source messages,
requests, responses, blind identity mappings and reconciliation evidence remain
in a private directory and are excluded from Git.

Aggregate machine-readable results are in the
[table snapshot](2026-09-15-controlled-model-quality-tables.json).
The private evidence, ledger, diagnostic responses and final aggregation helpers
are archived under
`~/.local/share/mrcall/evaluations/2026-09-15-controlled-quality/`, restricted to
the local user, with a SHA256 file manifest. Original private working paths under
`/tmp/mrcall-controlled-eval-20260915` remain recorded in frozen provenance;
replay after relocation must preserve or explicitly map those paths. The archive
is local evidence, not a publicly distributable dataset or an off-host backup.
The versioned preparation and summary CLIs support reproducible offline checks
against explicit private input paths. Frozen parsing remains the default;
compatibility counterfactuals require an explicit mode and record source hashes.

## Runner operation

`engine/scripts/evaluate_model_quality.py` defaults to a dry-run reservation
forecast. `--execute` additionally reads the API key from standard input; never
put a key in command arguments or shell history. `--ledger`, `--manifest` and
`--output` are explicit private paths. The ledger must carry its reviewed
experiment marker and cumulative cap. A typical dry run is:

```sh
python engine/scripts/evaluate_model_quality.py \
  --ledger /private/evaluation-ledger \
  --manifest /private/frozen-manifest.json \
  --output /private/evaluation-results
```

Resume with the identical manifest/output directory. Only cells without a prior
durable intent may dispatch. A separate recovery directory is an explicitly
reviewed additional attempt, never a way to bypass an intent or uncertain hold.
`--per-model` and `--max-active` apply together; the latter caps concurrent calls
across models. Role-specific completion and service availability are separate
from parser, contract and semantic grades. Dry-run reservation bounds are not
predicted bills: actual token usage/provider cost determines settlement.

## 2026-09-16 grading correction

The earlier downgrade of Opus for an ambient-storage statement was itself wrong:
ambient 12-month shelf life is a correct company fact, confirmed by the CTO.
That downgrade is reversed consistently with the corresponding K3 judgment.
Further uniform review corrects no-glass/cold-brew scope penalties, missed FAQ
instructions and unknown payment/capability claims. The original quality
recommendation is withdrawn. Main tables and JSON preserve an intermediate revision of the
canonical grades; their semantic interpretation is now superseded. Original
snapshots and adjudications are preserved, and exhaustive regrading is pending.
See the [correction note](2026-09-16-grading-correction.md) for exact distinctions,
context limitations and the post-hoc status of the revised evaluation.
