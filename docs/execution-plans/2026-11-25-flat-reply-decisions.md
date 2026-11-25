---
status: completed
created: 2026-11-25
brief: ../briefs/2026-11-25-flat-reply-decisions.md
owners: [desktop-engine, release-operator, integration-lead]
---

# Flat reply decisions in the installed Desktop engine

The formatter is implemented, installed as dev16 on all seven hosted engines and
published in Desktop `v0.1.57`. The current verification boundary below records
the approved outcomes and their qualifications. Component source/build/switch,
qualified final review and public publication are complete. The primary mailbox
plan owns the remaining global final verdict. Retained milestone procedures
preserve their proposed ordering and requirements verbatim; their starting fleet
is historical.

This is a substantial change to paid generation on both the mailbox draft and direct-send paths. The [approved brief](../briefs/2026-11-25-flat-reply-decisions.md) has SHA-256 `b990e4930fb4ebb85585893fd96c3093d4b612306d1c5ef7686bf31f0596991c`. Its framing verdict and approved copy are in `/tmp/mrcall-ai-kit/flat-reply-candidate-brief-review-20261125/`. A fresh plan reviewer must approve the exact brief and plan before M1 starts. Each dependent milestone uses its predecessor's actual reviewed output. Retain approved copies, hashes, adverse results and any qualifications.

The [Desktop mailbox plan](2026-11-23-mailbox-drafts.md) and the HB November 23 delivery, November 24 IMAP amendment and November 25 [component release boundaries](/home/mal/hb/docs/execution-plans/2026-11-25-mailbox-component-release-boundaries.md) govern integrated acceptance. The recorded starting fleet is seven engines on dev15 at `96f02460bab9f0c9909ed663ae07cfa5c8a075dd`. The kernel has published `v0.76.1` at `6b5fa007c8c0fa98c0d5f5a05a76052eea3f3d0f`. Its two normal clones' public-origin adoption has a separate owner and can proceed alongside offline work. Before live tests, bind the actual installed origins, payloads and modes. Where public adoption has completed, use the new default verification receipts. Serialize every shared operational window with that owner.

Operational packet names below are relative to the private evidence root `~/.local/share/mrcall-operational-evidence/2026-11-24/`. Extend existing tools in new candidate-specific directories. Keep controlled body reading inside the authorized private verification path. Durable reports contain identifiers, counts, hashes and semantic judgments. Preserve grants, settings and credentials in place.

## M1. Change the shared formatter and prove its callers

**Owner:** Desktop engine. Start from `engine/zylch/services/operator_reply_generation.py`. Change its existing schema, decision instructions and decoder. Send a closed object requiring exactly `decision`, `body`, `reason` and `missing_facts`. Bind the two allowed decisions and all field types in the provider schema. Apply cross-field and UTF-8 constraints locally. Preserve the response envelope limit (70,000 bytes), completion/tool/refusal checks and duplicate-key rejection. Preserve the existing context, model, strict schema capability, provider restrictions, pricing, fallback setting, reservation site and token limits.

For a draft, accept only a nonblank plain-text body (up to 65,536 UTF-8 bytes), an empty facts array, and an empty or nonblank explanation of at most 4,096 UTF-8 bytes. Reject invalid Unicode, whitespace-only nonempty explanations and contradictory field values. Pass only the body to the existing plain-text writer. For review, require the literal empty body and use `ReviewRequired` in `operator_reply_operations.py` with its existing reason and facts validation (up to 20 genuine nonblank facts of at most 1,024 UTF-8 bytes each). A policy escalation can have zero facts. Keep the stored/public review shape and existing safe diagnostic taxonomy. Use the existing validation logic where possible. No prose matching or fixture-specific branch selects a decision.

**Source verification owned by the engine author:**

