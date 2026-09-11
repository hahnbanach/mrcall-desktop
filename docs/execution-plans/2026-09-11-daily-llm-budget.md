---
status: active
---
# Daily LLM budget execution plan

## Reviewed intent

Brief independently APPROVED. Preserve the existing USD5 profile setting.
Containment: four Café124 daemon units stopped to interrupt ongoing runaway AI;
no data deletion. Restore RPC/sync with automatic processing disabled until
acceptance. Existing unrelated profiles and user edits remain untouched.

## M1 — Central cost admission

Add an additive profile-local reservation ledger using the existing SQLite
engine. Reserve under BEGIN IMMEDIATE against immutable owner, historical
llm_usage plus outstanding holds, including unresolved prior-day requests.
The existing usage log remains the settled estimate source. Settlement inserts
usage and closes reservation atomically; errors retain holds and stop dispatch.
Use integer USD micro-units for admission, rounding upward. No automatic expiry
of uncertain requests. UTC reset applies to settled daily spend; pending holds
remain until reconciled. Zero pauses; negative/nonfinite limits fail closed.

Exact supported model-price allowlist, conservative text-byte token upper bound
with protocol allowance, full output allowance and maximum cache-write rate.
Refuse unknown models or unsupported cost-bearing request options. No hidden
SDK retries; ambiguous failures retain the reservation. Provider server-side
tools/multimodal requests require a defensible bound or explicit refusal.
Proxy billing needs markup-aware pricing or refusal; never silently claim
Anthropic list prices bound MrCall debits. Guard sync and async common client;
route chat compaction through it. Tests use a fake transport with real SQLite.

M1 integration review precedes further integration.

## M2 — Pipeline correctness and cost amplification

Propagate budget/LLM failures without marking unfinished emails processed.
Analyse and fix repeated merge calls using source and recorded aggregates;
retain LLM semantic decisions and evidence. Prefer structurally identifying
candidate records/caching unchanged negative comparisons, never heuristic
semantic labelling. Validate extraction failure checkpoint and candidate-count
regressions with meaningful tests. Audit provider routing and prior GLM evidence;
model changes must distinguish classifier evidence from memory quality.

## M3 — Visible limits and acceptance

Reuse Settings budget field; usage.today includes reserved amount, remaining
capacity, UTC reset and pause state. User-visible budget errors show recovery
without suggesting key replacement. Add documentation and incident/routing
reports, avoiding customer content and secrets. Cross-repo changes only if
required; no unrelated kernel release. Verify controlled CLI/RPC and live
read-only configuration/status; no live paid LLM calls.

Fresh final reviewer checks bypasses, races, retries, accounting errors,
checkpoint safety and UI contract. Run focused engine tests, existing billing,
usage, pipeline and RPC contract tests plus app typecheck if app is changed.
Run mechanical/semantic doc gates. Commit/push reviewed source. Deploy guarded
engine only after tests/review; maintain AUTO_UPDATE_ENABLED=n on affected
profiles pending deliberate resumption. Capture rollback: reverting guard code
requires keeping automatic processing paused, never restoring the unsafe loop.

## Evidence and pending work

- [x] Brief independently approved.
- [x] Reversible incident containment: four affected engine units stopped.
- [x] Plan independently approved.
- [x] M1 implementation and integration review.
- [x] M2 failure/cost fixes and integration review.
- [ ] M3 user-path acceptance, final review and documentation.
- [ ] Safe hosted-engine rollout and final status report.

## Verification and recovery evidence

M1 and M2 received separate independent approvals after stale settings,
unsupported billing tiers, malformed saved policy and truncated-output checks
were tightened. An actual observed bound breach now remains a persistent
pricing fault across process restart and UTC rollover.

Fresh final implementation review: APPROVED. Independent 68-case suite passed;
additional actual client + SQLite + dispatch_raw(usage.today) journey proved
cancellation holds, saved-zero refusal and exactly-once late settlement with a
fake upstream. Static SDK scan confirms centralized dispatch. No live paid calls.

Checkpoint recovery completed with both source daemons stopped and a private
SQLite backup per profile. Conditional updates matched every audited original
checkpoint; 1,962 + 40 memory checkpoints restored to pending. Independent task
checkpoints unchanged; no existing source/blob links and no paid replay.
Private metadata and backups: /tmp/mrcall-incident-recovery-20260911.

Scoped rollout uses an isolated source release and per-unit PYTHONPATH override
for the four affected direct-key accounts only. The three other engine units
and original release checkout stay unchanged because their billing coverage
requires separate work. No packaged Desktop release is part of this fix.
