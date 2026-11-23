---
status: active
created: 2026-11-23
brief: ../briefs/2026-11-23-mailbox-drafts.md
owners: [lead, engine, desktop]
---

# Desktop mailbox draft implementation

The governing plan is HB's November 23 mailbox draft plan at
`/home/mal/hb/docs/execution-plans/2026-11-23-drafts-live-in-the-mailbox.md`.
Its reviewed intent, provider decision and installed acceptance remain binding.

## Current candidate

The clean worktree is `/home/mal/worktrees/mrcall-desktop-mailbox-drafts`, on
`feat/mailbox-drafts-20261123`, based on hosted source `e703c808`. Existing dirty
base-checkout changes are preserved. The managed instruction refresh is a
separate commit `b399a564`.

- Native provider and encrypted OAuth: `email/gmail_mailbox.py`,
  `email/gmail_auth.py`, and `rpc/google_gmail_actions.py`.
- Shared service and receipts: `services/mailbox_drafts.py`, MIME/send helpers,
  and `storage/mailbox_operations.py`.
- Caller wiring: Storage adapters, chat, commands, task/approval, RPC and MCP.
- Desktop: existing Email view, typed preload and mailbox Drafts component.
- Legacy retirement and rollback: `storage/mailbox_draft_migration.py` and
  [migration contract](../mailbox-draft-migration.md).

The [mailbox contract](../mailbox-drafts.md) describes current candidate behavior.
No candidate deployment or installed product acceptance is established here.

## Verification and reviews

- [x] Root brief framing and plan reviews are approved.
- [x] Provider evidence review approves native Gmail draft container identity.
- [x] Focused provider, authentication, receipt, process-restart and migration
  checks pass. The combined retained run is 96 passed in 11.02 seconds at
  `/tmp/mrcall-ai-kit/mailbox-engine-targeted-final.log`.
- [x] Actual Email view and preload run in Chromium against synthetic RPC,
  including consumed-draft pending recovery. Typecheck and build pass.
  Evidence is `/tmp/mrcall-ai-kit/mailbox-drafts-ui/browser-final.log`.
- [x] Integrated engine/Desktop milestone review is APPROVED; the retained report is
  `/tmp/mrcall-ai-kit/mailbox-engine-milestone-review/report.md`.
- [x] Migration/compatible rollback milestone review is APPROVED, with 26 focused
  cases and independent repeated-retirement refutation. Report:
  `/tmp/mrcall-ai-kit/mailbox-migration-review/report.md`.
- [ ] Kernel integration and both clone checks under the governing plan.
- [ ] Documentation critic and separate final review through final-user paths.
- [ ] Native mailbox authorization, candidate operational acceptance, publication,
  seven-engine cutover and installed acceptance.

## Deployment dependency

The application OAuth client is staged at `/etc/mrcalld/gmail-oauth-client.env`.
The service-user authorization bootstrap and checks are retained under
`~/.local/share/mrcall-operational-evidence/2026-11-23/mailbox-gmail-auth/`.
Actual support and Café credential checks return `gmail_authorization_required`.
No live consent flow, unit restart or destructive migration occurs without the
required mailbox grant. Independent implementation and verification continue.

Recurring schedules remain paused. Launchers retain their configured USD 8
run caps and saved engine budgets. Migration requires stopped real writers,
fresh state digest and read-only exact Sent proof; it restores no discarded
draft and retransmits no uncertain operation.
