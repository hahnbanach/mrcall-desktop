---
status: completed
---

# MrCall company memory sharing — operational plan

Approved [brief](../briefs/2026-10-08-mrcall-company-memory-sharing.md), SHA256
03fb76ceda452e8ac4b4548b9a8ed5a5b248b6fb88e7bed499ad6b53c74c25e7.
Evidence: `fanout-recovery-20261008/company-memory-sharing/` outside Git.
Lead owns host operations and documentation. Fresh reviewers own gates, read-only.
Other sessions' source and staged work are excluded. No source release or push.

## P1 — Frozen preflight and copy rehearsal

Read the actual unit source pin, tenant users/groups, identity-bound profile settings,
complete assignment schema/history, active fences and source journal. Preserve all
non-target profile unit/binding fingerprints. Source is Mario x59G6SnymAN2lkFny0JDGJgdFz33;
destination is support 9nXeYF8OXPetUFsSP4zDC3F2i673, space
b8580be8-de2a-446b-a980-51fda735a2c3. Require the released source pin, no source
assignment rows/history, no incomplete schema, no active join or unsettled source
journal. Do not use the unreviewed legacy join-company wrapper: it prints the key
and may use the unpinned checkout. Invoke the released Python join directly.

Retain SQLite backup-API copies, settings, unit/trust configuration and group state
in a fresh root-only directory. Hash private table rows and company row IDs/content
in reports; retain no plaintext body, capability, credentials or signing key there.
Operational backups necessarily contain private data and remain root-only.

Run a fresh process with released PYTHONPATH and scratch ZYLCH_HOME/MEMORY_DB_DIR,
activate the copied Mario profile, restore its copied encryption environment in
process, and block socket network connections before engine initialization. Call
actual memory.join.join(destination_key), with the key read in process from the
copied support settings. No drain, dismissal or paid work. Reinitialize in another
fresh process to exercise boot recovery. Require ok, completed source fence and
matching committed destination receipt; no active fence; Mario settings name the
destination. Verify every visible source company blob ID/text is present or retained
in lossless conflict history, destination projects/revisions unchanged, private
profile table digests unchanged, both assignment ledgers empty, and destination
self-notion/blob counts preserved. Record actual result and limitations. A fresh
integration reviewer approves P1 before live cutover.

## P2 — Stopped live cutover and read-only acceptance

Hold /run/mrcalld/reconcile.lock for the complete window (inherited fd 9 for
mrcall-tenant). Preserve existing MrCall clone pause file; add only a temporary
pause if absent, and refuse a currently running relevant operator tick. Stop both
affected systemd units and verify no competing profile processes/writers. Retain
fresh stopped backups and expected-state fingerprints before any mutation; repeat
P1 safety preflight. Preparation must be idle; preserve paused/budget/auto-update
values exactly. The join itself dispatches no model or provider calls.

Add Mario to support's destination company group using the installed root-owned
mrcall-tenant join helper. Pass the destination key through a protected process
environment, never argv/output. Run the released direct join under Mario's tenant
identity with umask 0007 and exact profile/data-root settings. Retain the old source
store. If the join refuses or differs from rehearsal, stop and restore owned state;
never force a key switch or discard blocking journal/history.

Atomically extend destination public trust to both exact UID/mailbox aliases,
preserving version/issuer/public key and root-owned safe path/0644 permissions.
Retain source trust for backup/recovery; no new private signer or real assignment.
Regenerate only Mario's tenant configuration, preserving egress/source pins and
private encryption-key files. Complete recovery before removing his obsolete source
company group. Restart both original units with controls preserved; no new source
activation or preparation setting change.

Authenticate independently for both UIDs and require account.who_am_i, memory.status,
complete tasks.assignment.list with the identical expected space and actor UID,
projects.list/files/read for shared destination project data, and private tasks/mail
reads. Compare a known company self-notion hash and blob counts across both engines.
Retain only hashes/metadata, not project body text or capability values. Probe foreign
private task/email identifiers through the existing read surface and confirm refusal
or empty data. Verify private table rows/credentials, support Qonto status/encryption
and host binding, source pins, budgets/pauses and non-target unit/binding fingerprints.
No live assignment write, mail send, provider sync, chat generation or paid tick.

