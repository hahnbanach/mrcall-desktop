---
status: active
created: 2026-11-23
brief: ../briefs/2026-11-23-mailbox-drafts.md
owners: [lead, engine, desktop]
---

# Desktop mailbox draft implementation

The governing plan is HB's November 23 mailbox draft plan at
`/home/mal/hb/docs/execution-plans/2026-11-23-drafts-live-in-the-mailbox.md`.
Its reviewed intent and installed acceptance remain binding. The reviewed HB
November 24 IMAP amendment supersedes the API transport and OAuth dependency.

## Current candidate

The delivery worktree is `/home/mal/worktrees/mrcall-desktop-mailbox-drafts`, on
`feat/mailbox-drafts-20261123`, based on hosted source `e703c808`. Existing dirty
base-checkout changes are preserved. The managed instruction refresh is a
separate commit `b399a564`.

- Primary-mailbox IMAP provider: `email/imap_mailbox.py`, structured protocol
  parsing, neutral provider errors and raw SMTP submission through existing credentials.
- Shared service and receipts: `services/mailbox_drafts.py`, MIME/send helpers,
  and `storage/mailbox_operations.py`.
- Caller wiring: Storage adapters, chat, commands, task/approval, RPC and MCP.
- Desktop: existing Email view, typed preload and mailbox Drafts component.
- Legacy retirement and rollback: `storage/mailbox_draft_migration.py` and
  [migration contract](../mailbox-draft-migration.md).

The [mailbox contract](../mailbox-drafts.md) describes current candidate behavior.
Installed state and its remaining acceptance boundaries are recorded below.

## Retained verification and remaining delivery

The November 23 source checks below certify their recorded API candidate bytes.
The IMAP amendment records replacement-transport checks and its fresh milestone.
They do not transfer provider coverage implicitly.

- [x] Root brief framing and plan reviews are approved.
- [x] November 24 provider/plan review approves exact IMAP handles, distinct
  replacement Message-IDs, SMTP submission and verified post-Sent retirement.
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
- [x] Kernel source integration is APPROVED; the complete frozen suite exits zero.
  The M2 report is `/tmp/mrcall-ai-kit/mailbox-kernel-integration-review/report.md`.
- [ ] Both installed-clone FULL checks under the governing plan.
- [ ] Documentation critic and separate final review through final-user paths.
- [x] Existing primary IMAP/SMTP admission and seven-engine cutover.
- [x] Actual saved Gmail IMAP edit, keyed MCP send, receipt replay after engine
  restart, and independently matching Sent/received message.
- [x] Installed Linux Desktop 0.1.57 default authentication and full restart.
- [x] Durable binding and status recovery for a second key on the same canonical
  send. Dev13 is installed on all seven engines. Authenticated RPC accepts the
  alias and actual post-restart RPC status and MCP recovery retain the original
  operation and Message-ID.
- [x] First ordinary Café draft-mode tick and installed Linux Desktop opening
  of its exact native draft on dev13.
- [ ] Second ordinary Café tick, first ordinary MrCall direct send, public
  release and final review.
- [ ] Gmail web verification of the controlled journey.

## Deployment boundary

The primary mailbox already supplies IMAP/SMTP credentials. Gmail OAuth consent
is not a dependency. Current source removes the unreleased Gmail OAuth surface.
The original API candidate and its 403 evidence remain historical artifacts.
All seven hosted engines run immutable dev13. Both normal clones use the exact
local `v0.76.1` package at commit
`6b5fa007c8c0fa98c0d5f5a05a76052eea3f3d0f`. Their FULL acceptance and public
provenance remain required.

Recurring schedules remain paused outside the bounded acceptance window. The
current two ordinary ticks share one window with recurring cron suppressed and
both pause files temporarily removed. Restore exact cron and both pause files
after both runs finish. Launchers retain their configured USD 8 run caps and
saved engine budgets. Migration requires stopped real writers,
fresh state digest and read-only exact Sent proof; it restores no discarded
draft and retransmits no uncertain operation.


## Installed IMAP checkpoint — 2026-11-25

