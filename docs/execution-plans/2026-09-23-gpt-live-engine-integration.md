---
status: active
date: 2026-09-23
---

# GPT-Live: incoming calls backed by company memory

<!-- doc-scope:start -->
Scope: execution plan for the first telephone customer-service prototype: one
incoming call at a time, asynchronous caller recognition and read-only memory.
Owns milestones, verification and rollback; product intent lives in the brief.
<!-- doc-scope:end -->

Brief: [telephone customer service](../brief/2026-09-23-gpt-live-engine-integration.md).
Its adversarial review returned APPROVED after the caller-context and spoken
correction clarifications. A separate fresh plan review returned APPROVED;
an additional adversarial review also approved after the cold-start correction.
M1 is complete: live demonstration and final integration review passed. The first
implementation's approval was withdrawn by the subsequent failure-path review.
M2 is complete: authenticated client/fixture demonstration and independent
integration review passed. M3 is complete: direct GPT-6 backend demonstration,
integrated telephone call and fresh independent integration review are APPROVED.
Listening evidence and its limits are recorded below. M4 remains unstarted; this
four-milestone plan stays active.

## Current M3 correction — 2026-09-24

This supersedes earlier requirements for a funded MrCall business and the earlier
provider-change prohibition. The user explicitly selected the dedicated OpenAI
key/project at `/home/mal/.config/mrcall/gpt-live-test.env` for the backend too.
Use the latest verified models: `gpt-live-1` voice and `gpt-6-sol` backend, with
Responses function calling. Never select obsolete models for implementation
convenience. Official model and function-calling references are in the brief.
The unactivated GPT-4.1 adapter is an incomplete abandoned draft; no GPT-4.1
inference was sent. Its partial regression run finished with 56 passing tests.

M3-only completion steps, owned by the lead and independently reviewed:

1. Verify official model/API/prices and dedicated-project model availability.
   Replace the draft with Responses text/function conversion, explicit GPT-6
   validation, standard-tier pricing and conservative durable accounting.
   Select `reasoning.effort=none` for the short, selected-fact voice backend;
   this is documented GPT-6 Sol support, not a model substitution.
2. Keep direct OpenAI selection confined to the explicit isolated voice profile.
   Test function round trips, usage/cache accounting, incomplete/error responses,
   no billing fallback, ordinary chat regression and call cancellation.
3. Run real GPT-6 inference through the common budget ledger and frozen synthetic
   memory, including a tool round trip, follow-up, correction and missing facts.
   Model listing/health alone is not acceptance. Review before activation.
4. Activate only the isolated voice backend, retain every ledger row/hold and
   the tunnel URL, then cold-start the existing service without operator RPC.
   Keep both services at infinite lifetime and all local test ceilings removed.
5. Listen to an integrated incoming phone demonstration with cs-operator stopped;
   record facts used, follow-up/correction behavior, closure, latency and usage.
   Obtain independent M3 integration review. Do not start M4 or certify its full
   scenario matrix. Without successful phone evidence M3 remains incomplete.

Rollback disables the isolated OpenAI voice selection or listener and retains
accounting; no production profile, memory fixture, carrier routing or tunnel
changes. Prior failed MrCall holds remain unresolved historical liabilities.
Brief and plan corrections independently APPROVED before implementation.

## M1 rewrite — 2026-09-23

The operator requested a rewrite after review reproduced credential logging,
untracked acceptance after timeout, missing hangup on sideband EOF, volatile
spending limits, blocked event processing during delegation and an ambient-only
test-profile gate. Commit `b9d4075` remains the recovery point, not an approved
live-test candidate. Replace its smoke runtime and tests within this worktree.

Keep the existing brief and milestone boundaries. Use a small durable SQLite
ledger: reserve before accepting, deduplicate by session across restarts, retain
uncertain attempts and refuse new calls until closure is known. Keep the event
reader running while the fixed result waits. Verify signatures using the real
SDK and fake signed requests, and test transport logging with fake credentials.
Read isolation/routing configuration from the explicitly selected profile file.
Prove all reproduced failure paths locally, then obtain a fresh integration
review. SIP remains a candidate until real Vonage/project compatibility passes;
local tests cannot approve live acceptance or authorize M2.

## Delivery shape

### M1 carrier provisioning follow-through — 2026-09-23

The user explicitly released and authorized `+390289047081` for this experiment.
Create a dedicated Vonage application rather than change the shared test app.
Its answer webhook needs a small authenticated NCCO adapter: verify the Vonage
HS256 callback and body hash, match only the selected number, and return the
fixed OpenAI project SIP destination with TLS/SRTP and a carrier duration limit.
Reserve the attempt before returning the NCCO, deduplicate carrier UUIDs, and
bind the subsequent OpenAI session to that same hold through a one-use SIP
correlation nonce. Missing ingress must retain the reservation and block retry.
The event endpoint verifies and discards metadata; accounting still requires
provider receipts, not untrusted callback text. This is M1 carrier plumbing,
not outbound calling or M2 operator configuration. Keep routing disabled until
the remaining live preflight passes and review this addition before a paid test.

Four sequential milestones, each ending in a demonstration and an integration
review before dependent work. The lead implements and integrates; a fresh
reviewer checks each milestone, and a separate reviewer checks final acceptance.
No parallel implementation is needed for this small slice.

| Milestone | Demonstrable result | Depends on |
|-----------|----------------------|------------|
| M1 — Connect a call | A test phone reaches GPT-Live, Python receives its events and closes it cleanly. | Project/carrier access and an isolated test number. |
| M2 — Configure and retrieve | Operator can configure the agent; a phone number retrieves only the selected customer facts. | M1 transport decision. |
| M3 — Converse with memory | Greeting and lookup run together; follow-up questions and corrections use the engine. | M2. |
| M4 — Call and listen | Real incoming calls pass the brief's five acceptance criteria. | M3. |

