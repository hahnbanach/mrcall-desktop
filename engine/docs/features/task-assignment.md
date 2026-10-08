# Company task assignments

## Availability and authority

The explicit company task subtype is local source work. Signed operations,
RPC, mail-provider protocol fixtures and scoped draft enforcement have executable
local acceptance. The delivery plan owns current milestone and native-workflow
verification. No production trust files, keys, membership,
clone pins or installed clients are changed by this work. The
[delivery plan](../../../docs/execution-plans/2026-10-08-explicit-task-assignment.md)
owns verification status and remaining release acceptance.

Private [ordinary tasks](task-management.md), including Qonto financial rows,
retain their own storage and visibility. Assignment records share only company
space, exact RFC thread identity, stable actor/assignee UIDs, revision, covered
inbound identities and audit. They contain no message body or company capability.
`assigned_tasks` holds the current row; `assigned_task_events` retains operations;
`assigned_task_receipts` retains exact retry acknowledgements.

## Operator configuration

The engine reads public trust at the fixed path
`/etc/mrcalld/assignment-trust/<space-id>.json`. Version 1 requires exactly:

```json
{
  "version": 1,
  "issuer": "host-operator",
  "space_id": "<company ProjectSpace UUID>",
  "public_key": "<base64 raw Ed25519 public key>",
  "members": {
    "<Firebase UID>": ["person@example.com"]
  }
}
```

Aliases are unique normalized mailbox addresses. The document must match the
bound company space. The file and every parent directory must be root-owned,
non-symlinked and not group/world writable. There is no tenant-controlled path
override. Missing, malformed, revoked or unsafe trust refuses assignment access;
it never means an empty authoritative assignment ledger.

The independent signer reads
`/etc/mrcalld/assignment-signing/<issuer>.pem`. It must contain the matching
Ed25519 private key, be root-owned and exclude all group/other permissions.
The engine needs public verification material only. Creating/installing these
files and enabling real users require separately authorized host operations.

`engine/scripts/server/assignment_approve.py` accepts one exported intent JSON.
Run it with the engine Python environment under the independent host operator's
root authority. It displays the whole intent on stderr and requires the literal
`APPROVE` before emitting the signed grant JSON on stdout. It refuses unprivileged
execution. This is a separate OS authority, not a TTY check or chat approval;
there is no signing RPC or tenant key. Grants expire with the exact intent,
whose lifetime is at most five minutes.

## Mutation contract

Assignment, reassignment and close bind verified Firebase actor, company space,
thread/task identity, expected revision and the complete operation payload.
Source confirmation and close coverage, when present, are part of that payload.
A first-statement SQLite writer lock covers final membership/binding/revision
checks, mutation, audit and nonce consumption. Provider IO happens outside it.

An unchanged operation/grant retry returns its stored receipt, including after
intent expiry, only with current valid identity, membership and verification key.
Changed bytes, consumed nonce for another operation, stale revision, revoked
membership, wrong company or invalid signature refuse. Read-only requests cannot
commit even with a valid grant. Caller `actor`, `interactive` or approval flags
cannot replace independently signed authority.

Direct filesystem writers with company-database write access remain trusted.
The grant protects the API mutation boundary; it is not tamper-proof storage
against root or other trusted local database writers.

## Evidence and lifecycle

A nonautomatic message is not proof that a human wrote it. The engine must
validate its own scoped message against the owner's actual Sent folder, exact
RFC identity/thread/recipients and stable provider UIDVALIDITY, and reuse the
archive's automation checks. An unconfirmed member reply remains a held
candidate needing human verification. A separately signed exact-source
confirmation records supervised provenance. Manual assignment is explicit
operator authority and is labelled separately from answer confirmation.

Close requires nonempty complete fresh inbound identity coverage, including archived mail.
It rechecks source immediately before commit and rechecks private-store identities
inside the company CAS transaction. Dates are annotations, not a closure cutoff:
a later new identity with the same or older Date returns operator work without
restoring the previous assignee. Active assignment retains later inbound with
its human. Incomplete or conflicting evidence remains visible and held.

Close is scoped to the original creator/source owner's authenticated engine;
another member's empty private mailbox cannot establish closure coverage.
Company-wide assignment reads do not expose private mailbox rows. A local kernel
handled record alone cannot close ownership; only the exact engine acknowledgement
can settle it, and failed acknowledgement leaves held work visible.

## Joins and rollback

Company joins refuse source stores containing assignment state or history, and
incomplete assignment schemas, before profile/env/store changes. A separately
reviewed lossless history migration is required to lift this restriction.
Disabling trust denies access/mutations without deleting assignment history or
receipts. Older builds without this join guard must not perform joins involving
assignment-bearing stores. Rollback retains all assignment tables and audit.

Offline source/SQLite/RPC fixtures establish their observed cases. They do not
prove production key permissions, real mailbox parity/latency, installed Desktop
behavior or FULL acceptance on both maintained clones.