All seven hosted engines run `0.1.57.dev13+mailboximap20261124.mrcall` from
`2e27f02e14c80ce43fff59dc53d150a7e05efc3b`. All 492 package files match
SHA-256 `8b15a97654043409f5aac027664eb4999cb2fa9cc71027c5f189b21375581ed1`.
The source aggregate passes 398 cases with those bytes unchanged. The 00:22:28
UTC release-only upgrade records actual process identities and listeners, 124
preserved canonical receipts, zero existing aliases and zero provider effects.
It retains profile settings, budgets, parked voice and the recurring cron and
pause state at the rollout.

An independent synthetic SQLite audit of dev12 reproduced cross-target reuse
of an unbound key after database reopen. Dev13 binds accepted aliases to
canonical receipts inside the serialized key namespace and refuses conflicting
reuse. The approved source checks exercise the writer race, SQLite reopen,
legacy import collisions and concurrent first schema creation. Installed
verification replays the original key and accepts a new alias through native
RPC. After the actual Café engine restart, RPC status and MCP with the accepted
alias return operation `620cc478-aa3f-43d6-8077-689d25864f6b` and its original
Message-ID. The edited recipients and body match the independent one Sent and
one received message. Drafts remains empty for that operation. MCP refuses a new,
unbound key on the retired handle before binding.

The original-17 conditional order is complete with zero moves, 14 exact originals
in recoverable Trash and three unlocated. Later UID 2342 remains untouched.
Internal retirement is already complete. Its counts are retained below.

Both normal clones retain local exact `v0.76.1`, all 164 files and 115 denies
per clone. Four installed safety suites and authenticated identity pass on both.
The at-tag source suite exits 0 with its optional golden-pack test skipped.
The first successful ordinary Café tick `run-uutzflaz` exits 0 on dev12 at USD
2.7702404, with one provider proof and one selection in complete discovery.
It creates one draft (UID 2515, UIDVALIDITY 6) and sends zero replies. The
preliminary failure below does not count. The second Café tick on the same
original and the first ordinary MrCall send run on dev13 in one shared window.
The ordinary launchers, USD 8 caps and model settings remain unchanged.

Packaged Linux Desktop 0.1.57 opens the exact first Café draft on dev13.
Closed-home scans find no persisted ID token. The seven Linux ASAR files match
the local production build. All four CI workflows pass at `2e27f02e`: stable
installer `45516547567`, kernel journey `45516341963`, memory-write boundary
`45516341850` and RPC contracts `45516341849`. The Apple Silicon installer
ZIP digest and CRC pass. Its 249,587,606-byte DMG has SHA-256
`178f6e4979e27b812b188d72f33cb9e9b6acf29728cc80f3e33ee0d4b29db92a`.
CI reports distribution signing. Apple's fresh agreement-related HTTP 403
leaves the DMG unnotarized. Git app source is unchanged from dev12 and
`4740f220`. Mac ASAR comparison, independent Mac signature verification and
native Mac or Windows execution remain unverified.

The November 24 private evidence root contains the dev13 fleet proof under
`mailbox-upgrade-dev13/run-20261125T002228476949Z/`, alias receipts under
`mailbox-interactive/`, ordinary run records under `mailbox-drafts/`, Linux
UI evidence under `desktop-installed-v0157/` and the CI artifact under
`desktop-stable-dev13-release-assets/`.

Verify both running outcomes and restore cron and both pause files after both
exit. Both-clone FULL includes retained and outstanding live read, dedup,
degraded CRM, safety and fixed-template evidence in addition to the ordinary
ticks. Literal Gmail web, public kernel and Desktop provenance, documentation
criticism and a separate final installed review remain required.

## Retained dev12 IMAP checkpoint — historical

````markdown
## Installed IMAP checkpoint — 2026-11-24

Source `a4b03ad5`, engine `0.1.57.dev12+mailboximap20261124.mrcall`, runs on all
seven actual hosted profiles. All 492 package files, process UID/cwd/arguments
and expected listeners match. The aggregate passes 377 checks on unchanged
product bytes with SHA-256
`b2bb31d6c8a78a08a9a7179ec35832f285fdd5bbe6891ce99c92ad18ca2c6f1d`.
Fresh capability and release-only upgrade reviews approve the
fix. Its fresh authenticated CAPABILITY observes MOVE after login; cached
pre-login capabilities never authorize effects. Actual restart preserves all
receipt rows and settings without another migration or provider mutation.

