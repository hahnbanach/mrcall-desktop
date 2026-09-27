---
status: superseded
date: 2026-09-25
---

# Desktop voice alpha: manual Café 124 number pilot

This original pilot procedure targeted `+390289047081` and creation of a
`desktop` business. It is superseded by the operator's 2026-09-27 test input:
`+390250552776` and an existing business whose template remains `starter`.
The operator guarantees that number/business assignment. Do not execute the
old provisioning steps below for the current test; the production-account
runtime and carrier cutover still need a current plan.

<!-- doc-scope:start -->
Scope: historical implementation plan and operator procedure for the original
GPT-Live pilot proposed for production@cafe124.it on +390289047081. Its number
and business-creation steps are superseded; the paired UX brief remains the
product intent.
<!-- doc-scope:end -->

Product intent: [Desktop voice alpha UX](../briefs/2026-09-25-desktop-voice-assistant-alpha-ux.md).
Telephone behavior: [GPT-Live M4](2026-09-23-gpt-live-engine-integration.md).

## Current starting point

The M4 telephone service runs from an explicit isolated profile, with a
synthetic company-memory fixture and `VOICE_SMOKE_TEST_NUMBER`; its runtime
looks up the fixture for that configured number. The number +390289047081 is
linked to the dedicated Vonage GPT-Live test application. The provisioning
record found the StarChat **test** service-number row unassigned and no
matching production row on 2026-09-23. These are historical checks; repeat
read-only inventory and carrier checks immediately before any assignment.

StarChat's Firebase business API supports creation and updates with owner
scope. Its Firebase service-number POST endpoint at
`/mrcall/v1/<realm>/crm/servicenumber/<businessId>` calls `autoAssign`: it
chooses an available number by country, checks the subscription, and does
not accept an exact number. The admin service-number POST also calls
`autoAssign`. **Neither route proves that it will pick +390289047081.** A
specific-number path through StarChat must be established before changing
the number inventory. Merely setting `business.service_number` would leave
the service-number inventory inconsistent.

## Implementation scope

The target is the existing `production@cafe124.it` account, not a rollout to
all hosted engines. Start with one explicitly bound business, number and
UID-keyed profile in a dedicated voice process. Do not switch process-global
profile settings between customers. Desktop checkout, Electron preview and
the new configuration skill are subsequent deliveries; this pilot uses the
same StarChat API contracts those clients will use.

Source inspection identifies three implementation gaps: the launcher
`engine/scripts/voice_engine_isolated.py` refuses populated profiles; telephone
admission uses the configured test number in `engine_runtime.py`; and
`agent_config.py` stores local `VoiceAgentConfig` snapshots with explicitly
selected memory sentences. None of these currently makes StarChat variables
the source of truth for a customer's telephone configuration. The isolated
unlimited override also cannot simply be copied to a populated profile.

## Delivery milestones

Each milestone produces evidence before its checkbox is completed. The
procedure below supplies the operational details for the activation stages.

### P1 — Establish the actual account and routing contract

- [ ] Read the live UID, engine endpoint/profile identity, memory membership,
  existing businesses, template schema and both number inventories. Record
  non-secret identifiers and deployment versions in a private pilot manifest.
- [ ] Read the Vonage application/number association and current OpenAI incoming
  call webhook configuration. Identify the host, public HTTPS endpoint and
  credential references for the new listener; save the current routing.
- [ ] Resolve assignment of this specific number through StarChat APIs. A read
  showing it first in the free pool is insufficient under concurrent allocation.
  If available APIs cannot guarantee the selected number and consistent records,
  record the precise missing capability before choosing a narrow server change.
- [ ] Specify actual charging for the pilot: model/carrier payer, durable holds,
  usage settlement and whether any MrCall credit debit is implemented. The M4
  direct-provider path does not establish CALLCREDIT billing. Preserve existing
  account billing choices and historical reserves; do not add local test caps
  or fabricate a payment, credit grant or debit.

Exit: one explicit account/business/number/host contract, a verified assignment
path, and a documented billing path. No carrier cutover occurs at this stage.

### P2 — Implement StarChat configuration and the profile binding

- [ ] Define the minimal `desktop` variable schema through supported template
  administration. Map greeting, instructions, hours/timezone and enabled tools
  to a validated engine configuration. Define customer-editable fields and
  preserve StarChat owner/admin enforcement.
- [ ] Create or reuse one manual-trial `desktop` business through StarChat
  APIs; read back ownership and initial variables. Reconcile an uncertain
  create before retrying to avoid duplicate businesses.
