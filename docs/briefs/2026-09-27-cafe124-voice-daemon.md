---
status: draft
date: 2026-09-27
---

# Café 124: GPT-Live in the production daemon

<!-- doc-scope:start -->
Scope: desired behavior and acceptance boundary for the manual Café 124 voice
alpha on +390250552776. This brief does not claim that customer activation or
StarChat credit billing has been implemented. The superseded pilot procedure is
not the execution plan for this number.
<!-- doc-scope:end -->

## Objective and fixed inputs

Serve incoming calls to **+390250552776** with GPT-Live and the real
`production@cafe124.it` engine profile. The phone listener belongs to that
profile's existing `mrcalld` daemon on `desktop.mrcall.ai`. The daemon continues
to serve Desktop through its per-UID Unix socket and also exposes the provider
HTTP callbacks on loopback. One process owns the profile and its lock; do not
start a second ordinary-profile engine beside it.

The operator confirms that the new number and Café 124 business are already
assigned in the production database. The business ID is
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop`. Its template is `starter`
because `desktop` is not yet an available key. The operator also confirms that
**+390250552776 is connected to the Vonage application “GPT-Live M1 isolated
test,” currently used for this number only**. These are operator-supplied
inputs, not claims of an independent live readback. Do not create another
business, reassign the number, change its template, or broaden this application
to other customers as part of this alpha.

The existing Cloudflare tunnel runs on the **same host** and forwards its public
URL to `127.0.0.1:8787`. The production daemon under `mrcalld` now serves that
port and its Desktop RPC Unix socket from one pinned release. The isolated M4
process under `mal` remains available for rollback but is stopped during the
production call test. A Git push or checkout update alone does not change the
running daemon.

## Customer call contract

The called number selects the one authorized business and its immutable
Firebase-UID profile. The engine validates the called-number/business/profile
binding before accepting the carrier connection and again before disclosing
facts. Unknown numbers, owner mismatches, disabled configuration and failed
headless authentication refuse admission. The caller's phone number helps
retrieve permitted context; it is not proof of identity. For the supervised
pilot, the greeting discloses only the approved name of the uniquely matched
contact. After a caller request and GPT-Live delegation, the on-demand review
path can supply filtered company-scoped sentence candidates from that contact.
GPT-Live judges the relevant portion to say. Internal notes and other
companies' facts stay out of the model context.

StarChat is authoritative for the business ID, owner UID, service number,
template and business version. Read these through an authenticated StarChat API
as the production account. Accept **only** an exact `businessId` match with the
expected owner, +390250552776 and `starter` template. The existing
`get_business_config` helper falls back to the first search result when no ID
matches; the telephone binding must not use that fallback. Missing, stale or
ambiguous identity data refuses admission. Read back the version and binding
before activation and each call; changes to binding fields require reapproval.

For this **manual** alpha, the engine's `voice_agent_config` facility, once
deployed and configured in the production profile, is the approved source for
the GPT-Live greeting,
instructions, enabled tools, called number, caller policy and approved caller
context. An authenticated operator creates and approves that record if absent.
The existing `voice.config.get/update` RPC supplies the revision and company
binding. The configuration model has a production policy branch without M2
test limits, while the isolated policy retains them. Production admission
still requires the protected service enablement and approved caller selection;
an RPC record alone does not activate the phone. The StarChat business version
and this local voice-config revision are distinct.
The `starter` template inherits variables used by the older assistant,
including welcome and conversation prompts; this pilot does not silently
interpret any of them as GPT-Live instructions. No customer-editable Desktop
voice settings are promised while this business remains `starter`. The
longer-term `desktop` template and StarChat-variable mapping remain separate
work; this temporary local configuration is disclosed rather than presented
as the finished Desktop configuration journey.

GPT-Live remains the **only telephone conversational model**. The engine
resolves the approved display name and rechecks both bindings before Live's
initial greeting. Selected-fact mode supplies approved pinned history as quiet
`thinking`. The supervised production on-demand mode starts with only the name
and consults the matched contact after a legitimate caller question.
For missing or fresh data, Live delegates and the engine returns the specific
tool result or an explicit unavailable answer in task-bound `commentary`. No
telephone GPT-6 agent, dispatch or fallback returns. Preserve interruption,
correction, follow-up and historical-versus-current wording from M4.

The production call uses durable admission, reservation, usage and closure
accounting. Existing holds and ledger rows are never reset. The M4 isolated
test's unlimited override cannot simply be copied into the populated profile;
the production admission policy and config schema must be adapted explicitly,
without introducing local call-count, duration or spending ceilings. Direct
OpenAI and carrier charges must be represented honestly: this pilot does **not** prove a
StarChat CALLCREDIT debit. Saving configuration remains free.

## Routing and lifecycle

The intended callback path is Vonage's already selected application → the
existing Cloudflare URL → a loopback HTTP listener in the `production@` daemon.
The OpenAI incoming-call webhook must reach the same listener. The daemon's
Desktop Unix-socket route remains available. The tunnel is a separate process;
its location on the same host and its target are the relevant facts. Keep the
current tunnel and public URL during the handoff if the provider callback URLs
still match. Do not restart the tunnel merely to move port 8787 from the test
listener to the production listener. The current tunnel is a transient user
service under `mal`, with its executable in `/tmp`; an unlimited runtime does
not make it restart automatically after a host reboot. Treat this alpha as
supervised until tunnel persistence and URL recovery are established. Record
who monitors its availability and restores the provider URLs if they change.

Cut over only this number. Stop the isolated process before the production
daemon binds port 8787. If activation fails, disable the new number's admission
and restore the old test listener on that port. The old listener is bound to
its former test number and **cannot serve +390250552776**; the new number
remains unavailable until the problem is fixed. Restore Vonage or OpenAI URLs
only if they were actually changed. No change to other Vonage applications or
numbers is part of this pilot. The phone service must continue with Electron
and cs-operator closed. A managed restart must recover its ledger and provider
session state without accepting duplicate or unfunded calls. The test and
production profiles and their accounting remain separate.

## Acceptance and limits

Before a carrier cutover, verify the live production owner UID, business and
service-number binding through authorized StarChat reads; verify the Vonage
application's number association and callback URLs through provider reads.
The operator's confirmations above are inputs, not substitutes for those
deployment checks. Verify that the daemon under `mrcalld` can use its own
protected Vonage and OpenAI credential references without copying the isolated
profile, its `.env` or either ledger. Vonage's callback signature secret is
distinct from its application private key; keep both in protected server-side
storage if their respective operations need them. Verify provider signature
handling,
local/public health, account isolation, rejection of every other called number
and preservation of the Desktop RPC route. Rehearse rollback without deleting
ledgers or profile data.

Then place a real incoming call to +390250552776 from the selected caller.
Human listening must confirm the greeting with the name, Café 124
identification, invitation to speak, a suitable answer from the on-demand
review, a follow-up and an interruption. Correlate private transcript and
diagnostics with the caller match, provider receipts and closed ledger rows. An ACK,
transcript or counter alone does not prove heard audio. Exercise missing data
and an unrecognized caller without exposing another customer's facts. An
independent end-to-end review checks code, configuration, route, accounting,
call evidence and remaining limitations before calling this alpha active.

If binding, routing, account isolation, accounting or the heard call fails,
leave the alpha inactive. Restore a provider URL only if it changed. Preserve all
historical evidence and uncertain reservations. This brief covers the one
manual Café 124 pilot; it does not certify checkout, preview in Electron,
multi-business routing or general availability.

## Caller memory after the first call

The first call recognized the selected caller's number and name, while its
then-current configuration made no historical sentence available. The operator
prefers a per-question disclosure judgment during the
supervised call over adding a shareability field to every blob now. The goal is
to answer useful questions about the caller without treating a phone-number
match as identity proof or broadcasting the contact's whole history.

The operator clarified the sequence: GPT-Live judges whether a caller's
request justifies consulting the matched contact; only then does the engine
read memory, and Live judges what is appropriate to say. A broad request for
information about oneself is eligible for that judgment. The engine still
enforces exact contact and company scope, excludes obvious private/secret
notes, redacts contact details, bounds model input and keeps source text out of
diagnostic event records. Full caller and assistant transcription deltas belong
in a separate private call record. The model can still misjudge a mixed note. This is a
supervised pilot risk, not a general authorization system; human listening and
independent predeploy review remain required. GPT-Live remains the sole
conversational telephone model, with no agent dispatch or GPT-6 phone fallback.

The operator requires every phone call to be transcribed and its transcript
eventually stored in StarChat. The production daemon must retain the exact
provider transcript in a private call record now. StarChat currently offers
search and properties updates for existing customer conversations but no
creation/import route for this external Cloudflare call, so remote archival
needs a backend contract before it can be claimed active. Prior calls without
stored text cannot be reconstructed from diagnostic counts.

Related contracts: [M4 Live-context plan](../execution-plans/2026-09-23-gpt-live-engine-integration.md#current-m4-plan--live-uses-selected-context-engine-supplies-new-results),
[this alpha's development plan](../execution-plans/2026-09-27-cafe124-voice-daemon.md),
[engine voice configuration](../../engine/docs/features/voice-agent-configuration.md),
[remote daemon layout](../remote-backend.md), and
[Desktop voice alpha UX](2026-09-25-desktop-voice-assistant-alpha-ux.md).
