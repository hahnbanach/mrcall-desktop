---
status: active
date: 2026-09-27
---

# Café 124: put GPT-Live in the production profile daemon

<!-- doc-scope:start -->
Scope: development, verification and one-number cutover plan for the manual
Café 124 alpha on +390250552776. Paired with the
[brief](../briefs/2026-09-27-cafe124-voice-daemon.md). A supervised second
cutover serves the production daemon with the known caller's name. The
supervised per-question memory review is active. The independent review passed
the manual handset and identity gates before the local archive release. The
operator permanently accepts possible missing words before transcript attach.
The local `sessions` table is deployed; post-release final acceptance remains open.
No upload of call transcripts to StarChat is planned.
<!-- doc-scope:end -->

## Fixed boundary and observed starting point

The operator has created business
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop` in production, with template
`starter` and service number +390250552776. The operator connected that number
to the Vonage application **GPT-Live M1 isolated test**. This application is
used for this number only. These are operator statements; the deployment gate
below requires authorized provider and StarChat readback. Do not create another
business, change its template, assign a different number or expand the app.

On `desktop.mrcall.ai`, the isolated M4 listener under `mal` serves loopback
port 8787; the existing Cloudflare tunnel targets that port. The
`production@cafe124.it` daemon under `mrcalld` serves its Desktop Unix socket
from a pinned release. Its unit currently has a versioned release `ExecStart`
and drop-ins, including daily-budget and evolution-pilot settings. The shared
`mrcalld` checkout is a different revision. Updating GitHub or that checkout
alone does not change the running daemon. The general
`engine/scripts/server/update-daemons.sh` can restart other profiles and is
unsuitable for this targeted cutover.

Two open StarChat requests cover the later shared product route:
[public ingress and routing, #4](https://github.com/hahnbanach/starchat/issues/4)
and [the `desktop` template, #5](https://github.com/hahnbanach/starchat/issues/5).
Their issue text explicitly permits this one-number Cloudflare test with an
explicit `starter` business binding. Neither issue is a prerequisite for this
manual alpha, and closing an issue alone is not proof that its code is deployed.
The test is bounded by its supervised, one-number scope, not by a local call
duration or spending ceiling; the shared customer-production route remains
separate work.

The isolated script refuses populated profiles and retains bounded test
policy. The production implementation uses its own admission policy and exact
StarChat adapter. The generic `StarChatClient.get_business_config` still has a
first-result fallback and must not be used for telephone binding.

## Delivery order

### 1. Freeze the read-only deployment inventory

- Resolve `production@cafe124.it` to its immutable Firebase UID and record the
  profile path, company-memory membership, current voice-config revision,
  daemon unit/drop-ins, pinned release, socket health and ledger locations in a
  private non-secret manifest. Inspect files as `mrcalld`; do not load `mal`'s
  personal profile or copy the isolated M4 `.env` or ledgers.
- Use an owner-authenticated StarChat read to check the **exact** business ID,
  owner UID, service number, `starter` template and business version. The
  `CrmBusiness` schema defines `businessId`, `owner`, `serviceNumber`, `template`
  and optional `version`; inspect what this endpoint actually returns. If it
  cannot expose authoritative owner and number fields, stop and resolve that
  contract before coding an assumption into admission. Use `version`, when
  present, to detect a changed read and revalidate the binding fields; changes
  to unrelated legacy variables alone do not revoke a valid phone binding.
  The operator's DB statement is not a substitute.
- Read the Vonage application ID, this number's association and its answer/event
  callback URLs, plus the OpenAI incoming-call webhook URL/project. Save their
  existing non-secret values for cutover/rollback. Confirm the Cloudflare URL,
  current `127.0.0.1:8787` target and tunnel lifecycle without restarting it.
- Check the current state and scope of StarChat issues
  [#4](https://github.com/hahnbanach/starchat/issues/4) and
  [#5](https://github.com/hahnbanach/starchat/issues/5), including linked merged
  PRs and any deployed behavior. Record their status in the private inventory.
  If either contract changed, reconcile this plan before implementing its
  affected step. Keep Cloudflare and the explicit `starter` binding for this
  test; do not switch to shared `PRODUCTION 2.0` ingress or migrate the template
  merely because an issue was closed.
- Identify the production account's protected OpenAI key/webhook secret,
  Vonage application identity/account signing secret and Firebase refresh-token
  source. The Vonage callback signing secret and application private key are
  different credentials. Record references and access permissions, never values.
  The operator permits reuse of the same provider accounts and keys used by the
  isolated test, sourced from their original protected private files. Establish
  service-readable production references; do not copy the isolated profile,
  its `.env`, memory key or ledger. Verify account, project and webhook identity
  against the provider readbacks. Confirm the provider payer/rates and existing financial holds. The direct
  OpenAI/carrier path does not establish a StarChat CALLCREDIT debit.

**Exit evidence:** a private inventory with exact UID, business and route
readbacks; successful read-only Desktop RPC health; ledger row/hold counts and
paths; named credential references. **Stop:** any missing or conflicting
business binding, unknown payer, inaccessible credentials, or unexplained
provider route.

### 2. Implement exact business admission and headless authentication

- Add a voice-specific StarChat adapter near
  `engine/zylch/services/voice/preparation.py` and
  `engine/zylch/tools/starchat.py`. Search by the fixed business ID, then require
  exactly one returned object with that exact ID. Validate owner UID,
  +390250552776 and `starter`. Use the optional version to detect concurrent
  changes, then revalidate binding fields rather than pinning all variables. Never
  use `get_business_config`'s first-result fallback for telephone admission.
  Do not interpret legacy `starter` variables as GPT-Live instructions.
- Use the existing encrypted Firebase refresh-token storage and
  `zylch.auth.refresh.ensure_fresh_session` to obtain an in-memory ID token while
  Electron is closed. Check the refreshed UID against the daemon's profile UID
  before constructing the owner-scoped StarChat client. Handle token expiry,
  rotation and failed refresh with refusal. Do not persist an ID token or log
  credentials. Verify the actual StarChat endpoint and response schema in an
  authorized integration check before relying on them.
- At startup, before signed Vonage answer admission, and before selected facts
  or delegated commentary leave the engine, check the immutable call's owner,
  company-memory binding, exact business fields and local config revision.
  Define a bounded read/cache policy only after measuring the API contract; a
  stale or failed read must refuse new calls. A mid-call binding change must
  suppress further disclosures and close safely. Do not switch to another
  business returned by search.

**Tests:** exact/multiple/missing search results, wrong owner/number/template,
changed business version with both unchanged and changed binding fields,
expired refresh token, Desktop closed, provider/API
timeout, changed company membership, late result after invalidation. Assert that
rejection precedes NCCO reservation or disclosure where possible; preserve any
already retained carrier hold if a later check fails.

### 3. Separate the real profile's voice policy from the test fixture

- In `engine/zylch/services/voice/agent_config.py` and
  `engine/zylch/rpc/voice_actions.py`, introduce an explicit production voice
  policy/schema for this one bound profile. Keep `voice.config.get/update` on
  the existing owner-authenticated RPC route with revision checks. An operator
  approves an explicit caller display name or complete sentence IDs, and saves
  greeting, instructions, enabled tools, caller policy and called number. Keep
  saving configuration free. Default to disabled, and validate the exact
  business/owner/company binding before enabling. For this supervised call,
  only the first name of one uniquely phone-matched contact is approved; no
  sentence is selected. Do not read the rest of that contact's memory.
- Remove the test-only duration, max-call and aggregate-spend ceilings from the
  production policy; do not copy the isolated `VOICE_ENGINE_UNLIMITED` marker
  into a populated profile. Retain durable per-attempt reservations, duplicate
  rejection, uncertain-session blocking, usage reconciliation and shutdown
  closure. Before paid admission, verify the provider-enforced maximum call
  exposure, including both carrier legs, voice billing, ringing and cleanup;
  the documented Vonage default is a hypothesis until the active contract is
  checked. If a finite external maximum is confirmed, reserve a conservative
  upper-bound estimate for that exposure before NCCO, without setting a local
  duration limit. Otherwise design and independently review durable incremental
  holds before activation; a fixed M1/M4 smoke reservation is not enough for an
  unbounded call. An internal reserve is an exposure estimate, not proof that
  either provider has captured funds. Do not alter historical holds,
  daily-budget settings for unrelated LLM workflows, or the isolated ledger.
- Extend the production ledger beyond the fixed `SmokeLedger` amount: persist
  metered cost accrued during a call, any hold increases, provider usage and
  eventual receipts as distinct states. Atomically increase the hold before
  expected exposure exceeds it when a provider limit or rate changes. If a
  required increase fails, keep the active call's exposure marked uncertain,
  block new admissions and reconcile it from receipts; do not claim the
  original hold covered the overrun or impose a hidden local call cutoff.
  At closure, record actual provider amounts separately from estimates and
  retain unresolved reservations for supervised reconciliation.
- Keep `CallerMemory` and `Conversation` as the M4 behavior: immediate Live
  greeting; selected historical facts via quiet `thinking`; direct answers from
  those facts; task-bound `commentary` for missing/fresh data; only supported
  deterministic tools; correction, interruption and late-result suppression.
  No GPT-6 telephone agent, dispatcher or fallback. Phone matching is
  recognition, never identity proof. Approved sentences must exclude private
  notes and other companies' data; pin and revalidate their content.

**Tests:** old bounded isolated fixtures still behave as before; production
config accepts no test caps, wrong/missing fields or foreign sentence IDs;
next-call revision changes; caller ambiguity/unknown caller; direct blue-filter
and Thursday history; unsupported live tracking returns unavailable; clock uses
its tool; no telephone GPT-6 path. Verify ledger persistence across restart and
UTC midnight without resetting or transferring rows.

### 4. Run HTTP callbacks inside the existing production daemon

- Add a deliberately enabled option to the normal `zylch -p <UID> serve --unix
  /run/mrcalld/<UID>.sock` path in `engine/zylch/cli/main.py`. Pass the voice
  listener to `serve_ws`; do not create a second process that holds the same
  profile lock. Bind HTTP only to `127.0.0.1:8787` and keep the Unix socket and
  normal headless Desktop tasks alive. Avoid activation from an ambient shell
  variable; load protected profile/service configuration for this exact UID.
- Adapt `engine/zylch/services/voice/listener.py`, `engine_runtime.py`,
  `smoke_vonage.py`, `smoke_runtime.py` and the ledger interface so the
  production path accepts only the signed callback for +390250552776 and the
  configured Vonage application, reserves before emitting NCCO, correlates the
  OpenAI ingress once, and refuses every other number. Continue to validate
  both provider signatures. The current Vonage verifier silently accepts a
  missing JWT `application_id` by substituting the expected ID; remove that
  fallback. Require a present, exact application claim if the live provider
  contract supplies it. If legitimate callbacks omit the claim, stop and
  approve an alternative signed application-binding check before activation.
  Keep the test listener's behavior and storage
  isolated. Ensure a failed listener startup fails the targeted daemon visibly;
  do not leave a healthy Desktop socket that falsely reports phone readiness.
- Use a distinct production voice ledger in the production profile, created
  transactionally and protected as `mrcalld`. Do not point it at the M4 smoke
  ledger. If the schema is reused, make the policy identity and migration rule
  explicit; an old test digest must not block legitimate production restarts or
  silently erase historical rows. Persist interim accrual, hold adjustments,
  provider usage and carrier receipts; label estimates and unknown currency
  honestly.
- Keep private diagnostics opt-in for the production profile with protected
  storage and retention. Correlate call UUID, session, business/config revision,
  approved sentence IDs, append/delegation events, transcript and closure.
  Never log audio, tokens, memory key, unselected facts or provider payloads.

**Tests:** signed/unsigned/stale callbacks, missing/wrong Vonage application
claim, exact destination, callback replay,
double reservation, concurrent calls at actual supported capacity, startup
failure, normal hangup, in-flight lookup shutdown, crash/restart recovery and
uncertain holds. Exercise authenticated Desktop RPC while the loopback listener
is healthy. Run focused `engine/tests/voice`, relevant daemon/RPC tests,
format/lint and a fresh independent code review before deployment.

### 5. Deploy only the Café 124 daemon and cut over port 8787

- Build a versioned release from the reviewed commit under `mrcalld`, with the
  voice dependencies installed there. Preserve the previous release and exact
  unit/drop-in contents. Install a **targeted** drop-in for only the
  `production@` UID instance that selects the new release and protected voice
  configuration. The existing `90-daily-budget.conf` sets `PYTHONPATH` to the
  older release and `95-evolution-pilot.conf` resets it while replacing
  `ExecStart`. Make the new, later drop-in explicitly reset `ExecStart`, point
  it at the reviewed release and clear or set `PYTHONPATH` to that same release.
  Inspect the effective unit with `systemctl cat/show` and verify the running
  process imports the expected voice module from the reviewed release, using a
  sanitized build/path marker; entrypoint path alone is insufficient. Do not
  run `update-daemons.sh`, restart all `zylch-server@*` units or switch the
  shared checkout as the deployment mechanism.
- Before the port handoff, validate the new release/config without paid
  admission: exact StarChat read, local voice revision, protected credential
  access, memory selection, migration dry run, provider signature fixtures and
  recovery state. Use a safe copy or read-only checks for live profile data;
  the current daemon still owns its lock, so a second process cannot prove the
  new release's actual RPC path before handoff. Verify that path after the
  targeted restart. Snapshot ledger metadata without editing rows.
  The live production daemon must not bind 8787 until the isolated listener
  releases it.
- In one supervised window, stop only the idle isolated M4 listener under
  `mal`. Restart only the `production@` daemon from its targeted release; the
  same process must own both its existing Unix socket and `127.0.0.1:8787`.
  Leave the Cloudflare tunnel process and public URL running. Read back local
  `/healthz`, the public health route, signed/unsigned webhook behavior,
  `voice.status`, Desktop RPC and the effective unit/port owner. Recheck that
  provider callbacks still point to the same public URL; change URLs only if
  readback proves a mismatch. Do not reassign the Vonage number/application.
- Keep the tunnel's transient nature explicit: designate a supervisor and a
  URL recovery procedure. A persistent tunnel unit and stable hostname can be
  a separate improvement; do not claim reboot survival for this alpha until
  actually configured and tested. The daemon itself must have no planned
  service expiry.

**Stop/rollback:** on route, authentication, accounting, identity, socket or
health failure, disable the new number's admission and stop the targeted voice
listener. Restore the prior `production@` release/drop-in and its Desktop RPC
without touching other daemons. Restore the isolated M4 listener to port 8787
only after its own recovery checks; it is bound to its former test number and
**cannot serve +390250552776**. Thus the new number remains unavailable until
fixed. Restore a provider URL only if this deployment changed it. Keep all
ledgers, reservations and private evidence intact.

### 6. Prove the call and review end to end

- Place a real incoming call to +390250552776 from the selected caller. A
  human must report what was **heard**: prompt greeting with the approved
  first name, Café 124 identification, an invitation to speak, refusal to
  disclose unapproved history, a follow-up and an
  interruption/correction that stops or supersedes the old answer. An ACK,
  transcript or audio counter is diagnostic evidence, not proof of handset
  playback. Repeat a failed scenario after its specific fix.
- Exercise an unknown/ambiguous caller and a missing/fresh-data question.
  Confirm no cross-customer disclosure or invented live check. Correlate the
  human report with private diagnostic transcript, the selected name grant,
  Vonage/OpenAI receipts and closed ledger rows. Preserve unresolved holds for
  reconciliation; do not call estimates invoices or CALLCREDIT debits.
- Have an independent reviewer inspect the actual deployed commit, targeted
  unit, exact business/number/profile binding, provider routing, code path,
  isolation, account/ledger behavior, rollback evidence and heard call. Record
  findings and remaining alpha limits in this plan. Recheck StarChat issues
  #4 and #5 and state which future shared-ingress/template work remains open;
  issue status does not substitute for this pilot's call evidence. Mark the
  plan completed only if every acceptance gate passes; otherwise leave it
  active with the failed criterion, safe service state and next action.

## Admission decisions and remaining evidence

The authenticated StarChat response exposes the expected owner UID, service
number, template and version; the dedicated adapter requires one exact match.
The daemon can refresh the existing production Firebase token using its
protected Web API key and can read protected provider credentials. Vonage and
OpenAI callbacks retain the same public URL, which reached the production
listener during the reversible cutover. Direct carrier/OpenAI charges remain
separate from StarChat credits. The ledger's rates and holds are conservative
estimates; a real call and provider receipts are still required to establish
actual amounts and reconciliation behavior. The name-only selection is
approved; heard audio and provider receipts remain unverified.

## Gate evidence and current outcome — 2026-09-27

The private, non-secret inventory is
`~/.config/mrcall/cafe124-voice/inventory-2026-09-27.md` (mode 0600).
Authenticated StarChat readback found exactly one business
`d44a1864-23cc-34f9-aec5-6e04bb2fd2ef-desktop`, owned by production UID
`Gn9IcuWzYyY7DBMHkVUGB7bIiTp2`, with +390250552776, `starter`, version 9.
Vonage found that number on application
`38a9213c-296d-464d-9f94-77b53134a924` with signed callbacks at the
existing Cloudflare URL. OpenAI found one `live.transport.incoming` webhook
at that URL's `/openai/live` path. Issues [#4](https://github.com/hahnbanach/starchat/issues/4)
and [#5](https://github.com/hahnbanach/starchat/issues/5) remained open, with
no relevant merged PR found. They concern the later shared route and template.

The implementation is committed as `fae6fd1` and `f7f08d2`. It adds exact
headless owner/business/number validation, production-only voice configuration,
no local call-count/duration/spend caps, in-call exposure accrual and durable
holds, signed one-number callbacks, and a listener in the existing daemon.
GPT-Live remains the sole phone conversational model. Existing LLM and M4
isolated ledgers were not copied or reset. The original protected provider
sources, rather than the isolated profile, supplied a dedicated root-managed
`/etc/mrcalld/voice-cafe124.env` (root:`mrcalld`, 0640). The service-owned
Firebase refresh-token row had raw encrypted text where JSON was expected;
that existing ciphertext was wrapped in a JSON string in place. Headless
refresh then succeeded, without persisting an ID token. No key or token value
is recorded here.

Focused voice and RPC WebSocket tests passed (200 passed, 1 skipped), and lint
passed. A broader run had one pre-existing `llm.models` RPC signature failure
outside this change. Independent predeployment code review cleared the
production path after fixes. A production-data copy passed the voice schema
migration and was also opened by the previous pinned release. The targeted
release was `/home/mrcalld/releases/mrcall-voice-cafe124-f7f08d2`.

The supervised cutover briefly put the production daemon on that release. Its
effective `ExecStart`, cleared `PYTHONPATH`, running imported module path,
existing Desktop Unix socket, authenticated RPC, local/public HTTP 200 health,
and negative signed/unsigned callback behavior were checked. Vonage and
OpenAI callback URL readbacks were unchanged. The Cloudflare process and URL
were retained. No paid call was admitted; the production voice ledger has zero
call rows, zero usage and zero unresolved holds.

The final independent rollback review found that the pre-existing root DEBUG
logging allowed the WebSocket library to record fragments of raw RPC frames in
the production journal during cutover. Dispatcher redaction does not cover
those library records. Commit `78dddf4` suppresses the `websockets` protocol
logger; its focused CLI test passes and an independent reviewer checked the
fix. It was not in the cutover release. Before any new activation, deploy a
new targeted release and confirm the production journal does not
record RPC frames. Treat previous private logs as sensitive.

**Failed fact-selection gate:** the caller +393480727052 matched one contact in
the company store, but the initially selected sentence was unrelated private
material. Its phone match was insufficient evidence for disclosure. The
selection was removed and voice configuration disabled before a real call.
Inspection of the remaining contact sentences found no complete, suitable
Café 124 hospitality fact approved for phone disclosure. The user reported
that a subsequent dial returned “busy.” This is negative handset evidence;
the timing and cause of the busy response are not established by the available
private service log, and no greeting or facts were heard. No call transcript,
provider receipt or correlated diagnostic exists. The listening request issued
before the bad selection was discovered was withdrawn.

The targeted voice drop-in was removed, `VOICE_PRODUCTION_ENABLED` is `0`, and
only the production daemon was restarted to its prior
`mrcall-evolution-pilot-340a99d` release. Its Desktop socket and authenticated
RPC work. The isolated M4 listener again owns 127.0.0.1:8787; local and public
health return HTTP 200 through the original tunnel. Its transient unit needed
recreation after stopping it, with a short recovery gap. The isolated test
number is different, so it cannot serve +390250552776. No Vonage assignment,
business/template, callback URL, tunnel, other daemon, or historical hold was
changed for rollback.

## Second supervised cutover — 2026-09-27

The operator specified the greeting order: greet, use the caller's name if
known, identify the Café 124 assistant, then invite the caller to speak. For
this call the only approved caller-specific content is the first name from the
unique contact matching +393480727052. No historical sentence is selected or
authorized for disclosure. The production configuration revision 3 grants a
display name to that contact's blob and an empty sentence list; unknown and
ambiguous callers receive a generic greeting. A phone match is not identity
proof. The supervised source check confirmed the configured first name against
the contact's person summary without copying the summary or other facts into
the voice configuration.

Commit `a9e6539` adds the name-only production grant and passes the selected
name to GPT-Live before its first turn. It reloads local configuration and
rechecks StarChat after lookup, refusing to send the name if either binding
changes. The isolated M4 policy still requires selected sentences. The focused
voice/RPC suite passed (206 passed, 1 skipped), lint passed, and independent
code review cleared the changes after both invalidation races were fixed.

The versioned release `/home/mrcalld/releases/mrcall-voice-cafe124-a9e6539`
was built under `mrcalld` and its actual voice module import path checked. A
targeted drop-in first ran it without a phone listener, retaining the Desktop
socket. Owner-authenticated `voice.config.update` verified StarChat and saved
revision 3. The isolated listener was then stopped and only the production
daemon restarted with the protected voice configuration. Its effective
`ExecStart` points to `a9e6539`, `PYTHONPATH` is empty, and the imported voice
module path is in that release. The same process serves the Unix socket and
127.0.0.1:8787; local/public health returned HTTP 200 with calls available.
Authenticated `settings.get` and `voice.status` passed. Public negative webhook
probes returned 401 for unsigned Vonage and signed missing-app callbacks, 403
for a signed wrong destination, and 400 for an unsigned OpenAI callback. No
raw WebSocket RPC frames appeared in the journal after the new release began.
Read-only Vonage account lookup found exactly one +390250552776 entry still
linked to the same application. Application readback confirmed its signed
answer/event/fallback URLs still point to the existing Cloudflare URL. OpenAI
project readback found exactly one matching `/openai/live` webhook. The
Cloudflare process and URL and provider callback settings were not changed.

An independent read-only pre-call review checked the running unit, imported
release files, protected binding, name-only revision, socket, tunnel, empty
ledger, unaffected peer daemons and rollback path. It found no technical
deployment blocker. It cannot certify handset audio or end-to-end behavior
before the operator's real call. The latest ledger read before that call still
has zero call, carrier and meter rows.

**Pending acceptance:** the operator has been asked to call from the selected
number and report what was actually heard. Then correlate a private diagnostic
transcript and provider receipts with the call UUID and ledger closure, test
unknown/ambiguous caller handling and missing-data behavior, and obtain the
independent final end-to-end review. A successful health check, webhook
rejection or usage counter alone does not prove handset playback. On failure,
disable admission and restore the prior release and isolated listener while
preserving the ledger and evidence.

## First real call and remaining acceptance — 2026-09-28

The operator called from the selected number and reported hearing the greeting
with their name. They also heard the assistant say it had no information about
them. The production ledger has exactly one closed call, one carrier attempt
and one closed exposure meter. Its private diagnostic file is complete and
records unique caller recognition, the approved display name and **zero
selected facts** under voice configuration revision 3. This explains the
answer: company memory did contain contact information, but the telephone
selection exposed only the name. The phone number matches one company-memory
contact with 11 stored sentences. Matching the number does not authorize those
sentences, and the relevant originals mix suitable context with material not
approved for this call.

The private trace contains inbound and outbound audio events, transcription
events and normal closure. The operator's report supplies evidence that the
greeting and name were heard; the trace alone would not. Provider usage records
29 voice seconds. Vonage reported two completed carrier legs with prices. The
ledger retains a 10,000,000 micro-USD reserve against a 39,337 micro-USD
accrued estimate, with no hold increase; reconciliation is **provisionally
covered**, not an invoice or settled charge. An independent read-only call
review confirmed the call-to-config and ledger correlation. The operator has
not yet confirmed a follow-up or interruption/correction, so that acceptance
gate remains open.

An authenticated configuration update advanced to revision 4 after this call.
It still selects zero historical sentences and now instructs Live to say that
only the caller's name is available to share on this call, rather than implying
that company memory has no information. The exact first name and a short role
statement supported by the contact's person summary have been proposed for
explicit telephone approval; no extra fact has been selected while awaiting
that approval. Production voice stays enabled for the supervised one-number
test. The daemon, tunnel and public health remain available after a midnight
service restart; the current unit still imports `a9e6539`.

**Next gate:** receive the operator's decision on the proposed role statement.
If approved, grant only that statement with a stable source/pin, independently
review its disclosure path, then repeat the real call and obtain an explicit
report covering the permitted fact, follow-up and interruption. Preserve the
historical hold and provider evidence; keep this plan active until the final
end-to-end review passes.

## Operator revision: review memory during the call — 2026-09-28

The operator chose per-question judgment for this supervised pilot rather than
adding a persistent shareability field to company blobs or approving one more
fixed phrase. The previous **Next gate** above is superseded by this decision.
The runtime path must still bind the same production business, UID, called
number and uniquely matched caller. The greeting may use the approved first
name. Two local prototypes were tested but **neither was deployed**. The first
would have forwarded mixed historical sentences to GPT-Live; one such sentence
combined the caller's company role with unrelated private context. The second
would have emitted a fixed role statement after finding role words in one
sentence. Independent predeploy review rejected both. Co-occurring words do
not prove which person has a role, and an unpinned sentence can change without
a voice-config revision. The second prototype also accepted unrelated questions
containing “me.” The local prototypes and their tests were reverted after the
failed gate. Production remains on release `a9e6539` with the name-only policy,
voice-config revision 4, and no selected historical sentence.

The operator's preferred design is a runtime disclosure assessment, without a
new field on every blob. A safe implementation still needs a stable source and
subject binding plus an output boundary that cannot turn a mixed private note
into unrestricted telephone context. GPT-Live remains the only conversational
telephone model; no agent dispatch or GPT-6 phone fallback is authorized.

**Revised gate:** design and independently review a disclosure boundary that
meets the operator's runtime preference. Then implement it with meaningful
negative tests and another independent predeploy review. Only after that review
passes, build a new pinned release and update the production config through
authenticated RPC. Preserve the business, number, tunnel, other profiles,
ledger and rollback. Verify imported module, health, webhook behavior and
private diagnostic redaction; obtain a real call report covering the response,
follow-up and interruption, then run final independent end-to-end review. The
plan stays active while this gate is unresolved.

## Clarified on-demand memory judgment — 2026-09-28

The operator clarified that GPT-Live should first decide whether a caller's
request legitimately calls for memory. Only after a caller utterance and a Live
client delegation may the engine read that caller's company contact; Live then
judges what to say. “What information do you have about me?” is an intended
broad request. This instruction supersedes the earlier proposed fixed-role
grant. The operator accepts supervised model judgment as the pilot's disclosure
policy, while the deterministic contact, company and log boundaries remain.

An opt-in `on_demand_review` implementation is in the checkout, not yet in the
pinned production release or voice configuration. It keeps the greeting to the
name, enforces a single company-wide phone match and configured customer blob,
reads sentence columns only after a question, refuses oversized histories,
excludes obvious private/secret markers and credential formats, and redacts
contact details. It sends
remaining sentences to GPT-Live as untrusted candidates with an explicit
relevance and privacy instruction. Local diagnostics omit source text, queries,
transcript deltas and appended content. The production binding and revision
checks still guard every outbound append. This cannot guarantee that GPT-Live
will not disclose a sensitive part of a mixed candidate; the handset test must
inspect that behavior.

**Next gate:** run the complete meaningful voice suite and adversarial cases,
then obtain a new independent predeploy code review against this clarified
policy. If it passes, create a new pinned release, update the authenticated
production voice configuration to `on_demand_review`, verify service, webhooks
and redacted diagnostics, and invite a real call. Correlate the heard answer,
follow-up and interruption with private call evidence and provider/ledger
receipts. Run final independent end-to-end review before marking this plan
completed. On any gate failure, keep the current name-only daemon active and
record the exact blocker.

## Targeted on-demand deployment — 2026-09-28

Commit `94b42de` contains the on-demand path. The final voice suite passed
212 tests with one skip; Ruff and `git diff --check` passed. Independent
predeploy review found and then cleared credential-pattern leaks, including a
fine-grained GitHub token. It accepted the code for this supervised policy and
left the model's judgment of mixed notes to the real-call gate.

Release `/home/mrcalld/releases/mrcall-voice-cafe124-94b42de` was built from
tracked commit files under `mrcalld`, with its own virtual environment. The
source hash and module import path were checked before service change. The
previous `99-cafe124-voice.conf` drop-in, its release and a private copy of
the voice-config row are retained for targeted rollback without rewinding the
profile database or ledger. Only the production UID service was restarted;
the effective `ExecStart` and logged imported runtime module point at
`94b42de`, with empty `PYTHONPATH`. The Desktop socket and loopback listener
remain in that process. The Cloudflare tunnel PID and URL are unchanged;
local/public health return `calls_available: true` and no local test limits.

An owner-authenticated, headless Unix-socket RPC read checked revision 4 and
the exact pilot customer before update. `voice.config.update` then reverified
the StarChat business and saved revision 5 with `on_demand_review`, the same
customer name and zero pinned sentences. Authenticated `voice.status` reported
enabled and available; a second authenticated read returned revision 5.
Public unsigned Vonage answer/event probes return 401; unsigned OpenAI webhook
returns 400. No provider callback, business, number, template or tunnel setting
was changed.

**Awaiting heard-audio gate:** the operator has been invited to call from the
selected number and report the greeting, answer to “quali informazioni avete su
di me?”, a follow-up and an interruption/correction. Correlate that report
with private diagnostic events and the newly retained provider/ledger rows.
If the model speaks inappropriate detail or audio fails, execute the targeted
rollback and keep this plan open. Final independent end-to-end review follows
the heard call and reconciliation checks.

## Supervised calls on revisions 5 and 6 — 2026-09-28

The operator heard the revision-5 greeting name, but no additional information;
an order question also returned no data. The private diagnostic is complete at
revision 5: one unique caller match, zero facts in the initial greeting, seven
candidate sentences after the broad personal question, three delegations, and
later queries with zero matches. Its 71 voice seconds and two covered carrier
legs correlate with a closed ledger row: 10,000,000 micro-USD reserve, 89,936
micro-USD accrued estimate, and `provisionally_covered` reconciliation. This
shows the history reached GPT-Live; the operator's heard report shows it was
too reluctant to summarize an ordinary business fact. The company contact
matched by phone contains the Café 124 email the operator named, not their
personal Gmail address; phone matching is not email authentication. There is
no Shopify order entry in that contact, and this voice path has no live Shopify
order tool.

The authenticated headless RPC updated only the approved voice instructions to
revision 6. They now explicitly allow a short summary of a relevant ordinary
professional fact even if other parts of the same note must be withheld, and
distinguish historical memory from unavailable live Shopify orders. The
rollback preflight now accepts revisions 4–6; a private revision-5 row backup
is retained. Service PID, pinned release, Desktop socket, tunnel and URL were
unchanged. Authenticated readback confirmed revision 6, the same one customer,
zero pinned sentences and `on_demand_review`; health still reports calls
available.

The operator's revision-6 call report confirms the name and some appropriate
professional notes were heard, with no private detail reported. The assistant
correctly said it could not see Shopify orders. The operator perceived about
five seconds before the greeting; this is a separate latency issue. Private
timing places the call ledger start 3.5 seconds before diagnostic attach and
the first outbound audio delta 0.46 seconds after attach. These events cannot
establish handset playback timing, so the operator's estimate is the audio
evidence. The revision-6 private trace is complete and redacted: unique match,
zero initial facts, seven candidates after one delegation, 60 voice seconds,
two covered carrier legs and a closed 10,000,000 micro-USD reserve against a
75,089 micro-USD accrued estimate. Reconciliation remains provisional, not a
settled invoice. The current diagnostic mode records event counts and timings,
not transcript text; the earlier isolated trace behavior does not apply here.

**Remaining acceptance:** obtain the operator's interruption/correction report,
perform final independent end-to-end review of the revision-6 call, and close
the plan only if those gates pass. Retain the latency issue as a separate
follow-up with its measured preattach interval. If a disclosure or audio gate
fails, execute the targeted rollback, preserve the ledger and keep this plan
open.

## Transcript requirement correction at the time — 2026-09-28

The operator then asked for every telephone conversation to be transcribed
and later stored in StarChat. The later local-table decision at the end of
this plan cancels the StarChat upload. The revision-6 diagnostic
mode retained only event counts and timing, so its three completed production
calls have no recoverable transcript text in the local files. Those calls must
not be described as archived. The operator also reports that the revision-6
assistant shared appropriate professional notes and correctly lacked Shopify
order access; the perceived greeting delay was about five seconds. The
interruption/correction report remains pending.

The next code change adds an exact provider-transcript table to the private
per-call SQLite record while keeping source memory and append text out of debug
events. Production admission must require a writable record before Live accept;
the greeting must wait for sideband attachment so the first spoken words can
be observed. A failed write stops the call, and a call with no provider text is
marked separately. These measures capture received provider transcript events;
they do not prove that no audio was omitted or that handset playback matched
the text. Review, pinned release deployment and a new heard call are required
before accepting this behavior.

The local StarChat backend exposed customer-conversation search and property
updates for existing sessions, but no creation/import endpoint for this
external Cloudflare call. This prevented the upload then under consideration.
The proposed upload was subsequently cancelled.

## Targeted transcript-delta release — 2026-09-28

Commit `d60d46b` contains the private `transcript_deltas` table and provider
event wiring. Diagnostic events in on-demand mode still retain only counts and
timing. The voice suite passed 214 tests with one skip; Ruff and
`git diff --check` passed. Independent code review approved deployment of
**received provider deltas only**, with an explicit incomplete-capture limit.
The review confirmed a writable sink is required before Live accept, write
failure stops the call, and statuses distinguish observed deltas, possible
gaps, no provider text and incomplete capture. It did not certify a complete
transcription, because provider accept precedes sideband attach. Live is
instructed to wait for a backend greeting instruction after attachment, but caller
speech or provider output in that gap is still possible.

Release `/home/mrcalld/releases/mrcall-voice-cafe124-d60d46b` was built from
tracked commit files with its own virtual environment. Source hash, release
marker and imported module path were checked. A new root-only rollback folder
holds the previous 99 drop-in and a targeted script; a private revision-6
config snapshot is retained. Only the production daemon restarted. Effective
`ExecStart` and logged imported module point at `d60d46b`; `PYTHONPATH` is
empty. The Desktop socket remains mode 0660 `mrcalld:caddy`, the tunnel PID and
URL are unchanged, and local/public health report calls available. Public
unsigned Vonage and OpenAI probes returned 401 and 400. Authenticated RPC
readback still shows revision 6, one configured customer, zero pins and
`on_demand_review`. The prior three call ledgers and holds remain intact.

**Next gate:** obtain a real heard call on this release, read the private
transcript table and diagnostic statuses without printing its text to general
logs, correlate provider usage and ledger, and obtain final independent
end-to-end review. At that point the plan stayed active pending interruption,
transcript coverage and the proposed StarChat upload. Later operator decisions
accepted the initial coverage gap and cancelled the upload. A failure of the
new capture would call for the prepared targeted rollback; historical ledger
and transcript evidence must remain intact.

## First transcript-capture call — 2026-09-28

The operator made an adversarial call on the new release and reported that the
assistant behaved well. This is a human report about the heard response, not a
claim that every provider transcript delta reached the handset. The production
ledger has a fourth closed call, started at 11:18:58 UTC, using voice config
revision 6. Its private mode-0600 file contains 172 caller and 228 assistant
transcript deltas in the dedicated table. The diagnostic event table contains
redacted event metadata, counts and timing, without transcript, query or
sentence text or memory candidates. The call ID matches
through the trace and ledger. The trace records one `session.started`, one
`session.closed`, six delegations and memory results, and `trace_closed`.
`transcript_capture` is `deltas_observed`, `diagnostics` is `complete`, and
provider finalization is confirmed. These statuses establish receipt and
retention of the provider's deltas, not completeness of the audio transcript.

The call meter records 170 voice seconds and two carrier legs. Its
10,000,000-micro-USD reserve covers a 205,029-micro-USD accrued estimate with
`provisionally_covered` reconciliation; no hold was deleted or called settled.
A local pattern scan found no credential-format string in the assistant
transcript and no transcript, query or sentence text in diagnostic events.
The operator subsequently confirmed that interruption/correction worked well
in the same call. This closes the human listening gate for the supervised
manual test. At that review, complete-call capture and the proposed StarChat
upload were treated as open.
Independent final end-to-end review checked the live release,
route, binding, ledger, private file and redacted diagnostics, and returned
**Blocked** before this last heard report. It found no obvious
credential or contact-detail pattern in the assistant transcript, but a
pattern scan cannot certify semantic privacy or handset playback. An
independent reassessment of the pilot gate returned **Blocked**. The reviewer
accepted the heard answer, follow-up and interruption/correction evidence for
the selected caller. It found no real unknown/ambiguous-caller call; code tests
exercise unknown, ambiguous and unselected memory lookup, but they do not
establish handset behavior for another caller. The received-delta record still
does not guarantee complete transcription, and StarChat had no import contract
for this external call. The plan remained `active` at that review; later
operator decisions superseded those two transcript gates.

## Archive deferral and alternate number check — 2026-09-28

At this point, the operator deferred sending call transcripts to StarChat.
The private production transcript remained retained. The later decision at the
end of this plan cancels the upload rather than scheduling it as future work.

The operator offered +393518808669 for an unknown-caller exercise. A read-only
lookup of the production company's exact phone identifier found one match:
the **same** configured pilot contact. The national-format identifier had no
separate match, while the number also appears in company text. Calling from
this second number may legitimately trigger the approved name and on-demand
review, so it cannot prove the unknown-caller branch. Another number must be
checked before that live gate. The operator has been asked for one. The
accept-before-sideband interval remains a documented transcript-completeness
limit; the observed 400 deltas from the adversarial call are retained.

## Anonymous caller and explicit number validation — 2026-09-28

The operator called with withheld caller ID on release `d60d46b` at 11:38:58
UTC. The fifth production call closed with `caller_recognition=unknown`, zero
caller facts, confirmed provider finalization, complete private diagnostics and
`deltas_observed`. Its private call file retained 74 caller and 148 voice
transcript deltas. The ledger retained a 10,000,000-micro-USD reserve against a
142,128-micro-USD accrued estimate for 117 voice seconds; reconciliation is
`provisionally_covered`, not a settled charge. The operator heard a generic
response and reported that saying they were Mario Alemi did not unlock history.
They asked for an explicit rule that invalid or withheld incoming numbers may
never read customer memory, even after a spoken identity claim.

Commit `d7fa315` implements that rule. The incoming caller string must have a
single international `+` prefix or `00` prefix and pass the Python
`phonenumbers` port of libphonenumber before any company-memory identifier
search. Missing, withheld, malformed and implausible numbers return `unknown`
without that search. On-demand conversation delegation now refuses historical
lookup for every recognition other than `matched`, regardless of the spoken
name or number; it does not assert whether a record exists. A valid number
still needs the exact unique selected contact. No caller may choose a different
memory key or business through model input.

The full voice suite passed with 221 tests and one skipped before the last raw
syntax fix. The final 46 focused tests, Ruff and diff check passed after it.
An independent code review found and blocked an initial malformed-plus case;
after the fix, its nine invalid-number spy cases and self-claim test passed and
the reviewer approved deployment. A new production release
`/home/mrcalld/releases/mrcall-voice-cafe124-d7fa315` installed
`phonenumbers` 9.0.40. The installed caller-memory and conversation modules
match the committed source hashes. The production daemon alone restarted at
11:51:40 UTC with effective ExecStart in that release, empty PYTHONPATH and an
imported voice module under its venv. The Desktop socket remains mode 660,
`mrcalld:caddy`. Local and public health passed; unsigned Vonage answer/event
and OpenAI webhook probes returned 401/401/400. Authenticated owner RPC read
voice revision 6 with no selected sentence IDs. The tunnel retained its PID,
target and URL. Root-only rollback
`/etc/mrcalld/rollback-cafe124-phone-validation-20260928/rollback.sh` restores
the prior `d60d46b` drop-in after checking revision 6 and no active call; its
syntax was checked, and it does not touch ledger or tunnel.

A repeat anonymous handset call on `d7fa315` was completed after this cutover;
its correlation and outcome follow below. Full transcription of the
accept-to-sideband interval is not established. StarChat upload is explicitly
deferred by the operator.

## Anonymous handset acceptance on the validation release — 2026-09-28

The operator called with withheld caller ID at 13:16:07 UTC, after the
`d7fa315` daemon started at 11:51:40 UTC. They heard the assistant decline
historical data and offer to answer general questions about the service. They
judged that response perfect. The closed call has config revision 6,
`caller_recognition=unknown` and zero caller facts. Its private mode-0600 trace
has one initial memory recognition call with `query_present=false`, one
delegated work result, one Live session start and close, and `trace_closed`.
There is no on-demand memory query for the spoken self-identification. The
trace contains 11 caller and 43 assistant transcript deltas; diagnostics are
complete and provider finalization is confirmed. The human report establishes
what was heard; the deltas establish only provider text received and retained.

The ledger retains a 10,000,000-micro-USD reserve for this sixth call. Its
accrued estimate is 48,796 microUSD over 36 voice seconds, with two completed
priced carrier legs and `provisionally_covered` reconciliation. No reserve was
deleted and no settled charge is claimed. Public health remains available
with `calls_available=true` and no local test limits. Independent final
end-to-end reassessment found the deployed module path, exact owner/business/
number binding, unchanged tunnel and Desktop socket, healthy webhook route,
private trace, closed ledger, both priced carrier legs and root-only rollback
consistent with this call. The supervised one-number functional, audio and
unknown-caller gates **pass** on `d7fa315`. The ambiguous-number branch remains
covered by tests rather than a handset call.

At that review, the independent overall verdict was **Blocked** on transcript
completeness.
The 54 received deltas do not establish what, if anything, was spoken before
the sideband attached after provider acceptance. The operator deferred upload
to StarChat, not the requirement that calls be transcribed. The plan remained
`active` with this limit visible; full transcription and remote archival were
not marked complete. The production phone service remained active and healthy,
with the targeted rollback prepared if a concrete safety or audio failure
appears.

## Final acceptance decision — 2026-09-28

The operator explicitly and permanently accepts that words spoken before the
sideband transcript connection may be absent from the saved call record. This
changes the product acceptance rule, not the observed capture: the daemon
retains received caller and assistant provider deltas in private per-call
records, and no one claims verbatim coverage of the pre-attach interval or
recovery of earlier calls without stored text. The operator separately deferred
upload to StarChat at that point. The later cancellation supersedes the upload
proposal entirely.

With this explicit acceptance, the independent final end-to-end reviewer
reassessed the verified `d7fa315` release and returned **Done** for the manual
Café 124 one-number test. The heard selected-caller and anonymous calls, exact
business binding, headless authentication, service and webhook checks, private
diagnostics, provisional exposure ledger, and targeted rollback satisfy this
manual test's supervised gates. The service remains active on the pinned
release with the existing tunnel and Desktop socket. The accepted transcript
timing limit remains recorded as a product fact.

## Local call-transcript table — planned after manual acceptance

The operator cancelled the proposal to upload call transcripts to StarChat.
Keep StarChat only for the exact business binding and other existing service
contracts. Store future call transcripts locally, in a private table owned by
the production profile. No StarChat session creation, import, or upload belongs
to this plan.

A read-only inspection of the StarChat source checkout found that its current
`SessionTimescaleService.createSchemaSqlStatement()` creates a `sessions` table
with `id`, `start_timestamp`, `timestamp`, `created_at`, `updated_at`, `owner`,
`business_id`, and a JSONB `data` field, among other lifecycle fields.
`CustomerConversationService` writes the parsed `public.CONVERSATION_JSON`
value under `data.conversation_transcription`; the customer-conversation API
guide shows entries with `role` (`user` or `assistant`) and `content`. The
configured table name is `sessions`. The code does not qualify it with a
PostgreSQL schema, and no live database schema was queried, so the suggested
`business.sessions` namespace is unconfirmed. The older reference migration
shows a `conversation_log` column absent from the current startup schema;
model the current `data.conversation_transcription` shape, not that column.

Create a SQLite table named `sessions` in a dedicated profile-owned
`sessions.db` (mode 0600), with one row per production call. Match StarChat's
useful column names and meanings: `id` is the existing voice ledger session ID;
`start_timestamp`, `timestamp`, `created_at`, and `updated_at` are UTC
timestamps; `owner` is the Firebase UID; `business_id` is the exact bound
business; and `data` is validated JSON. Include `expired`, `deleted`, and
`archived` only if their lifecycle semantics are needed for local reads and
retention. Use an index on `(business_id, start_timestamp)` for ordered lookup.
There is no need to copy StarChat's state variables, access key, audio fields,
or PostgreSQL/TimescaleDB machinery into SQLite.

In `data`, store `conversation_transcription` as an ordered array of
`{role, content}` entries, using `user`/`assistant` like StarChat. Put local
call metadata such as called number, nullable validated caller number,
duration and capture status in `data` without inventing a different top-level
table contract. Optional timing fields may accompany a transcript entry if
the provider supplies them. Do not store company memory keys or unselected
memory facts. The local SQLite table is named `sessions` deliberately; the
unverified PostgreSQL schema name `business` is not copied.

Populate the row from the existing append-only private `transcript_deltas`
source. Create an identifiable row when a call starts, update it durably as
provider text arrives, and finalize it on closure; a restart must leave a
readable partial state and permit idempotent recovery from the per-call source.
Preserve the raw delta files and the ledger. Backfill only calls whose delta
text exists locally; for earlier calls with diagnostic counts alone, record
`legacy_no_text` without inventing speech. Keep the permanent acceptance of
possible missing words before sideband attachment explicit in `capture_status`
or adjacent metadata.

Before activation, review the table migration and privacy boundary
independently. Test ordered role assembly, empty/partial calls, restart and
duplicate replay, exact profile/business binding, file permissions, and
absence of transcript text in ordinary logs. On a supervised real call, read
back the table under `mrcalld` and correlate its `id`, roles, capture status,
and timing to the private deltas and ledger. The table is not implemented by
this planning edit. The execution plan remains `active` for this local storage
phase, while the one-number phone acceptance remains complete.

## Local sessions implementation and activation — 2026-09-28

Commit `1d1a43f` adds `sessions.db` with a private `sessions` table and the
StarChat-derived `id`, timestamp, owner, business ID and JSON data fields.
Provider deltas are replayed in order into `data.conversation_transcription`;
the local ID equals the ledger session ID. The production call starts a row
before provider accept, commits each received delta into the raw private trace
and the durable archive, then finalizes capture status and duration. Startup
replays funded ledger calls from private delta files. Old files without a
`transcript_deltas` table become `legacy_no_text` with empty messages. The
accepted possible pre-attachment gap is recorded on every row. No transcript
is sent to StarChat. GPT-Live, business binding, the approved voice settings,
headless authentication and the existing accounting ledger are unchanged.

Predeploy independent code review returned **APPROVED** after finding and
resolving an old-trace startup failure. The full voice suite passed with 227
tests and one skip; Ruff and `git diff --check` passed. The dedicated tests
cover role order, restart replay, duplicate replay, empty and partial calls,
legacy missing text, exact owner/business binding and private file modes.

Commit `8fb21d3` makes each production delta-source commit WAL/FULL before the
archive commit, while ordinary diagnostic metadata stays WAL/NORMAL. This
prevents a power-loss restart from replacing a durable archive with a shorter
source. The focused 22-test suite and Ruff passed; an independent review
approved the durability and audio-path separation.

Release `/home/mrcalld/releases/mrcall-voice-cafe124-8fb21d3` was built from
the committed engine tree with its own environment. The installed voice
module hash matches source. Only the production instance restarted. Effective
`ExecStart`, empty `PYTHONPATH` and the running imported module point to this
release. The Desktop socket remains mode 0660 (`mrcalld:caddy`), and the
existing tunnel PID, target and public URL remain live. Local/public health
report available; unsigned Vonage answer/event probes return 401 and unsigned
OpenAI webhook returns 400. The unchanged voice config is revision 6, and the
ledger had no active calls at cutover. A root-only targeted rollback script and
the previous drop-in are retained under
`/etc/mrcalld/rollback-cafe124-local-sessions-20260928/`.

Startup created `sessions.db` mode 0600 under the production UID profile.
Six funded ledger calls have six archive rows with matching IDs and exact
owner/business: three historical calls have `legacy_no_text` and zero messages,
and three calls with retained deltas have ordered messages. Raw files and the
ledger remain in place. **Open gate:** a new supervised real call must be
correlated across the private delta file, `sessions` row and closed ledger;
then obtain a fresh independent final end-to-end review. The plan remains
`active` until those checks pass.

The independent final review returned **BLOCKED** on the new-call gate alone:
at 14:08:08 UTC release activation and at the later read-only review, all six
funded calls predated the release, and there was no active call. The reviewer
verified the live pinned import, archive schema/mode, all six ledger matches,
exact old-delta reconstruction, Desktop socket, tunnel, public health and
rollback evidence. The requested supervised call has not yet produced a new
ledger ID; no archive/trace/ledger correlation for this release can be claimed.
After that call, repeat the correlation and obtain another independent final
review before setting `status: completed`.

## Post-release transcript calls and grounding failure — 2026-09-28

Two real calls on release `8fb21d3` started at 14:33:05 and 14:34:29 UTC.
Both are closed in the production ledger and have private `sessions` rows with
the exact owner and business binding. Each row's ordered messages match its
private `transcript_deltas` source exactly. Both rows report
`deltas_observed` and retain the accepted possible pre-attachment gap.
The ledger now has eight funded closed calls and the archive has eight rows:
three historical `legacy_no_text` rows and five with received text. The two
new holds are `provisionally_covered`, not settled provider invoices. This
correlation verifies the local archival path for real post-release calls; it
does not by itself verify every spoken word or handset playback.

The operator heard a severe incorrect answer on the 14:34 call. The private
transcript records a question about the business's services and an answer
inventing hospitality offerings. Its trace records no delegation for that
question and no business-fact lookup; the initial matched-caller lookup
returned no facts. GPT-Live had the business name in its instructions, but no
verified service catalog. This establishes an ungrounded answer, not the
business's actual services. The operator asked to discuss wider sharing of
verified company information and controls against such answers, without
implementing a correction yet.

The prior independent final review predates these calls. The following fresh
production review supersedes its missing-new-call finding. Archive correlation
does not constitute acceptance of the incorrect spoken response.

## Independent post-release final review — 2026-09-28

The fresh reviewer inspected the running production daemon and private call
evidence in read-only mode. The daemon has run release `8fb21d3` since
14:08:08 UTC; its effective command and imported archive module point to that
release, with an empty `PYTHONPATH`. The same process owns the phone listener
and Desktop socket. Local health reports calls available and no test limits;
the targeted rollback remains protected. The profile-owned `sessions.db` is
mode 0600. No service or file was changed during this review.

**Local call-transcript table — APPROVED.** The 14:33 and 14:34 calls started
after the release. Their archive rows have the exact owner and business, the
same IDs as the funded closed ledgers, `deltas_observed` capture status and the
accepted possible pre-attachment gap. The ordered archive messages match all
77 and 59 received private deltas respectively (7 and 3 assembled messages).
Both private traces are closed. All eight funded ledger IDs have archive rows.
This satisfies the previously missing post-release call correlation gate. It
proves preservation of received text, not every spoken word or handset audio.
The two new ledger reconciliations remain provisional, not settled invoices.

**Overall plan acceptance — REVISE.** The 14:34 private transcript records a
business-services question followed by an unsupported hospitality-service
answer. Its complete trace has no delegation or delegated work for that
question. The only memory lookup was initial caller recognition, with no
query and zero facts delivered. The current telephone path exposes selected
caller history, not a verified company service catalog. The trace cannot
establish the model's internal reasoning or recover words before transcript
attachment, but the recorded answer has no verified source in this call. It
fails the plan's suitable, fact-grounded answer gate. The earlier independent
`BLOCKED` verdict concerned only the missing post-release call; that condition
is resolved. Archive approval does not approve the spoken response.

Keep this plan `active`. Discuss a design for broad, scoped access to verified
company facts and an enforceable response-grounding rule before changing phone
behavior. After the chosen design is implemented and reviewed, its acceptance
must include a real business-services question with verified source evidence
and a spoken answer that neither invents services nor exposes unselected or
private facts. Do not repeat the already completed archive correlation merely
to satisfy that new behavioral gate.
