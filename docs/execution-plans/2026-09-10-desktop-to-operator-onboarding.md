---
status: completed
---

# Desktop-to-operator UX delivery

<!-- doc-scope:start -->
Scope: reviewed milestone execution and evidence for the two-worktree delivery;
product intent is in the paired brief, and shipped behavior belongs in the
setup guide and IPC contract. The final section records the separately authorized
Desktop production rollout; kernel release and clone upgrades are excluded.
<!-- doc-scope:end -->

## Brief gate and baselines

The [brief](../briefs/2026-09-10-desktop-to-operator-onboarding.md) and the
kernel slice brief passed independent review after clarifying that descriptor
secrets are excluded from templates, but non-secret identity metadata is allowed.

- Desktop worktree: `/home/mal/worktrees/mrcall-desktop-operator-setup`, branch
  `feat/operator-setup-ux`, baseline `9ea3dae`.
- Kernel worktree: `/home/mal/worktrees/cs-kernel-operator-setup`, same branch
  name in its repository, baseline `7d8d3f0`.
- Desktop typecheck baseline passes after the standard postinstall helper
  creates the ignored empty OAuth-secret example (no real secret copied).
- Kernel baseline `bash tests/run.sh`: all gates green; optional external golden
  fixtures remain absent. Baseline log `/tmp/cs-kernel-operator-setup-baseline.log`.

## Frozen integration seams

- Engine `setup.state` keeps all existing fields and adds
  `emails_analyzed_count: int | null`, `emails_pending_analysis: int | null`,
  `last_email_analyzed_at: string | null`. Count owner-scoped email rows whose
  `memory_processed_at` is set; missing/failed evidence is null, not zero.
  These fields prove mailbox memory processing only, not successful task
  detection, all sources processed, or quality of generated replies.
- App-only `workspace:status` IPC, exposed as `window.zylch.workspace.status()`,
  reads the bound profile's descriptor and returns a discriminated result:
  `{available: true, uid, email, engineWsUrl, descriptorPath, command}` or
  `{available: false, reason}`. All values are strings apart from the flag.
  `command` is native-shell quoted `cs init --descriptor PATH` (POSIX or
  PowerShell). Never return refresh token, raw JSON, API keys, or memory keys.
  Reject malformed, mismatched UID, or stale endpoint descriptors. This proves
  handoff availability, not remote liveness; the UI proves that separately.
- Kernel accepts `cs init --descriptor PATH`, maintaining the old unflagged
  flow. New `cs setup [--json]` emits a structured checklist and a nonzero
  result while prerequisites are missing or unverified. Human output includes
  next actions. Never invoke mutating RPCs or an LLM in the check.

## M1 — Parallel implementation, integrated review before M2

### Lead: engine evidence and desktop handoff boundary

Own `engine/zylch/rpc/setup.py`, its tests, new `app/src/main/workspaceStatus.ts`,
minimal IPC registration in main/preload/types, and IPC documentation.

Add the evidence and redacted handoff seam above. Scope to the bound profile;
write no credentials. Synthetic filesystem tests prove malformed/missing/stale
descriptors and quoting for spaces/apostrophes on both supported shells.
Engine tests use an isolated SQLite profile and dispatch the real handler to
prove per-owner counts, unknown evidence, and compatibility.

### Desktop implementer: Setup UX and recovery

Own new Setup view/model, App navigation, onboarding copy, Update feedback,
and provisioning error UX. Do not edit root-owned IPC/type files.

Create a default Setup hub with four steps: account settings; remote activation
and authenticated connection; preparation; workspace handoff. Existing backend
selection remains explicit. Show actionable provision/network/auth errors and
retry; 409 triggers status verification. Keep backend settings reachable when
the engine is down. Refresh state on restart/reconnection and after actions;
discard obsolete async snapshots from previous transports.

Use existing sync/training/update actions through Prepare data. No automatic
paid work on mount. Show partial vs unknown preparation honestly; the handoff
does not claim independent runtime login or a publicly released new kernel.
Surface the same-machine prerequisite, separate agent billing, and the copyable
descriptor-path command. Update copy must not promise local-only storage or
unconditional background continuation. Add deterministic state and rendered
component tests with failure/retry scenarios.

### Kernel implementer: explicit handoff and resumable setup

Own kernel source/tests and kernel-specific documentation. Thread the selected
descriptor outside serializable template config; use it consistently for safe
mail settings and credential transfer. Recover gracefully when settings cannot
be read and avoid silent wrong-provider defaults.

Return truthful installation stages. Use argument-list subprocesses for paths;
offer login only after successful install, explicitly confirmed. Validate the
expected UID in the proof response before reporting signed in. `cs setup`
checks workspace, matching engine identity, configured mailbox, trained prompts,
owner-mail preparation evidence, company memory, and external-agent executable.
Report absent/old engine evidence as incomplete. Check bounded read RPCs; do
not read raw secret settings or include exception payloads in JSON.

Add meaningful isolated tests including explicit descriptor dominance, no secret
serialization, failed install/login and retry, empty/new mailbox, wrong UID,
old engine, and a real stamped workspace with an offline transport fixture.
Preserve canonical agent-surface checks. No release/version bump or clone edits.

### M1 review gate

A fresh reviewer inspects both worktrees and focused results for integration,
truthful readiness, profile/endpoint identity, error recovery, credential
handling, and changes to existing paths. Repair all material findings before M2.

## M2 — End-to-end verification and delivery

Lead integrates M1 after approval; then:

