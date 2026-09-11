---
doc_baseline_commit: da85537b809ba278de66ced021fcab758f6c7655
doc_baseline_date: 2026-09-11
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

Predictable spending is implemented with independent M1–M4 and final approvals.
Billing server `prod-c238edf8` is deployed with the additive PostgreSQL ledger;
authenticated free capabilities and quote return the bounded protocol. Four
Café124 engines run isolated release `83075a0`. Each retains its USD5 daily cap,
uses the explicit economy preset (Haiku), and has automatic processing disabled
and preparation paused. No paid acceptance calls have been made.
See [current delivery plan](execution-plans/2026-09-11-predictable-ai-spending.md).

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

Setup reports the engine's saved provider and credential availability. Settings
separates saved billing from unsaved choices and keeps personal API-key entry
optional. Check connection verifies the selected transport without a restart.
The [acceptance recovery plan](execution-plans/2026-09-10-setup-billing-recovery.md)
tracks these UI corrections and their verification.

Settings remains reachable when the engine is down. Reconnection invalidates
stale snapshots; unsaved settings must be explicitly discarded before loading
a different backend. Preparation actions remain user-triggered.

Desktop v0.1.47 remains the published Apple Silicon installer; v0.1.48 is prepared
for release with spending controls and shared project RPC. The new UI passes
component journeys, typecheck and build; installation on the CTO's Mac is not
verified. Other hosted accounts retain the previous checkout until the host's
normal reconciliation; the four affected accounts use pinned guarded releases.

Kernel v0.44.0 is publicly released and installed in both maintained operational
clones. Desktop v0.1.47 still has cosmetic development-kernel wording; its linked guide
now installs the public kernel release.
See [operator setup](operator-setup.md), the
[brief](briefs/2026-09-10-desktop-to-operator-onboarding.md), and the
[delivery plan](execution-plans/2026-09-10-desktop-to-operator-onboarding.md).

Existing source supports local stdio and Firebase-authenticated remote engines,
shared company memory through `memory.join`, headless descriptors, provisioning,
BYOK and MrCall-credit LLM routing. Contracts live in [IPC](ipc-contract.md),
[remote backend](remote-backend.md), and the per-tree documentation.
Prior deployment/package observations remain historical in the archive;
the spending rollout above is verified on 2026-09-11; project-memory
deployment evidence is from 2026-09-10.

Shared written projects are revisioned company-engine records, separate from
entity blobs, accessed through `cs project` in kernel v0.44.0. The company store contains six 124 projects
(28 documents) and four MrCall projects (23 documents), shared with other company
members. Original folders remain in the private clone Git histories
(124 `abd48c8`, MrCall `3f53462`) and are absent from working trees. This is deployed on the hosted
engine; the bundled v0.1.47 sidecar does not include these RPC methods.
See the [brief](briefs/2026-09-10-shared-project-memory.md) and
[plan](execution-plans/2026-09-10-shared-project-memory.md).

## Unresolved

- Windows and Intel are outside this release's default matrix. Live fresh-account
  provisioning and a
  packaged-app acceptance pass remain separate from the CTO's development-app
  acceptance and the authenticated hosted-engine read check.
- Remote provisioning requires host UID-to-company membership. Choosing
  `wss://desktop.mrcall.ai` alone does not establish that prerequisite.
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

1. Publish Desktop v0.1.48 and verify the release artifacts.
2. Evaluate economy/GLM task quality before enabling recurring backlogs.
3. Continue the deferred product work from its existing briefs.

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
