---
status: blocked
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
No implementation or live call has run under this plan.

## Delivery shape

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
- New implementation belongs in a small `engine/zylch/services/voice/` package
  and a `rpc/voice_actions.py` handler module, with focused tests under
  `engine/tests/voice/`. These are proposed paths, not existing capabilities.
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
- M1 local implementation (2026-09-23): `zylch voice-smoke` is an opt-in,
  test-profile-only signed OpenAI webhook listener. It uses the direct GPT-Live
  SIP + sideband shape, admits one call, retries a failed accept only on a
  repeated signed delivery, deduplicates successful delivery, refuses a second
  call, applies a 180-second watchdog, attempts hangup after a broken control
  connection or process shutdown, and returns one fixed non-customer fact on
  client delegation with a unique event ID. It requires an explicit selected
  profile whose `VOICE_SMOKE_TEST_PROFILE` exactly names that profile, and a
  conservative per-call reservation which cannot exceed USD5 over six calls.
  It is not started by the normal daemon, has no outbound path, does not read
  Vonage credentials, and changes no routing. Sanitized event shapes retain
  only event type and whether final usage was present. Offline controller tests
  pass (7); the SDK wheel check confirms `openai==3.19.0` contains the
  Live connection/types required by the implementation. The dependency now
  requires that version or newer.
- M1 live demonstration: **blocked**. This host has no `OPENAI_API_KEY` or
  `OPENAI_WEBHOOK_SECRET`, no confirmed GPT-Live project/SIP entitlement, no
  isolated Vonage application/private key or test-number routing, and no
  reachable HTTPS webhook endpoint. Existing ambient Vonage API credentials
  were only checked for presence and deliberately not read or used. Therefore
  no call, carrier/voice/engine charge, number change, transcript, event shape
  or usage measurement has occurred. To unblock: provide an isolated profile
  marked `VOICE_SMOKE_TEST_PROFILE=1`, the two OpenAI secret references, a
  public HTTPS route to `/openai/live`, an enabled GPT-Live project, and a
  Vonage test trunk/number confirmed to support TLS/SRTP routing to that
  project. Then pre-reserve within the plan's six-call/180-second/USD5 limit
  before placing the first test call.
- Pre-existing local verification limits (2026-09-23): repository-wide Black
  would reformat 42 unrelated engine files; focused existing memory/chat tests
  cannot collect because this environment lacks `numpy`; even the new test file
  hits the shared `tests/conftest.py` storage fixture, which references removed
  `Settings.supabase_*` fields. The M1 tests pass with that stale fixture
  excluded (`PYTHONPATH=. pytest --noconftest -q tests/voice/test_live_sip_smoke.py`).
- M1 integration review: APPROVED on 2026-09-23 by the fresh M1 reviewer after
  a revision. The review confirmed the GPT-Live (not Realtime) direct-SIP
  contract, safe accept retry/deduplication, event ID, admission/reservation
  limits, shutdown/watchdog closure, explicit isolated-profile gate and
  sanitized evidence. M2 must not begin until the documented live M1 blocker
  is cleared and the real-call demonstration is reviewed.

API basis: [OpenAI telephony](https://developers.openai.com/api/docs/guides/voice-sip)
and [client delegation](https://developers.openai.com/api/docs/guides/live-delegation),
checked 2026-09-23. Provider-specific compatibility is deliberately M1's experiment.
