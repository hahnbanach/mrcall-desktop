---
doc_baseline_commit: 225f455f0a4c725c7459e776cfdf5167b7022240
doc_baseline_date: 2026-09-13
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

The CTO selected K3 max. Billing server `prod-99091c35` and four pinned
Café124 engines `8d83193` are deployed. Production uses K3/custom through its personal OpenRouter
key; the other three retain their billing/model settings pending a choice
between credits and personal OpenRouter keys. See the [adoption plan](execution-plans/2026-09-16-k3-production.md)
and [runtime contract](../engine/docs/features/k3-reasoning.md).

Authenticated production identity, model catalog and preparation status checks
pass. A personal-key K3 max smoke returned OK with 68 reasoning tokens and
USD0.00137515 provider cost, settled with no remaining hold in its USD0.20 test
ledger. The earlier credit-path execute was refused with HTTP402 before provider
dispatch; its separate test ledger retains USD0.209. Funded credit acceptance
remains outstanding.
Production keeps its current USD20/day cap; the other three keep USD5/day.
Automatic processing remains off and preparation remains paused for all four.

Engine API spending controls are independent of Claude Code operator ticks and
direct kernel classifiers. See [execution/control boundaries](operator-setup.md#ai-execution-and-controls).

The 360-output [model comparison](evaluations/2026-09-15-controlled-model-quality.md)
and 180-output [reasoning comparison](evaluations/2026-09-16-k3-reasoning-quality.md)
have superseded semantic scores after confirmed reviewer errors. Neither original
nor intermediate counts establish business-decision error rates or model rankings.
The [disputed cases](evaluations/2026-09-16-disputed-case-review.md) separate task
decisions, unsupported explanations and unknown facts. Offline grading now binds
each output to complete per-label evidence and validates exact source quotations;
legacy judgments remain unassessed under that protocol. The
[complete selected review](evaluations/2026-09-16-reviewed-model-comparison.md)
covers all 60 selected cases and 240 outputs, with explicit peer adjudications;
it is post-hoc evidence, not a fresh holdout or a production error-rate estimate.
Automatic backlogs stay paused. K3 max runtime support is deployed; this does
not turn the limited comparison into a production quality guarantee.

Desktop includes the V1 Desktop → engine → operator setup journey.
Desktop opens Setup by default: configuration, authenticated remote connection,
mailbox preparation, then a copyable descriptor-based workspace command.
The engine owns mailbox processing and company memory; the cs-kernel workspace
owns operator procedures. Codex/Claude Code subscriptions remain separate from
engine LLM billing. A product chat and personal delegated sending are future work.

Setup reports owner-scoped preparation evidence, saved billing and credential
availability; unknown evidence is not readiness. The workspace handoff exposes
identity, endpoint and command without refresh credentials. Check connection
verifies the selected transport without restarting it.

Settings remains reachable when the engine is down. Reconnection invalidates
stale snapshots; unsaved settings must be explicitly discarded before loading
a different backend. Preparation actions remain user-triggered.

Desktop v0.1.49 is published for Apple Silicon from reviewed source `225f455`.
Component journeys, typecheck, build, signing and custom notarization pass in
workflow34759876569. Installation and personal-key GUI entry on the CTO's Mac
remain unverified. Other hosted accounts retain the previous checkout until the host's
normal reconciliation; the four affected accounts use pinned guarded releases.

Kernel v0.44.0 is publicly released and installed in both maintained operational
clones. The linked operator guide installs the public kernel release.
See [operator setup](operator-setup.md), the
[brief](briefs/2026-09-10-desktop-to-operator-onboarding.md), and the
[delivery plan](execution-plans/2026-09-10-desktop-to-operator-onboarding.md).

Existing source supports local stdio and Firebase-authenticated remote engines,
shared company memory through `memory.join`, headless descriptors, provisioning,
BYOK and MrCall-credit LLM routing. Contracts live in [IPC](ipc-contract.md),
[remote backend](remote-backend.md), and the per-tree documentation.
Prior deployment/package observations remain historical in the archive;
the OpenRouter rollout above is verified on 2026-09-13; project-memory
deployment evidence is from 2026-09-10.

Shared written projects are revisioned company-engine records, separate from
entity blobs, accessed through `cs project` in kernel v0.44.0. The company store contains six 124 projects
(28 documents) and four MrCall projects (23 documents), shared with other company
members. Original folders remain in the private clone Git histories
(124 `abd48c8`, MrCall `3f53462`) and are absent from working trees. This is deployed on the hosted
engine; the bundled v0.1.48 sidecar includes these RPC methods.
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

1. Verify v0.1.49 installation and personal-key entry on the CTO's Mac.
2. Apply the controlled comparison's quality gates before any model change or
   backlog activation.
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