- [ ] Add the engine adapter that reads the explicitly selected business via
  StarChat, checks owner/template, and builds an immutable per-call
  configuration snapshot. StarChat owns business variables; engine storage
  owns compiled snapshots and permitted memory selections. Define refresh and
  failure behavior so a failed read never silently activates another business.
  Before assignment, validate the expected number only in an explicit inactive
  preparation mode. Paid admission remains disabled until the authoritative
  StarChat number binding is checked after P4 assignment.
- [ ] Wire owner-scoped headless StarChat authentication into voice startup and
  configuration refresh. Reuse supported encrypted refresh-token storage and
  refresh logic; keep Firebase ID tokens in memory. Refresh must work with
  Desktop closed and automatic mailbox processing disabled. Refuse admission
  on failed refresh or identity mismatch; test token expiry and cold restart.
- [ ] Build permitted fact selection against the existing company store without
  copying it into the synthetic fixture. Revalidate selected sentences and
  membership when admitting a call; caller-number matching is not identity proof.
- [ ] Test wrong owner/number, stale or malformed configuration, changed memory
  membership, excluded facts, and a saved edit taking effect on the next call.

Exit: an authenticated configuration read and a local conversation preparation
resolve only the intended business and permitted facts, without a carrier call.

### P3 — Run the voice service against a real profile

- [ ] Add a supported explicit-profile startup path alongside the isolated
  launcher. Reuse the existing conversation and carrier validation code; support
  the real profile schema and company store without replacing data or sharing
  the isolated process lock. Determine how it coexists with the existing daemon.
- [ ] Remove fixture-only admission and test-limit dependencies from this path.
  Keep one GPT-Live conversational model, immediate greeting, quiet initial
  facts, specific tool delegation, cancellation and closure accounting.
- [ ] Provide independent durable voice accounting and private diagnostic
  transcripts, correlated with business/configuration revision and carrier call.
  Keep the existing M4 ledger intact. Reject concurrent admissions consistently
  with actual listener capacity; do not claim multi-call support without testing.
- [ ] Verify cold start, authenticated webhook rejection, duplicate delivery,
  closure with a pending lookup, retained uncertain holds and restart recovery.
  Run the focused voice suite and independently review the runtime changes.

Exit: the target service is healthy on its intended host with no Desktop or
operator workspace running; routing still points to the previous service and
the unassigned target refuses live call admission.

### P4 — Provision and switch the pilot

- [ ] Read back the prepared manual-trial business, owner and saved variables
  immediately before activation; verify they still match the tested snapshot.
- [ ] Assign +390289047081 through the verified StarChat path and read back both
  inventory and business records. Validate the authoritative number binding
  in the target runtime before enabling admission. Preserve the prior state
  for recovery.
- [ ] Apply the Vonage application update and verify its number association,
  signed callbacks and public answer/event URLs. Also update or explicitly
  verify the OpenAI incoming-call webhook reaches this same listener at
  `/openai/live`, with its corresponding verification secret. Updating Vonage
  alone does not move the OpenAI sideband path. Recheck that no call is active
  immediately before cutover; preserve tunnel continuity.

Exit: provider routing, engine binding and StarChat records agree. Save the
actual read-back results privately; API acknowledgements alone do not accept
telephone behavior.

### P5 — Accept the real customer call and hand over

- [ ] Exercise a real incoming call with correct company facts, a follow-up,
  interruption and missing data. Obtain human listening feedback and correlate
  it with the diagnostic trace; use deterministic tests for failure boundaries.
- [ ] Verify closure and provider usage/accounting, continued availability with
  Electron closed, and configuration refresh on a subsequent call.
- [ ] Obtain an independent end-to-end review of deployed identity, routing,
  fact selection, runtime tests, real call and listening evidence. Restore the
  previous provider routes on failure without discarding any accounting history.
- [ ] Record the deployment version, private manifest/evidence locations,
  operational recovery commands and any remaining limitations. Mark this plan
  completed only after the manual pilot passes; retain separate UX acceptance
  for checkout, credit fulfillment and Electron preview.

## Procedure and stop conditions

1. **Read-only identity and inventory.** Resolve `production@cafe124.it` to
   its immutable Firebase UID. Read its existing StarChat businesses,
   subscription and credit state, and the number's test and production
   service-number rows. Confirm that no business owns the number. Record the
   business and owner IDs privately; neither a mailbox address nor a phone
   number is a substitute for the UID. Stop on any owner or inventory mismatch.
