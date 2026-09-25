---
status: planned
date: 2026-09-25
---

# Desktop voice alpha: manual Café 124 number pilot

<!-- doc-scope:start -->
Scope: operator procedure and stop conditions for a manual alpha pilot that
connects +390289047081 to production@cafe124.it. Tracks the first instance of
the customer journey in the paired UX brief; no steps here claim activation.
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
   `business.service_number`. The existing `autoAssign` route is usable only
   if its selection is demonstrably deterministic for this number at the
   time of the request; otherwise this is a blocker requiring a narrow API
   capability. Read back both records and stop on partial assignment. Do
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
   change its URL. Verify a signed callback reaches the intended business
   before inviting callers.
9. **Call and verify.** Make a real incoming call and listen for immediate
   greeting, correct Café 124 facts, a follow-up, an interruption and a
   missing-data answer. Correlate the heard words with private diagnostic
   transcription, selected facts, tool results, carrier closure and cost
   ledger. An ACK or transcript alone is not proof of audible delivery.
   Verify the assistant remains reachable with Electron closed.
10. **Finish or restore.** If any gate fails, restore the previous Vonage
   application configuration and number association, then keep the pilot
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