1. Extend `engine/tests/assignments/test_scheduled_reply_generation.py` through the real `drafts.compose_reply` RPC, guarded SDK, SQLite operations and synthetic mailbox. Exercise both scheduled modes and the authorized personal draft entry through the installed MCP service implementation in the caller journey harness. Its normal fixture replaces `generate`; restore the production generator and stub only external boundaries for the formatter cases. Keep personal direct send refused at admission. Inspect actual outbound SDK payloads on supported native, K3/OpenRouter and managed gateway routes using the existing LLM request-shape, K3 and gateway translator tests. Require the exact flat schema, no tools, fixed endpoint/price admission and strict structured output. Missing capability or unsupported route must fail closed.
2. For each affected mode cover a draft with empty explanation, a draft with distinctive private explanation, review with facts, and policy-only review. Read actual persisted MIME or transmitted MIME for the draft body and prove private explanation is absent from outgoing content, public results and persisted draft results. Assert one create and zero transmissions for a draft or one direct send and zero creates for send mode. Review stores only its existing private result and produces zero mailbox receipts or writes.
3. In both modes exercise missing/extra/duplicate fields, old nested shape, unknown decision, wrong types, nonempty review body (including whitespace), draft facts, blank/oversize/invalid UTF-8 text, inclusive limits and oversize arrays, malformed/partial JSON, incomplete/tool response and provider refusal. Assert zero SMTP, APPEND, edits or Trash and no mailbox write receipt. Check the original paid or refused attempt against its actual reservation/usage disposition. Reopen SQLite and repeat the key, including recover-only, verifying exact previous outcome and no generation or writer retry. Retain admission/authority, existing-draft, human-answer, instruction-change, alias and uncertain-send regression checks. Open pre-dev16 review, failure and uncertain records with the forward reader.
4. Run the affected caller suites and the existing offline mailbox, request-shape, routing and accounting aggregate. Capture exact arguments, versions, exits and exclusions. A fresh source reviewer must approve the exact changed product and test bytes, dev16 packaging version, source commit and compatibility evidence before build. Compare against dev15 at the transport, storage, public protocol, authority and charging boundaries. A passing parser-only unit test cannot establish a caller outcome.

## M2. Build and qualify one inactive dev16

**Owner:** Desktop release operator, after M1 approval. Extend `mailbox-candidate-build-dev15` to bind the M1 commit/report, archive that commit, build its wheel offline, and stage one immutable, service-readable dev16 release. Verify its entire source/wheel/installed product manifest, explicitly account for every difference from dev15, and verify the retained 109 dependency distributions, 11,740 vendor files and SDK 1.8.0. Run the isolated CLI, empty-profile daemon, imports under each of the seven actual service users and the candidate aggregate with the installed payload. Record before/after payload hashes, real exit codes, test-path provenance and any pre-existing exclusion. Verify the live fleet is still dev15. The milestone ends with an independently checked source-to-wheel-to-install receipt usable by M3.

## M3. Review and perform the release-only fleet switch

**Owner:** Release operator, with independent transaction review. Extend `mailbox-upgrade-dev15`. Its former byte-equality guard compares against the *nested* schema. Qualify the changed schema through the real installed serializer and existing deployed gateway translator, including strict schema wire, provider restriction, caps, fallback refusal and authenticated free capability/quote checks for both realms. Bind their provenance and the exact candidate schema. Test rejection of the old schema and of an altered candidate binding. A prior gateway receipt alone cannot qualify the new shape. This candidate changes no gateway deployment, model or budget.

Freeze the build receipt, transaction code, existing nine interpreter declarations, current seven unit/PID/birth/owner/argv/cwd/listener bindings, profile and parked-voice settings, package hashes, cron and both pause files with metadata. Bind read-only snapshots of canonical receipts, aliases, generation operations, reservations, usage and credit authorizations, including absences. Add all terminal Café decisions, the older uncertain and completed MrCall records and both diagnostic intents/accounting. Keep the existing pre-intent typed settled-background qualification on its named profiles and exact retention after first stop intent. Exercise drift, interruption, partial stop/start and restoration controls with the new candidate. Obtain fresh fleet readiness approval over these exact inputs and the released exclusive window before stopping real writers.

Execute the reviewed switch once. Record all seven actual process births, interpreter roots, users, arguments, listeners and product digests, preserved rows and zero migration or provider effects. Verify exact cron and both pauses, and release the window. A staged wheel, declaration or successful service restart alone cannot pass this check. On interruption reconcile the original journal and stopped-state baseline. Keep live data intact. Before rollback to dev15 prove that it recovers every persisted dev16 disposition with its original identities. Otherwise retain dev16 or use a reviewed forward-compatible reader. Dev14 cannot read existing policy-only reviews.

## Current fixture continuity and the new installed journey

