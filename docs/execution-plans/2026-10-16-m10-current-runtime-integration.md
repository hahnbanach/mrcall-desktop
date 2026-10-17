---
date: 2026-10-16
kind: execution-plan
status: completed
task: m10-current-runtime-20261016
brief: ../briefs/2026-10-16-m10-current-runtime-integration.md
---

# Integrate M10 with the effective runtime

## Classification, inputs and ownership

Substantial integration: assignment authority, provider observations and persisted
reply bindings cross behavior and security boundaries. This is not a fast path.
The approved brief is SHA256
`d02e8f32891282356b4275260d05f42c73ef3059f16f0f7aac022557aa9f4c8b`.
Work only in the isolated desktop M10 worktree based on `58778222`; retain its
existing dirty M10 changes and the previous task's immutable approvals.

The lead owns frozen inputs, runtime identities, integration evidence, deployment
packet and documentation. One implementation owner owns the coupled engine
modules and affected tests; do not split their shared effect/transaction changes
between concurrent writers. The billing-server owner retains its reviewed source
unchanged. The V7 owner retains sole control of its staged releases and six live
services. This plan grants no live operational authority.

Private evidence root: `/home/mal/worktrees/.evidence/m10-current-runtime-20261016`.
Use its complete frozen-effective manifests, `effective-vs-old-freeze-final.json`
and `provisional-targets.json`. The latter's ten staged files and all 22 V4
per-profile delta hashes were verified during planning. Twelve distinct V4 modules
and one additional IMAP module require disposition. The provisional V7 manifest
is SHA256 `506f35afdf2dd8204161022b16fce992f1e59a4f4e24bc13f583f68795444a50`.
Its source approval does not establish deployment or a combined M10 acceptance.

## M1 — Compose preservation behavior with M10 authority

Dependency: approved plan. Owner: engine implementation owner; lead integrates.
Before editing, freeze the current candidate hashes/diff and run the focused
baseline below once in the existing private installed-dependency environment,
with candidate source explicitly selected and external connections denied. Keep
actual failures with their causes; do not erase assertions or normalize unrelated
baseline lint debt. Reuse the existing 551 bounded-server and 1507 full-server-CI
receipts only while their source identities remain unchanged.

Produce a complete per-module disposition against both effective packages, both
provisional target inventories and the previous M10 wheel. Each row records input
hashes, adopted behavior, retained M10 behavior, resulting hash and proving test.
Account for unchanged and profile-exclusive modules across the whole inventory,
not only the initial 12/10 deltas. Do not copy complete overlays over M10.

| Module under `engine/zylch/` | Required composition |
| --- | --- |
| `rpc/methods.py` | Adopt production's RFC-component scheduled admission and source/route binding. Retain M10 `routed_model`, narration pause behavior, contextual chat/task-solve scopes and capability, cancellation and duplicate-checked exact-draft/assignment registration. |
| `rpc/task_assignments.py` | Resolve previews to current component authority, require complete evidence, and retain M10 enrollment and authenticated RPC behavior. |
| `services/operator_reply_origin.py` | Retain V4 locked task/component/source/route rechecks through actual handoff, scoped automatic provenance and reset behavior. Compose with the shared effect/claim reservation without taking a second conflicting writer. |
| `services/task_assignment_draft_policy.py` | Preserve component-aware scoped admission and route/task freshness. Keep M10's single authoritative email-effect transaction; do not restore V4's separate attached-profile draft session alongside the M10 writer. |
| `services/task_assignment_evidence.py` | Compose V4 source/route/internal correspondence checks with staged V7 scoped provider reuse, exact header targets, proven inherited References, external own-Sent follow-up and observation-only malformed-Sent handling. Preserve real PEC body verification, deadline and UNKNOWN outcomes. |
| `services/task_assignment_mail.py` | Preserve bounded transitive RFC component resolution, authoritative aliases/digests and trusted delivery routes. Preserve V7's proven same-component nonterminal reply-target case without rewriting the exact target; missing/foreign ancestry still refuses. Retain owner/mailbox isolation, cycle/conflict rejection and the shared 40-second bound. |
| `services/task_assignment_projection.py` | Preserve component authority and route freshness; compose V7 observation lifecycle and follow-up states. Malformed own Sent may hold an exact observed message; it must never become complete assignment authority or a send permit. |
| `services/task_assignment_sent_index.py` | Compose complete bounded component searches, aggregate byte/request/identity limits and per-observation clients with full Sent membership and exact related-message revalidation. Cache keys include source/component identity and changing folder state invalidates old results. |
| `services/task_assignment_store.py` | Adopt component authority, locked attached-profile resolution and component-bound previews/commits. Keep M10 `require_managed`, join fence and trust identity checks. Old durable matching receipts remain replayable; newly executed operations require fresh component-bound authority. |
| `services/task_assignment_trust.py` | Add protected delivery-route reads/digests while keeping M10 `parse`, `probe` and its safely inspected missing-file semantics. Keep the existing `missing_ok` callers; do not replace them with the overlay's incompatible `optional` signature. |
| `services/task_assignment_types.py` | Validate the component digest strictly and preserve typed canonical intent, actor, expiry and operation rules, including the distinction between historical replay and a new operation. |
| `storage/storage.py` | Keep M10 create/update effect guards, immutable reply binding, private draft transaction and fresh-claim short circuit. Preserve actual emitted Sent References as in production/M10; do not restore Mario's older omission or backfill historical rows. |
| `email/imap_client.py` | Adopt only V7's `folder_headers` search/proof/aggregate-budget behavior; preserve M10 transport guards and automatic provenance on both send paths, attachments and existing adapter signatures. The peer variant's missing provenance is not a behavior to propagate. |

