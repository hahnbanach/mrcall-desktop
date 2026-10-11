---
status: approved
date: 2026-10-05
---

# Include PEC mailboxes and Qonto in the next Desktop source release

<!-- doc-scope:start -->
Scope: integrate the reviewed additional-mailboxes delivery with Qonto and the
current shared Desktop source, preparing the next release without publishing it.
<!-- doc-scope:end -->

## Requested outcome

The next Desktop release built from shared main must contain both the Qonto
Settings card and Settings → Email → Mailboxes for adding a PEC/other IMAP
mailbox. Preserve the latest authentication, billing-business discovery and
opaque-ID fixes. The operator explicitly forbids a release in this task.

The approved additional-mailboxes product scope is unchanged: additional IMAP
accounts, encrypted passwords, per-mailbox sync/attribution, PEC envelope
unwrapping, and primary-only outgoing mail. Qonto retains its existing private
source, managed-chat and explicit-consent boundaries. This is integration of
reviewed work, not a new PEC receipt-certification or sending feature.

## Evidence and boundaries

Main's local `a68ea7b` contains Qonto; remote main and tags 0.1.54/0.1.55 do not.
The published 0.1.54 installer was built from `0ab1bd7`. Remote main at task
start is `cf642ef`, including the subsequent opaque business-ID correction.
The PEC implementation is the eight focused commits after `65659b3` through
`83a6700` on `feat/additional-mailboxes`; do not import its unrelated divergent
voice history. Its original brief/plan and review records travel with the code.

Use an isolated integration checkout, preserve unrelated work and all three
feature lines, then update main with reviewed source commits. Updating shared
main is part of making the next release include these features; no tag,
release workflow dispatch, installer publication or hosted-engine rollout is
authorized. Do not use live bank/mail credentials or mutate profile databases.

## Acceptance

- Both cards are reachable in the same actual Settings render; their preload
  calls reach registered engine methods and selected-profile storage.
- PEC migration and Qonto migrations coexist on fresh and legacy databases;
  protected backup, row identity, tenant confinement, mail filtering and bank
  privacy remain intact. Old engines receive actionable errors.
- Logout, same-UID relogin, engine/profile changes and late results preserve
  the current auth/finance guarantees, including mailbox password form state.
- Relevant engine regressions, combined Settings/user-path checks, auth and
  billing-picker regressions, TypeScript and production app build pass.
- Release packaging includes both engine modules; shared main contains both
  integrations and latest fixes after a fresh final review. Document the exact
  delivery commits and distinguish source acceptance from installed Desktop,
  live PEC/provider-UI acceptance and a future remote-engine rollout.