A later independent read finds the earlier ordinary Café draft UID 2515 and its All Mail UID 4489 absent. Exact native UID fetches and Message-ID/source searches return no object in Drafts, All Mail or Trash. The cause and actor are unknown. The two ordinary examinations and earlier Desktop openings remain evidence only at their observed times and versions. Do not recreate, reattach or silently replace that historical object.

Before M4 or M6 uses a new baseline, separately review the exact absence witnesses and the unchanged original generation/receipt/accounting records. Bind their actual current state explicitly. A recorded absence is an observation, never proof of who removed the object or permission to retry the historical generation. Read-only recovery of the historical key must retain its original operation and disposition, without generation or mailbox effects. Any unexpected mutation of protected rows or the new M4 original still refuses. This adjustment changes only operational fixture continuity; M1 code and all product acceptance remain unchanged. M6 opens the new successful M4 draft instead of requiring an old user-editable draft to exist indefinitely.

## Current verification boundary

The governing HB November 25 takeover plan and approved fixture amendment bind
the actual outcomes: positive model preparation, later old-handle absence and
same-operation read-only recovery, distinct free RPC fixture, current packaged
Desktop opening and ordinary dev16 formatter proof. The ordinary dev16 recipient
remains unobserved; the original controlled dev14 transport/recipient result
retains its version scope. The extra controlled dev16 518 case stays unsuccessful.

Gmail A has one actual MCP send and original-key replay, one Sent, one received
and zero drafts with all 223 saved body bytes preserved. Independent review
approves composed verification: Gmail recipient/body ingestion precedes an
explicit engine correction of the sole controlled recipient; current native MIME
then supplies MCP send without a client-origin branch. Literal uninterrupted
Gmail-recipient-edit-to-SMTP remains unestablished, and browser actions remain
operator-reported. The approved framing report is
`/tmp/mrcall-ai-kit/composed-recipient-framing-review-20261125/report.md`, SHA-256
`b2d3f61b15139717adada933a14410a930f843ea09923f67eeb1c220c3d01daf`.
B has one exact unflagged draft in recoverable Trash with zero outgoing mail.
C has one external Sent/received message, zero drafts and typed old-handle refusal
with no new rows or recreation. Older operations and accounting remain preserved.

Both normal clones use actual public kernel `v0.76.1`. All seven engines retain
immutable dev16 product source `626d303d`. Published immutable Desktop `v0.1.57`
binds release source `50ee8316`; its publication service pull verifies that head
with all seven process identities unchanged. Later documentation-only main
descendants are tracked by actual pull receipts. Public tag workflow `45617312164`, attempt 1,
succeeds in all four jobs. Exact consumed sidecar, complete ZIP digest/CRC and
anonymous 249,599,199-byte public ARM64 DMG size/hash pass. Runner signing passes;
Apple agreement HTTP 403 leaves the package unnotarized. Native Mac execution
and independent Mac signature validation remain unverified. The terminal public
receipt is `desktop-publication-dev16-r4-final-20261125/public-verification.json`
under the November 24 private evidence root, SHA-256
`841aa0c7349a98dff5542f854c09434ed268f0cdbed7fae9546fc089d8558061`.
The qualified component final review is APPROVED in
`/tmp/mrcall-ai-kit/mailbox-component-takeover-20261125/component-final-release/report.md`.
Its immutable retained copy is
`desktop-publication-dev16-r4-final-20261125/component-final-review.md` under the
same evidence root, SHA-256
`31284212c033fd44094473e88a87a04840e07be12b21aa1d3de78d3035034ce3`.
The exact clean-commit publication approval is
`desktop-publication-dev16-r4-final-20261125/publication-approval-50ee8316.json`,
SHA-256 `64b04f6cc2ca34e0de61acbf1b0bca501b52006233c023191a31d009a072a1e7`.
That frozen component review excludes later Gmail A/B; their separate approved
composed-verification framing and actual terminal results remain bound above.

The [parent mailbox plan](2026-11-23-mailbox-drafts.md) binds the exact A/B/C and
public artifact hashes. Its original-17 result remains zero moves, fourteen in
recoverable Trash and three unlocated with unknown cause. Cron, pauses, budgets
and old send fences remain preserved. The retained procedures do not authorize
recreating absent originals or claiming positive present-draft replay. This plan
is complete within its reviewed component boundary. The primary November 23
mailbox plan retains global documentation closure and final-review state.

