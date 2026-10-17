# Stripe test installer

## Intent and scope

Produce an installable test candidate for the operator to exercise the native
Stripe Settings connection. Isolate the existing Stripe implementation from
unrelated local changes on Desktop base `434f325a`.

## Constraints and acceptance

Use the existing workflow-dispatch artifact build. No tag, public release,
hosted activation or clone update is part of this candidate. Keep the existing
release workflow intact. Preserve all original working-tree changes.
App `0.1.57-stripe.1` and PEP 440 engine `0.1.57.dev1` identify this test build.
Local source checks must pass before dispatch; installation and a restricted
Stripe account remain separate acceptance evidence.

The cross-repository design and implementation record remain in HB
`docs/briefs/2026-10-16-stripe-connection.md` and its matching execution plan.
