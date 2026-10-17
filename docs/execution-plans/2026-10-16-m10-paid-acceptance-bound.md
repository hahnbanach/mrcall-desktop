---
date: 2026-10-16
kind: execution-plan
status: active
task: m10-paid-acceptance-bound-20261016
brief: ../briefs/2026-10-16-m10-paid-acceptance-bound.md
---

# Bound additional M10 acceptance activity

## Classification, approved input and ownership

Substantial development: a temporary persistent admission guard and control
restoration cross behavior and data boundaries. Not a fast path. Approved brief
SHA256 `3d6d12e920ce2e67af6253806fae83643379a201ef28cacb085e18218376835a`;
actual brief review is retained in `paid-budget-boundary-brief-review/report.md` under
`/home/mal/worktrees/.evidence/m10-execution-20261016`. This boundary-aligned plan revision requires
a fresh plan reviewer APPROVED verdict before the M1 repair or dependent work.

One executor owns only `engine/scripts/m10_acceptance_budget.py`, narrow sibling
`m10_acceptance_budget_*.py` modules if necessary to keep the helper readable,
and `engine/tests/llm/test_m10_acceptance_budget*.py`. The lead owns scoped brief,
plan, evaluations, durable-doc reconciliation, artifacts and later operational
authority. The server owner retains billing source/release responsibility. The
runtime owner retains its three clone-cron maintenance locks and accepted service
descriptors. Its credit-stop handoff released the engine source/verification hold;
this does not grant cron ownership or establish successful ordinary acceptance.
No delegation split within the coupled helper/SQL/control implementation.

The helper is an operator tool outside the `zylch` package. Do not change product
modules, packaged resources, pyproject/dependencies, permanent model choices,
normal daily accounting or the reviewed engine wheel. Reuse `LLMClient`,
`BoundedProxyClient`, existing quote/receipt validation and real SQLite admission.
No new inference transport or funding stand-in. A concrete product dependency
requiring expansion returns to the lead for revised scope/review before editing.
Other sessions own concurrent changes; preserve them and all primary worktrees.

## Accounting contract and frozen allocations

The ceiling is USD5 of ADDITIONAL acceptance activity. It is not a cap on past
liabilities, unrelated consumers or a provider invoice. The approved inventory
found127 production open holds at25,180,581 micro-USD and24 Mario holds at4,820,134;
these are unresolved maxima, not established charges. Freeze current baseline
atomically at activation; those prior values are context, not activation authority.
The earlier unapproved proposal's all-old-holds-in-USD5 arithmetic is superseded.

For each database, freeze BOTH all existing reservation IDs R0 and all existing
usage IDs U0, with original identity/immutable-field hashes and schema binding.
Existing reservation calls remain historical even if a matching usage receipt
arrives AFTER activation. Only matching genuine settlement of that historical
reservation is excluded; an identity/receipt mismatch must refuse admission.
Its cost appears in a separately reported historical-liability account. U0 also
remains historical. Never dispatch/retry a baseline call in this acceptance run.

Inside every reservation insertion transaction compute:

    new_holds = sum(maximum for each open reservation whose ID is not in R0)
    new_spend = sum(conservative micro-USD for each usage whose ID is not in U0
                    AND is not attached to an R0 reservation)
    committed = new_holds + new_spend
    admit iff valid ledger/baseline/guard AND committed + NEW.maximum <= allocation

There is no date or age predicate. Every non-baseline unbound usage row also
counts conservatively; invalid/unaccountable rows refuse further admission.
Every new closed reservation requires its matching valid usage row. No missing,
malformed, unknown or uncertain outcome can free its maximum. Genuine new
settlement atomically replaces its hold with actual recorded cost. Replayed
settlement cannot be counted twice. Full actual overrun must still be recorded;
subsequent admission refuses, preserving the existing pricing-fault behavior.

Use integer micro-USD, validated finite nonnegative amounts, and safe overflow
handling. Freeze unique run/database/allocation IDs and exact database identity
in one manifest whose allocations sum to at most5,000,000. Proposed initial split:
production2,000,000; Mario2,000,000; private BYOK500,000; private real-credit500,000.
The lead may choose a different fixed split before activation within the same
ceiling. An activated allocation cannot be reset, duplicated, replenished or
reassigned because a run failed. The same manifest/baseline is resumed after a
crash. Backups/copies of activated stores must never become additional paid
execution targets under the same allocation. Other hosts/unguarded ledgers are
excluded. Exhaustion can prevent twenty answers; it never authorizes more spend.

