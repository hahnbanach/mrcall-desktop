---
status: completed
---

# Explicit task assignment — local delivery

Approved intent: [brief](../briefs/2026-10-08-explicit-task-assignment.md).
Fresh brief review APPROVED: persistent fanout recovery evidence,
`engine-assignment-brief-review.txt` and immutable approved brief/hash JSON.
Operator chose engine task assignment on 2026-10-08. No release or installation.

## Dependencies and starting verification

The approved kernel ownership design supplies lifecycle requirements. Its original
review and all recovered fanout evidence remain retained independently. New source
investigation is `engine-assignment-contracts.txt` in the same persistent directory.
Existing private task ownership is email-based; all new actor identities use
verified Firebase UIDs. Current company ProjectSpace provides immutable space ID.
No existing approval RPC provides independent human authority.

Before source edits, run engine `venv/bin/python -m pytest -q` for
`tests/storage/test_tasks_create_close.py`, `tests/storage/test_task_due.py`,
`tests/rpc/test_task_transport_contract.py`, `tests/memory/test_projects.py`,
`tests/qonto/test_tasks.py`, `tests/qonto/test_session_admission.py` and
`tests/provisiond/test_company_map.py`. Preserve actual output/exit in persistent
evidence. System Python lacks SQLAlchemy; use the existing engine venv instead.

## Ownership and contract

Lead owns brief, plan, durable reconciliation, review/completion records and
integration decisions. One execute worker owns M1 new assignment models, services,
trust/signer code and their tests, plus narrow store-install/join hooks. A later
execute worker owns M2 RPC/CLI/evidence and kernel consumers under the reviewed
engine contract. They are not alone in the codebase and must preserve foreign
changes. No source work begins before fresh plan APPROVED; M2 waits for M1 review.
All new Python modules stay below 500 lines; split by responsibility if needed.

Private ordinary TaskItem, financial predicates and default tasks.* APIs stay
unchanged. Add company `AssignedTask`, `AssignedTaskEvent`, `AssignedTaskReceipt`
models to company table bindings and migration installation. Exact RFC thread key
is a bounded normalized root message ID. One current row per space/thread with
immutable task ID; all generations/reassignments remain in events. Store no mail
body, company key or finance source in shared rows. State: assigned or closed;
needs-assignment and later-inbound states are computed read projections, not
unattended assignment mutations. Explicit human assignment can use a thread even
without a detected answer, but must never label that action detected-by-answer.

RPC reads derive verified live actor from session/token/profile owner and require
trusted membership matching bound company space. Reads return completeness,
state and audit with explicit unavailable/refusal, never soft-null on failure.
Preview builds a canonical versioned operation with authenticated actor, space,
thread/task ID, expected revision, assignee, close cutoff/reason/handled record
where applicable, operation ID and expiry. It is nonmutating. Commit verifies an
operator grant for exactly that operation. Assignment/reassignment/close use
first-statement SQLite writer lock, same-transaction membership/binding/CAS checks,
nonce/operation receipts and audit. Same operation ID with identical payload
returns the original acknowledgement; conflicting bytes or nonce reuse fail.
Receipt replay still requires current valid identity and membership. No network,
model inference or expensive mail scan while holding the writer lock.

Trust is an operator-managed per-company document at a fixed privileged path
(or a configuration path whose complete ancestry and file ownership/modes are
validated). It carries schema/version, issuer, immutable company space, public
Ed25519 verification key and current member UID/alias mapping. Never expose a
global company map or secret capability. Reject symlinks and writable/untrusted
ancestors; root-owned files cannot be overridden with tenant-controlled env paths.
Signer private key is separate, root-only, and never loaded by engine. Standalone
host-operator command checks effective OS authority, validates trust/membership,
displays the canonical intent and confirms the exact action before signing a
short-lived nonce-bearing grant. No signer RPC, generic chat approval bypass,
NOPASSWD policy, installation or key generation in real host config. Offline
process fixtures create their own isolated keys/config and exercise permissions;
test seams must not create a production trust bypass. Read-only policy rejects
commits even with a valid grant. Scheduled/raw clients without the separately
approved grant are denied regardless of caller flags.

## M1 — Company task persistence and independent approval