- Run desktop typecheck, build, existing onboarding tests, and new setup/handoff
  tests. Run focused engine readiness and dispatch-contract tests in isolation.
- Run kernel `bash tests/run.sh` after changes; record optional fixture skips.
- Exercise the actual Setup component in an offline browser fixture with fresh,
  failed/retry, partial, and ready states. Inspect screenshots at desktop and
  narrow widths. A synthetic Electron bridge is an explicit test seam, not a
  claim of live Firebase/provisioning validation.
- Run an isolated generated clone against a controlled local/read transport and
  the installed changed kernel. Verify descriptor identity, checklist recovery,
  and no mutation/LLM method use. Keep all state under a task-specific temp root.
- Write a concise source-worktree runbook for both development workspaces, the
  new user journey, expected prerequisites, and honest live-validation limits.
- Reconcile living docs and plan state; run the mechanical doc gate and a
  separate semantic review of changed documentation.
- A fresh final reviewer checks the final-user path and evidence separately from
  M1. Complete delivery only after its material findings are resolved.

## Risk and rollback

No shared profiles, installed operational clones, remote services, tags, or
release pins are changed. Worktree removal or discarding this branch reverts
the development change. New RPC evidence is additive, old engines remain usable
with an unverified preparation state, and old init callers remain supported.
Do not mark activation success on an open TCP socket or descriptor presence.
No provisioning mapping bypass, personal delegation, or new payment integration.

## Progress

- Brief review: approved.
- Plan review: approved (independent reviewer, 2026-09-10).
- M1 implementation/integration review: approved after fixing engine-down navigation and Settings transport reload; independent reviewer, 2026-09-10.
- M2 implementation/user-path review: approved by a fresh independent reviewer.
- Verification: app typecheck and production build pass; existing onboarding,
  descriptor boundary, setup model and eight browser states pass. Settings browser
  recovery covers unavailable engine and dirty drafts across backend switches.
- Engine readiness and dispatch-contract tests: 20 passed (27 dependency warnings).
- Kernel full suite: all gates green, including gate 53's installed-source
  workspace journey; optional external golden fixtures remain absent.
- [Source acceptance guide](../operator-setup.md) includes explicit source install
  and refusal of the old-pin installation for this development pass.
- Documentation semantic review: approved; both snapshots and 24 load-bearing
  claims verified across repositories. Mechanical gates clean.
- Delivery complete for the bounded source slice. No deployment or live validation.

## Desktop production rollout — v0.1.47

The CTO accepted the macOS Desktop test and authorized production on 2026-09-10.
Scope is Desktop plus its packaged/hosted engine, not a kernel release or clone
upgrade. Independent release review accepts this scope with synchronized version
metadata, an explicit development-kernel prerequisite and installation guide,
and verification of the workflow's actual notarization result.

Preflight: hosted checkout clean at `9ea3dae` on main; seven profile daemons,
provisiond and Caddy active. One pre-existing failed escaped-comma orphan unit
is outside the discovered profile set; the updater must run without pruning.
Latest public release is v0.1.46 (macOS arm64, signed and notarized).

Sequence: verify candidate; fast-forward main; update hosted engine with existing
update-daemons.sh; verify daemon status and expected source; tag v0.1.47; watch
installer workflow and confirm release asset and signing/notarization outcome.
Rollback keeps v0.1.46 available; revert the additive source change on main and
re-run the updater if runtime verification fails. Never force-rewrite main.

Rollout status: completed — source, hosted engine and macOS arm64 release verified.
Main and v0.1.47 target `6f0b8f8`. The existing updater completed without pruning;
all seven expected profile services, provisiond and Caddy are active. Authenticated
setup.state through the existing operator client returns the new analysis fields
and known counts (the same call lacked those fields before rollout). No paid
model call or operational clone upgrade was performed.

Release-candidate checks: 40 targeted engine tests pass, including dispatch,
readiness and packaged-memory identifier/sweep/split-store coverage. TypeScript
and actual Setup browser checks pass, including the development-guide link.
Installer workflow: https://github.com/hahnbanach/mrcall-desktop/actions/runs/34486691290.
Production updater log: `/tmp/mrcall-0.1.47-deploy.log`.

Installer workflow completed successfully. The Apple credential probe succeeded;
installer logs confirm Developer ID signing and notarization submission with no
skip, followed by successful build completion. The stable, non-draft v0.1.47
release contains `MrCall.Desktop-0.1.47-arm64.dmg` (236,930,949 bytes); the public
download responds HTTP 200. No Windows/Intel assets are claimed. Release notes
explicitly retain the development-kernel installation prerequisite.

Release: https://github.com/hahnbanach/mrcall-desktop/releases/tag/v0.1.47.
The production identity read also confirms signed_in=true after deployment.


## Kernel release guide transition — v0.43.0

The operator guide now targets the kernel v0.43.0 public-tag bootstrap and the
normal wizard installation/login offers. It preserves the
`#kernel-macos-or-linux` anchor used by Desktop v0.1.47. The Desktop binary's
existing development-kernel banner is cosmetic stale wording; no installer or
app-code change accompanies this documentation transition.

The public kernel v0.43.0 tag is published at `ead47a6`. Both maintained
operational clones install it and reconstruct independently from their frozen
locks; their automated FULL comparison was approved without material regression.
The documented `uvx --from` bootstrap resolves the public tag and exposes
`init --descriptor`. A fresh real-account wizard was not run in this release
check. Earlier source-acceptance and Desktop-release observations above remain
historical evidence. The kernel delivery plan records detailed verification
limits and existing external-harness drift.
