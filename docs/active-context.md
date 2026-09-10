---
doc_baseline_commit: 6b94746
doc_baseline_date: 2026-08-28
---

# Active Context — Cross-cutting

<!-- doc-scope:start -->
Scope: the cross-cutting volatile state of mrcall-desktop — what spans
engine ↔ app or describes the repo as a whole (the JSON-RPC contract, the
release pipeline, the brand rename, monorepo conventions). Engine-only state
lives in [`../engine/docs/active-context.md`](../engine/docs/active-context.md),
app-only state in [`../app/docs/active-context.md`](../app/docs/active-context.md),
durable cross-cutting facts in [`../AGENTS.md`](../AGENTS.md) and the documents
[`README.md`](README.md) routes to, pruned narrative in
[`active-context-archive.md`](active-context-archive.md). A living snapshot of
what is *current*, targeting ≤ ~120 lines.
<!-- doc-scope:end -->

## State now

Desktop includes the V1 Desktop → engine → operator setup journey.
Desktop opens Setup by default: configuration, authenticated remote connection,
mailbox preparation, then a copyable descriptor-based workspace command.
The engine owns mailbox processing and company memory; the cs-kernel workspace
owns operator procedures. Codex/Claude Code subscriptions remain separate from
engine LLM billing. A product chat and personal delegated sending are future work.

`setup.state` includes nullable owner-scoped mailbox memory-processing evidence.
Unknown evidence is not readiness; empty and partially processed mailboxes remain
incomplete. This does not certify reply quality or successful task detection.
The desktop handoff exposes selected identity, endpoint, path and command only;
refresh credentials remain in the existing private descriptor.

Setup reports the engine's current key-or-Firebase billing policy. Settings
separates saved billing from unsaved choices and keeps personal API-key entry
optional. Check connection verifies the selected transport without a restart.
The [acceptance recovery plan](execution-plans/2026-09-10-setup-billing-recovery.md)
tracks these UI corrections and their verification.

Settings remains reachable when the engine is down. Reconnection invalidates
stale snapshots; unsaved settings must be explicitly discarded before loading
a different backend. Preparation actions remain user-triggered.

Desktop changes are on main and tagged `v0.1.47` at `6f0b8f8`. The hosted engine
runs that revision: seven profile services, provisiond and Caddy are active;
authenticated `setup.state` returns the new evidence fields. The CTO has accepted
the macOS Desktop test. The macOS Apple Silicon installer is published as
[v0.1.47](https://github.com/hahnbanach/mrcall-desktop/releases/tag/v0.1.47),
Developer ID signed and Apple-notarized.

The kernel changes remain on `feat/operator-setup-ux`; no kernel release or
operational clone upgrade is included. Its released pin lacks the new commands,
so workspace setup requires the linked development-source installation.
See [operator setup](operator-setup.md), the
[brief](briefs/2026-09-10-desktop-to-operator-onboarding.md), and the
[delivery plan](execution-plans/2026-09-10-desktop-to-operator-onboarding.md).

Existing source supports local stdio and Firebase-authenticated remote engines,
shared company memory through `memory.join`, headless descriptors, provisioning,
BYOK and MrCall-credit LLM routing. Contracts live in [IPC](ipc-contract.md),
[remote backend](remote-backend.md), and the per-tree documentation.
Prior deployment/package observations remain historical in the archive;
the production observation above is from the 2026-09-10 rollout.

## Unresolved

- Windows and Intel are outside this release's default matrix. Live fresh-account
  provisioning and a
  packaged-app acceptance pass remain separate from the CTO's development-app
  acceptance and the authenticated hosted-engine read check.
- Remote provisioning requires host UID-to-company membership. Choosing
  `wss://desktop.mrcall.ai` alone does not establish that prerequisite.
- The new CLI is unreleased. Public-install onboarding needs release coordination
  after source validation; do not present the old pin as containing `cs setup`.
- Chat approval isolation has a separate
  [brief](briefs/2026-09-10-chat-approval-isolation.md) and is deferred.
  A comprehensive security review is also deferred by the CTO.
- Existing backlog includes CI for engine tests/lint and app typecheck,
  desktop-to-proxy transport coverage, multi-window auth tests, installer
  completeness checks and OAuth-secret detection. See [harness backlog](harness-backlog.md).
- Historical task-mode broken-import and legacy transport issues need their own
  verification before that path is restored; this work does not restore it.
- Calendar token wiring, remaining raw RPC errors, Google packaged sign-in
  configuration and phone-call memory parity remain separate workstreams.

## Next

1. Coordinate the kernel release before claiming public-install operator setup.
2. Continue the deferred product work from its existing briefs.

### Deferred (nice-to-have)

Low-priority roadmap — the brief is written, execution is NOT scheduled.
**If Mario asks for one of these and has forgotten it exists, remind him the
brief is already written and restart from it** — do not re-analyse from
scratch. This subsection is durable: it is not session narrative and must
not be pruned or archived.

- **Thin web/mobile client (PWA) on top of the cross-machine transport** —
  *nice-to-have.* Electron stays the primary client; web/mobile is
  emergency access from a browser or phone. Single-tenant,
  single-active-client with eviction (a new connect closes the old one);
  PWA, not native; resume re-scoped to "continue a daemon-side operation
  remotely". Full brief:
  [`execution-plans/cross-machine-thin-clients.md`](execution-plans/cross-machine-thin-clients.md).
  Builds on [`execution-plans/cross-machine-transport.md`](execution-plans/cross-machine-transport.md)
  (Phase 1–3b implementation; deployment observations are historical).
