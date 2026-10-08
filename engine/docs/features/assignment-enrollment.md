# Assignment enrollment and legacy recovery

This contract describes local, unreleased contextual-email enforcement. Desktop
`v0.1.56`, kernel `v0.51.0` and their hosted activations retain the previous scoped
reply policy. This development does not activate or migrate a live company.

## Durable applicability

The company store holds one versioned `assignment_enrollment` row, bound to its
immutable `ProjectSpace.space_id`. Its provenance records the original schema
inspection and subsequent authority or join decisions.

| State | Contextual email behavior |
|---|---|
| `never-enabled` | Validate exact reply source and current profile; serialize the effect with enrollment. Root-owned assignment trust is unnecessary. |
| `managed` | Require current trusted company membership and complete exact-thread authority before writing or sending a reply. Missing or revoked trust holds replies even with an empty assignment ledger. |
| `legacy-unknown` | Hold contextual effects until trusted offline classification or privileged enrollment. |

Managed enrollment cannot be downgraded through application or maintenance APIs.
Removing trust does not remove enrollment, assignments, events or receipts.
Missing, unreadable or mismatched enrollment does not establish compatibility.
Genuinely source-free standalone email retains its existing approval rules;
removing headers from an already bound reply does not make it standalone.

Before additive company-table creation, startup retains pre-install schema
inspection under the memory migration lock. A new company or a complete store
with none of the three assignment tables can start never-enabled. Creation of
its ProjectSpace and binding of the enrollment receipt share one transaction.
Previously present assignment tables without a marker, history or usable trust
are ambiguous. Partial schemas and unavailable inspection do not establish
never-enabled status. Restart preserves the retained inspection evidence.
Existing valid trust or any task/event/receipt history latches managed before
serving contextual work. Unexpected trust during a never-enabled effect refuses
and requires trusted enrollment; tenant calls do not activate authority.

## Privileged enrollment

Use the candidate engine environment and reviewed source. Independently prepare
a root-owned public trust JSON with the exact company space, verification key and
member aliases specified in [task assignments](task-assignment.md). Retain a
company-store backup and verify its actual space before activation.

From the engine directory, the independent root operator runs:

```bash
python scripts/server/assignment_enroll.py \
  --store /absolute/path/to/company.sqlite \
  --space-id COMPANY_SPACE_UUID \
  --trust-json /absolute/root-owned/public-trust.json
```

The script refuses unprivileged execution before file access. It validates the
existing store and exact immutable space, commits managed enrollment under the
company writer lock, then publishes trust under another company writer lock.
A failed publication leaves the committed managed latch and blocks contextual
replies until valid trust is restored. Do not install or replace trust directly:
that bypasses the supported ordering with concurrent email effects.

Public trust remains at `/etc/mrcalld/assignment-trust/<space-id>.json`; the
independent signing key remains at its separate privileged path. This operation
installs no private signing key and grants no authority through a chat approval.
Do not remove enrollment or history to recover from a failed installation.

## One-time offline legacy classification

An empty assignment-capable legacy database with absent trust cannot prove that
assignments were never enabled. Classification requires independent trusted
historical knowledge. For a genuinely local store, its trusted filesystem/data
owner supplies that knowledge. For a hosted store, use the independent privileged
host operator; the daemon's tenant identity is insufficient.

There is no classification RPC, chat flag or tenant maintenance command.
`task_assignment_enrollment.classify_locked` is a direct database-writer
maintenance primitive. It has the same trust boundary as direct SQL access; it
is not protection against a trusted writer changing the database.

Stop competing profile processes, retain a backup, and independently identify
the physical company database and its actual ProjectSpace UUID. Using the
reviewed engine source, open that database and a write transaction. Acquire its
SQLite writer lock by updating ProjectSpace to its existing value, check the
exact expected UUID, then call `classify_locked(connection, space_id,
attestation)` and commit only on success. Supply a concrete historical
attestation of 20–1000 characters explaining why this company never had
assignment authority. A missing file alone is not that attestation.

The primitive accepts only legacy-unknown enrollment with complete readable
assignment schemas, no tasks/events/receipts and safely inspected absent trust.
Malformed trust, unsafe paths, permission errors and other inspection failures
refuse. The retained provenance includes the explicit attestation. Managed
companies cannot use this procedure, and it erases no history. A host operator
may instead enroll an ambiguous company as managed.

## Company joins and rollback

Assignment-bearing or incomplete-schema source stores retain their existing
join refusal. History-free joins preserve the stricter enrollment in the
actual destination space: managed, then legacy-unknown, then never-enabled.
The destination enrollment and join receipt retain source classification
provenance inside the existing import transaction. Joining memory does not
provision assignment membership; destination trust requires independent review.

Retain enrollment, assignment audit and private draft history during rollback.
Older binaries reopen the generic contextual-reply gap and must not activate
assignment authority or perform joins involving managed stores.