First delivery excludes external services, the meta-skill generator, outgoing
calls, concurrent calls, memory writes and Electron UI work. Preserve a reusable
memory tool contract so later integrations do not require new telephone plumbing.

## Existing code to reuse, and the small additions

- `engine/zylch/storage/storage.py:find_blobs_by_identifiers` already finds company
  entities by number. Reuse the normalization rules in `workers/memory.py` and
  the scope predicates in `memory/scope.py`; do not build another contact index.
- `memory/hybrid_search.py`, `memory/blob_storage.py` and `BlobSentence` supply
  real memory storage/retrieval. The ordinary search tool returns complete blobs;
  the voice path must select the approved facts before constructing model input.
- `assistant/core.py` supplies the agent/tool loop and paid engine dispatch. It
  currently installs the owner's prompt and personal context. Add an explicit
  customer-service mode with its own prompt/context and tool list; preserve the
  existing defaults and verify ordinary chat still receives its original inputs.
- The M1 runtime exists in `engine/zylch/services/voice/`, with focused tests in
  `engine/tests/voice/`. M2 adds `rpc/voice_actions.py` for operator configuration
  and `services/voice/agent_config.py` / `caller_memory.py` for snapshots and
  selected-fact retrieval. M3's opt-in engine listener now connects these to calls;
  live listening acceptance remains separately recorded below.
- Register configuration methods in the existing RPC table. Use the authenticated
  profile WebSocket transport for operator access; provider webhooks use their
  own verified route and never expose the owner RPC surface to callers.

## M1 — Establish one working telephone path

**Work.** Check GPT-Live project access and the Python SDK version that actually
provides Live APIs; the current `openai>=1.0.0` declaration proves neither. Check
Vonage routing, caller/destination metadata and public HTTPS reachability.
Prefer direct SIP if TLS/SRTP and project access work. Otherwise choose the audio
bridge after checking codecs and playback/interruption control. Implement only
the selected path, initially through a small engine-side smoke entry point.

Use a test number and isolated profile. Authenticate provider events, deduplicate
call acceptance, admit one call and refuse another while it is active. Establish
bidirectional audio, receive transcripts and one client delegation, return a
fixed test fact, and observe hangup/closure. No company memory is needed yet.
Set a duration watchdog before the first paid call; on a broken control connection
attempt provider hangup and record any uncertain closure rather than reconnecting.

**Inputs before live testing.** Record the chosen test number, reachable endpoint,
OpenAI project access, secret references, the test profile's explicitly selected
engine provider/payment mode, and current carrier/voice rates. Verify that mode's
headless credential source; do not change providers or enable fallback implicitly. Proposed
test limits are 180 seconds per call, at most six calls and USD5 total across
voice, carrier and engine; lower call count/duration if current prices require it.
Reserve a conservative per-call estimate within that allowance before admission;
retain allowance for uncertain usage and perform no automatic paid retries.
Use the existing engine budget for reasoning. These limits are for a supervised
test run, not a new production billing product. Resource availability is checked
at execution; do not infer credentials or permission to alter a production number.

**Done.** A real test call carries intelligible audio in both directions, a Python
client receives delegation and delivers the test result, and hangup or the
watchdog closes the call. In that same call, speak while the assistant responds
and while the fixed result is deliberately delayed, to check duplex early.
Save transport choice, SDK version, sanitized event
shapes and measured cost. If project access or both transport paths fail, report
the specific blocker; do not substitute Realtime or change carrier silently.

**Rollback.** Stop the smoke process and remove only its test-number routing.
Keep existing StarChat calling and production daemons untouched.

## M2 — Operator configuration and caller memory

**Work.** Persist a small configuration in the profile SQLite database, default
disabled: called-number binding, instructions, enabled read-only tools, test
limits and the selected caller facts. Bind it to the running Firebase UID/company;
configuration cannot change company membership or write MEMORY_KEY. Secrets stay
in server-side credential configuration, never in the returned settings.

Add proposed `voice.config.get`, `voice.config.update` and `voice.status` RPCs.
Reuse authenticated RPC access from the operator workspace. Verify the actual
cs-kernel client can invoke them; if it lacks a generic RPC path, deliver the
small client command in that repository under its own instructions as part of
this milestone. An undocumented hand-written HTTP call does not satisfy the
cs-operator configuration requirement. Snapshot configuration at call start.

Create a controlled company-memory fixture: two customers, a shared/ambiguous
number, facts about earlier requests and an internal note. Explicitly configure
which existing sentence IDs may be returned for each matched customer. Validate
company and customer association before returning their text; missing or replaced
IDs return no fact. The fixture remains frozen during the test run. Initial
recognition and follow-up search both use this restriction; do not pass a full
blob to either model and ask it to hide the private part. Unknown/ambiguous
callers receive no customer-specific context. This is a prototype fixture
selection, not a new general permission model or identity-verification service.

Run synchronous lookup/ranking work off the audio event loop, with a timeout.
Reuse real storage and identifier matching; search within the permitted facts
for follow-ups. Return facts, source references, missing information and errors
through ordinary `ToolResult` data, without adding a new skill runtime.

**Done.** Tests against temporary profile/company databases cover normalized,
unknown and ambiguous numbers, a follow-up question, and exclusion of internal
notes/other customers before model input. A real authenticated client can read
and change configuration; wrong-profile access fails and secrets are absent.

**Rollback.** Disable voice and restore its configuration. New profile tables are
additive; do not modify company memory or existing chat behavior.

## M3 — Join the conversation to the engine

Do not begin M3 until M2's independent integration review passes and the operator
gives a new go-ahead. M2 evidence is recorded below.