Concrete dependency expansion: `services/task_assignment_email_effect.py`
currently derives authority from the first stored References ID and selects an
assignment by that exact root. Compose component authority, route digest and
source freshness into this existing guard rather than bypassing it. Keep a single
company-to-private lock order using `task_assignment_draft_transaction.py` and
persisted draft CAS. Read its callers in contextual policy, storage, send-draft
and transport adapters. Change the transaction helper only if the composition
requires it, recording why. Other expansion requires a concrete selected-runtime
caller/dependency, a disposition and its focused check. No support-only finance
transplant, excluded-profile work, UID/company literals or new dependency is
planned.

Verification command pattern, run from `engine/` with private HOME, database and
memory directories, blank provider/Firebase credentials, and `PYTHONPATH` pointing
only to the candidate engine plus explicitly needed dependencies:

```sh
PRIVATE_PYTHON NETWORK_GUARD -q -p no:cacheprovider \
  tests/assignments tests/email/test_imap_uid_scan.py \
  tests/storage/test_create_draft_idempotency.py tests/storage/test_insert_sent_email.py \
  tests/llm/test_model_policy_roles.py tests/llm/test_role_inventory.py \
  tests/llm/test_role_pause.py tests/llm/test_budget_dispatch.py \
  tests/llm/test_provider_context_admission.py tests/llm/test_openrouter_dispatch.py \
  tests/rpc/test_exact_drafts.py tests/rpc/test_chat_send_cancel.py \
  tests/rpc/test_ws_cancels_inflight.py tests/operator_mcp/test_read_contract.py \
  tests/tools/test_send_draft_id_honoured.py tests/tools/test_send_draft_approval.py \
  tests/tools/test_send_draft_double_send.py
```

`PRIVATE_PYTHON` is the existing installation private venv's Python, not a live
unit's interpreter; `NETWORK_GUARD` is the retained server-context network guard
allowing only loopback fixture traffic. Freeze an actual argv/environment receipt
rather than treating this parameterized pattern as an executed command. Reuse
and adapt the V7 frozen `test_sent_index.py` and
`test_projection_observation.py` and relevant component/internal-correspondence
fixtures where they add genuine behavior coverage; do not overwrite M10 fixture
enrollment or weaken authority assertions. Where approved V7 provider proof now
permits inherited References, replace an older blanket-UNKNOWN expectation only
with a proven positive plus missing/changed-live-target negatives; never mutate
the stored source to manufacture that proof.

After composition, rerun the same selection plus the newly integrated provider
cases. Exercise actual RPC dispatch -> source projection -> draft create/update
-> approval -> claim -> real transport adapter, with SMTP/IMAP boundaries isolated.
Required positive cases include an authorized component alias, ordinary new work,
automatic scheduled reply, internal correspondence, external follow-up and a
closed assignment's genuinely later inbound. Required negatives include another
owner/mailbox, ambiguous/cyclic or changed component, stale/absent enrollment,
route/source/task drift before handoff, bound-draft edits, concurrent claim,
provider failure/uncertain SMTP, expired observation, Sent churn, malformed and
unsynced Sent, and PEC requiring body verification. Assert no effect on refusal
and retained uncertainty after an ambiguous transport outcome. Test actual
folder-header query/proof paths, aggregate bounds and resource cleanup, not only
mocked projection return values. Run changed-file syntax/style checks; no global
format cleanup. Store JUnit, complete command logs, source disposition and actual
failure corrections under private evidence.

