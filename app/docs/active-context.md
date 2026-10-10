# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

Desktop v0.1.56 is the current published Apple Silicon release (CI 37787264959; notarization
credentials validated, un-notarized path skipped). The CTO confirms
Remote Mario Gmail reconnects after full app quit/reopen. Fresh-device sign-in
and personal-key GUI entry remain unverified; engine/API checks do not establish
those packaged-app journeys.

The session-lifecycle repair passed two independent final source and delivery
reviews after the CTO's Remote timeout/403 cleared on full app quit/reopen. Main logout clears per-window credentials and
cancels refreshes offline; token UID/profile/expiry consistency and guarded
renderer refresh prevent stale-session reuse. Remote, Test connection and
provisioning share bounded fresh-token retrieval. Focused synthetic tests execute
actual App/preload/main IPC paths and a local WebSocket handshake; typecheck/build
pass. Signed/notarized Apple Silicon 0.1.53 is published (CI 37278638471;
source/tag match, signing observed, notarization required and not skipped).
0.1.55 and 0.1.56 include that repair; installed-patch GUI acceptance remains pending.
Work trace: [auth recovery](../../docs/execution-plans/2026-10-05-desktop-auth-session-recovery.md).

The billing-business picker repair is published in 0.1.54 after two independent
source approvals; signed CI 37289911832 passes and both delivery reviewers
return APPROVED. Discovery covers company and personal labels, distinguishes failure from
empty results, and requires explicit selection even for a sole result. Bounded
lookups ignore superseded account/transport results. The precise CTO incident
remains uncorrelated; an installed-patch search is still needed. Work trace:
[picker recovery](../../docs/execution-plans/2026-10-05-business-picker-recovery.md).

Published 0.1.55 fixes selected non-UUID businesses being re-resolved as
names and falsely marked invalid in 0.1.54. Save already validates exact IDs.
Explicit opaque-ID resolution and actual-picker numeric/non-UUID regressions
pass. Signed CI 37298416013 succeeds; both independent delivery reviews are
APPROVED. Installed-patch acceptance remains pending. Work trace:
[opaque IDs](../../docs/execution-plans/2026-10-05-business-id-resolution.md).

Settings separates MrCall/Anthropic/OpenRouter billing from model selection.
The free catalog follows the provider; custom defaults and advanced role
settings are explicit. Keys save on the active engine, including remote profiles.
Daily allowance, uncertain holds and paged reconciliation are visible. Top-up
opens the MrCall dashboard. Pending selections differ from saved policy, and
stale account/transport responses are ignored.

Preparation separates free sync from bounded analysis and persistent pause.
Errors survive refresh; older engines cannot fall back to unbounded analysis.
Automatic analysis defaults off. Resume starts one batch without enabling
recurring work. Setup retains the engine/operator handoff and saved billing state.

Settings carries a Mailboxes card (list with state, Add with preset and a
connection test before Save, Edit, Remove; the primary is read-only) and the
Email view a mailbox filter and per-message chip with more than one active
mailbox; archive reads the engine's `ok` and rolls back on a per-mailbox
failure. Typecheck, build, onboarding and `scripts/test-mailboxes-ui.mjs`
pass. Cancel, account changes and engine changes clear credentials and invalidate
late tests or mutations. Older engines receive an upgrade instruction.
Released in Desktop `v0.1.56`; [cross-cutting state](../../docs/active-context.md) tracks the hosted migration.

React component journeys use fake RPCs; their successful results, typecheck and
build are source checks, not live GUI acceptance. Current hosted deployment and
model selection are owned by [cross-cutting state](../../docs/active-context.md).

The [Qonto Settings and Tasks workflow](qonto.md) has a native browser fixture
through real preload and Python dispatch, durable SQLite, source reads, task
actions and priced publication receipts. Process restart preserves pause and
receipt replay; disconnect/deletion retain edited private shells and historical
facts. Electron IPC and external providers remain fixture substitutions. M5
review is approved, including company-change consent and late-reply guards.
Support now has real authenticated banking/source/managed-assistant acceptance;
its corrected UTC source timestamps match the managed answer. Packaged
Desktop and provider-UI acceptance remain pending in the delivery plan.
Qonto and PEC/additional mailboxes are combined with the 0.1.55 source fixes
and ship in Desktop `v0.1.56`. Tags 0.1.54 and 0.1.55 contain neither Settings card.
The [integration plan](../../docs/execution-plans/2026-10-05-mailboxes-qonto-release-integration.md)
records source delivery and verification; [cross-cutting state](../../docs/active-context.md) tracks the published release.
Explicit logout clears finance state and rejects late responses even if
Firebase signout fails; same-UID relogin is covered by the combined App/Qonto
lifecycle regression. The `v0.1.56` Qonto card still offers the engine bootstrap
option; current source has typed login and key as its only credential source.

## Unresolved

- Additional mailboxes: live PEC.net acceptance through the installed GUI
  and the hosted rollout are pending. Settings recovery and the combined
  Mailboxes/Qonto native browser journey pass on synthetic profiles.
- Reopen Settings after a connection change: reloading identical settings does
  not refetch the catalog. Stale choices remain disabled.
- Fresh-device sign-in and personal-key entry on the CTO's Mac
  still need an application acceptance pass. Synthetic model comparisons do not
  certify task quality.

## Next

Verify the signed patch installation and Settings journey. Keep hosted automatic work
paused until explicitly requested. References: [preparation](bounded-preparation.md)
and [archive](active-context-archive.md).
