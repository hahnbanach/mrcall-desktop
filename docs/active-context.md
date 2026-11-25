---
doc_baseline_commit: f937091a1ab3834f17e60479d567e68b3b0ca49e
doc_baseline_date: 2026-11-22
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

All seven hosted engines run the immutable dev15 release from source
`96f02460`. Actual process identities, arguments, listeners and all 492
package files match. Both normal operator clones use the exact local
`v0.76.1` artifact. Café Production is the routed operator MCP profile.

The [mailbox implementation](mailbox-drafts.md) uses existing primary IMAP/SMTP
app passwords. The engine owns the current mailbox draft, SMTP transmission and
exact Sent confirmation. Accepted secondary keys resolve the durable canonical
operation and Message-ID across process restarts. Strict singleton full-MIME
source headers are normalized; ambiguous sources remain held. The
[migration contract](mailbox-draft-migration.md) retains original send fences and
compatible recovery without restoring discarded internal text. All seven actual
databases have completed internal draft retirement with zero provider mutations.

Packaged Linux Desktop 0.1.57 restores hosted identity with refresh-only
Firebase persistence and opens the exact first Café tick's native draft
(UID 2515) on dev15. The first ordinary tick passes on dev12 and kernel
`v0.76.1` with one exact selection, one draft and zero replies. Closed-home
scans find no persisted ID token. Independent
Gmail IMAP edits and MCP sending have one matching Sent and received message.
The original key and an accepted RPC alias recover that delivery after real
restart, with zero remaining drafts. The signed Apple Silicon 0.1.57 candidate
is unnotarized after Apple's agreement-related refusal. The
[delivery plan](execution-plans/2026-11-23-mailbox-drafts.md) records the evidence.

The original 17-target order has zero remaining targets in Drafts at its first
new-route execution; the unrelated later draft is preserved. Exact read-only
reconciliation locates 14 originals in recoverable Trash and leaves three
unlocated. The command moves zero messages and does not establish the cause of
their earlier disappearance. The HB November 23 plan and November 24 IMAP/auth
amendments own installed acceptance and release. No Gmail OAuth grant is required.

Desktop configures accounts, services and client access. Daily operator work
uses the remote MCP. Ordinary opted-in rule changes are direct revisioned chat
writes; privileged legacy management retains verified-owner admission. Source
checks do not establish a new installed configurator or provider acceptance.
The [data flow](operator-data-flows.md) owns these boundaries.

Hosted profiles retain separate private stores and company-memory capabilities
under the [runtime contract](cross-cutting-contracts.md). The completed sandbox
work does not enable self-serve provisioning. Current task-assignment and company
sharing evidence retain their [assignment](execution-plans/2026-10-08-explicit-task-assignment.md)
and [fenced-join](execution-plans/2026-10-08-mrcall-company-memory-sharing.md) owners.
The separate contextual-email enrollment candidate remains unreleased.

The Stripe prerelease and hosted verification remain with the
[installer](execution-plans/2026-10-16-stripe-test-installer.md) and
[startup](execution-plans/2026-10-16-stripe-startup-recovery.md) plans. Qonto typed
credentials, packaged GUI and provider comparison remain with the
[banking plan](execution-plans/2026-10-04-qonto-connection.md). No new banking or
payment effect follows from the mailbox candidate.

Production voice and revisioned company instructions retain their
[source](execution-plans/2026-10-01-telephone-notes-source-is-phone-md.md) and
[knowledge](execution-plans/2026-09-28-voice-company-knowledge.md) owners. Settings
keeps engine provider, model, budget and preparation controls separate from
headless operator and direct kernel classifier controls; see
[setup](operator-setup.md#ai-execution-and-controls).

The two ordinary Café examinations retain one exact draft and zero sends.
MrCall's ordinary send has one verified received/Sent reply, zero drafts and
stable same-key recovery. Separate installed controls retain a human-edited draft
and hold a human-answered source before generation. Both gateway realms run
`2bf3a56b` with the exact published endpoint snapshot; free quote checks have
zero inference. Their evidence and recorded versions remain in the delivery plan.
The old failed support generation stays fenced.

## Unresolved

- Both-clone FULL awaits the canonical Café personal-K3 preparation and final
  independent judgment. Cumulative live-read,
  independent provider oracle, fixed-template safety and paused-launcher checks
  have qualified evidence. Gmail web, public installer/kernel provenance and
  separate final review remain open.
- Native automatic bootstrap, broad RPC parity, customer reply quality and full
  Desktop packaging retain the parent operator obligations. Historical MCP helper
  pairing does not establish wider kernel CLI or installed FULL acceptance.
- Qonto packaged/provider comparison, Stripe GUI acceptance, live PEC, Windows
  imports and Intel installer acceptance retain their existing owners.
- Provisioning/membership, same-value Settings catalog reload, product chat,
  approval isolation, Calendar and broader security verification remain open with
  their existing owners. Source checks make no paid preparation call.
- Broader spoken voice detail, repetition and latency, K3 funded-credit behavior
  and mnemonic corpus/model acceptance remain separate verification boundaries.

## Next

1. Complete the canonical Café personal-K3 preparation and replay on dev15.
   Ordinary support delivery and post-upgrade MCP original/alias recovery and
   packaged Linux draft opening pass. Preserve both Café examinations and
   exact restored scheduling state.
2. Complete both-clone FULL and Gmail web acceptance. Preserve the completed
   original-17 conditional result with its three unlocated identities.
3. Complete documentation review, separate final installed review and public
   provenance under the governing HB plan. Verify the seven engines after
   the actual service checkout follows Desktop main.
