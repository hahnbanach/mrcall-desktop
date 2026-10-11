---
status: active
---

# R5 mail-owner cleanup and billing diagnostic deployment

Brief: [authorized repair](../briefs/2026-10-04-r5-mail-owner-cleanup.md).
Brief review: `r5_owner_cleanup_brief_review`, **APPROVED**.

The lead owns live host mutations, operational script correction and the
R5 record. A read-only explorer confirmed native CLI locking, owner
resolution and database relationships. An execute agent prepared temporary
cleanup sources and synthetic guard tests; the lead runs live operations.

1. **Inventory and prove candidates, before mutation.** All seven R4
   profiles have recorded script execution. Query each database only as
   its own daemon user, with bytecode disabled, exposing owner counts
   only. Freeze exact UID-owned mail IDs and creation timestamps in
   root-private evidence. Cross-check recorded R4/R5 intervals and
   per-run counts, plus pre-R4 backups; inspect backup schema for triggers
   and foreign keys. Rows not proved to originate from this script are
   excluded. The Riccardo timeout's partial writes are included only with
   its recorded pre-second-run baseline and independent backup evidence.
   A fresh milestone reviewer must approve this inventory/provenance
   evidence before native sync or cleanup proceeds.
2. **Native sync on Mario Gmail.** Capture its initial unit environment
   privately. Under the
   existing reconcile lock, briefly stop only Mario Gmail so native CLI
   can acquire its profile lock. Run the exact installed CLI dispatch
   `-p <uid> sync` as its Unix user and groups in a fresh private mount
   namespace; bind only its dedicated resolver configuration read-only.
   This operator process uses the same host network and per-UID firewall,
   profile/company permissions, installed interpreter and startup
   environment. It does not claim the daemon's identical mount sandbox.
   Mark hosted mode first and preserve the per-unit key after
   both dotenv loads. Disable only incidental update checks/prompts in
   this auxiliary wrapper; suppress raw output. Observe the underlying
   archive result to distinguish successful fetching from the CLI's
   swallowed email failure. Record numeric new-message/fetch-failure
   counts, protected preexisting-row equality and memory availability.
   Restart the same existing unit in `finally`; no unit edits.
   Observe native email completion before unrelated WhatsApp work. Bound
   the auxiliary process after that evidence; record any interruption
   separately from mail success. Check protected existing rows after the
   real daemon restarts and is ready. Failed attempts using the stopped
   daemon's namespace are retained as failed evidence, not acceptance.
   A separate fresh milestone reviewer checks the actual sync result and
   native-wrapper implementation before the dependent cleanup milestone.
3. **Correct scripts and clean proven rows.** Correct both the Oct-3
   acceptance child and Oct-4 sync child to call `get_owner_id()` after
   activation, preserving the unit key. For each affected profile, make a
   consistent SQLite backup via the SQLite backup API as its daemon user
   into its own mode-0600 scratch file. Copy to a root-owned mode-0600 file
   under a root-owned mode-0700 directory, verify digest/integrity, then
   remove the tenant staging copy as that user. Check the backup is
   readable and complete before any deletion. Run raw SQLite cleanup as
   the daemon user under `BEGIN IMMEDIATE`: require the frozen candidate
   ID/timestamp/UID set and every full candidate row to match the verified
   backup, using private full-row digests. If candidate contents changed
   since the backup, abort and refresh/review the backup before retrying.
   Delete only those IDs with `owner_id=UID`,
   require exact affected-row count, and compare full protected-row
   hashes and every other profile table before/after inside the same
   transaction. Email-owner count and contents must stay identical;
   schema and foreign-key checks must remain identical. Commit only when
   all checks pass; otherwise rollback that transaction and investigate.
   Do not delete cursors, tasks, company memory or references. Root-only
   backups are retained; no destructive restore or broad delete.
   Before deletion, a fresh reviewer approves the actual verified backups,
   candidate digests and guarded cleanup source. After cleanup, a fresh
   milestone reviewer approves its actual invariants before deployment.
4. **Deploy and verify.** Release the reconcile lock; invoke only
   `systemctl start zylch-reconcile.service`. Inspect its journal through
   a metadata whitelist; require `Result=success` and `ExecMainStatus=0`,
   seven ready tenant applications, seven active own-user daemons and
   unchanged egress configuration/enforcement. Compare the installed
   billing module with `d30e5680`; pinned voice release stays untouched.
   Do not generate paid chat or extract a Firebase token. Report ready
   for the CTO's retry, which will reveal the billing reason through the
   newly deployed error handling.
   Deployment evidence receives its own integration review before the
   final publication milestone; no paid CTO retry is simulated.
