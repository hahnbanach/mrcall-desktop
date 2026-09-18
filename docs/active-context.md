---
doc_baseline_commit: 340a99d14ee40fc0b30b2d67ace83d63170cc7fb
doc_baseline_date: 2026-09-18
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

The Café124 production-mailbox hosted engine runs isolated pilot source
`340a99d` with kernel `2c6fa5a` and a private, expiring order-existence grant.
The selected real email passes Shopify lookup and unsent engine draft creation.
Its review copy is in the mailbox's Drafts through an explicit kernel mirror;
Desktop's Drafts tab remains a placeholder, not a working list of engine drafts.
The grant retires at 2026-09-19 09:00 UTC. Other hosted engines keep their releases.
Personal OpenRouter/K3, the USD20/day cap and paused automatic work are unchanged.
A saved Anthropic key does not change the provider or enable fallback. See the
[engine state](../engine/docs/active-context.md) and
[runtime contract](../engine/docs/features/k3-reasoning.md).

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

Desktop v0.1.49 is the recorded Apple Silicon release. Current installation and
personal-key GUI entry on the CTO's Mac remain unverified. Runtime contracts are
in [IPC](ipc-contract.md), [remote backend](remote-backend.md) and per-tree docs.

## Unresolved

- The three other Café124 profiles await a choice between MrCall credits and
  personal OpenRouter keys. Funded K3 credit acceptance remains open.
- Packaged-app/fresh-account acceptance remains separate from source and hosted
  API checks. Windows and Intel are outside the recorded default release matrix.
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
2. Verify the installed Mac application and personal-key entry through its GUI.
3. Resume deferred product work from its existing briefs when requested.
   The [thin web/mobile client brief](execution-plans/cross-machine-thin-clients.md)
   is a parked nice-to-have, not scheduled work; remind the CTO that it already
   exists rather than analysing it again. Electron remains the primary client.
