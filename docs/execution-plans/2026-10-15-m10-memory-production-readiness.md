---
date: 2026-10-15
status: completed
kind: execution-plan
---

# M10 company-memory source candidate and deployment gates

Approved brief: `docs/briefs/2026-10-15-m10-memory-production-readiness.md`,
SHA256 `29b3a3f82c953285fdf26a45e621094eaaa850cbe5dfbcf7e429d4db4a42eada`.
Approval: `/tmp/mrcall-ai-kit/m10-memory-readiness-20261015/m10_takeover_brief_review.log`.
Worktree: `/home/mal/worktrees/mrcall-desktop-m10-memory-readiness`, branch
`prepare/m10-memory-readiness-20261015`, starting commit
`5877822203ccb3e1d53951ead331574bff38fbb6`.

## Classification, authority and ownership

Substantial development: request-admission behavior and installed runtime
protections change, so the fast path does not apply. Deliver a reviewed source
candidate and concrete deployment-gate packet. Current authority excludes paid
calls, fixture sends/drafts, profile changes, server/service changes, deployment,
commits, pushes and release. Existing measurements and spending records remain.

The lead owns M1–M4, server prerequisite verification, final-user testing,
operational acceptance, deployment preparation and rollback. Operator and engine
maintainer below name engineering responsibilities that this session carries
or explicitly delegates; they are not work handed back to the human. The CTO
owns only unresolved external authority, credential grants and material risk
acceptance. No kernel/company-specific workaround.
M1 preservation and M2 admission are independent after plan approval and can
proceed concurrently with disjoint source ownership. M3 waits for both reviews.
Further delegation is optional, not required for small edits.

## Design decisions

- Extend M10 rather than rebuild its resolver or repay its corpus. Preserve the
  actual saved settings: production custom K3 and extraction/merge overrides
  remain K3; Mario Anthropic economy follows its table and explicit pauses.
- Separate supported-feature validation, context handling and monetary bounds.
  OpenRouter currently calls direct validation, including Anthropic's empirical
  context estimate, then reads monetary payload bytes as context tokens. K3
  repeats the byte-context mistake on translated Chat wire. Neither count nor
  Anthropic's divisor is a verified K3 tokenizer bound.
- Make provider tokenization authoritative for OpenRouter/K3 input fit. Remove
  the false byte-context gates and accidental direct-Anthropic context gate.
  Validate finite output reserves against applicable published snapshot context/
  output capabilities, retaining reviewed fallback limits for absent metadata.
  Do not invent a tokenizer ratio. Keep direct Anthropic admission behavior
  unchanged except any behavior-identical feature-validation extraction.