Gate: fresh M1 reviewer approves the complete composition, its source inventory
and real-path evidence before building the replacement artifact in M2. A source
failure is fixed here, then the affected checks and review are repeated.

## M2 — Prove the replacement artifact and actual-runtime compatibility

Dependency: M1 APPROVED. Owner: lead, with the same exclusive engine source owner
for any review repair. No service, live configuration, shared package or SQLite
write is part of this milestone.

Build a new immutable wheel with the retained local build procedure and declared
`setuptools>=68.0`/`wheel` backend, offline from verified local build requirements.
Planning found `build` installed but `wheel` absent in both inspected engine
environments: resolve that private build prerequisite from existing local artifacts
before running `python -m build --wheel --no-isolation --outdir PRIVATE_WHEELS engine`
from the repository root; do not bypass backend requirements or install into a live
interpreter. Capture the complete source manifest and wheel SHA256; compare
all packaged Python modules with both effective frozen runtimes, staged source
and the previous 369-module M10 wheel, retaining the per-module disposition.
Do not reuse old wheel hash `c4b208fb408f...` as proof of new bytes.

Install the new wheel in a new private environment from a private wheelhouse
using a hash-locked dependency set, `--no-index --require-hashes`, and retain the
exact `cs.operator_read` contract artifact with source hash
`3ab4969b3c3d61af473d418438edd82623cdeda9356337ef342979d9ac79e911`.
Replace only the engine wheel's lock entry; confirm the remaining dependency
identity or explain actual changes. Run `pip check`, installed-module parity,
fresh CLI imports/help and actual temporary authenticated MCP startup/read
contract. Clear source/PYTHONPATH leakage and prove loaded paths are inside the
new environment. No test imports from the old installed product count as new
artifact proof.

Create fresh private working copies from the immutable protected SQLite backups.
For each selected profile, run the installed candidate twice, then reopen with
the exact full effective-runtime source. Keep live UID/config/host binding
semantics only inside the isolated copy, with all network denied and background
work disabled there. Check every original row/column survives, candidate warm
startup is stable, enrollment provenance is valid and Qonto connection/privacy
state remains intact. Record only explained additive migrations/index effects;
never repair history or drop authority to make reopening pass. Remove temporary
copy environment files even after failed attempts. Earlier base-only reopening
is historical evidence, not this acceptance.

Run the existing six-case engine/server continuation journey against the new
installed engine and unchanged reviewed billing server with disposable PostgreSQL:
K3 Chat, GLM Messages and Sonnet Messages, each ordinary and lost-answer receipt
recovery. Adapt a private copy of the retained M2 runner to select the installed
engine; bind actual loaded modules to the new wheel and server source hashes.
Require six executed cases without skips, full multibyte evidence, proper budget
reservation/settlement and receipt-only recovery with no new inference. Existing
551/1507 server receipts remain supplemental unchanged-source evidence; rerun
server suites only if their source or a concrete concern changes.

Before finalizing the rollout packet, receive the V7 owner's exact accepted
runtime descriptor and outcomes after its stability window. Compare full source,
interpreter, argv, PYTHONPATH, selected imports and configuration against frozen
inputs. If accepted bytes differ, preserve both generations, update disposition,
repair/retest only affected composition and repeat its review. While acceptance
is pending, finish all independent M2 work but keep actual V7 acceptance pending;
never label staged source as accepted. No M10 live canary occurs under this plan.

Refresh the install/rollback packet to the newly approved wheel and exact selected
runtime/config hashes. It must stop on changed inputs, preserve MCP/voice flags
and live controls, and name the original full effective runtime as rollback.
Copied-data reopening establishes only that compatibility; live rollback still
requires a pre-switch backup and validation under the separately authorized
rollout. Retain old approval/evidence records unchanged.

Gate: fresh M2 integration reviewer approves wheel/install/source parity, private
copied-data results, six continuation cases and the exact remaining rollout gates.
Any source repair returns through M1's affected verification and review first.