## M1 — Implement the guard and prove actual admission

Dependency: approved plan. Owner: the single executor. No live data/config write.
Evidence: `paid-budget-plan/M1/` below the execution evidence root.

Implement inspect, activate/status and deactivate behavior in the existing
operator-helper surface above; explicit apply mode is required for mutations.
Inspection must not call engine database initialization, seed data, refresh auth,
contact providers, or create missing schema. Accept target paths/identities from
the manifest; never hard-code a company, UID, key or capability in source.

Activate under `BEGIN IMMEDIATE`: validate supported schema/identity, snapshot
R0/U0 and immutable values, bind run/allocation/schema, install exact owned
persistent BEFORE INSERT enforcement on `llm_reservations`, and commit together.
No connection-local Python UDF. The trigger runs within the unchanged engine's
existing serialized admission, before HTTP and before a proxy authorization can
survive a refused reservation. Missing/malformed control state, baseline drift,
inconsistent ledger, invalid amounts or unsupported schema refuse. Initialization
must refuse an existing incompatible/partial run, not silently reconstruct its
baseline. Resume validates the retained original baseline and trigger hashes.

Integrity must prevent or detect deleting/editing rows or markers that could
reopen allowance, including new reservations/usage. Use minimal owned integrity
objects/audit records as needed; do not rewrite product rows. Preserve legitimate
settled_at updates and all full actual-cost inserts, including breaches. Bind
new closed reservations to usage by ID and immutable owner/model/transport;
keep baseline late settlement historical. A guard must not suppress recording
an incurred charge merely because it exceeds allocation or the old reservation.
Do not invent SQL-authorized refunds or settle uncertain rows from timestamps.

Every reservation INSERT must encounter at least one intact effective INSERT
guard. All such guards validate the complete frozen owned schema and accounting;
include that enforcement in reservation capture as well as the two redundant
admission triggers. Add the independently demonstrated counterexample: after
filling an allocation, delete both admission triggers and retain capture; a new
reservation must refuse before wire/authorization. Exercise other single/multiple
object drift with an effective INSERT guard remaining. Helper status/resume must
refuse every missing expected object. Retain the failed independent probe.

Trusted DDL custody excludes a privileged actor removing EVERY effective
reservation-insert guard, even if unrelated usage/audit objects remain; SQL alone
cannot enforce admission after all its effective INSERT guards are removed.
Whole-store rollback at the same path, alternative manifests and extra paid
copies/hosts remain excluded. Do not describe this as detecting arbitrary partial
object deletion without the remaining-effective-guard condition. This reviewed
limit changes no USD5 allocation, baseline, settlement or no-replenishment rule.

Freeze usage-ID membership rather than subtracting large floating sums. Establish
one SQL-only conservative float-to-integer conversion, tested against production
`micro_usd(Decimal(str(value)))`, including sub-micro values, exact integers,
zero, binary boundaries, NaN/Infinity/NULL/negative inputs and overflow. Rounding
upward by a demonstrated small per-row allowance is acceptable; rounding below
the engine's estimate is not. Invalid new usage blocks the next admission while
remaining recorded; invalid historical data is separately reported, not repaired.

Create focused real SQLite/installed-client tests covering these independent
failure modes:

- R0/U0 capture is atomic with activation; an old hold settling later remains
  historical, while new bound AND unbound costs count regardless of timestamps.
- A new unknown hold counts after2days and across UTC midnight; genuine receipt
  settlement releases only its proven difference; absent/invalid receipt does not.
- Closed-without-usage and identity mismatches refuse; repeated valid settlement
  is idempotent; a full overrun remains stored and blocks subsequent dispatch.
- Threads and independently spawned processes sharing one database admit only
  affordable requests. An ordinary read-only multi-call RPC reaches scripted
  wire for affordable calls and refuses its later call before upstream dispatch.
- Proxy quote/execute through the real client uses full max debit/receipt,
  including markup and whole-credit rounding. A rejected reservation rolls back
  its billing authorization. Direct/OpenRouter use their existing request bounds.
