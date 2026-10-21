# Temporary M10 acceptance spending guard

Scope: the operator-only helper in `engine/scripts/m10_acceptance_budget.py` and
its SQL sibling. It is outside the engine package and normal Settings/RPC API.
M1 has independent source/installed-client approval; saved-control installation
and restoration have independently approved M2 implementation and packet evidence.
No live ledger is guarded yet.
The [plan](../../../docs/execution-plans/2026-10-16-m10-paid-acceptance-bound.md)
owns actual evidence and remaining paid/runtime authority.

## What the ceiling means

The reviewed ceiling is USD5 of additional acceptance activity across exactly
four named ledger allocations. It is not a cap on historical unknown liabilities,
other hosts/ledgers, headless Claude, kernel classifiers or a provider invoice.
Saved daily budgets remain a separate bound; UTC reset and hold aging in normal
accounting cannot reset this cumulative guard.

One immutable manifest binds run ID and four unique allocation IDs, canonical
absolute database paths, owner IDs, device/inode identities and positive integer
micro-USD amounts summing to at most5,000,000. Each allocation has the fields
`allocation_id`, `path`, `owner_id`, `micro_usd`, `device` and `inode`. The helper
refuses duplicates, aliases, changed identities and unsupported ledger schema.
It initializes no product database and reads no credentials or provider endpoint.

Activation freezes every pre-existing reservation ID R0 and usage ID U0, with
immutable projections and schema bindings, inside BEGIN IMMEDIATE. Historical
rows remain untouched. Their uncertainty is reported separately, including old
open maxima and invalid historical values. A genuine late settlement of an R0
reservation remains historical; its arrival cannot be relabeled new activity.

Every new open reservation counts at its maximum regardless of age/date. Genuine
matching settlement atomically replaces it with recorded cost; missing or
mismatched receipts cannot free the maximum. New unbound usage also counts.
Positive stored amounts use a conservative SQL-only conversion with at most two
extra micro-USD per row in the supported numeric range; invalid/unaccountable
new values block admission rather than being repaired. Full actual overrun stays
recorded and blocks further dispatch. No timeout, retry, reset, copy or failed
run replenishes an activated allocation.

## Persistent enforcement and its limit

Three effective reservation-insert triggers independently validate frozen schema
before consulting integrity/accounting views. Each remaining trigger refuses
missing/modified owned objects. Capture includes the post-insert maximum in its
check; BEFORE triggers include the proposed maximum. Actual SDK and bounded-proxy
proof confirms refusal before provider execute and rollback of an uncommitted
credit authorization. Existing ledger/audit mirrors cannot be silently deleted
or rewritten through normal DML.

This relies on trusted maintenance: deliberately removing every effective INSERT
guard or forging/replacing the authoritative baseline/binding evidence can defeat
SQL-only enforcement. Whole-store rollback, alternate manifests and paid copies
are excluded too. This is not tamper-proof storage against the database owner.
Status/resume refuse incomplete state; ordinary object/view drift is tested while
an effective INSERT guard remains. Independent deletion and view-substitution
counterexamples were retained and fixed before approval.

## Saved controls and maintenance

`m10_acceptance_budget_controls.py` and its file/SQL siblings provide `capture`,
`pause`, `admit`, `restore` and read-only `status`. Mutations require `--apply`,
an exact protected journal and an externally established maintenance lease.
The lease identifies its live holder PID/start, exact targets, stopped/reaped
writers and real daemon/settings/cron exclusion evidence. Its booleans and the
helper flock cannot establish exclusion from unrelated processes.

Capture retains original bytes/presence/hash/UID/GID/mode and preparation state in
protected files. Pause writes saved budget0/auto-updaten and only the exact owned
preparation flags. Malformed/duplicate settings, competing file/SQL edits or changed
identity refuse. Same-run journals support interrupted apply/admit/restore without
resetting their originals. Unknown drift keeps the restrictive maintenance pause.

Admit requires ALL FOUR exact active/accountable allocations, then restores only
the original saved daily budget while auto-update/preparation stay paused. An
original zero budget stays refused. A controlled process restart is necessary to
load changed auto-update state; a running daemon's cached environment is not CAS.
Before another control mutation its writers must again be stopped/reaped under
fresh actual lease evidence. Saved daily limits never become the USD5 task bound.

Pause/drain all owned intake before removing any guard. Restore compares the
owned exact state, preserves unrelated statistics and never invokes
`preparation.resume`. On drift retain the pause and protected recovery evidence.
Actual activation and restoration remain conditional on the concrete reviewed
packet and live authority; the local47-case lifecycle uses disposable stores.

## Commands and lifecycle

Pass a private hash-reviewed manifest and one allocation ID:

```bash
python engine/scripts/m10_acceptance_budget.py inspect --manifest MANIFEST --allocation ID
python engine/scripts/m10_acceptance_budget.py activate --manifest MANIFEST --allocation ID --apply
python engine/scripts/m10_acceptance_budget.py status --manifest MANIFEST --allocation ID
python engine/scripts/m10_acceptance_budget.py deactivate --manifest MANIFEST --allocation ID --apply --intake-stopped
```

Inspect/status are read-only. Without `--apply`, mutation commands inspect only.
An active exact allocation resumes its original baseline; a deactivated one cannot
reactivate. Activation is not permission to dispatch: all four guards, current
artifact/configuration identity, actual stopped/drained background/cron ownership
and saved-control handling must be verified first. M2 owns those controls.

Deactivation validates exact owned definitions and drops only owned enforcement
triggers on product-ledger tables. It preserves primary rows, baseline, immutable
mirrors and activation/deactivation evidence. `--intake-stopped` is an operator
assertion, not proof of actual drain. Collect final additional spending/holds and
separate historical exposure first. A failed/changed restoration leaves a named
restrictive pause and recovery obligation; no database rollback erases effects.
Never invoke preparation.resume as an inert restore: it starts bounded analysis.

The installed-client test is explicitly configured through
`M10_ACCEPTANCE_ARTIFACT_PYTHON`. Generic CI skips that opt-in proof when absent;
manual acceptance requires the exact artifact and zero skipped cases. The
[evaluation](../../../docs/evaluations/2026-10-16-m10-paid-acceptance-admission.md)
retains actual86-case evidence and twelve independent checks. Real funding,
provider/credit receipts, company-answer quality, clone operations and live
canary/rollback remain separate required acceptance.
