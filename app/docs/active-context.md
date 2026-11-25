# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

The mailbox candidate opens the current IMAP draft exposed by the engine.
A successful local Save adopts its returned replacement handle. An external
Gmail edit can replace the UID; refresh of the old detail keeps that exact ID,
so re-list drafts and select the current entry. A stale handle never silently
selects another draft. Read-only status
checks report pending retirement; an explicit replay of the same send operation
can finish cleanup after verified delivery. The [mailbox contract](mailbox-drafts.md)
owns this behavior and its installed acceptance boundary.

Default Firebase persistence stores the refresh credential and required identity
metadata, while ID/access tokens stay in memory. The official SDK renews identity
after a full app restart. Reads migrate legacy ID-token fields without restoring
credentials after a concurrent logout. Installed Electron 0.1.57
sign-in, authenticated hosted identity and full process restart pass on the test
Linux desktop. Its root-owned packaged bundle has seven compiled files identical
to the production build and a hashed 73-file runtime inventory. Closed-profile disk scans find neither actual ID token. Password,
Google-credential and restart cases also pass through the official SDK in Chromium.
The installed Linux app has historical dev15 opening proof for Café UID 2515,
which is now absent. Its closed-profile scan finds no persisted ID token. Current
Desktop opens the distinct explicit RPC-created fixture with the known
197-byte controlled body. The lead compares its full screenshot against the
body, reference, total 254 and signature. The closed-home token scan passes.
The original MCP-generated handle is absent and is never adopted by the new
fixture; read-only recovery retains the original operation without recreation.
The source-matching dev16 ARM64 dispatch succeeds. Its complete installer and
consumed-sidecar ZIP digests, CRC and DMG hash are verified. Runner signing
passes; Apple refuses notarization for the account agreement under the
workflow's explicit fallback. Published immutable tag `v0.1.57` binds release
source `50ee8316`. Public tag workflow `45617312164` succeeds in all four jobs.
The exact consumed sidecar, full installer ZIP digest/CRC and anonymously fetched
249,599,199-byte public ARM64 DMG match. Runner distribution signing passes;
Apple agreement HTTP 403 leaves the installer unnotarized.

Gmail A has one MCP send and original-key replay with the exact 223-byte body,
one Sent/received and zero drafts. The operator's Gmail body edit is independently
read; the engine corrects the sole test recipient. Independent review approves
composed recipient verification through the common native MIME reader. The literal
uninterrupted Gmail-recipient-edit-to-SMTP case remains unestablished; the
[delivery plan](../../docs/execution-plans/2026-11-23-mailbox-drafts.md) binds the
approved report and qualification. B has one exact unflagged draft
in recoverable Trash and zero outgoing mail. C external send and typed old-handle
refusal pass without recreation. Browser actions remain operator-reported.

Settings separates payment provider, model selection, daily allowance and bounded
preparation controls. Saved keys belong to the active engine. Pending choices
remain distinct from saved policy. Mailboxes, Qonto typed credentials, company
assignments and session recovery retain their owning contracts and plans;
mailbox acceptance does not certify their unrelated installed GUI journeys.

The verified public Apple Silicon installer is
[MrCall Desktop v0.1.57](https://github.com/hahnbanach/mrcall-desktop/releases/download/v0.1.57/MrCall.Desktop-0.1.57-arm64.dmg).
Native Mac execution and independent Mac signature validation remain unverified.
The [delivery plan](../../docs/execution-plans/2026-11-23-mailbox-drafts.md) retains
exact public artifact hashes. Current artifact, hosted deployment and model state
live in the
[cross-cutting context](../../docs/active-context.md).

## Unresolved

- Native Mac execution and independent Mac signature validation remain open. Historical ordinary support,
  both Café examinations and current dev16 ordinary formatter proof retain their
  stated limits. Three older controlled messages retain exact recoverable Trash
  proof; their historical Sent observations remain separate.
- Fresh-device Mac sign-in, personal-key entry, live PEC and the packaged Qonto
  provider comparison retain their existing acceptance owners.
- Reopen Settings after a connection change to reload its catalog. Reloading
  identical settings does not refetch it; stale choices remain disabled.

## Next

Retain the verified public `v0.1.57` asset and installed Linux opening receipts
under the primary delivery plan. External closure receipts retain check/review
outcomes. Preserve account partitions, budgets,
old send fences and the recurring schedule restoration boundary.
Historical snapshots are in [the archive](active-context-archive.md).