5. **Record, independent final review, publish.** Supersede the incorrect
   R5 claim that the engine's mail-owner contract was defective. Record
   native-sync result, per-profile UID/email counts, exact deleted counts,
   invariants, root-only backup protection and deploy evidence under R5.
   Two independent final reviewers check evidence and code. The parent
   sandbox plan remains active: this repair does not prove its missing
   signed-app journey or scratch offboarding. Before every push, pull
   with rebase and publish `HEAD:main`, preserving unrelated changes.

No message content, secret, token, address or voice-file value is printed.
Private evidence: `/root/r5-mail-owner-repair-20261004/`. Plan review and
execution results are recorded below after their respective gates.

- Plan review: `r5_owner_cleanup_plan_review`, REVISE for missing explicit
  milestone gates and full candidate-row backup equality; both repaired,
  rereview **APPROVED**.
- Inventory milestone: `r5_owner_provenance_review`, **APPROVED**. Seven
  pre-R4 backups contain zero UID-owner mail rows; all 3,207 candidate IDs
  are absent from every prior owner's rows and match recorded script
  intervals/counts. No native sync or deletion preceded this gate.
- Review deviation: an overly broad filename search exposed unrelated
  address-bearing filenames. It was stopped and narrowed to known sources;
  no address values are repeated here, and no mail content, secret values
  or voice files were read. Subsequent evidence queries expose only the
  requested owner counts and invariant booleans.

- Native milestone: `r5_owner_native_sync_review`, initially REVISE for
  swallowed SQLite storage failures; the fresh operator mount namespace
  completes 220 new emails with zero fetch/folder/storage failures and
  full protected-row comparisons. Rereview **APPROVED**. Three prior
  committed additions lack full invariant proof; total native delta 223.
  Overall WhatsApp/CLI completion remains unverified and is not claimed.
- Backup preparation: all seven consistent backups pass binary digest,
  full table/schema/candidate equality, integrity and root-only protection;
  tenant staging copies are removed. Fourteen synthetic cleanup tests and
  eight root-copy guard tests pass. Predelete review
  `r5_owner_predelete_review`: **APPROVED**.

- Actual cleanup: all seven transactions succeed; 3,207 exact candidate
  rows deleted, UID-owner counts all zero, protected email-owner counts
  unchanged. Full protected emails, all other profile tables, schema and
  foreign-key checks remain identical. Post-cleanup integration review
  precedes deployment.

- Post-cleanup milestone: `r5_owner_postcleanup_review`, **APPROVED**.
- Deployment: service checkout `d30e5680`, reconcile success/0, seven ready
  tenants and new main PIDs, all seven own users active with zero restarts
  and memory available. Six unpinned billing modules match checkout;
  production remains declared on its prior voice release. Egress config
  digests and compiled static rules pass; dynamic DNS elements account
  for five nonidentical exact dumps. Dedicated DNS/firewall services and
  log filters pass. The journal capture is repaired to tag-only, scoped
  to the actual run; no additional reconcile is executed. Existing pin
  declaration/module timestamps and running argv/PYTHONPATH agree; no
  complete pre-deploy pin digest was recorded. Private deploy summary is
  successful. Integration review precedes two independent final reviews.

- Deployment integration: `r5_owner_deploy_review`, **APPROVED**.
  CTO chat retry is pending. Corrected counter smoke test executes as
  Mario Gmail's daemon user and reports 3,898 email-owner rows.
- Fresh final review: `r5_owner_repair_final_a`, **APPROVED**. The platform
  rejects a
  second fresh reviewer with `agent thread limit reached`. Following the
  CLAUDE fallback, `r5_owner_provenance_review` performs an explicit
  separate final pass: **APPROVED**, independently of the fresh review. This reused
  session is disclosed and is not represented as a second fresh session.
  The operational work is done; fresh-review closure remains pending and
  this repair plan stays active until the required closure is available.

- Publication checks: document links and `git diff --check` pass. Only
  this brief, repair plan and the parent R5 section are staged; unrelated
  tracked/untracked work is preserved. Publish after pull with rebase.
