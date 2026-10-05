---
status: active
---

# Desktop authentication session recovery

Brief: [session lifecycle repair](../briefs/2026-10-05-desktop-auth-session-recovery.md).
Brief gate: `desktop_auth_brief_review`, **APPROVED**.

## Milestones and ownership

1. **Implement reviewed lifecycle in the clone.** Lead owns main-process
   cache/session helpers, `app/src/main/index.ts`, main/transport regression
   tests and delivery docs. One execute agent owns only renderer
   `firebase/authUtils.ts`, `App.tsx`, preload bridge, renderer types and focused renderer
   regression tests. It must preserve other edits and never change main/engine
   files. Work is parallel after this plan receives a fresh APPROVED verdict.

   Main keeps credentials in memory and validates JWT subject/expiry solely
   for consistency; server verification remains authoritative. Token pushes
   must match the originating window's bound profile and claimed UID. Getters,
   Test connection and provisioning share a bounded, coalesced fresh-token
   path with current-binding/session rechecks. Signout intercepts the existing
   `account.sign_out` IPC before generic RPC dispatch: clear cache/cancel
   refreshes, detach the old entry immediately, best-effort bounded old-engine
   signout, then stop that captured transport. Account switching invalidates
   cache/refresh work before attaching the new transport; same-account relogin
   must not preserve a stopped entry. Window close also invalidates requests.

   Main sends `account:requestTokenRefresh` with `{requestId, uid}` to only its
   owning renderer; preload invokes a registered
   `account.onTokenRefreshRequest(handler)` callback and acknowledges on
   `account:tokenRefreshResult` with `{requestId, ok}`. Credentials continue
   through existing `account:pushToken` only. Main verifies response sender,
   rechecks the current session, bounds/cancels requests, and does not log or
   persist credentials. Renderer subscribes during its auth listener and
   declines requests for another UID. An auth generation/current-user check
   discards old asynchronous token results, including same-account logout/
   login. The actual App logout invalidates the renderer generation before
   invoking main logout, independently of whether Firebase signout later
   succeeds. Both App token-pusher callbacks propagate `{ok:false}` as a
   failure for existing retries. Tests execute the actual App logout and
   token-pusher paths, including failed Firebase signout and late refreshes.

   Both sides receive focused tests with synthetic credentials. Integration
   review by a fresh reviewer requires actual tests and cross-boundary wiring,
   not source-shaped assertions alone; no dependent release starts until
   APPROVED. Repair REVISE findings and use the same reviewer for rereview.
2. **Integrate and verify user paths.** Run main/renderer regressions with
   deferred refreshes, missing/mismatched/expired credentials, independent
   windows, offline logout, same-user relogin and account change. Exercise
   actual WebSocket client against a local unsigned synthetic server to
   observe rejection followed by fresh successful connection. Test request
   cancellation and response sender/profile isolation. Run app typecheck and
   build. Read-only VPS metadata confirms the CTO's successful reopen without
   acquiring any token or generating paid calls. A fresh integration reviewer
   checks real output and the resulting docs before final delivery.
3. **Review and deliver.** Update only R5 of the sandbox plan with confirmed
   reopen, source causes versus historical uncertainty, tests and delivery
   state. Update app living context narrowly. Two fresh independent final
   reviewers inspect final code/results and constraints, without each other's
   verdict. Only after both APPROVED may the repair plan become completed.
   Pull with rebase before each main push, preserving unrelated dirty files.
   Assess the repository's signed Apple Silicon release path after checks;
   if an authorized release can be built, choose the next unused patch version,
   publish a reviewed tag and verify signing/notarization/artifact success.
   If delivery cannot be completed, record the concrete limitation and do not
   claim installed 0.1.52 contains the fix. Root sandbox R5 remains active for
   its separate mail/attachment/document and representative scratch gates.

## Risks and checks

- Claimed JWT metadata is untrusted. It prevents inconsistent local use; it
  never replaces Firebase cryptography or authorizes an owner mismatch.
- Logout, profile binding and refresh completion can race. Pending work is
  invalidated and old completion must not forward to a new/local engine.
- A suspended renderer may not answer refresh. Requests time out with clean
  disconnected state, never fall back to expired credentials or another user.
- Concurrent engine/config, AGENTS and README edits belong to other sessions;
  do not stage or revert them. No service-checkout, unit, key, policy or voice
  modification is part of this repair.

Plan review: `desktop_auth_plan_review`, REVISE for omitted App.tsx ownership
and explicit logout/pusher wiring checks; corrected before implementation.
Rereview: **APPROVED** before execution.

## Evidence and delivery state

- Renderer execute agent implemented only its assigned files. Thirteen actual
  behavior checks pass, including both App pusher paths and failed Firebase
  logout with a deferred refresh. Credentials in tests are synthetic.
- Lead implemented main in-memory sessions, correlated renderer refresh and
  bounded captured-transport retirement. Twelve actual behavior checks pass;
  fixture executes main IPC handlers and actual WebSocket transport against a
  loopback-only server (401 then fresh successful Test connection), plus local
  forwarding/current-binding guards. No real Firebase or paid request is used.
- App typecheck and production build pass. Build reports existing nonfatal
  module/Browserslist/chunk warnings.
- CTO confirms full app quit/reopen repaired Mario Gmail. The historical race
  is not reconstructed. No hosted service/profile/policy changes are made.
- Fresh integration gate: `desktop_auth_integration_review`, REVISE. Reviewer
  reproduced an existing restart continuation restoring a logged-out profile.
  Added captured-entry/window-lifetime guards before replacement and after
  waits; actual restart IPC regressions cover logout, different-account rebind
  and window close. All ten main checks pass; rereview **APPROVED**.
- Next unused patch tag is `v0.1.53` (checked remote tags). Package and lock
  metadata now agree on 0.1.53; `npm run test:auth` runs both focused suites.
  Existing tag workflow builds Apple Silicon only, with Developer ID signing
  and conditional notarization. CI success alone does not prove notarization:
  verify credential validation and selected build output before delivery.
- Final reviewer `desktop_auth_final_b`: REVISE for detached log polling
  surviving logout and orphaning after relogin. `detachWindowSession` now
  retires polling/scrollback with credentials; tailer replacement stops its
  predecessor and checks ownership before polling. Captured old transport
  callbacks cannot emit after detachment/rebind. Added actual tailer, logout,
  real window-close callback and retired local event regressions. Twelve main
  checks pass; final rereview **APPROVED**.
- Two fresh independent final source/publication-readiness reviews:
  `desktop_auth_final_a` **APPROVED**, `desktop_auth_final_b` **APPROVED**.
  Reviewer A also exercises actual profile bind/rebind and genuine 403 without
  reconnecting. Signed artifact delivery will receive post-CI rereview; this
  plan stays active until that delivery is verified.
- Signed patch delivery: starting. Existing
  0.1.52 does not contain this source repair. Parent sandbox R5 remains active.
