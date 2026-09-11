# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

Desktop v0.1.47 is the currently published signed/notarized Apple Silicon
installer. Predictable-spending UI is implemented and independently reviewed
on the daily-budget branch, but is not yet packaged or installed on the CTO's Mac.

Settings exposes explicit MrCall/Anthropic/OpenRouter billing, saved models,
daily allowance, uncertain holds and paged receipt reconciliation. Top-up opens
the MrCall dashboard. Pending choices are distinct from saved policy. Provider
selectors correctly resolve legacy profiles; balances and spending invalidate
on account/transport changes and ignore stale responses.

Preparation separates free synchronization from a bounded analysis run and
persistent pause. Errors survive refresh; older engines cannot fall back to
unbounded analysis. Automatic analysis is off by default. A resume action starts
one batch without enabling recurring work. Setup retains the engine/operator
workspace handoff and reports the selected billing provider.

Actual React component journeys with fake RPCs pass in test-preparation.mjs and
test-spending-ui.mjs. TypeScript checks and production build pass; existing build
module/chunk advisories remain. No paid provider call was made for acceptance.

## Unresolved

A new Mac installer requires the compatible server/engine rollout and release
pipeline. Source verification does not establish installation or a fresh-device
signin test on the CTO's Mac. OpenRouter task quality remains unmeasured.

## Next

Deploy compatible reviewed backend services,
then publish the signed Apple Silicon installer. Keep affected automatic work
paused. References: [preparation](bounded-preparation.md),
[cross-cutting state](../../docs/active-context.md),
[archive](active-context-archive.md).
