# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

Desktop v0.1.49 is published for Apple Silicon from reviewed source `225f455`.
Workflow34759876569 completed distribution signing and the custom notarization
hook before publishing the DMG.
Payment/model separation is implemented and independently reviewed.
Installation on the CTO's Mac remains unverified.

Settings exposes independent MrCall/Anthropic/OpenRouter billing and model
selection. Its free catalog reflects the active provider; the model card names
the active preset and marks inactive custom defaults. Changing a default selects
custom explicitly and preserves advanced role overrides. Personal OpenRouter
keys save on the active engine, including remote profiles. Settings also exposes
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
module/chunk advisories remain. A separate synthetic production API credit call and blinded model comparison
are verified; personal-key GUI entry on the CTO's Mac remains unverified.

## Unresolved

After a connection change, reopen Settings to reload the model catalog; an
in-place reload of identical values does not refetch it. Stale choices remain disabled.

The compatible server and four affected engines are deployed; Desktop v0.1.49
installer is published. Source verification does not establish installation or a fresh-device
signin test on the CTO's Mac. The small synthetic comparison does not certify production task quality.

## Next

Verify v0.1.49 installation on the CTO's Mac. Keep affected automatic work
paused. References: [preparation](bounded-preparation.md),
[cross-cutting state](../../docs/active-context.md),
[archive](active-context-archive.md).
