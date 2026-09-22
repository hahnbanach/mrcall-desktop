---
doc_baseline_commit: b2866badfee488a6b1bea2e18613c39cdf646d26
doc_baseline_date: 2026-09-22
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

Four Café124 engines run pinned release `8d83193`; the billing server is
`prod-99091c35`. Production uses K3 max through its personal OpenRouter key,
with a USD20/day limit. The other three profiles retain their previous billing
and model choices and USD5/day limits. All four have automatic processing off
and preparation paused. Adding a saved Anthropic key does not change the selected
provider or enable fallback. See [K3 adoption](execution-plans/2026-09-16-k3-production.md)
and [runtime contract](../engine/docs/features/k3-reasoning.md).

Personal-key K3 transport, reasoning and accounting have a successful synthetic
live acceptance; production identity, catalog and paused preparation checks pass.
A funded K3 credit response remains unverified. The separate failed credit smoke
has a conservative USD0.209 hold; hosted profile budgets are unaffected.

The [reviewed comparison](evaluations/2026-09-16-reviewed-model-comparison.md)
covers 60 selected cases and 240 outputs from 37 business clusters. It supersedes
older semantic scores. Its separate action, grounding and uncertainty findings
are post-hoc evidence, not a production error-rate estimate or model equivalence
claim. Deployment is the CTO's model choice under that limited evidence.

Desktop's setup journey configures an engine, verifies its authenticated
connection, prepares data and hands off a descriptor-based cs-kernel workspace.
The engine owns mailbox processing and shared memory; the clone owns operator
procedures. Claude Code headless and kernel direct classifiers have separate
billing and pause controls. See [operator setup](operator-setup.md#ai-execution-and-controls).

Settings supports independent provider/model selection, daily budgets and bounded
preparation. It remains reachable with an unavailable engine; stale connection
snapshots are invalidated. The workspace handoff exposes a path and command;
refresh credentials remain in the private descriptor outside the workspace.
Shared written projects are revisioned company-engine records separate from
entity blobs; see [project memory](../engine/docs/features/project-memory.md).

Desktop `v0.1.51-win` is the recorded release and carries a **Windows x64
installer alongside the Apple Silicon dmg**. The previous one was `v0.1.29`,
so a Windows user upgrading arrives from a build that old; `v0.1.40` through
`v0.1.51` ship the dmg alone. Neither application has been exercised: Mac
installation with personal-key GUI entry is unverified, and the `.exe` has not
been
downloaded from the release, let alone run. The Windows risk is specific —
neonize loads from loose files via `sys._MEIPASS` rather than as a collected
package, and a green build cannot prove that import resolves at run time.
Runtime contracts are in [IPC](ipc-contract.md),
[remote backend](remote-backend.md) and per-tree docs.

## Unresolved

- The three other Café124 profiles await a choice between MrCall credits and
  personal OpenRouter keys. Funded K3 credit acceptance remains open.
- Packaged-app/fresh-account acceptance remains separate from source and hosted
  API checks. Windows now builds (~3 minutes) and ships an installer, but stays
  opt-in and `continue-on-error`, so a regression would publish a release with
  no Windows installer and say nothing. Intel remains outside the matrix.
  Windows has no WhatsApp voice-note transcription: the transcription stack is
  excluded there to keep it out of the module graph.
- Remote provisioning needs host UID-to-company membership; an endpoint alone
  does not establish membership. Settings catalog refresh has a known same-value
  reload gap; reopen Settings after connection changes. See [backlog](harness-backlog.md).
- Product chat, delegated sending, approval isolation and a comprehensive security
  review are deferred. Calendar integration, phone memory parity, raw RPC errors,
  installer coverage and multi-window auth checks retain their existing owners.
- Historical task-mode/import and legacy transport issues need verification
  before their paths are restored.

## Next

1. Resolve the remaining billing choices and funded credit acceptance. Keep
   preparation paused until the CTO explicitly requests a bounded run.
2. Verify the installed applications through their GUI: the Mac one with
   personal-key entry, and the Windows one at all — install, open, scan the
   WhatsApp QR. Until that runs, support@ keeps telling customers macOS only.
3. Resume deferred product work from its existing briefs when requested.
   The [thin web/mobile client brief](execution-plans/cross-machine-thin-clients.md)
   is a parked nice-to-have, not scheduled work; remind the CTO that it already
   exists rather than analysing it again. Electron remains the primary client.
