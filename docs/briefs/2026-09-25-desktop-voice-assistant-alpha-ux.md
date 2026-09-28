# Desktop voice assistant: alpha UX

<!-- doc-scope:start -->
Scope: proposed customer journey for creating, configuring, trying and activating
a GPT-Live telephone assistant from MrCall Desktop. This is a product brief, not
an implementation plan or a claim that the journey already works.
<!-- doc-scope:end -->

## Goal

A signed-in customer can pay for Desktop, obtain a business with the `desktop`
template and €10 (1000) of MrCall credits, configure the assistant without
spending credits on each edit, hear a realistic preview in Electron, and put the
assistant on a service number. The first alpha may use an operator-assisted
step to assign or activate that number, provided Desktop shows the real state
and the customer can reach a working telephone assistant quickly.

The product uses StarChat APIs for business, template variables, identity,
permissions and credits. Desktop presents and edits the same business record
that the telephone service uses. It must not keep a second, divergent copy of
the assistant configuration. This brief assumes the existing StarChat business
APIs can serve the configuration journey; payment, credit grant and number
activation need verification before that assumption is extended to them.

## Customer journey

1. **Sign in and understand the offer.** Desktop shows the price before payment,
   what the purchase includes, and that the included €10 is a usage balance.
   It distinguishes the Desktop purchase from credits consumed by live calls,
   voice previews and any paid preparation. The current balance and a route to
   add credits remain visible after purchase.
2. **Pay and create the assistant.** A successful paid purchase creates its
   `desktop` business and grants 1000 credits exactly once. Returning from checkout
   or retrying after an interruption resumes the same business; it does not
   create duplicates or award credits twice. Desktop shows creation, pending and
   failure states separately. If the alpha requires a manual fulfillment step,
   it says what is pending and who will complete it.
3. **Set up the company.** A short guided form asks for the business identity,
   greeting, hours, services, tone and other variables defined for the `desktop`
   template. It explains each field in customer language, previews the value
   that will be saved, and allows later edits. Saving variables is free. A
   blank or incomplete field is visible as such; Desktop does not imply the
   assistant knows facts it has never received.
4. **Connect useful context.** Desktop offers mailbox connection and a bounded
   initial import, with the latest 10 messages as the proposed alpha
   default. It shows which mailbox and period are being read, the number of
   messages accepted, and whether the resulting facts are ready for the voice
   assistant. The customer can retry or skip this step and still configure the
   basic assistant. Any paid analysis is disclosed before it runs; merely
   changing a setting does not trigger paid preparation.
5. **Try the assistant.** A "Try voice" action starts a real GPT-Live session
   inside Electron against the saved configuration and selected company facts.
   The customer can speak, interrupt, correct and ask a follow-up. The preview
   makes it clear when a fact is unavailable and when it is checking fresh data.
   It shows that the session uses credits, including when it cannot start for
   insufficient balance. A text transcript may help inspection, but the
   acceptance signal is audible speech, not an event acknowledgement.
6. **Activate the phone number.** Desktop shows the assigned service number and
   a clear status: not assigned, awaiting activation, active or needs attention.
   It provides a test-call instruction once active. A customer can edit the
   assistant after activation without repeating checkout. The phone assistant
   continues running when Electron is closed.

The setup screen should always give the customer one next action. A failed step
keeps earlier paid and saved work intact and offers a retry from that step.

## Configuration through the operator workspace

The cs-kernel-based workspace gets a separate skill for the new Desktop voice
assistant. `/mrcall-assistant` continues to configure the older assistant; the
new skill targets only businesses with template `desktop` and uses StarChat APIs
to read the template schema, inspect a business, show proposed changes, and
save confirmed variables. The skill and Desktop UI edit the same StarChat
record, so a change in either place appears in the other after refresh.

The signed-in customer's Firebase identity determines access. An admin can
manage any authorized Desktop business; an ordinary customer can manage only
their own. StarChat enforces that boundary. The skill must not rely on its
prompt or on a support account's shared credentials as the access control.

## Production carrier credentials

Telephone activation requires a configured Vonage Voice application, its
assigned number and reachable answer/event webhooks. The application has a
public/private key pair for JWT-authenticated Voice API requests. Its **private
key stays in protected server-side storage**; Vonage generates it for download
or accepts the corresponding public key when the pair is supplied by the
operator. The private key is not pasted into the application or exposed in
Desktop. Managing the Vonage application and its number uses the account API
key and API secret. Signed incoming webhooks use a separate Vonage signature
secret, which the engine verifies before accepting a call. Provisioning must
verify the required credential paths and never put any of these secrets in a
business variable, customer profile export, transcript or Git. The existing
isolated test key is not evidence that production credentials are provisioned.

Vonage references: [application authentication](https://developer.vonage.com/en/dashboard/build/applications)
and [signed Voice webhooks](https://developer.vonage.com/en/voice/voice-api/webhook-reference),
plus the [Application](https://developer.vonage.com/en/api/application.v2) and
[Numbers](https://developer.vonage.com/en/api/numbers) management APIs.

## Alpha boundaries and acceptance

The first alpha favors a short path to a real call over full self-service.
Operator-assisted number assignment or activation is acceptable if its status
is accurate and the customer knows when to call. A manually created `desktop`
business can validate the journey before automated checkout and fulfillment;
it must be labeled as a manual trial, not counted as proof that payment works.

The UX is ready for alpha when a new customer can see the offer, obtain the
correct business and credit balance after payment, save and revisit variables,
load a bounded set of mail context, hear and interrupt the assistant in Desktop,
then call their assigned number and hear the same configuration. Verify account
isolation with two ordinary customers and an admin. Check interrupted checkout,
repeated return from checkout, insufficient credits, missing mailbox facts and
activation delay without losing a purchased business or silently changing its
owner. Human listening confirms preview and phone behavior.

The existing M4 prototype proves the conversational path for one isolated
profile and test number. It does not yet prove this customer journey, multiple
business routing, checkout fulfillment, or self-service number activation.