**Work.** Integrate the selected transport as an opt-in listener in the isolated
engine daemon (`cli/main.py` / `rpc/server_ws.py` lifecycle). Share its bound
profile and configuration, while keeping provider and operator routes separate.
Warm the engine client and memory dependencies before admitting calls.
For personal-key mode, verify the saved key works without an operator session.
For MrCall credits, reuse `auth/refresh.py:ensure_fresh_session` off the event
loop before creating a call's engine client, including after expiry. This must
work with automatic preparation disabled; never depend on a prior configuration
RPC connection to leave a usable token. Failed credential preparation makes the
voice service unavailable rather than accepting a call it cannot serve. Firebase
ID tokens remain memory-only, using the existing refresh-token storage path.

Give each call its own customer-service agent, transcript and pending task.
Inject only the voice instructions and allowed memory tools, without the owner's
persona, slash-command router or general tool factory. Keep the normal engine
provider/model and budget admission. Start caller lookup alongside the greeting;
return late permitted context quietly and useful answers for speech.

Use one backend request at a time. Accumulate transcript fragments and start work
on delegation, not on every fragment. Mark each run with its input revision;
coalesce new input while it runs, then ask the engine to reconcile it with the
result before delivery. A correction to already spoken information gets a clear
rectification. Do not restart every lookup or claim interruption cancels work.

On hangup/timeout close the session, cancel pending async work and suppress late
results; a running blocking read or dispatched LLM request may still finish in
its worker but cannot speak or start more work. Account for that dispatched
request even after hangup, and record incomplete usage conservatively. The read-only prototype
needs no operation replay or rollback machinery.

**Done.** Deterministic event tests cover greeting before delayed lookup, late
caller context, follow-up delegation, correction during a lookup, results after
hangup and a second call without the first call's history. They exercise the real
agent/tool boundary with mocked paid transports. A focused regression confirms
owner chat still has its prior prompt, tools and context. Listen to one integrated
live call within the shared test allowance; unit tests alone do not certify duplex.
If the chosen mode is MrCall credits, deterministically test missing/expired
in-memory sessions and refresh failure with automatic preparation disabled.

**Rollback.** Disable the listener; ordinary engine RPC/chat remain available.
Restore prior engine code if the focused regression fails.

## M4 — Verify the complete customer experience

Use a short call script with the controlled history: known customer and follow-up;
unknown/ambiguous caller; correction during delayed lookup; correction during
speech; failed lookup and forced closure. Combine scenarios within the remaining
call allowance rather than requiring a separate paid call for each assertion.
After configuring, stop the operator, disconnect its client and restart the
daemon. Make an incoming call without opening Desktop, cs-operator or another
configuration client; it must perform real engine reasoning in the recorded
payment mode. Keep automatic preparation disabled and the fixture frozen.
Also change configuration between calls and confirm that new instructions apply
only to the next call.

Listen to entire exchanges, not just final transcripts. The five brief criteria
must pass, including absence of internal/other-customer facts and explicit
rectification of stale speech. With lookup artificially delayed five seconds,
the greeting must start before lookup completion; after a correction, the next
substantive answer must address it or ask the necessary clarification. Record
actual first-audio and useful-answer latency rather than inventing a production
SLO. Save sanitized observations and usage; no raw audio retention by default.

A separate final review checks evidence against the brief and the actual operator
configuration path. Document setup, selected transport, teardown and limitations
in an engine voice-channel guide; update IPC and living context only for behavior
actually delivered. Mark this plan completed only after real-call acceptance;
missing access or a failed live scenario remains explicit unfinished work.

## Verification and review record

### M3 — 2026-09-24

**Integrated GPT-6 telephone retest — 2026-09-24 12:05 UTC:** the caller reports
that interruption happens at the right time. The agent correctly said it had no
tracking number, was interrupted, then repeated that answer; the caller judged
the exchange acceptable. The repetition is an observed quality limitation, not
proof of flawless correction handling. Audible delivery of the blue-filter and
Thursday facts is not explicitly confirmed by the caller; transcript/audio is not retained. Retrieval is verified,
but no claim is made that both facts were spoken. This distinction remains in
the evidence rather than being inferred from the caller's overall acceptance.

**Final independent M3 integration review: APPROVED.** The fresh reviewer
inspected the integrated boundaries and independently passed **43 focused tests**
covering follow-up delegation, correction during backend work, late-result
suppression, settlement after hangup, owner-context exclusion, fresh histories,
configuration snapshots, direct GPT-6 conversion and autonomous preparation.
The reviewer accepted this integrated call against M3's Done criteria, preserving
the limits above. M3 is complete; no M4 scenario or production readiness is
certified. The plan remains active because M4 is unstarted.

The isolated ledger confirms configuration revision 1, `gpt-6-sol` over
`openai_voice`, caller `matched`, exactly two selected facts and 145 ms caller
lookup. One client delegation ran one backend agent turn and delivered one
result; two paid Responses requests (tool request plus result response) settled
at USD0.004054. No backend failure or reconciliation event was recorded. This
phone call therefore does not by itself prove a multi-delegation follow-up or
correction-during-backend-work scenario. Deterministic tests cover those event
sequences; real backend-only demonstrations cover sequential follow-up/correction
content. The M4 scenario matrix remains unstarted.

Voice finalization is confirmed by `session.closed`: 48 reported seconds,
USD0.040 estimated voice cost, reflected first audio 3,337 ms (not handset
latency), 53,754 ms observed adapter lifetime. `sideband_eof` is the closure
trigger after confirmed finalization, not an unresolved call. Read-only Vonage
receipts confirm inbound 49 seconds and SIP bridge 50 seconds, both completed
12:05:41–12:06:30/31 UTC. Their prices are 0.00367500 + 0.00350000 = 0.00717500
account-currency units; the API omits currency, so no new cross-currency settled
invoice is claimed. Voice plus backend is USD0.044054 excluding carrier.