2. **Inspect the Vonage application.** Confirm that +390289047081 is linked
   to the dedicated GPT-Live application and that there are no active calls.
   Read the application's Voice region, signed-callback setting and
   answer/event webhook URLs. Confirm the account API key/secret references
   used to manage the application and number, the separate callback signature
   secret, and the application private-key reference if JWT-authenticated
   Voice operations are needed. Do not print any secret. Record its ID,
   number association and current configuration privately for rollback. Stop
   on any unexpected application, number link or route.
3. **Prepare the `desktop` template.** Read the actual StarChat template and
   variable schema. If absent, define the template and customer-editable
   variables through the supported StarChat administration path before
   creating the business. Record which fields are required. Do not copy the
   older assistant's variables blindly.
4. **Create one manual trial business.** Use an authenticated StarChat
   business API request with `template=desktop` and the verified owner UID.
   Read it back through the customer's identity to verify ownership and
   edit permissions. Mark it as a manual alpha trial. Do not represent this
   step as a paid checkout and do not grant 1000 credits without the intended
   payment or an explicitly recorded trial-credit operation.
5. **Prepare permitted context.** Use the verified `production@` engine
   profile and company-memory membership, preserving its existing memory
   capability and account isolation. Select business facts that callers may
   hear; verify their provenance and distinguish customer-specific facts
   from company facts. Do not copy its mailbox, database, credentials or
   memory key into the M4 synthetic test profile. A small bounded mail import
   may be used only after the mailbox and resulting fact selection are
   inspected. Stop if the selected context is ambiguous or unapproved.
6. **Make the telephone runtime business-aware.** Replace the current
   single-profile fixture binding with a mapping from the called service
   number to the StarChat business and the correct UID-keyed engine profile.
   Preserve GPT-Live as the only telephone conversational model and retain
   the engine's fact selection, tool permission checks, ledger reservations,
   closure accounting and indefinite service/tunnel lifetime. Prove that an
   unknown number or mismatched owner fails closed. Test the mapping and
   customer fact isolation before a carrier route is changed.
7. **Resolve exact-number assignment.** Establish and verify a StarChat API
   operation that can assign the selected free test number to the trial
   business while updating both `service_number.businessId` and
   `business.service_number`. The existing `autoAssign` route must not be used unless
   its assignment guarantees this number even under concurrent allocation;
   otherwise a specific-number API capability remains a blocker. Read back both records and stop on partial assignment. Do
   not mutate either table directly or silently move a production number.
8. **Update the Vonage application and route.** With the business-aware
   listener healthy, update the dedicated Vonage Voice application's answer
   and event webhook URLs to the new listener's `/vonage/answer` and
   `/vonage/event` endpoints, and verify its configured Voice region,
   signed callbacks, application public key and server-side credential
   references. Confirm that +390289047081 remains linked to that
   application; if its association must change, update and
   read back the number-to-application link as a separate carrier operation.
   Keep the previous application configuration and association for rollback.
   Change the tunnel URL if required; do not restart the tunnel merely to
   change its URL. Also update or verify the OpenAI incoming-call webhook
   at `/openai/live` and its verification secret for the same listener.
   Verify a signed callback reaches the intended business
   before inviting callers.
9. **Call and verify.** Make a real incoming call and listen for immediate
   greeting, correct Café 124 facts, a follow-up, an interruption and a
   missing-data answer. Correlate the heard words with private diagnostic
   transcription, selected facts, tool results, carrier closure and cost
   ledger. An ACK or transcript alone is not proof of audible delivery.
   Verify the assistant remains reachable with Electron closed.
10. **Finish or restore.** If any gate fails, restore the previous Vonage
   application configuration and number association, and the prior OpenAI
   incoming-call webhook with its matching verification-secret reference.
   Read back both provider routes and verify the previous listener, then keep the pilot
   inactive; retain the business and accounting evidence for diagnosis. Do
   not reset holds, reservations or call history.
   Mark the number active for the customer only after the real-call checks
   pass. Record the actual account, business ID, route and verification
   outcome in private operational notes, not in this repository.

## Completion evidence

- StarChat reads show the intended UID owns one `desktop` trial business and
  both number records agree on +390289047081.
- Vonage reads show the number attached to the intended application, with
  the intended Voice region, signed callbacks and live answer/event URLs.
- The listener resolves that business and its allowed context; an unrelated
  business and an unknown caller cannot see its private facts.
- A human-heard call demonstrates greeting, grounded answers, follow-up and
  interruption; correlated carrier and model ledgers close without lost holds.
- Checkout, automatic 1000-credit fulfillment and Electron preview remain
  separate UX acceptance items until they are implemented and exercised.
