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
The same installed Linux app opens the first ordinary Café tick's exact draft
(IMAP UID 2515) on dev15. Its closed-profile scan finds no persisted ID token.
The retained dev14 Apple Silicon artifact has verified ZIP and DMG digests, full CRC and runner signing evidence. Its notarization is refused for the Apple agreement. The source-matching dev15 ARM64 dispatch succeeds. Its complete ZIP hash and CRC and the 249,567,884-byte DMG hash are verified; runner signing passes and Apple refuses notarization for the account agreement.

Settings separates payment provider, model selection, daily allowance and bounded
preparation controls. Saved keys belong to the active engine. Pending choices
remain distinct from saved policy. Mailboxes, Qonto typed credentials, company
assignments and session recovery retain their owning contracts and plans;
mailbox acceptance does not certify their unrelated installed GUI journeys.

The current published Apple Silicon installer is v0.1.56. Source and compiled
Linux checks do not establish installation of a new signed Mac package. Current
artifact, hosted deployment and model state live in the
[cross-cutting context](../../docs/active-context.md).

## Unresolved

- The corrected ordinary support send and both Café examinations pass.
  Post-upgrade public MCP recovery and packaged Linux opening preserve their
  original objects. Canonical personal-K3 verification, both-clone FULL and
  literal Gmail web remain with the governing HB plan. Recurring pauses and
  cron are restored. Public release, Mac execution and independent validation of the signed,
  unnotarized DMG remain open.
- Fresh-device Mac sign-in, personal-key entry, live PEC and the packaged Qonto
  provider comparison retain their existing acceptance owners.
- Reopen Settings after a connection change to reload its catalog. Reloading
  identical settings does not refetch it; stale choices remain disabled.

## Next

Retain the installed Linux draft-opening receipt for final review, then publish
the reviewed artifact after the governing acceptance checks. Preserve account
partitions, budgets and the recurring schedule restoration boundary.
Historical snapshots are in [the archive](active-context-archive.md).
