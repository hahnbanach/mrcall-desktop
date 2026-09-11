# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

Desktop v0.1.48 is the published signed/notarized Apple Silicon installer.
Predictable-spending UI is implemented, independently reviewed and packaged.
Installation on the CTO's Mac remains unverified.

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

The compatible server and four affected engines are deployed; Desktop v0.1.48
installer is published. Source verification does not establish installation or a fresh-device
signin test on the CTO's Mac. OpenRouter task quality remains unmeasured.

## Next

Verify Desktop v0.1.48 installation on the CTO's Mac. Keep affected automatic work
paused. References: [preparation](bounded-preparation.md),
[cross-cutting state](../../docs/active-context.md),
[archive](active-context-archive.md).
