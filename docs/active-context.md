---
doc_baseline_commit: 33e157ecc04673859972f5beaeabc0e77c4843eb
doc_baseline_date: 2026-10-01
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

Mnemonic M9 source is integrated on `main` through fetched commit `19639d2`.
The recorded Haiku corpus failed AC 5; the CTO's decision defers its
re-measurement to M10 on the resolver-selected model. This reconciliation
does not establish deployment or change the rollout gates. Engine details are
in [the memory snapshot](../engine/docs/active-context.md).

Main and the Café 124 production voice release read standing instructions from
the reserved company-document project. Telephone conversion reads `phone.md`;
USER_NOTES is retired. See [standing instructions](../engine/docs/features/project-memory.md).

Three Café124 engines retain the `8d83193` release family; production runs
`phone-md-5ebe3fa` through its systemd drop-in. The billing server is
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
covers 60 cases and 240 outputs. Its findings do not estimate production error
rates or establish model equivalence.

Desktop's setup journey configures an engine, verifies its authenticated
connection, prepares data and hands off a descriptor-based cs-kernel workspace.
The engine owns mailbox processing and shared memory; the clone owns operator
procedures. Claude Code headless and kernel direct classifiers have separate
billing and pause controls. See [operator setup](operator-setup.md#ai-execution-and-controls).

GPT-Live is the sole telephone model. Café 124 serves its Desktop socket and
+390250552776 through the existing tunnel, bound to business
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop`, UID
`Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`, starter and voice configuration revision 6.
Production imports `mrcall-voice-cafe124-phone-md-5ebe3fa`, built from M1 base
`706fe2a` plus the reviewed voice/confinement patch. Conversion uses stored
`operator-instructions/phone.md` revision 1 (`cf61cd70…`), prompt/schema 8/6.
The reviewed derived view retains 270 initial characters, one complete detail
and six approved aliases. One K3 conversion settled; recovery preserved the
same selected facts at current source offsets. Production preview matches the
mailbox document and procedures; all six stored documents remain revision 1.
Health, authenticated binding and unsigned callback checks pass. Both clone
pause files are absent. Mario imports `bbde719` through his unchanged executable
and socket; actual preview matches his mailbox/procedures revision 1. Mario has
no operator schedule; 124's scheduled operator reads his inbox without drafting.
Mario's project-local permissions deny instruction writes in twelve supported
command spellings, including raw `instructions.store`. Read access is preserved;
the same [Astra reviewer approved the P1 repair](evaluations/2026-10-01-astra-instruction-write-denial-rereview.md).
See the [source migration](execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md).

The [pilot](execution-plans/2026-09-27-cafe124-voice-daemon.md) is completed;
the [knowledge plan](execution-plans/2026-09-28-voice-company-knowledge.md) remains
active. The owner accepted the October 1 handset call; independent review
approved its source-grounded direct service answer against the prior source.
That historical call does not certify the new conversion. Spoken company-detail
retrieval, broader repeated cases, later caller-history entailment and quantitative
latency remain open. Caller history requires a unique selected-contact match.
Archive acceptance remains APPROVED with nine funded private call archives;
StarChat transcript upload is cancelled. Old uncertain credit holds remain
quarantined. No further handset call was made for source migration.

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
- Café 124's manual pilot is approved. The broader knowledge plan still needs
  spoken detail retrieval, adverse/repetition coverage and quantitative latency
  evidence. Voice reserves remain provisional.

## Next

1. Continue the active knowledge plan from its untested company-detail and
   broader case/quantitative latency gates; do not repeat archive acceptance.
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