## M4. Renew the exact Café original and prove public preparation

**Owner:** Integration lead with the Café operator. After M3, obtain **separate readiness approval for fixture renewal**. Bind the canonical archive source `6ad2a64b-05b6-4f06-89da-7b93bd91bdf9`, exact Message-ID and controlled parties, All Mail UID 4496/UIDVALIDITY 12, original full MIME/body digests and existing draft-mode registry entry to read-only provider evidence. This is the protected personal preparation case, distinct from the earlier ordinary Café draft UID 2515. Under the existing locks, journal the actual registry preimage and proposed postimage. Renew only the exact entry's timestamps using the original 5,400-second lifetime. Preserve all other rows, metadata and prior SMTP intent. Verify the protected postimage and fresh installed normal admission. The renewal has zero source SMTP, mailbox write or inference. An ambiguous renewal is reconciled against the journal before proceeding.

Extend `cafe-dev15-admitted-proof-20261125` for the actual seven-process dev16 binding and **one new explicit key** on the same original. Freshly review the actual renewal and current installed admission, authenticated `draft.prepare` grant, exact source/correspondence, published instruction versions, runtime, headroom and frozen public request. Check expiry again after session setup immediately before dispatch. Use the normal installed public `prepare_reply`, saved personal K3 route and budget. Journal first intent before dispatch. No new original, alternate model, raised cap or additional paid attempt belongs to this transaction.

Read the actual draft from the named mailbox by exact thread, Message-ID, folder UIDVALIDITY/UID and independent raw/body digest. Require exactly one new create receipt, one draft, zero outgoing, and one settled generation/reservation/usage. The lead reads the actual body and binds approval to its digest only if it briefly acknowledges the controlled original in Italian, has its exact reference and total 254, follows the published signature and contains no internal explanation or unrelated material. Repeat the *identical* public prepare payload/key and independently recount. The operation, request, mailbox handle and bytes, linked reservation/usage IDs, tokens and costs must agree; no second generation, create or send may occur. Previous operations, diagnostic holds/settlement, canonical receipts, accepted aliases, early Café operation/accounting records and completed MrCall send remain intact. The separately reviewed current-state witness for the historical removed draft is preserved. Keep the new draft available for the Gmail journey. Legitimate review, bad content, ambiguity or missing replay response leaves positive acceptance open. Inspect only the already proven operation on uncertainty. Release the window with its actual outcome.

## M5. Confirm installed direct send through the ordinary MrCall launcher

**Owner:** Integration lead with the MrCall operator. After M3, serialize this window with M4 and clone adoption. Reuse the controller, native discovery/phase joins and independent observers in `mrcall-ordinary-dev14-20261125`. The completed dev14 source must remain answered. Use a **different eligible controlled original**, independently verified and registered for its intended mailbox/mode. If it must be created, freeze the exact new synthetic original and its one journaled controlled SMTP submission, isolated from Café renewal. Verify current source identity, authorization, expiry and absence of a prior answer/draft. Record the expected acknowledgment, reference and calculated total before launch.

Before any new original SMTP, obtain separate readiness approval of its exact synthetic MIME, one-submission intent and the registry append transaction. Freeze the complete existing MrCall registry bytes and metadata, including the old `9790` enrollment. On uncertain SMTP acknowledgment perform read-only reconciliation against the original Message-ID and intent; never resubmit. Under the existing acceptance and both operator locks, compare the registry with that approved preimage immediately before installation. Append only the newly provider-verified send-mode entry and atomically install the approved postimage. Read back the entire registry and prove every prior entry, including `9790`, remains byte-equivalent and in its original order, with no other field or metadata change. Keep the Café registry unchanged. Preserve both registry preimage and postimage evidence; reconcile an interrupted replacement before proceeding. Review the subsequent ordinary-launcher packet only after the new source admission and archive identity are actually established. Freshly review this exact launch transaction and all its preservation assertions.

