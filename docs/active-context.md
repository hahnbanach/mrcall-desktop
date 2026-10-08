---
doc_baseline_commit: c638922afa202b143c9534ca10e6ace26206570e
doc_baseline_date: 2026-10-08
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

Company assignment APIs have local engine, CLI and native workflow acceptance
with signed approvals, retained audit and exact inbound coverage. Scoped draft
writes hold assigned or unknown threads; ordinary and Qonto tasks remain private.
Production enablement and live acceptance remain separate under the
[assignment plan](execution-plans/2026-10-08-explicit-task-assignment.md).

Local Desktop/kernel reliability gates and task/RPC contract checks pass.
The August umbrella is retired; exact source-only evidence, withdrawn work and
remaining owners are in the [closure record](execution-plans/2026-10-07-desktop-kernel-hardening-closure.md).
No new release, clone upgrade, installer/fleet acceptance or live cleanup is implied.

Native Qonto code has reviewed engine and Desktop browser-fixture acceptance,
including private tasks, managed history and consented minimal company facts.
Support's isolated release has real authenticated banking acceptance: its
single account is connected, 30-day source sync completes across restart,
and independent provider balances/movements/flows agree with source reads.
A real managed assistant uses the bank tool and cites its source. Its
engine-formatted UTC retrieval strings match the accepted managed answer.
Six other daemons and saved controls remain unchanged. Packaged Desktop and provider UI acceptance
remain unverified. Exact release, usage, rollback and remaining criteria belong
to the active [Qonto plan](execution-plans/2026-10-04-qonto-connection.md).

All seven hosted profiles run as separate Unix users with enforced outbound
allow-lists. Production voice preserves its pinned release; support has its
Qonto source pin. Company stores use hashed hosted paths. Self-serve provisioning
remains closed; template/provisiond still use the shared key. Sandbox final
acceptance and its operational floor remain open in the
[rollout plan](execution-plans/2026-09-29-toward-sandbox.md).
Mario Gmail has CTO-reported installed-app acceptance for mail, attachment
transfer and document lookup/read by basename. Its attachment source pin is
separate from the service checkout. R5 still requires representative scratch
lifecycle and consistent A/B isolation evidence, followed by final reviews.

Production uses GPT-Live for telephone service and the scoped company-knowledge
trial. Its pinned release reads revisioned `operator-instructions/phone.md`;
StarChat transcript upload is cancelled. Private call archives are accepted.
The source migration does not establish broader spoken-detail or latency
acceptance. Mario has no operator schedule; the 124 schedule reads his inbox,
and his project permissions deny instruction writes. Runtime/source identity
and prior acceptance belong to the
[source plan](execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md)
and [knowledge plan](execution-plans/2026-09-28-voice-company-knowledge.md).

Production K3 uses its personal OpenRouter key with USD20/day; the other three
Café124 profiles preserve prior billing choices and USD5/day. Their saved host
configuration enables automatic work and has preparation unpaused; no run is
active in the release preflight. Preserve actual controls during rollout. Personal-key synthetic K3 acceptance
passes; funded credit acceptance remains open. See
[K3 adoption](execution-plans/2026-09-16-k3-production.md).

Mnemonic M9 source is retained in nonproduction engines. The failed Haiku
corpus criterion is deferred to M10 on the resolver-selected model; sandbox
acceptance does not close mnemonic product/corpus gates. The
[engine snapshot](../engine/docs/active-context.md) owns the detailed state.

Settings separates provider/model selection, daily budgets and bounded
preparation. Setup verifies an engine and hands off a descriptor-based kernel
workspace. Engine and operator billing/pause controls are separate. Shared
written projects are revisioned company records. See
[operator setup](operator-setup.md#ai-execution-and-controls) and
[project memory](../engine/docs/features/project-memory.md).

Desktop `v0.1.55` carries the auth and billing-business fixes; its tag and
`v0.1.54` contain neither Qonto nor PEC Settings. Both are now combined in
the next-release source with those fixes. No installer or hosted rollout is
part of this [integration](execution-plans/2026-10-05-mailboxes-qonto-release-integration.md);
installed Qonto and live PEC acceptance remain open. Windows neonize imports and
loose-file loading remain unverified. Runtime contracts belong to
[IPC](ipc-contract.md), [host operations](remote-backend.md) and per-tree docs.
WhatsApp's protocol can become stale; the checkout has a refresh loop,
production voice retains a release without it, and `whatsapp.status` has no
external reader. The app Refresh action only lists threads.

## Unresolved

- Qonto installed/packaged Electron and provider-UI comparison remain unverified.
  Hosted authentication, banking, restart/reconnect and source-grounded assistant
  acceptance have passed; the corrected UTC timestamp matches its source.
- Remaining Café124 billing choices and funded K3 credits are open. The reviewed
  comparison's 60 cases/240 outputs do not establish production equivalence.
- Sandbox final review, shared-key provisioning and operational floor remain
  open. One handset's speech is not transcribed by the voice provider.
- Installed/fresh-account GUI acceptance is open. Windows remains opt-in and
  `continue-on-error`; Intel is outside the release matrix. Windows voice-note
  transcription is excluded.
- Remote provisioning needs UID/company membership. Settings catalog reload
  has a same-value gap; reopen after changes. Product chat, delegated sending,
  approval isolation, Calendar and broad security review retain their owners.
- Telephone knowledge needs spoken detail, repeated/adverse cases and measured
  latency; voice reserves remain provisional. Caller history requires a unique
  selected-contact match. Historical task/import paths need verification.

## Next

1. Verify the installed Qonto Desktop workflow and provider UI comparison when
   a signed-in GUI is available; preserve billing and pause controls.
2. Continue the knowledge plan's detail/repetition/latency gates without
   repeating completed archive acceptance.
3. Resolve remaining billing choices and preserve actual saved controls;
   release verification initiates no paid preparation run.
4. Exercise installed Mac/Windows GUI and add an external WhatsApp status reader.
5. Resume deferred work from its existing briefs when requested. Electron stays
   primary; the [thin-client brief](execution-plans/cross-machine-thin-clients.md)
   remains parked.