All three voice ledger rows are closed, with USD3 retained call reservations;
the original two rows and USD0.110 historical MrCall holds remain untouched.
All 17 direct GPT-6 requests (diagnostics plus phone) are settled, total estimated
USD0.030836, with no new unresolved OpenAI holds. Both services are still active
with infinite runtime, unchanged PIDs since activation and post-call health
available. No operator RPC was needed for admission, memory, reasoning or closure.

**Direct GPT-6 correction (latest):** dedicated-key model discovery returns all
three GPT-6 variants and `gpt-live-1`. Replaced the unactivated GPT-4.1 draft with
GPT-6 Sol Responses/function calling; standard-tier prices, cache writes/reads
and long-context rates are explicitly accounted. No old-model inference occurred.
The adapter's 22 new tests pass. Also removed inherited generic-agent local
prompt/tool-result/ten-round ceilings solely for isolated unlimited voice calls.
The broad regression initially returned 414 passed, four failed and one skipped;
the failures exposed missing default initialization in legacy agent fixtures.
Fixed the compatible class default; the final affected selection passed all 40
cases (agent regressions, 22 adapter, seven runtime and real kernel CLI).
Final full regression on the corrected code: **423 passed, 1 skipped**; the skip
is the existing optional K3 credit-contract module because this voice environment
has no FastAPI. Actual kernel CLI coverage passed. Engine Ruff, changed voice
formatting and `git diff --check` pass. The mechanical docs gate is clean;
independent doc-critic verified 28 claim groups with zero stale findings after
repairs, while explicitly leaving provider/audio/runtime evidence to the parent
session rather than claiming to repeat it.
Independent activation review is APPROVED. Its missing-cache-breakdown finding
is fixed and tested: absent/partial usage retains the hold. The final strict-parser
real tool roundtrip passed at USD0.003166, bringing all diagnostics to USD0.026782.

The isolated profile explicitly saves `VOICE_ENGINE_PROVIDER=openai`, with the
dedicated key/project; original `LLM_PROVIDER` is retained only for smoke-policy
identity. Only the smoke-named service restarted. Cold-start health is available,
RPC port 8788 has no client connections, both services remain at infinite runtime,
tunnel PID/URL are unchanged, and the original voice ledger is byte-for-byte
identical at the row level before the integrated retest recorded above.

Real backend demonstration: recognized exactly two selected facts, executed tool
calls and settled usage through the original isolated engine ledger. The first
run exposed Italian-query/English-fixture lexical mismatch; the tool contract now
explains empty-query retrieval before claiming absence. The repeat passed blue
replacement filters, prior-email Thursday delivery, a follow-up and correction to
the absent tracking number. Four memory calls, seven model dispatches, estimated
USD0.013720 for the successful repeat; the initial diagnostic cost USD0.009896.
Prior MrCall USD0.110 liabilities remain; no ledger reset occurred. These
diagnostics preceded the integrated telephone retest recorded above.


**Latest operator instruction — supersedes earlier test caps:** remove all local
experiment limits. Unlimited incoming attempts, call duration and local engine/test
spending are authorized in this isolated profile. Do not request another approval
for a third call or test cost. Keep the accounting history and technical isolation;
this does not create external MrCall credit or authorize production changes. M4
remains excluded. The explicit saved `VOICE_ENGINE_UNLIMITED=1` mode removes local
attempt, spend, duration, transcript and delegation ceilings while retaining all
ledger history and receipts. Ordinary profiles remain bounded. Omitting the local
carrier duration still leaves Vonage's provider maximum/default of 7,200 seconds.

- Initial authorization (numeric limits superseded above): only M3, including deterministic verification, integrated
  demonstration and independent review. Preserve the existing ledger, limits and
  unlimited service/tunnel lifetime. Use isolated synthetic memory only.
- Baseline: clean branch `gpt-live-m1`, accepted M2 `c6c1fcf`; whole-engine Ruff
  passes. M4 remains unstarted.
- **Operator spending authorization (2026-09-24):** testing costs are authorized.
  Do not repeatedly ask for cost/budget confirmation or treat the inherited M1
  zero-engine budget as a product blocker. Configure the isolated test engine's
  allowance to perform M3 reasoning, keeping durable reservations and accounting.
  Initially use USD3 engine allowance within the former USD5 combined experiment
  ceiling (USD2 retained voice/carrier holds). Do not reset the existing ledger,
  alter production budgets, or add automatic service/tunnel expiry.

- Implemented the opt-in provider listener in the engine WebSocket lifecycle;
  explicit-path bootstrap uses only the isolated fixture, no ordinary profile
  activation or automatic channels. Carrier callbacks prepare credentials before
  reservation/NCCO and bind caller metadata to the one-use nonce in memory.
- Each call owns a customer-service agent, selected-memory tool, transcript and
  serialized delegation worker. Revision changes reconcile pending drafts against
  the latest input before speech. Late caller context is quiet. Ordinary owner
  prompt/tools/context stay on their original path. Hangup prevents further agent
  work while dispatched LLM threads retain normal accounting/settlement.
- Independent local activation review: **APPROVED** after suppressing inherited
  DEBUG fact logging and correcting runtime availability after exhaustion/busy
  callbacks. Reviewer independently passed 126 voice cases (125 plus the actual
  kernel CLI case separately), then the 20 M3 cases after fixes. This does not
  yet approve the integrated live call or M4.
