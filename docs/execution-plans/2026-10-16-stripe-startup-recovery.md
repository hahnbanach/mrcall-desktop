---
status: active
---
# Stripe startup recovery

Brief: [startup recovery](../briefs/2026-10-16-stripe-startup-recovery.md),
independent brief reviewer APPROVED on 2026-10-16.

## Sequence and ownership

A worker owns StripeCard and its browser fixtures only. Add a bounded startup
phase, repair the engine session using existing ensureEngineSession before
capturing finance context, preserve all epoch/sequence checks, and expose loading,
unavailable-memory, identity and timeout failures with an enabled retry action.
Do not change the shared finance hook or relax identity checks. Late timed-out
requests cannot update state. The lead owns version 0.1.57-stripe.2, docs, checks,
independent integration review, exact-commit CI dispatch and artifact inspection.

## Verification

Exercise cached synchronous sidecar ready replay, repairable missing session,
identity rejection, unavailable memory, bounded pending startup, recovery and
reconnect during pending startup in the actual card/preload Chromium fixture.
Preserve existing connect/disconnect, secret clearing and context fence cases.
Run app typecheck and production build. Independently review the integrated
source before dispatch. Inspect successful signed/notarized installer artifacts.
Reconcile affected documentation through doc-end, run mechanical and doc-critic
checks, then obtain a separate final review after artifact inspection. No
baseline advancement while full operational acceptance is pending.
No real-key or installed-user success is claimed from fixture evidence.

## Rollback and limits

No remote runtime changes, restart, stable tag, or unrelated working-tree edits.
Rollback is the previous test installer; prior test candidate remains available.
Full Stripe operational and native-agent gates remain pending.

## Current evidence

Independent M1 review APPROVED. Actual Chromium card/authUtils/preload fixture,
typecheck and production build pass. Source commit
`e8ee42b00e0071e335334647ff6559ca33ca9eb2` completed successfully via
[Actions 38883997676](https://github.com/hahnbanach/mrcall-desktop/actions/runs/38883997676).
No remote runtime changes occurred. The same focused source patch was applied
to the original Desktop workspace, preserving unrelated local edits.

The signed/notarized Mac ARM64 replacement test installer is
[artifact 12038782433](https://github.com/hahnbanach/mrcall-desktop/actions/runs/38883997676/artifacts/12038782433).
Installed-user recovery and real Stripe acceptance remain pending. No stable
release tag or remote runtime change was made.
