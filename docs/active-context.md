---
doc_baseline_commit: 8fb21d37781415c78259c94179927ffa8047e0f5
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
matched selected contact. Six calls have closed ledgers with provisional
exposure reconciliation. A private `sessions.db` (0600) now has six rows keyed
to those ledger calls: three backfilled from received transcript deltas and
three marked `legacy_no_text`. The operator cancelled StarChat transcript
upload and permanently accepts possible missing words before transcript
attachment. A new real call on this release still needs archive/trace/ledger
correlation and final independent review. See the active
[plan](execution-plans/2026-09-27-cafe124-voice-daemon.md).

The hosted engine is being isolated per tenant
([toward-sandbox](execution-plans/2026-09-29-toward-sandbox.md)): M1 (tool
path confinement, `run_python` refused when serving) and the host-independent
part of M2 (per-profile Unix user, dual-name company store, `rekey`,
`mrcall-tenant` helper, transitional unit template) are on `main` at
`c2b3ca5` and reviewed. **M1 is deployed to all seven daemons** (2026-09-30:
the three unpinned ones on the service checkout, the four Café124 ones as
backports onto their pinned releases, rollback recorded in the plan). **No
profile is migrated to its own Unix user yet**: M2 must first pass the
scratch-unit probes on a scratch VM (the operator keeps its address outside
the repo). Self-serve provisioning stays closed until M2b is on all seven
profiles.

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
- Toward-sandbox: run the M2 scratch-unit probes on the VM, then 2a (Café124
  store relocation, all four stopped) and 2b (one profile per day); M3 egress
  and the brief's parked operational floor (backups, pinned rollout) follow.
  All need a session with a shell on the host; the cloud session only reads
  what those sessions commit.
- Product chat, delegated sending, approval isolation and a comprehensive security
  review are deferred. Calendar integration, raw RPC errors,
  installer coverage and multi-window auth checks retain their existing owners.
- Historical task-mode/import and legacy transport issues need verification
  before their paths are restored.
- Café 124's manual one-number voice test passed independent final review.
  The local archive is deployed and backfilled; a new call and final review
  remain open. Model judgment of mixed notes remains supervised. Six call
  reserves remain held; exposure is provisional, not settled.

## Next

1. Correlate a new real call across the private delta file, `sessions` row and
   ledger, then obtain independent final review of the local archive.
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
