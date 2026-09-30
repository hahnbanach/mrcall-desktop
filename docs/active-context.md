---
doc_baseline_commit: b4e868ce42114b9fe277fa32def0fbc2e48d1ee9
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
separate voice release `8fb21d3` through its systemd drop-in. The
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
covers 60 cases and 240 outputs. Its findings do not estimate production error
rates or establish model equivalence.

Desktop's setup journey configures an engine, verifies its authenticated
connection, prepares data and hands off a descriptor-based cs-kernel workspace.
The engine owns mailbox processing and shared memory; the clone owns operator
procedures. Claude Code headless and kernel direct classifiers have separate
billing and pause controls. See [operator setup](operator-setup.md#ai-execution-and-controls).

GPT-Live M4 is phone-accepted for the isolated fixture. The Café 124 production
daemon serves both its Desktop socket and +390250552776 through the existing
Cloudflare tunnel and URL. StarChat readback binds business
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop`, UID
`Gn9IcuWzYyY7DBMHkVUGB7bIiTp2` and `starter`. Pinned release `8fb21d3`
and voice config revision 6 are live; health and negative
webhook probes pass. The caller policy validates incoming numbers with
libphonenumber and allows on-demand filtered history only for a uniquely
matched selected contact. Eight funded calls have closed ledgers with
provisional exposure reconciliation. Private `sessions.db` (0600) has eight
matching rows: three historical `legacy_no_text` rows and five reconstructed
from received deltas. The two post-release calls match their private delta
sources exactly. Local archive acceptance is independently APPROVED. StarChat
transcript upload is cancelled; possible missing words before attachment are
permanently accepted. The latest call contains invented business services
without delegation or a fact lookup. Overall acceptance is REVISE and the
[pilot plan](execution-plans/2026-09-27-cafe124-voice-daemon.md) remains active.
The [voice knowledge plan](execution-plans/2026-09-28-voice-company-knowledge.md)
is active. Corrected M2/M3 code in `d284414` has independent approval; prompt/schema
5/3 preserve qualified source spans and specific detail phrases. Its release and
rollback have independent approval, while production remains on `8fb21d3` with the company
path off. A real K3 conversion received HTTP 402 with no artifact; the checked
OpenRouter account balance is about USD0.21. This known refusal was reconciled
at zero; the older uncertain request remains quarantined. The owner explicitly
uses Café 124 production for handset trials after source/delta review and targeted
activation. Real-source semantics, spoken behavior and latency remain open.
No company-store revision is admitted.

Settings supports independent provider/model selection, daily budgets and bounded
preparation. It remains reachable with an unavailable engine; stale connection
snapshots are invalidated. The workspace handoff exposes a path and command;
refresh credentials remain in the private descriptor outside the workspace.
Shared written projects are revisioned company-engine records separate from
entity blobs; see [project memory](../engine/docs/features/project-memory.md).

Desktop `v0.1.51-win` ships a Windows x64 installer and Apple Silicon dmg.
Neither has been installed and exercised. Windows runtime import of neonize
remains unverified; its loose-file loading through `sys._MEIPASS` is a risk.
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
- Café 124's overall acceptance remains open after archive approval. Voice
  knowledge needs funded real-source conversion, semantic review and supervised
  production answer/latency evidence. Eight voice reserves remain provisional.

## Next

1. Finish the real-source conversion after OpenRouter funding, review its output,
   then use the approved deployment delta to activate the targeted Café 124 trial
   and request the owner's concrete services/detail call.
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
