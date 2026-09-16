# Active Context — App

<!-- doc-scope:start -->
Scope: current app capabilities, verification and immediate release work.
Engine state lives in ../../engine/docs/active-context.md; cross-cutting deployment
state lives in ../../docs/active-context.md. Historical snapshots are archived.
<!-- doc-scope:end -->

## State now

Desktop v0.1.49 is the recorded Apple Silicon release. Installation and personal-
key GUI entry on the CTO's Mac remain unverified; engine/API acceptance does not
establish packaged-app acceptance.

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

React component journeys use fake RPCs; their successful results, typecheck and
build are source checks, not live GUI acceptance. Current hosted deployment and
model selection are owned by [cross-cutting state](../../docs/active-context.md).

## Unresolved

- Reopen Settings after a connection change: reloading identical settings does
  not refetch the catalog. Stale choices remain disabled.
- Installation, fresh-device sign-in and personal-key entry on the CTO's Mac
  still need an application acceptance pass. Synthetic model comparisons do not
  certify task quality.

## Next

Verify the Mac installation and Settings journey. Keep hosted automatic work
paused until explicitly requested. References: [preparation](bounded-preparation.md)
and [archive](active-context-archive.md).