- Isolated provisioning and cold start: **PASSED**, real Firebase credentials.
  Frozen synthetic M2 facts only, company capability persisted through
  `memory.join`, freshly minted refresh token encrypted in the isolated OAuth
  table. ID tokens were never persisted. Caller binding comes from the completed
  authorized M1 carrier receipt, not the personal profile. Saved engine allowance
  is USD3 under the operator's explicit test-spending authorization.
- Initial activation, before the M3 call: the dedicated service started
  `scripts/voice_engine_isolated.py` on provider port 8787 and owner-authenticated
  RPC port 8788. Service and unchanged tunnel were active with
  `RuntimeMaxUSec=infinity`. Local/public `/healthz` returned `engine_listener` /
  `calls_available: true` after a fresh process start, before any operator RPC
  connection. At that point, only the original closed M1 row and USD1 hold existed.
- First integrated incoming-call demonstration: **FAILED**. The operator heard
  no knowledge of the filters/order. The session nevertheless closed cleanly:
  65 reported voice seconds, 4 client delegations, 4 backend turn attempts and
  zero successful results. No engine LLM reservation was created by that call.
  Reflected first audio was 3,553 ms; caller lookup completed in 9 ms. No raw
  transcript/audio was retained. Estimated voice cost: USD0.054167. Read-only
  Vonage receipts show two completed 66-second legs, 10:34:02–10:35:08 UTC,
  priced 0.00495000 and 0.00462000 account currency units. Currency is omitted;
  using the same M1 EUR inference/reference gives approximately USD0.0651 combined,
  not a settled invoice.
- Root causes reproduced independently of audio: Vonage's signed `from` uses
  international digits without `+`, while the fixture index uses E.164; lookup
  returned unknown. Also, real bounded quotations returned HTTP400
  `business_id_required`: this Firebase account sees two businesses and the
  engine client did not forward the server's supported explicit selection.
- Repairs: canonicalize the signed carrier representation before lookup; test
  actual matched recognition and two facts with a digits-only callback. Forward
  the saved `SMS_BUSINESS_ID` on quote and execute, verify quoted business and
  include the setting in client policy fingerprints. A free validated quotation
  now checks account/business/model readiness before carrier admission. Error
  evidence retains safe exception type and lookup outcome/count, not content.
- Independent repair review: **APPROVED locally**, 23 focused tests passed.
  Explicit billing selection in the isolated profile is the owner's named
  `Demo Convesazione Smart Dati Clienti` business; no server/business variables
  or production settings were changed. Both visible businesses were checked
  read-only and have **zero CALLCREDIT**. A real corrected diagnostic passed
  Firebase refresh, quotation and recognition (two permitted facts), then the
  server refused execution with **HTTP402 insufficient credits**. Its durable
  USD0.055 engine hold remains; do not refund/reset it manually.
- Final post-repair verification: **214 passed** (129 voice, including actual cs
  CLI authentication, plus 85 adjacent chat/prompt/tool/budget/OpenRouter cases).
  Whole-engine Ruff and changed voice-file formatting pass; the mechanical docs
  gate is clean. No whole-engine test/format cleanup was attempted.
- Final independent review: **APPROVED for the local repaired implementation**;
  complete M3 is **NOT APPROVED**, because integrated live acceptance has not passed.
  The reviewer checked the final code/tests and truthful documentation boundaries.
- Live M3 remains incomplete. The original two voice attempts are both closed,
  with USD2 retained. The latest instruction above supersedes the two-attempt
  admission ceiling and numeric spending ceilings. A repeat needs a funded MrCall
  business; further cost/attempt approval is not required. Do not switch billing
  provider, create production credits, reset the ledger, or call this M3 accepted.
  Services remain without automatic expiry. M4 is unstarted.
- Isolated unlimited mode is now active after **207 passing voice/LLM tests**
  and independent activation approval (**7 focused tests**). The original
  unreadable-budget error contract and ordinary-profile ceilings are preserved.
  Ambient-only flags, incorrect markers and populated profiles cannot enable it.
  Restart preserved the original ledger contents exactly. Local `/healthz`
  reports `calls_available: true`, `test_limits: "unlimited"`; both services
  remain active with `RuntimeMaxUSec=infinity`. No extra call was placed.
  Engine-package and changed voice/script Ruff checks, voice formatting and
  the mechanical documentation gate pass. A broader Ruff scan including legacy
  scripts/evaluation tests reports 11 unrelated existing findings; they were
  left untouched.
- The operator subsequently reported payment. Read-only checks at 11:12 UTC
  still return zero CALLCREDIT for the selected Demo business (including a check
  without category exclusions); its subscription status is FREE. The other
  visible business also returned zero. A single real engine diagnostic recognized
  both permitted facts but returned `BudgetError` before delivering a result.
  Retained engine reservations now total USD0.110; no rows were reset/refunded.
  Payment application is not yet confirmed by the API. No new telephone call was
  placed; the isolated listener remains available without local test ceilings.

### M2 — 2026-09-24

- Implemented only configuration and selected-fact retrieval. Additive profile
  table and `voice.config.get/update`, `voice.status` reuse RPC/auth. Owner/company
  binding, revision checks and immutable snapshots prevent silent retargeting or
  changing existing snapshots. Settings/tool output exclude server secrets.
- Existing cs-kernel provides `cs rpc`; no kernel edits were needed. The actual
  installed CLI reads/updates through the engine WebSocket. Status explicitly
  reports that M2 is not integrated into the telephone runtime.
- Temporary split SQLite fixture: two customers, shared number, prior request and
  delivery facts, internal note, foreign-company rows. Existing normalization and
  identifier lookup are reused. Only selected sentence columns enter `ToolResult`;
  text/creation fingerprints reject replacements. Follow-up ranking is restricted
  to permitted facts. Reads run off-loop with a timeout. No model/embedding call.