Implement additive company models and installation; current-space binding;
neutral verified identity and trusted membership; canonical intent/grant validation;
privileged operator signing command; transactional store read/assign/reassign/close,
receipts and audit. Block company join before writes if source has assignment
state/history (also incomplete schemas). Retain history on disable/downgrade;
old clients ignore the new subtype. Assignment state must never be imported by
ordinary memory joins accidentally.

Verify real SQLite fixtures: same company two actors versus outsider; ordinary
and finance tables untouched; CAS concurrent assign/reassign/close exactly one
winner; duplicate unchanged replay versus conflicting payload; nonce tampering,
expired/untrusted/revoked membership; switched store/profile; atomic rollback;
closed audit retained after restart; join refuses before env/profile/store edits.
Verify signer-to-verifier with real Ed25519, protected-file refusals and no
unprivileged signing entry. Run existing baseline regressions after narrow hooks.
Fresh M1 review covers source, actual logs and all security/privacy assertions.

## M2 — User entry points, real evidence and kernel integration

Expose bounded `tasks.assignment.list/get/preview/commit/project` methods through
the real dispatcher. Read projection joins stored assignment audit with current
inbound/answer evidence; source judgement stays in engine. Validate actual Sent,
RFC thread and recipient plus engine reply/auto-reply judgement from synced mail.
There is no existing outbound human-authorship classifier: auto-reply false is
not proof. For a member reply without supervised confirmation, project UNKNOWN
with an explicit needs-human-verification reason and hold action in the visible
needs-assignment queue. The operator grant may explicitly confirm that exact
source as human when assigning, after engine validates live Sent/thread/recipient
and rules out known automation. The engine records supervised confirmation
provenance; it never labels this autonomous detection. Do not introduce a new paid
classifier or mark all nonautomatic replies human. Return UNKNOWN if
message/classification/membership is unavailable. Kernel adds
only a projection carrying actual Sent folder/provenance from existing batched
reader; preserve scopes 1–5 return bytes, no second per-message reader. Candidate
source is untrusted input until engine validates against its own synced records.
Do not treat negative auto-reply detection alone as proof of human authorship.

Concrete source path: add owner-authenticated `tasks.assignment.reply_evidence`
RPC on each configured peer engine. It resolves scoped DB message IDs itself,
selects that owner's mailbox via `mailboxes.for_owner/by_id` and
`build_imap_client`, discovers the actual Sent folder with `_find_sent_folder`,
then `scan_folder` with safely validated/quoted exact RFC Message-ID criteria
and `fetch_messages_by_uid` using BODY.PEEK. Require successful search/fetch,
exact source ID/thread/recipients and stable UIDVALIDITY on re-EXAMINE; disconnect
in finally. Missing Sent, partial fetch, unavailable mailbox, changed UIDVALIDITY
or unverified scoped message produces UNKNOWN, never source success. Extract and
reuse archive header/product-sentinel auto-reply checks as a pure helper. Return
only source metadata/candidate/automatic/unknown; no credentials/body. Kernel
queries each configured peer with its existing authenticated RPC adapter and
merges projections, not arbitrary supplied proof. A grant confirms an exact
source ID/projection digest; changes invalidate it. Commit independently validates
source on the owning engine when assigning by answer. Cross-peer unverified proof
cannot be used as detected-by-answer authority: until independently verified,
only an explicit human assignment (labelled as such) is available.

Watermark is a canonical set/digest of exact inbound RFC message identities with
provider UIDVALIDITY/UID and scoped store message IDs; timestamps are annotations,
never the unique ordering/cutoff. Include every known inbound at a shared timestamp.
For close preview, obtain a complete live provider thread snapshot (including
archived inbound from the appropriate all-mail/archive source, not INBOX alone)
outside the writer lock; record its digest plus exact covered inbound IDs and
observation time in the intent. Repeat the snapshot immediately before commit;
changed/incomplete/unavailable source refuses closure. Re-read current synced
inbound identity set inside the CAS transaction and reject uncovered rows or
changed profile/company binding; no provider IO under lock. The close receipt
states exactly which messages were covered as of that verified observation, not
that a server cannot receive a subsequent email. A new inbound identity absent
from the closed covered set reopens operator work even at the same/older Date
header; it never restores the old assignee. If fresh source scope cannot establish
coverage, project UNKNOWN/held. Tests inject intervening inbound, same-second
messages, delayed ingestion with old Date, partial sync and changed UIDVALIDITY;
none may disappear behind a timestamp-only handled record. Source freshness is
bounded to the exact intent lifetime; no unbounded cached evidence acceptance.


