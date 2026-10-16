---
status: active
---

# Stripe test installer delivery

[Intent](../briefs/2026-10-16-stripe-test-installer.md).

## Ownership and sequence

The isolated Desktop branch owns Stripe engine modules, RPC registration,
Settings/preload wiring, focused tests, connection docs and candidate versions.
The lead owns independent review, artifact dispatch and installer delivery.
Keep the existing workflow unchanged; dispatch builds artifacts without a tag.

## Verification

Candidate source checks pass: app typecheck and production build; 13 engine
Stripe tests; two standalone egress-policy unittest cases; actual Chromium
StripeCard/preload fixture. The fixture mocks provider/RPC dispatch.
The combined egress pytest invocation encounters an existing autouse storage
fixture referencing unavailable `settings.supabase_url`; the standalone
unittest invocation executes both policy cases successfully.
Current-session logs and exact file hashes are under
`/tmp/stripe-test-candidate-evidence/`; these are temporary evidence references.

## Remaining acceptance and rollback

Workflow dispatch [38878411430](https://github.com/hahnbanach/mrcall-desktop/actions/runs/38878411430)
is building exact source `e2004d745d53f50c73802fb00715d9e2130aa04d`.
Signed/notarized installer production, installed Electron, real restricted-key
Stripe reads and authenticated hosted acceptance remain unverified.
No release tag or hosted activation is implied. Discard this isolated
candidate branch to roll back source; Stripe Disconnect removes a saved key,
while provider key revocation remains an independent action.