Run the unchanged normal `mrcall-cs/ext/cs_operator_send_cron.sh` once. Use its ordinary USD 8 headless cap, 10,800-second timeout, existing allowance, permissions, model and per-profile budgets. Keep Café paused and preserve the original cron and both pause files. Do not overlap activation, a second launcher or release promotion. Require actual successful wrapper/native completion, complete discovery and provider proof for the exact source, native health-nonce-derived key, one settled generation and one completed direct send receipt. Independent controlled Sent and recipient reads must find exactly one matching message with the same Message-ID and body hash. Require zero source draft/create/update receipts and no mailbox draft. Read the received body for the predeclared semantics; bind the verdict to the readback hash. Recover the confirmed key and recount identical source-specific operations, tokens/costs, provider identities and effects. Report launcher spend separately. Verify all owned processes terminated, exact cron and both pause bytes/mode/ownership restored, seven process bindings preserved and the old answered source untouched. On uncertainty preserve the original identities and reconcile Sent without retransmission.

## M6. Recover through installed clients and complete release

**Owners:** Desktop release operator and integration lead. After M3, run the existing `post-dev15-mcp-desktop-verification-20261125` checks rebound to the actual dev16 switch, restoration, package and process births during their own exclusive window. Replay the original sent key and accepted alias through installed public MCP. Check the same canonical operation and Message-ID with one Sent, one received and no recreated draft. Verify authenticated RPC recovery and the prior delayed-Sent/restart evidence. Use installed Linux Desktop's normal authenticated path to open the new successful M4 native Café draft and verify its actual bytes after restart and the closed-home ID-token scan. Preserve the earlier draft's actual absence and original operation without recreating it. Preserve the two original Café ticks and the separate edited-draft/human-answer hold proofs with their actual versions and qualifications.

Bind M4, M5 and current client receipts to the [parent mailbox plan](2026-11-23-mailbox-drafts.md). Literal Gmail client actions require their own authenticated evidence of the controlled open/edit/save, latest named draft fetch and one exact send/recovery with independent recipient/Sent checks. Use the parent journey's controlled object and key binding for each effect. If authenticated Gmail access is missing, report the exact unmet parent gate and finish independent Desktop checks. An IMAP observation or Linux Desktop screenshot cannot certify Gmail interaction.

Reconcile the Desktop mailbox contract, applicable engine/RPC and operator documentation, living contexts/archives, this plan and the HB parent record. Preserve the older approved briefs, plans and evidence. Run explicit documentation criticism, the current focused and mechanical completion checks on the existing task, and a **separate final review** through the real installed paths against the exact source, current installer CI and closed windows. Resolve material plan drift or missing evidence before promotion. Keep open any parent obligation lacking its own evidence.

Rebind the existing Desktop release transaction to dev16, the exact reviewed feature commit and a source-matching ordinary ARM64 installer build. Review release readiness from actual receipts. Use the governed fast-forward main push followed immediately by the service checkout's actual fast-forward-only pull under its existing locks. Verify its preserved local changes and all seven runtime bindings. Publish the ordinary immutable release tag, follow its own workflow to terminal status, and verify the exact sidecar consumed, complete installer archive digest/CRC, distribution-signing evidence and anonymous full public DMG size/SHA-256 against the released member. Record actual notarization outcome and platform execution coverage. A prior dev15 dispatch does not establish dev16 publication. On interrupted promotion inspect both refs, service state, process identities and the original journal before forward reconciliation. Never move a published tag. Record public checks, finalize only the applicable reviewed completion baseline, and report the separate parent disposition.

## What this plan establishes

The reviewed source and installed checks establish the flat formatter on both
caller paths, seven immutable dev16 installations, preserved recovery/accounting
and the verified public Desktop `v0.1.57` artifact. Actual model preparation,
ordinary direct-send formatter evidence, packaged Linux opening and Gmail A/B/C
retain the distinct source, fixture, recipient and composed-verification limits
recorded above. The qualified component final review and subsequent exact publication proof
complete this component; the primary mailbox plan owns the global final verdict.

## What remains unestablished

The original flat diagnostic remains terminal `invalid` / `unusable_output` because its decoder required an empty draft reason. Its settled flat call and the incomplete nested attempt retain their original financial identities. No nested provider outcome establishes causality or superiority. Current installed,
provider, publication and Gmail results are established only within the qualified
boundaries above. Literal uninterrupted Gmail-recipient-edit-to-SMTP, controlled
ordinary dev16 recipient readback, native Mac execution and independent Mac
signature validation remain unestablished. The primary mailbox plan owns the separate global final verdict and applicable
documentation closure; component completion does not broaden those claims.
