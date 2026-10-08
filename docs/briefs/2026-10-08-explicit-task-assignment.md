# Explicit company task assignment

Date: 2026-10-08. Implementation brief; release and production enablement excluded.

## Intent and authority

The operator selected explicit assignments in engine tasks after review of the
kernel's [human ownership design](../../../cs-kernel/docs/2026-10-07-human-thread-ownership-design.md).
The October 6 fan-out work must keep real human answers visible for assignment,
hold automatic replies, and close ownership only after an authoritative engine
acknowledgement. Complete the locally implementable engine and kernel contract.

## Present evidence

Ordinary TaskItem rows live in private profile stores; their legacy owner ID is
an email, not a stable human UID. They have neither company ownership nor CAS.
Moving them wholesale would expose ordinary and financial tasks. Firebase proves
account identity, not human presence: raw clients can call existing chat approval.
Hosted membership is maintained in a privileged UID/company map inaccessible to
tenants. Local same-user processes cannot prove distinct human origin by TTY or
caller flags. The bounded source investigation is retained in the persistent
fanout recovery evidence directory, engine-assignment-contracts.txt.

## Scope and decisions

Extend the engine task domain with an explicit company-assigned task subtype,
company-bound tables and tasks.assignment.* methods. Preserve existing private
TaskItem storage and ordinary/Qonto APIs. No kernel-local ownership ledger.
Use immutable company space ID, stable Firebase actor/assignee UID, exact RFC
thread identity, inbound watermark, revision, state and append-only events.
Complete reads distinguish authoritative absence from unavailable scope and
include closed audit. Pending assignment remains visible with auto reply held.

A privileged host-operator approval command signs one exact short-lived operation
using Ed25519 from the existing cryptography dependency. The engine has public
verification material only. The approval binds actor, company space, thread,
operation, expected revision, assignee, payload digest, expiry and nonce. A trusted
operator-managed membership document binds stable UIDs to company space and
mailbox aliases; unavailable, revoked or cross-company membership refuses. The
operator command independently checks membership before signing. It displays the
exact operation and requires explicit confirmation; the filesystem/OS authority,
not the confirmation flag or TTY, separates it from tenant and scheduled users.

Trust configuration and signer private files must be root-owned, non-symlinked,
not tenant-writable/readable as appropriate, with trusted parent directories.
Hosted tenant cannot mint a grant. Local writes require the same independent
privileged boundary; absent configuration fails closed. A same-token client may
submit a genuine grant only for its exact already approved operation once.
No claim of identifying the submitting process or of protecting against a trusted
root/operator job. No deployment, key installation, sudo policy or live membership
change is authorized here. Offline fixtures exercise the complete path.

Mutations atomically validate current identity, membership, company binding,
expected revision and operation; consume the grant and append audit together.
Identical retries return their original receipt; changed payload/reused nonce
refuse. Evidence/projection can never override a human assignment. Handled close
requires exact assignment ID/revision/cutoff acknowledgement. Later inbound
returns operator work without restoring the previous assignee. Unknown mail or
identity keeps work held. Joining company stores with assignment history must
refuse before any mutation until a separately reviewed lossless merge exists.

Kernel detection is read-only: reuse bounded source readers, actual Sent provenance,
exact RFC thread/recipient and the engine human-reply judgement. Address contact,
arbitrary source JSON or header From alone cannot establish human takeover.
Expose explicit preview, assignment/close acknowledgement and needs-assignment
projection through the existing CLI/RPC boundary; scheduled handlers must not
mint approval or mutate ownership. Preserve existing row contracts and explicit
uncertainty. Do not add paid calls inside database transactions.

## Acceptance

- A real SQLite/RPC journey with two same-company profiles and one outsider
  proves shared assigned tasks while private ordinary/Qonto tasks remain private.
- Authenticated actor comes from verified session, not caller actor/owner fields;
  current membership and company binding are rechecked for reads and commits.
- Operator command exports a signed exact grant; public commit verifies it.
  Raw/scheduled/read-only callers cannot mint grants or forge identity. Invalid
  signatures, writable trust files, expiry, revocation, switched company, payload
  tampering, stale revisions and nonce reuse refuse without state/audit changes.
- Concurrent assign/reassign/close/inbound and restart/replay checks prove CAS,
  human priority, atomic rollback, unique thread authority and retained audit.
- Real Sent/thread/recipient evidence produces held pending assignment; outbox to
  others, stale answers, incomplete scope and auto replies cannot establish it.
  Explicit handled acknowledgement closes the assignment; later inbound produces
  unassigned operator work. Failed acknowledgement remains held and visible.
- Company-join preflight refuses before profile/env/store changes if assignment
  history exists. Existing task, finance, project and transport regressions pass.
- Kernel/engine integration has executable offline transport acceptance, docs
  reconciled to actual available configuration, fresh milestone/doc/final reviews.
  No installed/fleet/live acceptance is implied.

## Constraints, assumptions and rollback

Keep new modules below 500 lines, English docs, secret-safe logging, no company
special cases or changes to ordinary task defaults. Additive company schema only;
retain history and receipts on rollback. Old clients ignore the new subtype.
Disabling trust denies new mutations without erasing data. Downgrade with existing
assignment history must refuse company joins, not silently abandon records.
An independent privileged operator boundary is required for real write enablement;
local fixture verification is not production activation. Existing historical
architecture/task docs contain stale mono-user and JSON-cache claims: reconcile
only the affected task/identity contracts, preserve unrelated work.