- Final verification: **106 voice tests passed** (68 M1 plus 38 M2), including
  actual cs CLI/WebSocket/dispatcher and RS256 with a synthetic signing key.
  Adjacent regression results and independent review follow below.
- Live M2 demonstration: **PASSED**, actual cs CLI and real Firebase RS256 owner
  authentication against disposable synthetic databases. Read/update reaches
  revision 2; invalid token and wrong profile fail; old snapshots retain their
  instructions; retrieval after client exit returns only the approved delivery
  fact. Kernel headless mint/exchange uses anonymous pipes/in-memory token supply,
  never its disk ID-token cache. No personal profile, paid call/model, carrier
  route change, service restart or ledger reset. Repeatable command and limits:
  [M2 guide](../../engine/docs/features/voice-agent-configuration.md).
- Smoke/tunnel remain active with `RuntimeMaxUSec=infinity`. M1's saved limits,
  attempt allowance and ledger are untouched. M2 does not alter smoke admission.
- Pre-change verification: 136 identifier/memory/chat/budget tests passed;
  whole-engine Ruff passed. Whole-engine Black has 42 pre-existing failures.
  No unrelated formatting repair is included.
- Adjacent post-change verification: **152 passed**, one pre-existing RPC
  contract test fails because `llm.models` has no parseable parameter signature.
  Its handler, signature parser and test are byte-identical to accepted HEAD.
  All three new voice RPC signatures are checked by the dispatcher. Whole-engine
  Ruff and changed-file formatting checks pass (the pre-existing methods-module
  formatting is preserved).
- Independent M2 integration review: **APPROVED**, 2026-09-24. The fresh reviewer
  independently ran the 105-test voice suite and the final 18-test caller-memory
  suite, checked the actual kernel/authentication path, SQL permission boundary,
  snapshots, cancellation and sanitized errors. No blocking findings remain.
  The reviewer did not repeat real authentication or paid calls. M3 is unstarted
  and this review does not authorize it.
- Review correction: the final binding revalidation now shares the complete
  lookup timeout. A slow final database read yields a safe timeout with no facts,
  rather than delaying the tool after its original deadline. The focused memory
  suite passes all 18 tests; the reviewer's separate 20 ms deadline probe also
  confirms bounded completion. The stale proposed-handler reference was corrected.

### Earlier milestone evidence

Before code changes, run engine lint and the focused existing identifier, memory,
chat and budget tests; record pre-existing failures without expanding this task
into unrelated cleanup. New voice tests use real temporary SQLite and mocked
network/model boundaries. Run changed-file lint and adjacent regression tests per
milestone; do not repeat the whole engine suite without evidence it is needed.
Run the documentation gate when contracts/docs change. Preserve unrelated work
already present in the working tree and keep the conversation transcript out of
commits unless explicitly requested.

- Brief review: APPROVED, including the two minimal adversarial corrections.
- Plan review: APPROVED on 2026-09-23 by a reviewer independent of the brief
  review. Checked milestone dependencies, code reuse, scope, acceptance and
  rollback; no revisions required before M1.
- Additional adversarial plan review: REVISE on 2026-09-23. Found that stopping
  the operator during a call could hide a dependency on its cached Firebase
  session. Added cold-start acceptance and explicit headless credential handling;
  also clarified post-hangup LLM accounting and added duplex to the M1 smoke.
  Re-review: APPROVED after those changes; no further requirements.
- First M1 prototype (`b9d4075`): its initial APPROVED verdict is **withdrawn**.
  The subsequent review reproduced critical failures despite seven passing
  tests: DEBUG logging exposed the fake authorization key; lost accept responses
  left no hold/watchdog; sideband EOF skipped hangup; restarts reset budgets;
  delayed delegation blocked event reads; the test marker was only ambient.
  Neither the prototype nor that review is evidence of readiness for live use.
- M1 rewrite: CLI runner, profile-file validation, durable SQLite ledger and
  asynchronous call lifecycle replace the first implementation. Admission
  reserves before dispatch and deduplicates sessions across restarts. An
  uncertain accept is never automatically retried. Failed/uncertain hangup
  blocks new calls; all reservations persist. A private WebSocket logger
  suppresses headers/frames. The reader runs during delayed delegation and
  finalization. The optional `voice-smoke` extra isolates SDK 3.19.0 and aiohttp
  from the normal engine. See the [smoke guide](../../engine/docs/features/gpt-live-smoke.md).
- Rewrite verification: **39 local tests passed**, using real temporary SQLite, real SDK webhook
  verification with synthetic signatures, a real localhost WebSocket handshake,
  and mocked paid control operations. They cover lost accept responses, EOF,
  restart limits, caller-route mismatch, transcript/hangup during delayed work,
  ledger-write failures, explicit CLI profile selection/lock cleanup and shutdown
  during accept/attach/hangup/socket closure, including repeated shutdown.
  No provider calls. The documentation mechanical gate is clean.
- Adjacent regressions: **136 passed** for identifier, memory-spend, chat reuse
  and budget dispatch/ledger tests, using the existing complete engine venv.
  The earlier `numpy` blocker concerned the shell's unrelated Python environment,
  not an engine failure. Voice tests override only the obsolete Supabase cleanup
  fixture locally, matching other engine test directories; `--noconftest` is
  no longer needed. Repository-wide Black still has pre-existing unrelated
  formatting failures; changed-file Black/Ruff checks pass.
- Rewrite integration review: initial **REVISE** found cleanup could be skipped
  by a ledger error and shutdown did not interrupt accept/attach. A second
  **REVISE** found shutdown could cancel cleanup already in progress. All three
  paths have focused regression scenarios; cleanup is no longer interruptible
  by repeated shutdown. Final re-review: **APPROVED for the local M1 rewrite
  only**, 2026-09-23. The reviewer independently ran all 39 voice tests and an
  aiohttp subprocess with actual SIGTERM and mocked provider transport: exit 0,
  one hangup, final usage retained, ledger closed, no remaining tasks. No blocking
  local findings remain; this verdict does not approve live acceptance or M2.
