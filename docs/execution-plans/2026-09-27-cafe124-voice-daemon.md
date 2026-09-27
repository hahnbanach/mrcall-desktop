---
status: blocked
date: 2026-09-27
---

# Café 124: put GPT-Live in the production profile daemon

<!-- doc-scope:start -->
Scope: development, verification and one-number cutover plan for the manual
Café 124 alpha on +390250552776. Paired with the
[brief](../briefs/2026-09-27-cafe124-voice-daemon.md). Implementation and a
reversible route cutover were verified; the customer fact-selection and heard
call gates remain blocked, so production voice admission is disabled.
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
  selects and approves complete sentence IDs from Café 124 memory and saves
  greeting, instructions, enabled tools, caller policy and called number. Keep
  saving configuration free. Default to disabled, and validate the exact
  business/owner/company binding before enabling.
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

- Place a real incoming call to +390250552776 from a caller whose Café 124
  sentences were approved for phone disclosure. A human must report what was
  **heard**: prompt greeting, correct permitted facts, follow-up and an
  interruption/correction that stops or supersedes the old answer. An ACK,
  transcript or audio counter is diagnostic evidence, not proof of handset
  playback. Repeat a failed scenario after its specific fix.
- Exercise an unknown/ambiguous caller and a missing/fresh-data question.
  Confirm no cross-customer disclosure or invented live check. Correlate the
  human report with private diagnostic transcript, selected sentence IDs,
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
actual amounts and reconciliation behavior. Approved customer fact selection
and heard audio are the immediate blockers.

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

**Open acceptance:** select and approve a specific Café 124 sentence or add a
verified, phone-safe fact for this caller, then revalidate exact IDs and
content. Deploy and verify the logging fix, re-run targeted deployment and
webhook checks, place the real call,
correlate private diagnostics and provider receipts, obtain a human report of
heard greeting/facts/follow-up/interruption, and run independent final
end-to-end review. Keep this plan blocked and the number inactive until those
gates pass. Neither health nor callback rejection tests establish audio.
