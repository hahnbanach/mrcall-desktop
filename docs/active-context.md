---
doc_baseline_commit: a9e6539d270d3272cdff83a39346be9372245809
doc_baseline_date: 2026-09-28
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

Three Café124 engines import pinned release `8d83193`; production runs the
separate evolution-pilot release `340a99d` through its systemd drop-in. The
billing server is `prod-99091c35`. Production uses K3 max through its personal OpenRouter key,
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

GPT-Live M4 is merged and phone-accepted for the isolated fixture. The
Cloudflare tunnel now forwards 127.0.0.1:8787 to the production daemon; its
public URL is unchanged. Authenticated StarChat readback confirms Café 124 business
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop` under production UID
`Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`, with number +390250552776, template
`starter` and version 9. Vonage and OpenAI callbacks retain their existing
public URLs. The production daemon runs pinned voice release `a9e6539`, with
the Desktop socket and loopback listener in one process. Local/public health,
authenticated Desktop RPC and negative webhook probes pass. The first real
call used voice config revision 3: the operator heard their name and an answer
that claimed no information was available. Private diagnostics confirm the
contact matched, with zero historical sentences selected; the closed ledger
holds correlated usage and two carrier leg receipts under provisional
reconciliation. Revision 4 clarifies that other contact details are simply
not authorized for this phone call. The company store has 11 sentences for
that contact, but none is selected. See the active
[plan](execution-plans/2026-09-27-cafe124-voice-daemon.md).

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
been downloaded from the release, let alone run. The Windows risk is specific —
neonize loads from loose files via `sys._MEIPASS` rather than as a collected
package, and a green build cannot prove that import resolves at run time.
Runtime contracts are in [IPC](ipc-contract.md),
[remote backend](remote-backend.md) and per-tree docs.

WhatsApp can silently disconnect when neonize's bundled protocol falls behind.
The current checkout defines a refresh loop, but the pinned Café 124 releases
do not contain it. `whatsapp.status` still has no external reader, and the app
Refresh button only lists threads. See the archived
[channel details](active-context-archive.md).

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
  review are deferred. Calendar integration, raw RPC errors,
  installer coverage and multi-window auth checks retain their existing owners.
- Historical task-mode/import and legacy transport issues need verification
  before their paths are restored.
- The Café 124 voice plan still needs production validation of the reviewed
  runtime disclosure path, heard follow-up and interruption evidence, and final
  independent review.
  An on-demand review path is coded and independently reviewed in the checkout;
  production still grants only the known caller's first name.
  The first call's reserve remains held against provisionally covered exposure;
  it is not a settled invoice. If a later test fails, restore the prior pinned
  release and isolated listener without changing the tunnel.

## Next

1. Deploy the reviewed per-question memory path for +393480727052 to a new
   pinned production release, then verify the service, webhooks and diagnostics.
   Repeat the call and obtain a human report on follow-up and interruption.
2. Resolve the remaining billing choices and funded credit acceptance. Keep
   preparation paused until the CTO explicitly requests a bounded run.
3. Verify the installed applications through their GUI: the Mac one with
   personal-key entry, and the Windows one at all — install, open, scan the
   WhatsApp QR. Until that runs, support@ keeps telling customers macOS only.
4. Give a headless caller a way to see the WhatsApp channel's state —
   `whatsapp.status` has no reader outside this repo.
5. Resume deferred product work from its existing briefs when requested.
   The [thin web/mobile client brief](execution-plans/cross-machine-thin-clients.md)
   is a parked nice-to-have, not scheduled work; remind the CTO that it already
   exists rather than analysing it again. Electron remains the primary client.