- Carrier follow-through integration review: **REVISE** found the first adapter
  could emit repeated connection NCCOs without a hold when OpenAI ingress was
  absent, and could configure an incompatible OpenAI `To` route. Fixed with
  transactional pre-NCCO reservation, carrier UUID deduplication, a one-use nonce
  (only its hash is retained), atomic binding to the original hold, and compatible
  route validation with narrow secure-parameter normalization. Missing ingress
  blocks further attempts across restart. A second **REVISE** found binding
  could proceed after a different session's rejection became uncertain; binding
  now checks other unresolved rows in the same transaction. The reservation also
  includes the 15-second carrier ringing timeout before billing rounding.
  Local verification: **65 voice tests
  passed**, including NCCO through real SDK-signed OpenAI ingress without double
  reservation, nonce replay/refusal, uncertain-rejection interleaving and
  missing-ingress recovery. Black/Ruff pass.
  Final re-review: **APPROVED for local carrier integration only**, 2026-09-23;
  reviewer independently ran all 65 voice tests and found no remaining blocking
  local findings. The mechanical documentation gate is clean (existing size/date
  advisories unchanged). The adapter was not yet active at that review;
  this verdict does not approve live acceptance or M2.
- Isolated-launch review: **APPROVED for the local launch delta**, 2026-09-23.
  The explicit-path bootstrap refuses populated profiles and symlink locks,
  holds the test lock through cleanup, and never activates a normal profile.
  The reviewer independently ran all **68 voice tests**, with no blocking local
  findings. This does not certify provider interoperability or M2.
- M1 live demonstration: **PASSED on 2026-09-24** with the isolated runner,
  OpenAI SDK **3.19.0**, and direct Vonage SIP → GPT-Live → Python sideband.
  The caller confirmed intelligible conversation, interruption during assistant
  speech, and continued speech during the five-second fixed-result delay.
  No cs-operator process conducts this call. The durable ledger has one funded
  call, closed with confirmed `session.closed`, and no unresolved sessions.
  Sanitized event counts: `session.started=1`, `session.input_audio.append=249`,
  `session.output_audio.delta=243`, `session.input_transcript.delta=15`,
  `session.output_transcript.delta=68`, `session.delegation.created=1`,
  `session.closed=1`; Python sent one fixed result. No explicit hangup was needed
  after finalization: `hangup_confirmed=false` is expected here; the default
  `closure_trigger=sideband_eof` is not evidence of an unclosed session.
  Reflected first-audio timing was 4,248 ms, not measured handset latency.
  No raw audio or transcript text is retained. The live watchdog fault scenario
  was not exercised; its failure paths remain locally tested.
- Measured usage: OpenAI finalization reported **49 voice seconds**, yielding
  **USD0.040834 estimated voice cost** at the recorded rate; engine cost is zero.
  Read-only regional Vonage Voice API receipts for the same conversation show
  exactly two completed legs, both **50 seconds**, 09:21:26–09:22:16 UTC:
  inbound phone rate `0.00450000`, price `0.00375000`; NCCO SIP leg rate
  `0.00420000`, price `0.00350000`. Total carrier price is `0.00725000` account
  currency units. The API omits currency; EUR is inferred from the operator's
  matching account rate, not independently supplied in the receipts. At the
  recorded ECB reference, combined cost is approximately **USD0.0491**, not a
  settled cross-provider invoice. The SIP leg's API direction `outbound` is the
  incoming call's bridge, not an outbound-calling feature. Receipts were fetched
  without originating another call. One of the two existing attempts remains;
  all holds and the ledger are preserved.
- Final M1 live integration review: **APPROVED on 2026-09-24**. The independent
  reviewer reran all 68 voice tests and checked the implementation and live
  acceptance evidence; no blocking findings remain. M1 is complete. M2 is the
  next milestone, not implemented; this approval does not certify M2, M4 or
  production readiness.

## Isolated provisioning record — 2026-09-23