Actual migration discards 175 legacy rows and clears 47 campaign contacts,
preserving 32 journals and 118 original identities. Exact Sent completes 93;
25 remain uncertain. The original 17-target public route finds every original
absent and preserves the unrelated draft. It moves zero items. Independent exact
Trash reconciliation locates 14 originals; three are absent from both searched
folders. No actor or cause is inferred for their earlier disappearance.

The controlled draft opens through Desktop and independent Gmail IMAP. An
independent saved recipient/body edit is read by fresh MCP inventory. MCP sends
one matching message, with independent Sent and recipient proof. Replaying the
same original request key after the actual dev11 process restart completes only
recoverable draft retirement. A further replay keeps the same operation and
Message-ID. The final provider observation has one Sent, one received and zero
drafts. Gmail web interaction is not established by this IMAP proof.

Packaged Linux Desktop `0.1.57` uses default refresh-only Firebase persistence,
authenticates to the Café hosted profile and restores identity after a full
process restart. Closed-home scans find no actual ID token. The seven compiled
files in the installed Linux ASAR match its local production build. The
installed check covers the remote backend.

Stable Apple Silicon workflow 45471910348 succeeds on `a4b03ad5` with the dev12
sidecar. The app source tree matches the earlier installer source `4740f220`.
The complete CI artifact ZIP passes its checksum and CRC checks. Its
249,595,523-byte DMG has SHA-256
`9e5c8ec4b6297d86a1fead4d52029a1bfc0eb4b7229fcfd6481e04780930ccac`.
CI records distribution signing. Notarization remains blocked by Apple's
missing or expired developer agreement. Mac ASAR file equivalence, independent
Mac signature verification, Mac and Windows execution, and publication remain
unverified.

Two successful ordinary Café selections of the same original, one ordinary
MrCall direct send, opening the tick-created draft in installed Desktop, both
normal-clone FULL checks, immutable public installer and kernel provenance,
Gmail web verification, documentation closure and separate final review remain
required. Evidence is under
`~/.local/share/mrcall-operational-evidence/2026-11-24/` in
`mailbox-upgrade-dev12/`, `mailbox-migration/`, `mailbox-interactive/`,
`desktop-installed-v0157/`, `desktop-stable-dev12-release-assets/` and `mailbox-drafts/`.

The first ordinary Café run `run-t1wx3jrh` exits 1. Its verified test original
is not selected and has zero draft/reply effects. The independently reviewed
engine repair normalizes one valid singleton full-MIME Message-ID with leading
whitespace; duplicate or defective headers and multiple sources still refuse.
The dev12 release-only restart preserves all receipt rows, exact cron bytes,
pauses and profile settings. The kernel selection correction is separately
reviewed and installed in both normal clones as immutable local `v0.76.1`.
Each installed `cs` inventory matches all 164 source files (SHA-256 prefix
`f328692d`). MrCall retains 94 third-party distributions and effective send
mode. Café retains 57 third-party distributions and effective draft mode.
Each clone retains 115 deny entries. Four installed safety suites and an
authenticated identity call pass on each. At the 21:00:56 UTC checkpoint,
the first post-repair ordinary Café tick is running against the same original.
Stable installer workflow 45471910348 and the three actual RPC, memory-write and
kernel-journey workflows all succeed on `a4b03ad5`. Their results establish the
recorded source and artifact checks; installed ordinary acceptance remains open.

The installed dev12 named-send path can reuse an existing operation for a
second key without persisting its binding. The synthetic SQLite reproducer
completes retirement under that key, reopens the database, and dispatches a
different draft using that same key. The original and second draft each have
one synthetic SMTP submission, with no real provider calls. The transactional
Trash path also needs a durable binding when returning an in-flight receipt.
The repair must bind the new key before recovery or cleanup, preserve the
canonical operation and Message-ID, resolve status for the bound key, and
reject reuse for a different draft. This acceptance includes the transaction
race and database reopen.
````