- Restart/crash at activation/reservation/settlement boundaries preserves one
  baseline and every uncertain maximum. Partial/missing/wrong guard or schema,
  destructive ledger changes and duplicate allocation identity cannot reopen it.
- Four guarded database allocations compose to at most5,000,000, including
  concurrent activity; reproducing a private client never mints another budget.

The installed-client/RPC proof runs in a subprocess with `PRIVATE_PYTHON -I`,
loading only the helper by explicit path. Assert zylch/budget/client/RPC module
paths/hashes belong to the retained installed candidate. Its HTTP wire is scripted
and external networking denied. No source-PYTHONPATH test may substitute for that
artifact proof. Reuse existing read-only/cancel/credit fixtures without weakening
the ordinary dispatch path or treating synthetic receipts as real paid outcomes.

Gate: fresh M1 review approves helper/SQL hashes, numeric proof, actual installed
multi-call/refusal journey, cross-process/cross-database results and failure logs
before dependent activation/control packaging. Source repairs rerun affected
cases and return to this same milestone reviewer.

## M2 — Prove controls, installation and the execution packet

Dependency: M1 APPROVED. Owners: executor for helper/tests; lead for packet/docs.
Evidence: `paid-budget-plan/M2/`. Only disposable private stores/configuration.

Prove full helper lifecycle on disposable copies with realistic baseline sizes
and independent connections. Activation/restart must preserve original product
rows, permit genuine historical settlement without charging it as new activity,
and retain exact baseline/audit identity on resume. Bind unchanged369-module/
seven-resource installed artifact and helper/source/schema/manifest hashes.
A new product wheel is not needed; verify the existing wheel SHA256 remains
`3fb25d395d8896e3ba10baa2014aef96a6b602329e1f5da0f078771ae784b541`.

Control handling must preserve exact original bytes/values, presence, ownership
and modes for affected saved settings and preparation state. Malformed/duplicate
effective keys refuse. Saved cap0 is a paid-admission pause; automatic-update
and cron/preparation controls are separate. No environment-only override counts
as changing saved policy. A running daemon's cached auto-update setting must be
handled through an actually proved mechanism or a controlled restart in the
later authorized window, not assumed to notice an external file edit.

Ordinary settings.update is not compare-and-swap. Require an exclusive maintenance
lease with daemon/settings writers stopped or drained and scoped cron paused;
cooperative locks alone do not constrain unrelated writers. Under that proven
precondition compare exact expected file/state before atomic replacement or DB
update; recheck identity/modes afterward. Test conflict detection and recovery on
disposable copies, including a competing control edit before apply/restore.
Never overwrite detected drift or claim atomic CAS against an uncooperative
writer that the maintenance lease did not exclude.

Preparation restoration compares the exact owned state and restores only the
original affected flags/metadata under a transaction, without invoking
preparation.resume or starting processing. Preserve unrelated run statistics and
stop on changes. If exact safe restoration cannot be proved, keep a documented
pause. Test missing/present original state, already-paused profiles, original
model/provider retention, failed helper recovery and no backlog/model dispatch.
Exercise actual ownership/mode handling with private fixture files, including
refusal when the executor cannot preserve the deployment identity.

Produce a hash-bound four-allocation activation/teardown packet. Hosted targets
are only production UID Gn9IcuWzYyY7DBMHkVUGB7bIiTp2 and Mario UID
C06xHKoRcfdz94FaLPKuJuo0xVo1; private clients use actual installed LLMClient,
with the real business-bound proxy client for later credit acceptance. Never use
the old fake Firebase/StarChat driver as funding proof. No tokens outside RAM;
no credential/capability content in logs or receipts. Include source/schema/
config freshness, protected backups, held window/lock owner, allocations,
historical-vs-additional status, stop conditions, exact restoration and recovery.

Local closure: lead reconciles scoped durable docs and current living context,
preserving historical narrative; invoke doc-end, mechanical/focused checks,
explicit fresh documentation critic and separate final review against approved
brief/plan and immutable M1/M2 artifacts. Existing current-runtime final approval
does not cover this new helper. Only the completion checker advances its baseline.
Local closure records the helper ready; M3 paid/runtime obligations remain open.
M2 approval must not mark M3 or this overall execution plan complete while those
required outcomes are pending.

## Verification commands and retained environment