Wire explicit kernel preview/export/commit commands for assign/reassign/close;
no kernel ownership persistence. Deny named mutation/approval surfaces in all six
cron spellings; engine grant validation remains the real boundary. Preserve
ordinary escalation authority. Handled integration closes only exact assignment
ID/revision/cutoff and records acknowledged result; failure remains visible and
held, and local handled records alone cannot settle ownership.

Unanswered/review/dossier consume the same typed engine projection: normal,
needs-assignment, assigned, conflict, unknown, closed, later-inbound. Keep human
work visible in a separate queue; later inbound after close returns operator
work and does not revive old assignment. Active assignment keeps later inbound
with its human. Escalation and assignment agree render both reasons once;
disagreement holds action. Triage must respect these states before drop/draft.
Do not duplicate reply classification in the kernel.

Verify actual raw/stdio and authenticated WebSocket dispatch with isolated mail,
company stores and signer fixtures; full CLI lifecycle including retained unknown,
conflict, handled acknowledgement/failure and later inbound; malicious caller
UID/evidence/grant/source JSON refuses. Prove unchanged ordinary/Qonto transport.
Any canonical skill changes require actual execution on all three hosts, preserving
byte identity and full reads; extend existing native fixtures only as needed.
Run scoped engine tests, kernel full `bash tests/run.sh`, fresh installed-package
checks and template/permission gates. Fresh M2 integration review before closure.

## M3 — Documentation and final-user closure

Lead reconciles task-management as-built docs, new assignment operational guide,
IPC routing/contract inventory if needed, affected identity/company/approval docs,
root/kernel/Desktop gap/plan status and living snapshots with verbatim archives.
Old ownership design is a reviewed historical design, not an as-built claim.
Record selected mechanism and exact local availability/production configuration
limits. Do not manufacture erased historical receipts or live clone acceptance.

Run doc-end for each affected repository: real completion records with immutable
brief/plan/milestone versions, personally held startup, impact and reconciliation,
mechanical/keyword/size ledger, final focused real-user check, fresh doc-critic
including all living-context shapes, pre-review readiness and separate fresh final
review. Finalize only records whose actual obligations pass. The original root
umbrella stays active for live both-clone FULL acceptance/latency where required;
this local implementation plan can finish its verified local scope independently.

## Rollback and pending external obligations

Disable assignment trust to deny writes while retaining task/event/receipt data.
Revert only owned source hunks; never drop tables or reset foreign work. Company
join must continue refusing assignment-bearing stores on rollback; document that
older versions lacking this guard cannot safely perform such joins. No release,
clone pin, installed app, live mail, keys, company membership or production service
changes. Live Sent/recipient thread parity, real mailbox latency and both-clone
FULL acceptance remain separate authorized release obligations.

## Local verification record — 2026-10-08

M1 has fresh independent APPROVED evidence at the persistent recovery directory's
`assignment-m1-review.txt`; its immutable approved source and plan are retained.
The final frozen engine regression run exits 0: 280 tests pass, with all 17 M2
source hashes unchanged (`assignment-engine-m2/expanded-final-result.json`).
Actual stdio and authenticated WebSocket fixtures cover grant refusal, assignment,
closure and exact-identity reopening; private ordinary/Qonto regressions pass.
The independent WAL writer fixture verifies the private-store reservation during
locked closure validation. Scoped chat reaches the actual guarded draft insert.

Kernel K1 is independently APPROVED (`assignment-k1-review/final-review.txt`):
15 focused commands and 13 independently repeated real CLI/WebSocket/SQLite
lifecycle commands pass. The final kernel suite exits 0 with all gates green;
all 173 frozen source entries match. Nine native cases pass across Claude, Codex
and OpenCode with complete canonical reads, held UNKNOWN, retained audit and
unchanged product state. Six harmless-command classification corrections retain
their original raw results; an aborted duplicate is excluded. The first two
cases retain computed equality checks without full persisted before maps.

Fresh K2 integration is APPROVED (`assignment-k2-review/final-review.txt`), followed
by fresh M2 integration APPROVED (`assignment-m2-review/final-review.txt`). Their
immutable artifacts and actual source/log comparisons are retained. Documentation
and separate final-user closure use the completion record; only checker finalization
transitions this local plan to completed. No release or live configuration is included.
Live provider body/search success is not established by native fixture failures.
