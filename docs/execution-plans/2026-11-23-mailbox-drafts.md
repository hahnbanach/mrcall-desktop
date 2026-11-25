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
  send. Dev15 is installed on all seven engines; the recorded alias proof uses dev13. Authenticated RPC accepts the
  alias and actual post-restart RPC status and MCP recovery retain the original
  operation and Message-ID.
- [x] First ordinary Café draft-mode tick and installed Linux Desktop opening
  of its exact native draft on dev13.
- [x] Second ordinary Café tick examines the same original with one unchanged
  draft and zero sends. Its incomplete Sent-body hold retains its qualification.
- [x] Installed support hold controls preserve an edited draft and leave an
  independently human-answered source alone, without generation or sending.
- [x] Successful corrected ordinary MrCall direct send with received/Sent,
  semantic, same-key recovery and accounting verification.
- [ ] Public release and final installed review.
- [ ] Gmail web verification of the controlled journey.

## Deployment boundary

The primary mailbox already supplies IMAP/SMTP credentials. Gmail OAuth consent
is not a dependency. Current source removes the unreleased Gmail OAuth surface.
The original API candidate and its 403 evidence remain historical artifacts.
All seven hosted engines run immutable dev15 from `96f02460`. Both normal clones use the exact
local `v0.76.1` package at commit
`6b5fa007c8c0fa98c0d5f5a05a76052eea3f3d0f`. Their FULL acceptance and public
provenance remain required.

Recurring schedules remain paused outside bounded acceptance windows. The
corrected ordinary MrCall run completes with exact cron and both pause files
restored and no owned descendants remaining. Launchers retain their configured USD 8 run caps and
saved engine budgets. Migration requires stopped real writers,
fresh state digest and read-only exact Sent proof; it restores no discarded
draft and retransmits no uncertain operation.


## Installed dev15 checkpoint — 2026-11-25 05:49 UTC

All seven hosted engines run immutable `0.1.57.dev15+mailboximap20261125.mrcall`
from `96f02460bab9f0c9909ed663ae07cfa5c8a075dd`. Their 492 product files match
SHA-256 `70a55a907ee5287be5a574260d5a13178e79eb974ed8c653d474f25efa5a3dba`.
The reviewed artifact passes 461 cases and seven real service-user imports.
All 109 retained dependency distributions and 11,740 vendor files remain exact,
including SDK 1.8.0. The failed permission-only packaging attempt is retained;
the verified artifact has readable immutable modes. Source and fleet reviews
are independently approved. Actual activation exits zero and restores exact
cron and pauses. Settings, budgets, parked voice, original operations and
accounting are preserved, with no migration or provider effects.

The actual proof is `mailbox-upgrade-dev15/run-20261125T054855731472Z/running-proof.json`
under the November 24 private evidence root. Its SHA-256 is
`c9f4b95b72f46437d571c3da19a3c81dcc2c8d4b6f0eeeabefebe7c15fda05a8`.
Post-switch public MCP original-key and accepted-alias replays retain the
original canonical receipt and Message-ID with one Sent, one received and zero
drafts. Packaged Linux Desktop 0.1.57 opens the unchanged first Café draft
UID 2515/UIDVALIDITY 6. The closed-home scan checks 734 files without matching
the observed ID token. The packet is `post-dev15-mcp-desktop-verification-20261125/`.

Café generation `af047ec8-ead2-40c4-a94f-c01ca8fd849e` records a valid review
with zero missing facts, one settled USD 0.027780 usage and zero mailbox effects.
Its assessment conflicts with the only verified controlled original. The saved source, sole
correspondence and offline request reconstruction contain the correct controlled
original; no local response cache is used. Actual transmitted HTTP digest and
provider generation ID are unavailable. A model error and upstream association
cannot be distinguished. Unverified generated identities/text are excluded
from acceptance evidence. The source-selection code has no demonstrated defect.
The normal authenticated clarification on that same verified original ends in
`needs_review` as generation `a4369dda-a712-4e99-aaeb-152968ca107c`. Its one settled
USD 0.037419 usage has 7,107 input and 1,490 output tokens. Provider observations
find no draft or outgoing reply; all previous objects and accounting remain
unchanged. This review accepts the reference and total but asks for proof of
the protected-original exception. The model context contains source,
correspondence and published rules, without the kernel's typed discovery receipt.
The distinct request does not change registry, model, policy or caps and submits
no SMTP. Its 17-file terminal manifest is
`522b5b13d22989229a53abfc9bd1b4b37b6ba3e369825494ec581aa0eb390767`.
Read-only diagnosis confirms a conservative review with the kernel verification
receipt absent from the model context. Positive preparation/replay remain open. Old operations
and charges remain terminal and intact. Literal Gmail client acceptance and
public release remain open.

The source-matching ordinary ARM64 dispatch `45554892753` succeeds on exact
`96f02460`. Its installer embeds sidecar artifact 14995826319; installer artifact
14995891640 has ZIP SHA-256
`ab7472bf6151558856d23ecbf56270be9239d9df7e9afc0b4bd2132faccb2257`.
Full ZIP CRC passes. Its sole 249,567,884-byte DMG has SHA-256
`1061af5f3a9870d2560f19eeb0b33ee5f32a62f9bba00f89a88d96e47fe889d8`.
Runner distribution signing succeeds. Apple refuses notarization with the
agreement-related HTTP 403; the workflow's signed fallback remains qualified.
This dispatch does not attach a release. All three source-bound RPC, memory
boundary and kernel-journey CI workflows succeed. Actual public-tag publication,
anonymous asset verification and native Mac execution remain separate.
The durable receipt is `desktop-stable-dev15-dispatch-evidence/source15-evidence.json`
under the private evidence root, SHA-256 `67e3b77ebf7da09a4877e217e6ea83ecd62761066cbd58137a119df035c4beab`.