Use `/home/mal/worktrees/.evidence/m10-current-runtime-20261016/installed-candidate-venv/bin/python`
as PRIVATE_PYTHON. Run from candidate `engine/` with clean environment, private
HOME/ZYLCH_HOME/TMPDIR, placeholder credentials, no live DB/profile paths,
`PYTHONDONTWRITEBYTECODE=1`, and PYTHONPATH only for explicitly source-bound tests.
Use the retained guard at
`/home/mal/worktrees/.evidence/m10-server-context-20261016/network_guard.py` through
this invocation pattern, which was actually exercised by planning:

    PRIVATE_PYTHON -c 'import runpy; runpy.run_path("/home/mal/worktrees/.evidence/m10-server-context-20261016/network_guard.py", run_name="_m10_budget_network_guard")' -q -p no:cacheprovider tests/llm/test_m10_acceptance_budget*.py --junitxml=PRIVATE_EVIDENCE/milestone.xml

Expand the new owned test glob to actual existing files at execution. Record
actual argv, clean environment names, exit code, complete output and JUnit.
The original guard's direct-script entry recurses under multiprocessing spawn;
the non-main runpy invocation avoids that without editing the retained helper.
The installed subprocess test needs its own inherited no-network fixture as -I
removes PYTHONPATH; prove no external connect succeeds there too.

Rerun existing directly affected regressions:
`tests/llm/test_budget_ledger.py`, `test_budget_dispatch.py`,
`test_bounded_credit_dispatch.py`, `test_bounded_v2.py`, and
`tests/rpc/test_memory_readonly.py`, using the same command/environment pattern.
Run Ruff/Black check and py_compile on new owned helper/tests only, then git diff
--check. Retain the actual source-snapshot hashes; do not rebuild/retest unrelated
product/server suites without an affected change. Prior54 engine and5 server
budget-driver tests are supporting seam evidence, not proof of this new guard.

## M3 — Conditional paid acceptance and operational restoration

Dependency: local M2/critic/final APPROVED, actual paid/live-control authority,
released runtime/Stripe maintenance window and fresh accepted full runtime/
config descriptor. Owner: lead. No M3 effect is authorized by this plan alone.
Respect any current maintenance window and retained cron locks; independent local
implementation can continue. Successful ordinary operational acceptance remains
required by the rollout packet and has not been established.

Recheck exact source/package/config/DB/control identities and required backup
space. Stop/own paid intake, preparation, auto-update and scoped cron; drain work
without deleting holds. Activate each unique allocation under atomic current
R0/U0 capture, validate trigger/manifest identity from another connection, and
only then enable owned paid requests. A changed accepted runtime reopens its
necessary preservation evidence. Do not use stale V8 descriptors or override
another owner's maintenance locks.

Execute private direct/real-credit checks and the twenty independent ordinary
read-only company questions sequentially, keeping saved models/providers. Bind
real Firebase/business/funding and validated receipts; reconcile uncertain credit
receipts by status only. A cap refusal stops the phase with incomplete acceptance
explicit; no model change, top-up, allocation increase, retry or memory rewrite.
Source-grounded answer grading remains the separate required quality gate.

Teardown closes paid intake/saved admission and cancels/disconnects owned turns,
then waits actual dispatch threads idle. Record final additional spending/holds
and separate historical liabilities. Validate exact owned trigger definitions
before removal; drop only owned enforcement objects, retain baseline/audit
records and every original ledger row. Never reset to get another allowance.
Restore unchanged controls by proved CAS without backlog launch, when their
owners authorize normal activity. On failure/drift leave the restrictive guard/
pause in place, record the precise recovery obligation, and preserve uncertainty.
No DB rollback may erase calls, receipts, memories or unrelated concurrent work.

## What this establishes and what remains open

M1/M2 establish a reviewed operator-only temporary admission/control mechanism,
unchanged product artifact and a concrete bounded execution/rollback packet.
They do not establish real funding/payment correctness, twenty correct answers,
protected clone operations, accepted engine canary or live rollback. M3 remains
conditional required rollout work even if local implementation is completed.
The USD5 claim covers only additional activity in the four declared guarded
ledgers. Historical liabilities, Claude headless reasoning, kernel direct
classifiers, other hosts/copies and any unguarded client remain outside it.
