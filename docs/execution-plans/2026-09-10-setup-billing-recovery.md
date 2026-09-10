---
status: completed
---

# Setup billing recovery delivery

<!-- doc-scope:start -->
Scope: execution and evidence for the paired acceptance-defect brief, with one
renderer milestone and independent integration/final review. No server rollout.
<!-- doc-scope:end -->

## Gates

[Brief](../briefs/2026-09-10-setup-billing-recovery.md): independently approved.
Plan and M1 independently approved. Final code/user-path and scoped documentation
review approved; delivery checks pass.

## M1 — Renderer correction and focused reproduction

Root owns Setup: mirror profile key/Firebase billing policy, describe the selected
billing source, and give Check connection its own read/proof path on the existing
transport. Check current expected UID; never select/restart/provision on that
button. Keep initial remote activation unchanged. Extend the actual Setup browser
fixture to omit obsolete LLM_PROVIDER, cover BYOK/unsigned-in states, and assert
no mutation/restart or transient alert on checking a ready connection, including
wrong-identity refusal after a previously valid snapshot.

Settings implementer owns Settings and its actual browser fixture: distinguish
saved mode from pending key edits, explain Save is required, hide optional BYOK
entry by default on credits, keep explicit reveal, and preserve existing save
and stale-backend protection. Top-up opens only the existing dashboard URL;
handle failure visibly without changing billing. Browser checks cover unsaved
switch, explicit save/readback, key visibility and top-up destination/no write.
No real credential changes, automatic migration or paid actions; explicit user
Save retains the existing key-clear behavior.

Independent M1 review checks both paths before final verification.

## M2 — Verify and deliver

Run app typecheck and build, both real-component browser suites and existing
onboarding tests. Keep engine unchanged; no broad engine/kernel reruns needed.
Reconcile source guide/context and record evidence. Fresh final review follows
M1; mechanical doc check and diff check precede commit/push to the existing
feature branch. No package release or production deployment.

Rollback is reverting the bounded UI commit. Controlled synthetic bridges
prove UI semantics, not live provider balance or production authentication.

## Verification evidence

- Actual Setup browser: current key/Firebase billing without LLM_PROVIDER;
  successful check calls only current-transport identity; changed UID refuses;
  no transient alert, provisioning, selection or restart. Existing activation,
  partial/old evidence, retry, clipboard and responsive checks pass.
- Actual Settings browser: unsaved credits retains saved BYOK; explicit Save
  clears the fixture key once and reads back credits; optional key visibility,
  top-up URL/no write/error display and existing backend recovery all pass.
- Final TypeScript check, production build and existing onboarding tests pass.
  Mechanical docs gate and diff check pass. No engine/kernel source changes.
- Local evidence: `/tmp/mrcall-billing-setup-browser.log`,
  `/tmp/mrcall-billing-settings-browser.log`, `/tmp/mrcall-billing-build.log`,
  `/tmp/mrcall-billing-onboarding.log`; screenshots in
  `/tmp/mrcall-billing-recovery-artifacts/` and the Settings log's output directory.
- No live billable calls, production settings changes, release or deployment.
  The user must explicitly save the desired billing change in their app.