## Current main integration before publication

Current remote main `b43b9f274f9324b1f70d7860c03c02c89579b183` has 14
documentation-only differences beyond the M10 fork. After M1 source approval,
freeze owned candidate bytes and test the merge in isolation. Local commits of
reviewed, owned bytes are reversible source bookkeeping. Reconcile current main
and candidate documentation without discarding either workstream, and review
any unexpected product-source conflict before proceeding. Preserve all primary
worktrees and refresh affected orientation after an instruction/index change.
Final documentation and integration review cover this combined candidate;
publish nothing before scoped authority. A later remote change reopens the
necessary ancestry/integration checks.

## Documentation closure and the continuing rollout

The lead reconciles current engine/root living context and relevant assignment,
contextual-email, model-selection, remote-backend, operator-MCP and deployment
contracts; include unchanged affected docs and missing coverage in the impact
record. Preserve historical narrative in the archive verbatim. Correct old
base-only preservation claims and point current instructions at the newly
approved source/wheel/runtime identities. Keep copied-data proof, provider source
approval and actual deployed outcomes distinct.

Run doc-end reconciliation, actual focused/mechanical receipts, explicit fresh
doc-critic including living-context shape, then a separate final reviewer against
the approved brief/plan and immutable M1/M2 evidence. Only the installed completion
checker advances the baseline. Final source changes invalidate affected evidence
and reviews; metadata-only finalization follows the approved lifecycle.

This plan establishes a locally reviewed combined candidate, reproducible private
installation and bounded copied-data/client-server compatibility. It does not
establish CI publication, billing promotion, provider-paid correctness, repeated
source-grounded company answers, protected two-clone operations, production
memory quality or live rollout/rollback. Those remain required to finish the
CTO's goal. Continue all authorized local preparation; present a concrete scoped
external execution packet only when that is the next genuine authority boundary.
No pushes, secret/protection changes, paid requests, sends/drafts, live
memory changes or deployment are authorized by this plan.

## Acceptance record and continuing obligations

The source inputs advanced from provisional V7 to actually activated V8, manifest
`ff55134005c0e11c89affee5eb2df767cfdf24d970fe74e35250a1e3de035897`.
Complete stable captures cover both selected regular packages and configuration.
Both selected UIDs are currently Café124 identities; historical Mario/support
prose is not authority for selecting their company.

M1 source composition passed 746 affected cases and twenty independently executed
authority/race cases, all without skips. The first M2 wheel exposed missing runtime
JSON before any provider dispatch. The same M1 reviewer approved the narrow
package-data repair; its immutable evaluation is `approved-M1-r2.md` in private
evidence, with actual report `M1-review/report-r2.md`. All 369 Python modules
remain unchanged; seven explicit JSON/schema/prompt resources are included.

The replacement wheel is SHA256
`3fb25d395d8896e3ba10baa2014aef96a6b602329e1f5da0f078771ae784b541`.
Offline installation, 369-module/seven-resource parity, actual metadata/table/schema
loading and 26 installed SDK/read/auth/listener cases pass. Six fresh copied boots
preserve every original row/column, managed enrollment and Qonto one/zero, with
stable warm/V8 reopening. Six installed-engine/server continuations pass, including
lost-answer receipt recovery without inference replay. New working-copy archives
have verified streaming byte/hash roundtrips. The first failure artifacts remain.

Owned source checkpoint `0a4261f8`, current-main merge `e48dcdef` and packaging
repair `c4593726` are local. The merge reconciles main's fourteen documentation
paths while preserving product bytes and both previous living-context bodies.
Billing-server candidate `01909353` contains its separately reviewed correction.
None of these commits is published by this preparation.

Fresh M2 review approves local preparation; documentation closure and separate
final approval are tracked by this task's completion record. The
runtime owner's full ordinary batch failed on transport timeouts/capacity; its
six-service stability window remains held. `external-execution/proposal.json`
therefore keeps engine activation blocked until successful operational acceptance,
final descriptor, window release, source/configuration freshness and sufficient
staging/backup space. CI/billing preparation is independent of that window.

Local artifact acceptance never closes the overall rollout goal. Required external
publication/CI/data, server promotion, real provider/credits receipts, twenty
company answers against originals, protected clone operations and controlled
canary/rollback remain open, with scoped authority required for external effects.