- Preserve finite local assistant prompt/tool-result limits, reasoning headroom,
  K3 output cap, byte-based monetary bounds and protocol allowances, cache-write
  maxima, price ceilings, endpoint pin, unknown-feature rejection and no retries.
  No automatic compression, silent evidence loss, model switch or overflow retry.
  A definite no-work refusal releases its hold; uncertainty retains it.
  [OpenRouter Message Transforms](https://openrouter.ai/docs/guides/features/message-transforms)
  documents refusal without compression and removal of content with compression.
  That is the design basis, not live candidate acceptance.

## Existing evidence and execution environment

Lead startup and durable-document reads are complete. The source-only inventory
`/tmp/mrcall-ai-kit/m10-memory-readiness/runtime-inventory/inventory.json`
records 348 production Python modules: 257 identical to M10, 75 different and
16 absent. Its real unit/process identity includes `serve --operator-config`
and voice configuration. Installed `operator_mcp/read_port.py` and `server.py`
do not match nominal release source; only installed bytes have verified identity.
Inventory counts/hashes are preservation inputs, not semantic equivalence.

The pre-change focused command used the existing interpreter
`/home/mal/hb/mrcall-desktop/engine/venv/bin/python`, candidate `PYTHONPATH=.`,
and scratch HOME/ZYLCH_HOME/ZYLCH_DB_PATH set before imports. From `engine/`,
`pytest -q -p no:cacheprovider` covered `tests/llm/test_openrouter_policy.py`,
`test_k3_production.py`, `test_budget_ledger.py`, `test_request_shape.py`,
`test_role_pause.py`, `test_routed_model.py`,
`tests/services/test_prompt_too_large_metadata.py`, and
`tests/rpc/test_memory_readonly.py`: **176 passed, 19 warnings in 27.30s**.
Log: `/tmp/mrcall-ai-kit/m10-memory-readiness-20261015/m10_takeover_plan/baseline-focused.log`.

Lead baseline `make lint PYTHON=/home/mal/hb/mrcall-desktop/engine/venv/bin/python`
already fails: Black would reformat 71 files, 282 unchanged; separate Ruff finds
E402 in `rpc/methods.py` and four unused imports in `task_assignment_draft_policy.py`.
Ruff log: `/tmp/mrcall-ai-kit/m10-memory-readiness-20261015/baseline-ruff.log`.
Do not reformat 71 files. Require clean changed-file lint and no new whole-tree
diagnostics; retain the honest whole-tree failure. All local checks isolate
HOME/ZYLCH_HOME/ZYLCH_DB_PATH before imports and use temporary stores/transports.

## M1 — Preserve the actual runtime

Dependency: plan APPROVED. Owner: engine lead, with operator read-only identity.
Output: reviewed preservation manifest and minimally composed runtime sources.

1. Freeze exact installed source bytes outside source control and verify their
   inventory SHA256, relative paths and provenance. Capture both noncanonical
   MCP files; never substitute sibling release bytes or copy secrets/data/config.
2. Disposition all 75 differing and 16 absent modules: preserve, compose with
   M10, or intentionally supersede with explicit reason/install boundary.
   No unexplained difference. Use exact matching retained ancestry/deadline/
   sent-index/operator-origin sources from the inventory, checking call sites.
3. Preserve exact-draft inspection/discard/reconciliation/delivery proofs,
   scheduled-reply provenance, assignment guards/sent index, read-only policy,
   private/company ownership, Qonto bootstrap access, all ten operator_mcp
   modules and startup wiring. Preserve settings/budgets/pauses without copying
   live values. No Qonto bootstrap removal before its separate installed-GUI gate.
4. Before later canary preparation, obtain equivalent exact source/startup
   identity for Mario and reconcile profile-specific differences explicitly;
   the production inventory alone does not prove Mario preservation.

Verification: complete manifest disposition and frozen hashes; candidate imports
and actual `serve --help`/argument parsing retain `--operator-config`; isolated
startup with temporary config/socket exercises wiring without live services.
Run assignment, Qonto startup/privacy and draft-approval regressions, adding
focused checks for restored exact-draft RPC registration, provenance and MCP
read-only/auth contracts. Missing modules, startup flags or weakened boundaries
must fail checks. Review M1 APPROVED before M3 relies on it. Rollback: remove
only isolated integration changes; keep frozen sources and live runtime intact.

## M2 — Repair admission and preserve cost protection

Dependency: plan APPROVED; independent of M1 until M3. Owner: engine admission
files `budget_pricing.py`, `openrouter_pricing.py`, `k3_reasoning.py`, and only
directly necessary client/error paths.

1. Reuse pure feature validation without direct-Anthropic context decisions.
   Retain malformed controls, unknown options, multimodal/server-tool rejection.
2. Implement the context decision above for original Messages and translated
   K3 Chat shapes with current metadata. Keep conservative monetary reservation
   across both shapes; admission must not lower the amount reserved to pass.
3. Preserve useful context-refusal status/reason without logging company payloads
   or secrets. Do not classify uncertain work as free from an untrusted body.

Verification: regression for a short memory/mail question with large retrieved
JSON formerly rejected by bytes; original/translated K3, system/tools/schemas,
multibyte input, replayed reasoning, metadata change, finite output caps, genuine
upstream overflow and malformed features. Assert one dispatch for admitted input,
none for invalid shape/output, unchanged or larger cost holds, correct release
for definite refusal, retained hold for malformed success/5xx/uncertainty, and
no retry/compression/model change. Repeat the 176-test baseline and affected
K3-credit, bounded-v2, reasoning-transport, free-preflight and memory-spend-safety
checks; exercise unchanged assistant limits on its actual loop. Scripted overflow
proves handling, not real provider fit. Review M2 APPROVED. Rollback: restore
bounded admission diff; no persistent-data transformation.

## M3 — Integrate and prove the local source candidate

Dependencies: M1 and M2 APPROVED. Owner: engine lead with clone entry-point owner.

1. Compose once; rerun affected checks on exact combined bytes. If installation
   includes packaging, install/build in a scratch environment and check imports,
   entry points and preservation hashes there. No shared-venv mutation.
2. Create repeatable permitted-source incident cases: short question/large
   retrieval; production method; patent filing versus grant and 24/25 July
   conflict; certification evidence versus unsupported claim; current offer
   versus historical proposal. Include Ivan's 4 October original thread.
   Record source IDs/dates/authority and uncertainty. Selective absence cannot
   prove no patent grant/certification. Keep sensitive originals outside public
   artifacts; never read excluded personal memory or rewrite live memory.
3. Exercise local RPC/`cs ask` with isolated fixtures/scripted providers. Cover
   retrieval error versus empty result, conflict and narrowing after cutoff.
   Preserve source references; hostile retrieved text cannot write memory,
   drafts/tasks or send mail. These prove local paths, not model factual quality.
4. Produce sanitized all-role reports from actual saved production/Mario choices:
   overrides versus table picks, transport, rates, pauses, fingerprint and
   downloaded/cached/build hashes. Verify saved controls unchanged; reuse free
   M10 harness/resolution tests. Proposed transitions are separate, with estimated
   role/rate effects and workload assumptions, never silently applied.
5. Retain exact candidate HEAD, dirty diff/untracked-source hashes, table/snapshot
   hashes, dependency/interpreter identity and logs. HEAD alone is insufficient.

Verification: combined suites/startup/local CLI journey pass; every incident case
and both profiles have acceptance rows with external legs marked pending; every
preserved-source difference has reviewed rationale. Rerun `make lint`, compare
baseline, require clean touched-file lint/no new failures. Add app/IPC checks only
if changed, otherwise state no impact. Review M3 APPROVED before closure.

## M4 — Documentation closure and separate source-candidate final review

Dependency: M3 APPROVED. Owner: lead reconciliation, separate critic/reviewer.

1. Reconcile admission/model-selection, budget, runtime/install/rollback contracts,
   root/engine living state and this plan, including affected unchanged docs and
   missing coverage. Preserve 12 October reports as history; archive displaced
   living narrative verbatim and retain State now/Unresolved/Next shape.
2. Prepare concrete artifact/hash, per-profile unit/interpreter/startup/install
   scope, old artifact/service command, config references without values,
   source/table hashes, staged switch/revert commands, health checks and stop
   conditions. Preserve all other service identities; do not execute live steps.
3. Use lead's exact existing completion task, or initialize one development task
   if absent. Retain approved brief/plan/M1–M3 immutable versions/raw reports.
   Follow installed doc-end: lead startup/impact/reconciliation; mechanical gate;
   keyword coverage; actual focused check through `--completion focused`; current
   snapshot; explicit doc-critic for all affected docs and living-context shape,
   even untouched context. Repair STALE; retain UNVERIFIABLE. Run installed
   verification-warnings check with exact repo/task; do not guess a session ID.
4. Pass `--completion check --phase pre-review`; separate fresh final review
   compares current sources with retained approvals and reviews local final-user
   evidence plus owned external gates. After actual APPROVED, record result,
   pass full `--completion check`, then `--completion finalize`. Only checker
   advances baseline/predeclared source-plan status. No commit/push/release.

Verification: current closure receipts and all required reviews; no missing/stale
evidence. Final verdict says **source candidate**, retaining lint debt and every
unrun deployment gate. Scope changes reopen review; deferrals never waive
ordinary-read/factual-quality acceptance or relabel pending runtime checks.

## External gates: prepare concretely now; obtain scoped authority before execution

The lead assigns actual identities/commands/environments in the packet before
requesting authority. These remain mandatory for deployment-ready status.

| Gate | Owner | Required evidence |
|---|---|---|
| CI/table | Repository maintainer + CTO | Read current job/secret-presence status without values; obtain authorized secret repair, successful required job, source/run ID and fresh published hashes. State paid/publishing effects before a rerun. |
| Server first | mrcall-agent maintainer + operator | Current installed protocol-v2 capabilities/table; generation-ID and recovery fixes; exact artifact/egress/protected-table prerequisites, interrupted-row recovery and rollback. No unrelated server rewrite. |
| Missing paid legs | CTO + engine/server owners | Valid Anthropic credential/Firebase test account; fresh bounded ledger/no retry; outstanding direct economy/balanced/custom, credits quote/execute/settlement and server direct legs on exact identities. Reuse unaffected historic OpenRouter evidence. |
| Ordinary reads | Engine lead + operator | Authenticated actual-transport `cs ask` incident cases on production and Mario, repeated/source-compared claims, conflicts/unknowns preserved, models/tables recorded. A precise refusal is diagnostic, not a passing ordinary read. No model changes. |
| Two-clone operations | Operator + both clone owners | Applicable real two-clone acceptance on exact integrated runtime: send/draft/provenance/assignment/read-only/tenant boundaries, private/Qonto access and preserved billing/pause/budget/membership. Historic R9 is not new-candidate acceptance. |
| Canary/recovery | Operator, CTO authorization | Bounded production/Mario canary only after explicit preservation of each runtime, with old artifact/config references and tested rollback; other services retain identity. Stop/revert on failed reads, startup mismatch, boundary regression or uncontrolled cost. Any migration first needs reviewed isolated rehearsal/data-compatible reversal. Wider rollout remains separately reviewed/authorized. |

## What this plan does not establish

It does not prove real provider fit, model factual quality, stored-memory
correctness/completeness, installed auth/isolation, paid/CI/server success,
clean whole-tree lint or deployment readiness. It authorizes no memory reset,
re-extraction/reconsolidation, personal-memory access, automatic Drive fallback,
second entity store, bootstrap integration, unrelated M10 work, profile change,
external write or release. A qualified source candidate may be the full current
deliverable; all deployment gates remain individually owned and visible.

## Current delivery disposition

The reviewed source phase is M1–M4; checker finalization of this plan means that
source candidate and its deployment-gate packet are complete, not that the
external gates passed or a rollout occurred. Current receipts:

- M1 APPROVED after the sync wrapper declaration repair; retained r2 evaluation,
  source/packaging hashes and fresh registry/email-only checks supplement earlier
  sensitive-runtime acceptance. The revised wheel is bound by the evaluation.
- M2 APPROVED after its exact-server fixture repair; byte-context admission,
  payload/cost protection and four local credit cases are verified separately.
- M3 APPROVED on the integrated RPC, free distribution matrix, actual saved
  profile forecast, original-source acceptance inputs and proposed per-unit
  installation/rollback packet. Real answers and provider quality remain open.
- Lead reconciliation and the exact completion record own M4 critic, focused,
  mechanical and separate final-review results. No baseline is edited by hand.

The profile forecast preserves production custom K3 in all roles and Mario's
Anthropic/economy selection with its NARRATION pause. The original report's
October 5 business-plan reference is not independently rebound; the commercial
case uses verified pricing revisions 21/29. Initial direct SQL diagnostics used
root before the host-runbook reload; exact reads were repeated as each daemon
identity and DB/WAL/SHM owners were verified correct, with no repair/restart.
All later live SQL reads must retain that daemon identity.

CI/secret/protection, additional server admission/compression alignment and
promotion, credentials/paid checks, real ordinary reads and factual quality,
data-compatible rehearsal, actual dependency installation and two-clone canary
remain owned external deployment obligations. The source candidate does not
authorize their execution, a model change, merge, push, release or memory repair.