## P3 — Closure, owned commits and rollback

Reconcile Desktop, kernel and root current-sharing claims, preserving superseded
living paragraphs verbatim in their archives. Keep the unrelated local contextual
candidate's unreleased status and Gmail external-copy limitations. Record actual
copy/live/read checks and pending acceptance accurately. Run proportionate doc-end,
mechanical/keyword and fresh scoped doc-critic plus separate final review. Finalize
this plan only through the checker after approval. Commit exact owned files/hunks,
including previously approved contextual guard and separately owned launcher patch;
leave other sessions' edits intact. No blanket staging, branch reset, push or tag.

Rollback before acceptance: keep both units stopped and reconcile lock held, stop
all owned helper processes, restore source/destination databases from fresh stopped
backups (including SQLite sidecars only after all handles close), profile settings,
owned trust/unit files and Mario's original supplementary groups. Restore original
active/inactive state and owned temporary pause only, then verify old space/identity
and encryption. Never restore an old snapshot over detected concurrent writes or
another session's host changes; keep affected units held and report the exact issue.
Successful cutover retains all backups and the old source store for recovery.


## Verified operational results

P1 copy rehearsal and its fresh integration review are APPROVED. The actual
released join and a second-process restart preserve all 670 Mario blobs and all
1,730 support blobs, 68 project documents / 159 revisions, both complete private
profile databases and owner-scoped rules. The source fence completes and the
destination import receipt commits, with no active fence or assignment history.
Evidence: `preflight.json`, `rehearsal-result.json`, and `reviews/p1-review/` under
the external evidence directory above.

P2 live cutover passes after the repaired helper's safety review. Both authenticated
identities name space b8580be8-de2a-446b-a980-51fda735a2c3, read the same company
project content and self-notion, and report 2,400 memory blobs. Their private task
counts remain 259 and 153; cross-owner task and mailbox probes return no private
rows. All private tables match the stopped backup before restart; protected mail,
drafts, OAuth, mailbox and Qonto connection/transaction data remain identical after
acceptance. Private task IDs and core content remain unchanged; concurrent task
closure/source metadata and account balance-retrieval timestamps are retained.
Rollback refuses unexpected private changes instead of restoring over them.
Qonto/voice status, encryption files, budgets, source pins and all excluded tenant
bindings/units are preserved. Public trust contains exactly the two authorized
UID/address members; Mario retains only the destination company group. The owned
temporary pause is removed and both services are active. No model generation,
provider sync, customer send or assignment mutation is performed by this operation.
Evidence: `live-result.json`, `auth-before.json`, `auth-after.json`; root-only
stopped backups and the old source store remain available for recovery.

The contextual-email guard is committed locally in Desktop `06cc4895` and kernel
`672d7022`. The reviewed MrCall launcher is saved as `11272d61` on
`work/contextual-email-launcher-20261008`; the live launcher and original clone
index are unchanged. These candidates remain unreleased and uninstalled. Manual
external Gmail sending and the existing non-atomic review-copy append retain
previous limitations. No live assignment-write or installed GUI acceptance is
claimed. The first cutover attempt hit the installed tenant helper's drop-in-order refusal.
The complete rollback and authenticated original-space/private-task readback pass.
The retry updates only the three existing Mario sandbox company-path/group lines,
preserving all source-pin and other unit bytes. Its initial acceptance probe compared
the entire voice-status hash, which includes the intentionally changed company
space ID. The subsequent rollback correctly refuses a concurrent Qonto retrieval
timestamp update before restoring any data. Reviewed roll-forward verifies the
completed join and exact controls, then checks voice status with only the expected
space change and preserves the newer private data. Rollback refusal/failure paths also
have focused scratch checks and safety review; accepted live data is not rolled back.

P3 documentation reconciliation is prepared for doc-critic and separate final
review. Intended lifecycle transition: active to completed only through checker
finalization after those gates; owned commits follow with other sessions preserved.
