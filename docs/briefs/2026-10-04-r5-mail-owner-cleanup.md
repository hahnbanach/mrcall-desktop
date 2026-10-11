# R5: correct the acceptance sync owner and remove its invisible mail rows

The CTO authorizes a native engine sync for Mario Gmail, cleanup of only
mail rows written under the Firebase UID by the R4/R5 acceptance script,
correction of that script to use `get_owner_id()`, and deployment of
`d30e5680` through the installed reconcile service.

The engine's mail owner is `EMAIL_ADDRESS`; the Firebase UID identifies the
profile. The earlier R5 interpretation of this distinction as an engine
mail-owner bug was wrong. Native sync must populate the owner's existing
mailbox without changing engine identity contracts.

Acceptance:

- Report native Mario Gmail sync success and new-message count from the
  engine's real CLI, under its daemon user/runtime and hosted constraints.
- Inventory every profile on which the erroneous script ran; expose only
  UID-owner and email-owner mail counts, never addresses or message data.
- Establish exact candidate IDs from script execution evidence and row
  creation timestamps. Retain any row whose provenance cannot be proved.
- Before deletion, create and verify a consistent SQLite backup as the
  daemon user, then protect its host copy as root-only. Delete only the
  identified `emails` rows with the UID owner, as the daemon user, in one
  guarded transaction. Email-owner rows and all other profile tables must
  remain unchanged by cleanup; abort on any failed invariant.
- Correct operational sync scripts to call `get_owner_id()` and check the
  resolved owner without printing its value. Preserve the per-user unit
  encryption key when activating a profile.
- Start only the already installed reconcile service to deploy; verify
  success, deployed billing source, all seven tenant users and enforced
  services. Do not directly modify the service checkout or pinned voice
  release. Do not perform paid chat: the CTO retries after deployment.
- Publish counts, backup protection, deletion invariants, deployment and
  independent review evidence under R5; leave the sandbox plan active.

Constraints: no secrets, email/call content, voice files, owner addresses or
raw logs in output/git; private evidence and backups are root-only. No
profile/unit/key/provider/policy changes, no cursor cleanup, no offboarding.
The existing unrelated worktree changes and concurrent plan sections remain
untouched. Pull with rebase before every push.

Uncertainty: script-run metadata must establish provenance before deleting;
an unproven row is retained rather than treating all UID-owned rows as bad.
CLI exit status alone is insufficient because its email error is caught;
successful email result and owner-count change must also be checked.