- OpenAI credential reference: `/home/mal/.config/mrcall/gpt-live-test.env`
  (mode 600, outside Git). Read-only models request returned 200 and included
  `gpt-live-1`. [Published GPT-Live price](https://developers.openai.com/api/docs/models/gpt-live-1)
  checked at USD0.05/minute, per-second billing; carrier rates are recorded below.
- User explicitly authorized number `+390289047081`. Read-only checks found its
  test service-number row unassigned and no matching production row. Created
  Vonage app `GPT-Live M1 isolated test`, ID
  `38a9213c-296d-464d-9f94-77b53134a924`, Voice/eu-west, signed callbacks on,
  AI data improvement off. Linked only that number and verified the resulting
  mapping. The existing shared test and production applications were not edited.
- Dedicated app private-key reference:
  `/home/mal/.config/mrcall/gpt-live-vonage.key` (mode 600, outside Git).
- The operator supplied `VONAGE_SIGNATURE_SECRET` in the same private test env
  file; presence and mode 600 were verified without printing the value. Local
  synthetic signature/tampering checks with that configured secret pass; this
  does not verify an actual Vonage-originated callback.
- The operator subsequently selected their personal Firebase identity and
  explicitly chose `mrcall`. Email/UID and enabled status were verified against
  Firebase; both matching business records returned `FREE`. No business binding,
  account billing settings or existing profile was modified. A fresh headless
  sign-in using the documented operator service-account/Web-API-key references
  succeeded; cryptographic ID-token verification matched the chosen UID, and
  read-only MrCall bounded capabilities returned 200 with the expected protocol.
  No ID or refresh token was persisted, and no inference/debit was requested.
- Private operational note: `/home/mal/.config/mrcall/gpt-live-m1/PREFLIGHT.md`.
  The UID-keyed configuration is under that directory's `profiles/`,
  outside the normal profile root, with no customer DB/mail/memory or copied
  tokens. Engine billing is explicitly MrCall, engine daily budget zero,
  readiness was initially zero and is now one for the supervised experiment.
  Initial limits are two 120-second calls, with exclusive test-profile locking.
  Do not run the normal CLI
  against the selected UID and inadvertently load the existing populated profile.
  The MrCall `FREE` plan is not a waiver of separate OpenAI/carrier charges.
- Carrier rate discovery: the documented [Pricing API v1](https://developer.vonage.com/en/api/pricing)
  and [v2](https://developer.vonage.com/en/api/pricing.v2) expose outbound pricing,
  not a verified quote for this Italian inbound number plus the NCCO SIP leg.
  [Account-specific pricing](https://developer.vonage.com/en/dashboard/control/pricing)
  is exported from Dashboard → Billing → Pricing. The operator supplied
  `Voice Inbound / IT / LVN / 0s/1s / EUR / 0.00450` and confirmed no discounts.
- Rate basis: inbound EUR0.00450/minute from the operator; standard
  [Vonage SIP listing](https://www.vonage.com/communications-apis/voice/pricing/)
  USD0.00492/minute. [Vonage billing guidance](https://api.support.vonage.com/hc/en-us/articles/204015203-How-does-voice-pricing-work-for-inbound-and-outbound-calls)
  confirms second-based charging and no ringing/connection charge.
  [ECB 2026-09-23](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
  quotes EUR1 = USD1.1411; reservation uses a padded 1.25 conversion and rounds
  the combined carrier allowance up to USD0.02/minute. This is not the account's
  settlement exchange rate. Setup allowance is zero under the published rule;
  no number was purchased.
- Actual limits: two 120-second attempts, USD1 hold each, no refund or paid retry.
  The calculated minimum is USD0.21 per attempt (three rounded minutes including
  ringing/cleanup at USD0.07 combined/minute). Maximum admitted holds USD2 leave
  USD3 within the original ceiling for carrier variance/refused-call uncertainty.
  The first-call receipts and remaining settlement uncertainty are recorded above.
- Temporary public base:
  `https://briefing-lab-care-delicious.trycloudflare.com`. No production DNS,
  Caddy, firewall or daemon configuration was changed. User-level transient
  services `mrcall-gpt-live-tunnel` and `mrcall-gpt-live-preflight` have a
  24-hour maximum runtime, started around 21:10–21:13 UTC. Cloudflared 2026.9.1
  ARM64 was checked against the release SHA-256 before execution.
- OpenAI webhook `whe_6ab4409d166c81908de19b21fa244a2b`, subscribed only to
  `live.transport.incoming`, points at `/openai/live`. Its signing secret was
  saved directly in the private env file, never printed. The provider's sample
  delivery returned 200 through HTTPS and real SDK signature verification;
  an unsigned request returned 400. This is a webhook test, not a call.
- The initial temporary receiver was
  `/tmp/mrcall-gpt-live-preflight-rynivv/receiver.py`, on loopback 8787. It verifies
  and acknowledges OpenAI events but **cannot accept a call**. `/vonage/answer`
  returns 503; `/vonage/event` discards all data with 204. It stores no callback
  bodies, call state or usage. `/healthz` reports `calls_enabled: false`.
  Its service was stopped when the reviewed runner was activated.
- Activated user service `mrcall-gpt-live-smoke` at **22:07:58 UTC**, with
  `RuntimeMaxSec=1800`, no restart, and `TimeoutStopSec=30`, using
  `engine/scripts/voice_smoke_isolated.py` and the explicit private UID directory.
  The existing tunnel still forwards only loopback 8787. Automatic test-window
  expiry is approximately **22:37:58 UTC**.
- The first window expired cleanly without calls. At the operator's request,
  the same service restarted **2026-09-24 09:20:29 UTC**, preserving its ledger
  and limits. The operator subsequently removed the wall-clock test window:
  both smoke and tunnel now have `RuntimeMaxSec=infinity`, verified active
  without restarting either service or changing the tunnel URL. Runtime-only
  `no-window.conf` drop-ins live under `/run/user/1001/systemd/user/` for these
  two units; these transient services are not a reboot-persistent deployment.
  Per-call duration, attempt allowance and ledger remain unchanged. The authorized
  number remains linked to the dedicated app. Do not reintroduce an arbitrary
  service-expiry window; stop the test services explicitly when teardown is wanted.
- Public activation checks: unsigned OpenAI POST 400, unsigned Vonage answer
  POST 401, locally signed synthetic Vonage event POST 204. The last check proves
  verification wiring, not a real Vonage signature. Exclusive lock contention was
  confirmed; the new smoke ledger had zero rows/holds. No outbound call was placed.
- Teardown: stop only the smoke/preflight/tunnel test services; remove the dedicated OpenAI
  webhook and unlink the authorized number from the dedicated Vonage app after
  confirming no call is active. Do not restore production routing or delete the
  number. Keep credentials private and retain any future paid-call ledger.
  Restarting the temporary tunnel changes its URL; update only this test app's
  webhook URLs and the dedicated OpenAI webhook before further testing.

API basis: [OpenAI telephony](https://developers.openai.com/api/docs/guides/voice-sip)
and [client delegation](https://developers.openai.com/api/docs/guides/live-delegation),
checked 2026-09-23. Provider-specific compatibility is deliberately M1's experiment.