## Retained dev14 checkpoint — historical

### Forward review-validation repair

The canonical, provider-verified and registered Café test reaches K3 once. Its
generation `f4e9cc9a-cfb6-4654-b6f5-b3fb801225c1` ends with
`bounded_internal_review_required`, one settled USD 0.026759 usage and zero
mailbox effects. The original response is not retained, so its exact invalid
field and semantic reason are unknown. The same deployed schema admits empty
fact lists and blank strings that the local review constructor rejects with one
opaque cause. `not-dispatched` describes the mailbox action, not model accounting.

Dev15 repairs this boundary without changing mailbox admission or dispatch.
A justified policy escalation may have no missing facts. Its nonblank reason
and every supplied fact retain bounded UTF-8 validation; malformed values remain
held with safe field/constraint diagnostics. The prompt states the local bounds.
The provider-supported structural schema and deployed gateway remain unchanged.
String byte bounds remain local; the [provider schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
do not support general string-length or array-maximum constraints.

The source milestone review precedes an immutable dev15 artifact and fresh
seven-engine rollout review. Preserve every old operation and settled charge,
all canonical receipts and aliases, settings, budgets, cron, pauses and voice.
Run no migration or automatic inference retry. The positive continuation uses
the same verified original without another SMTP submission and a distinct
explicit request after the repaired release is installed. Its original failed
request remains terminal. Independent provider, semantic and same-key accounting
checks, post-upgrade MCP/Desktop checks and the public-release gates remain required.

All seven processes load `0.1.57.dev14+mailboximap20261125.mrcall` from exact
source `74f15a135277c6a417eac2837f5cd8c5d01f3c18`. All 492 package files match
SHA-256 `b11ae7d4eb25ab6ac7e9a69d7f4e3bd1546c55370a26c5d5fda96de8f10deaab`.
The artifact passes 449 focused checks. Actual reviewed rollout preserves
canonical receipts and aliases, generation and budget state, settings, caps,
voice and exact scheduling state, with no provider effects or migration rerun.

Both gateway realms run `2bf3a56b` with all 78 source/schema files matching.
They serve published snapshot `ceba39dabf9c394c561a10eb96faf57402fa3e81d34588766dac98eb1498cabc`
after supported restarts. Twelve authenticated free quote checks per realm pass
with zero inference. Data commit `b7e2d960` changes only the snapshot and preserves
the table, ranking policy and other public blobs. Exact provider capabilities
and required structured output are bound in the approved quote wire.

The two successful Café ticks retain their actual dev12/dev13 versions, same
examined original, byte-identical draft and zero sends. Separate installed dev13
hold controls preserve an edited draft and recognize an exact human reply
before generation or dispatch. Corrected ordinary support run `run-v3wrbl3l`
exits zero on dev14 against the original without source resubmission. Independent
IMAP finds one matching Sent and received reply, with zero drafts. The lead reads
the received body and verifies its reference and sum 416. Same-key recovery and
recount preserve generation, send receipt, Message-ID, reservation, usage, tokens
and costs. The ordinary run reports USD 2.3511234 under its USD 8 cap; its direct
reply usage estimates USD 0.022551. These are distinct accounting scopes.
The failed earlier generation recovers its original uncertain identity on dev14
without another model request or mailbox effect.

Both normal clones still have exact local `v0.76.1`. The qualified read matrix,
independent read-only IMAP oracle, historical fixed-template goldens, installed
safety and actual paused ordinary launchers have evidence. BOTH FULL still
requires canonical Café personal-K3 preparation on dev14 and independent sign-off.

Stable ARM64 workflow `45533053445` succeeds on exact source `74f15a13`.
The complete ZIP digest and CRC pass; the retained 249,606,782-byte DMG SHA-256
is `cf82d0460f0f02efb27dafac985d1c9c53b799afd56778805d6dd97af45b9ccd`.
Signing is observed. Apple's actual account-agreement refusal leaves it
unnotarized. The public installer remains v0.1.56. This proves neither native
Mac execution nor a new public release.

Evidence is under `/home/mal/.local/share/mrcall-operational-evidence/2026-11-24/`:
`mailbox-upgrade-dev14/run-20261125T033835231071Z/running-proof.json`,
`mrcall-ordinary-dev14-20261125/`, `scheduled-hold-controls-20261125/`,
`normal-full-read-matrix/` and `desktop-stable-dev14-release-assets/`.
Post-upgrade public MCP original/alias replay and packaged Linux draft opening
pass. The exact original message, UID 2515/UIDVALIDITY 6 draft and accounting
remain intact. The closed-home scan checks 734 files without a match for the
observed ID token. These proofs are in `post-dev14-mcp-desktop-verification-20261125/`.
Public kernel/installer provenance, literal Gmail web, documentation criticism and
separate final installed review remain required. Pull the service checkout
after every Desktop main push and verify the seven process bindings again.

## Retained dev13 IMAP checkpoint — historical

````markdown
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

````

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
