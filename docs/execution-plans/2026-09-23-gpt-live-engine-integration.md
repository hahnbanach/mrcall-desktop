---
status: active
date: 2026-09-23
---

# GPT-Live: incoming calls backed by company memory

<!-- doc-scope:start -->
Scope: execution plan for the isolated telephone customer-service prototype:
caller recognition, GPT-6 answers, selected-memory/clock tools and autonomous
carrier verification. Owns milestones, evidence and rollback; intent is in the brief.
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
Listening evidence and its limits are recorded below. M4 is now active; this
four-milestone plan stays active.

## Active M4 implementation: GPT-6 answers and incremental tools — 2026-09-24

The amended brief independently returned APPROVED before this plan amendment.
This is within M4, superseding the direct-context voice policy in older entries.
Owner: lead implementation/activation; independent reviewers own each review gate.

1. Extend the explicit voice tool allowlist and immutable configuration with
   `get_current_time`; preserve default memory-only configurations and reject
   unknown/duplicate capabilities. Implement a read-only ZoneInfo clock requiring
   a valid IANA timezone, structured ISO datetime/timezone/UTC offset and private
   argument/result diagnostics. No shell, customer data, writes or new framework.
   Wire both concrete agent tool validation and all Responses conversion paths.
2. Give GPT-6 caller facts plus accumulated transcript; instruct GPT-Live to
   delegate substantive questions and present results without inventing checks.
   Keep immediate one-shot greeting. Stop pushing full memory to quiet voice
   context. Initial lookup still runs independently; the existing bounded read
   returns empty facts and an explicit missing/error result on timeout/failure,
   so GPT-6 can answer without memory. Diagnostic delay is test-only, normally 0.
   Remove voice-only invalidation at final delivery and fragment append; retain
   caller revision, binding and closure guards. Retain the backend no-further-
   response decision for already-completed history, without a mandatory extra run.
3. Verify config/tool permissions (including disabled clock), malformed zones,
   timezone offsets/DST, clock request/result through real Responses translation
   and common ledger, preload/no extra lookup, voice progress (one semantic run),
   caller corrections, chunk interruption and hangup. Preserve normal owner-agent
   tool behavior. Run voice/kernel/budget regression and changed-file lint.
4. Run real GPT-6 backend-only replays with the frozen isolated profile: preloaded
   tracking facts with voice acknowledgement in flight, then fresh Rome time with
   an actual clock-tool result. Record exact traces, serial dispatch counts and
   settled costs. No artificial intent routing; GPT-6 chooses tools. Backend-only
   evidence is not phone acceptance. Obtain independent integration review before
   activation; address failures and re-review.
5. While idle, snapshot all voice ledger rows; update isolated config through
   actual authenticated cs rpc to enable the clock and replace obsolete direct-
   voice instructions (Europe/Rome is an explicit test default). Restart only the
   smoke service; verify cold health before operator reconnect, unchanged ledger,
   unlimited mode, diagnostics, zero delays, tunnel PID and infinite lifetimes.
   Rollback: restore previous source/config while idle with a NEW config revision;
   keep every hold/receipt, do not overwrite live data or restart the tunnel.
6. Offer a short phone retest: tracking, delivery follow-up, current Rome time and
   interruption; inspect correlated text and tool payloads alongside listening.
   Final independent end-to-end review and doc reconciliation must distinguish
   implementation readiness from M4's still-open live matrix. If the caller is
   unavailable, leave the runtime ready and M4 active, without claiming acceptance.

Evidence motivating this correction: call 6 (`call-948ead5eac1b4b5ea09525519eaf267d.db`)
loaded two selected facts in 132 ms. The tracking answer completed in 4.427 s but
was discarded solely because voice said “Certo, controllo subito.”; caller revision
stayed 4. A second run took 4.667 s, then one result was sent/acknowledged. Only the
historical Thursday/blue-filter sentence was transcribed before closure; no proof
that the missing-tracking clause reached the caller. Private report and literal
sequence diagram are retained outside tracked documentation (DUPLEX.md remains
operator-owned/untracked). This demonstrates redundant backend latency, not the
cause of every previous interruption or an instrumented handset measurement.

Implementation verification in progress: the plan gate returned APPROVED. The
voice/kernel/budget regression passes 239 tests; changed-source Ruff passes.
Real backend replay `call-b624cd90150145c0b67a49fd5e654e9f.db` answers tracking in
2.448 seconds with one GPT-6 request despite injected voice progress, then calls
`get_current_time` for Rome and answers from its result (two more serial Responses
requests). The replay explicitly simulates spoken delivery before the follow-up;
it is not telephone audio. An earlier replay omitted that simulated delivery and
therefore repeated the still-undelivered tracking correction; retain its trace
`call-f2d405bb1b1d49c9b9b3a092a7cdc666.db` as evidence of this test limitation.
Independent integration review APPROVED after 51 focused tests. Configuration
4→5 replaced obsolete voice instructions through actual authenticated cs rpc;
the old daemon correctly refused the new clock capability. After smoke-only
restart and cold health readiness, config 5→6 enabled the clock through the same
client. No ID token persisted. Nine previous voice rows hash-match the prestart
snapshot; tunnel PID 1903954 and both infinite lifetimes remain unchanged.
The diagnostic caller extension received separate brief/plan approval and
integration APPROVED after four independently passing lifecycle tests.
Before autonomous calls: 57 settled GPT-6 requests, estimated USD0.137293,
no unresolved OpenAI reservations; two old proxy holds total USD0.110 unchanged.

### Correction-fragment scheduling follow-through

The first autonomous correction trace (`call-ff6c480d2d02447e84a8062bd247815c.db`)
proves stale New York/tracking answers are suppressed and corrected Rome/time/date
answers reach voice. It also exposes seven semantic runs/five invalidations caused
by immediately re-dispatching incomplete caller fragments. Commit 98e5d8d coalesces
only superseded work: it waits for a new delegation at the current caller revision,
or 1.2 seconds of input quiet if no new delegation arrives. Initial dispatch is
unchanged; this is cancellable scheduling, not a conversation/duration/attempt
ceiling or an assertion of a provider turn-complete event. Voice progress does
not affect the wait. Tests cover complete correction dispatch, no-new-delegation fallback and close
cancellation. The identical carrier retest after independent integration review
used four semantic runs/two invalidations rather than seven/five; caller correction
end to first final voice transcript fell from 6.602/7.365 s to 3.303/3.675 s. These
are service-observed receipt times, not instrumented handset audio latency.

The autonomous lookup-failure trace (`call-3f15e1ef4f894d5483ed568542d097b2.db`)
FAILED greeting/voice grounding: the greeting instruction was sent and acknowledged,
but no greeting transcript preceded caller speech. With no facts supplied to voice,
GPT-Live independently claimed to see a filter order before GPT-6's safe unavailable
answer. GPT-6 corrected that claim on the next turn, which is insufficient acceptance.
Shared configuration also made GPT-6 include a late greeting. Commit 98e5d8d puts
role-specific instructions after shared configuration: backend never greets; before
a backend answer voice uses only silence/neutral acknowledgement, no claimed facts,
access or operations. Actual facts remain backend-only. Two real fault repeats
greeted before caller speech and produced safe unavailable answers, privacy
refusals and fresh clock results, without an invented order. Do not claim the cause of the provider's ignored
greeting is known, or a prompt can guarantee against every unsupported generation.

### Spoken-correction follow-through

Autonomous trace `call-c1113311959f4eaea4cd54dbd0cd390e.db` exposes another
failure: the caller corrects red/Friday to blue/Thursday during voice output;
GPT-Live repeats the corrected facts without another delegation to GPT-6. The
content matches the caller but violates the agreed semantic ownership. GPT-6
also expanded Friday into September 25 without evidence of the intended date. Retain
this failed trace. The reviewed prompt refinement removes the ambiguous voice
instruction to rectify facts itself: all corrections, even obvious restatements, must be
re-delegated and only GPT-6's new result may supply the substantive correction.
Backend rules attribute caller-provided facts and preserve relative weekdays
without adding dates unless an explicit dated fact establishes the intended date;
a clock result alone cannot establish which Friday an order meant. Independent plan
and integration reviews APPROVED this refinement (26 independent tests; 27 lead
focused tests). The identical tenth call now delegates the correction to a second
GPT-6 run and speaks its attributed blue/Thursday answer, with no added date.
However, the preceding obsolete answer continues during caller correction. Prompt
compliance is empirical; immediate interruption remains unresolved.

### Autonomous phone tests authorized — 2026-09-24

The operator must leave and explicitly requests autonomous test calls. Use a
standalone diagnostic caller to dial ONLY the already-authorized test number,
with that same owned number as caller ID; never impersonate the frozen customer
or call the operator's personal number. Vonage NCCO text-to-speech and waits
exercise the real incoming carrier/audio path. This is a test driver, not a
production outbound feature. Keep a private durable attempt/receipt ledger before
origination, retain uncertain reservations, do not automatically retry an
uncertain create, and collect actual provider closure/price evidence. The existing
incoming ledger is unchanged. No recordings, routing changes or tunnel restart.
A scripted test has finite dialogue steps and hangs up when done; it adds no
runtime expiry or general conversation ceiling. Calls from this test number may
correctly be unidentified; label identity scenarios honestly. Pair the incoming
correlated transcript with the exact scripted caller text and observed tool
results. These calls can prove provider paths and failures, but cannot stand in
for human handset listening or certify known-caller recognition when unidentified.

Driver implementation/verification (lead-owned, reviewed before paid origination):
fix and enforce both destination and owned caller ID to the authorized number;
persist intent before POST, with a durable unresolved-state guard across restarts.
A lost create response or uncertain closure blocks a new origination rather than
retrying. For each known UUID, finally attempts hangup if active and reconciles
terminal status/price receipts, preserving all reservations. Mocked transport
checks must cover lost create responses, exceptions after UUID receipt and terminal
receipt handling. Independent integration review must approve the driver before
its first paid origination. This guard prevents overlapping uncertain calls; it is
not a reinstated financial, duration or attempt ceiling.

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

**Required diagnostic addition (operator request, 2026-09-24):** before the M4
calls, implement opt-in transcript capture for the isolated test. Record caller
and voice transcript events with timestamps and call/delegation/revision IDs;
correlate them with selected-memory tool results, the backend's final answer and
the commentary actually sent to GPT-Live. Keep retrieved facts, backend answers
and voice output distinct, including interruptions and repeated or superseded
answers. Do not capture hidden model reasoning. Store this diagnostic privately
outside Git, excluding credentials, tokens, MEMORY_KEY and unselected facts.
Ordinary profiles keep transcript persistence off; no raw audio is retained by
default. Capture implementation/activation are M4 tasks, not established evidence yet.

Use the correlated trace to locate failures between retrieval, backend reasoning,
voice delivery and interruption handling. Specifically verify that blue filters
and the prior-email Thursday agreement are used correctly when asked, and explain
the reported repetition after interruption. A retrieved-fact count is insufficient
acceptance evidence. Transcript output also does not prove what reached the
handset: retain the real listening check alongside the trace.

Use a short call script with the controlled history: known customer and follow-up;
unknown/ambiguous caller; correction during delayed lookup; correction during
speech; failed lookup and forced closure. Combine scenarios where useful; the operator removed all local call/spend ceilings.
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

### M4 execution sequence — authorized 2026-09-24

1. Lead: implement opt-in private SQLite traces in the isolated profile only.
   Correlate call/config revision, backend run/input revision, delegation IDs,
   selected tool results, final backend answer, actual append commands and server
   acknowledgements. Preserve transcript deltas and provider timeline offsets,
   reflected audio ranges without audio bytes, closure and suppression decisions.
   Mark overlap as an interruption candidate, never handset playback proof.
   Failures mark diagnostics incomplete but cannot prevent cleanup/accounting.
2. Lead: test real agent/tool/transport boundaries, default-off and file privacy,
   credential exclusion, duplicate/overlapping events, stale-answer suppression,
   lookup failure and close races. Reproduce defects before changing behavior;
   do not infer the old call's unavailable content. Run focused voice/adjacent
   regression and actual kernel-client tests. Fresh local review before activation.
3. Lead: enable capture in the private saved profile; restart only the existing
   smoke-named service after checking it is idle. Preserve unlimited settings,
   tunnel PID/URL, memory fixture and ledger history. Verify cold start before
   any operator RPC. Collect real GPT-6 backend evidence with frozen selected facts.
4. Lead/operator: real calls with short scripts and listening feedback. First call:
   historical filters, Thursday, missing tracking, follow-up and interruption.
   Between calls use authenticated actual kernel `cs rpc` configuration update
   via in-memory auth, then disconnect it. Verify next-call changed greeting.
   Use explicit isolated fault/delay controls for five-second lookup, corrections
   during backend work, lookup error and forced closure; no numeric call ceiling.
   Unknown/ambiguous cases use withheld/other caller when available; any injected
   fixture number is labeled simulated and cannot alone certify physical caller
   recognition. Unperformed/failed scenarios stay open.
5. Lead: correlate transcripts with caller feedback, timings, voice/backend usage
   and available carrier receipts. Fix demonstrated faults, repeat affected calls.
   Fresh independent end-to-end review evaluates all M4 criteria and actual
   operator path. Update guide, living context and this matrix faithfully; only
   real passing evidence permits completion. Rollback disables diagnostics or
   restores the isolated runtime/configuration, retaining all evidence and holds.

No implementation is delegated. Review gates: M4 brief amendment independently
APPROVED; fresh plan amendment review also APPROVED. Existing M1–M3 approvals remain scoped.

| M4 criterion | Evidence/state |
| --- | --- |
| Cold start without operator/Desktop | Config-6 autonomous calls use real GPT-6 tools after cold restart; no RPC client connected. |
| Configuration changes from next call | Authenticated client changed greeting 1→2 and capabilities/instructions 4→5→6; later calls snapshot revision 6 and execute the clock. |
| Greeting before delayed lookup | Delayed lookup greets around 2 s before context at 15 s. One later fault call misses greeting; two strict-role fault repeats greet before the caller. Provider reliability is not certified by these samples. |
| Blue filters / Thursday / follow-up / missing facts | Real backend replay uses both preloaded facts without another lookup; automated telephone tracking states absent tracking/status. Latest known-customer handset retest remains open; spoken-correction tests use caller assertions, not recognized memory. |
| Unknown / ambiguous identity | Real autonomous caller is unknown with no selected facts/invented identity. Ambiguous case has local/backend evidence only; live ambiguous scenario remains open. |
| Correction during backend work / speech | Backend correction retest suppresses stale results and improves 7→4 runs. Spoken retest now delegates the correction and voices GPT-6's answer, but continues obsolete speech during overlap: immediate interruption remains OPEN. |
| Internal / other-customer exclusion | Real unknown caller requests internal notes and other customers' orders; backend/voice refuse without selected-fact disclosure. Complements local scope tests. |
| Lookup failure / forced close / no late output | First fault call FAILED with an invented order. Two strict-role repeats pass. Actual paid-request shutdown closes the call without commentary; the dispatched request settles USD0.002926 with no unresolved OpenAI hold. |
| Latency / costs / continuity | Ten automated calls retain correlated text/tool/receipt evidence. Corrected-request receipt latency improves 6.602/7.365→3.303/3.675 s in the repeated backend scenario. Last spoken correction takes 7.082 s after caller transcript end; no general latency guarantee. |
| Independent final end-to-end review | Final independent review: APPROVED for isolated implementation/retests, REVISE for full M4. Interruption, final known-caller handset/follow-up, ambiguous-caller and human continuity evidence remain open. |

### Autonomous evidence — 2026-09-24

All trace names below have prefix `call-` and suffix `.db`; full private dialogue
stays in the isolated profile. No historical M3 transcript has been reconstructed.
All ten originator attempts and corresponding incoming calls are closed.

| Test | Trace identifier | Observed result |
| --- | --- | --- |
| Rome/New York clock, tracking | `8587b02f460d435badce563367ceccc5` | Fresh clock tools and spoken results; one semantic run per question. |
| Privacy, 15 s initial lookup | `509ef0e9e38b4cd9a98ce2d0a171c1e4` | Greeting precedes context; unknown identity and privacy refusal. |
| Backend corrections before scheduling fix | `ff6c480d2d02447e84a8062bd247815c` | Correct final answers but seven runs/five invalidations. |
| Lookup failure before role fix | `3f15e1ef4f894d5483ed568542d097b2` | FAILED: late greeting and unsupported order claim; retained. |
| Lookup failure after role fix | `96d2d9cebcfc4579a2b10ed9fd15f53f` | Timely greeting, safe unavailable answer, privacy refusal and clock. |
| Same lookup-failure repeat | `86265a9fbe604f5089602cf7241df121` | Same safe outcome. |
| Backend corrections after scheduling fix | `11a26f75d04f4dde9f69e89d4d968379` | Four runs/two invalidations, corrected Rome/date spoken. |
| Shutdown during dispatched inference | `5406606caefb40cf81f9f272a876c73f` | No late answer; settled request and confirmed closure. |
| Spoken correction before explicit re-delegation | `c1113311959f4eaea4cd54dbd0cd390e` | FAILED ownership/date grounding; voice answers correction alone. |
| Identical spoken-correction repeat | `b8103bdaeb6641449de0d21124e31ad1` | New delegation/backend answer, caller attribution and weekday granularity; obsolete speech overlap persists. |

Verification: 248 voice/kernel/budget tests passed, then 41 focused adapter/clock/
scheduling tests and 27 focused conversation/driver tests after the final prompt
change. Independent reviews ran 51 initial, 30 follow-through, four driver and
26 final prompt/conversation tests; final end-to-end reviewer ran 33 modified-path
and 12 runtime/scheduling tests. These overlapping sets are not summed.
The real backend-only preload replay `5904bc592c9c418bbbe88fdd0838f0bf` returns
blue filters then Thursday with two GPT-6 requests and no additional memory lookup;
it does not replace a recognized-caller phone test.

Final accounting snapshot: 19 closed incoming calls with USD19 retained holds;
all nine pre-activation rows compare byte-for-byte unchanged. The separate
originator ledger has ten closed attempts and USD10 retained holds. GPT-6 has
103 settled usage rows, estimated USD0.307244; no unresolved OpenAI reservations.
Two old proxy holds totaling USD0.110 remain. Holds are not expenditure. Carrier
receipts omit currency, so their prices are retained without a fabricated USD
aggregate. Private summaries and receipts remain outside Git.

The paid-shutdown test stopped a transient `--collect` smoke unit, so a plain
start failed after collection. One recreation lacking PYTHONPATH failed before
paid work. Correct recreation restored the service with its explicit engine
PYTHONPATH. Final smoke PID 2982956 and unchanged tunnel PID 1903954 are active,
both lifetimes infinite; health is ready/unlimited with no operator RPC client.
Config revision 6, capture/unlimited 1, both delays and lookup-failure injection 0.

## Verification and review record

### M4 — in progress, 2026-09-24

- Brief/plan amendments independently APPROVED. Added opt-in isolated SQLite
  diagnostics with selected-tool, final-answer, append/acknowledgement, transcript,
  timing and closure correlation. No audio or hidden thinking capture.
- Initial voice regression: 156 passed, one real-kernel test skipped without its
  interpreter. Located the installed kernel and reran: 157 passed including its
  actual CLI journey. New diagnostics independently passed seven tests; the
  focused conversation/runtime/kernel selection passed 20 before the final extra
  close-failure regression. Whole-engine Ruff and mechanical docs checks pass.
- Local activation review first returned REVISE: diagnostic close failure could
  bypass final ledger update. Fixed sink and runtime finalizer, added the injected
  failure regression. Same independent reviewer reran seven diagnostic tests and
  returned APPROVED for activation only.
- Enabled private capture plus five-second lookup/backend delays only in the
  saved isolated profile. Restarted only `mrcall-gpt-live-smoke`; cold-start health
  is available/unlimited before any operator RPC. Tunnel PID remains 1903954;
  both services retain infinite lifetime. All three previous closed voice rows
  hash-match the preactivation snapshot. USD3 voice holds, USD0.110 unresolved
  MrCall holds, 17 settled GPT-6 requests/USD0.030836 were verified beforehand.
- First M4 call, 13:46:53–13:47:32 UTC, configuration revision 1: private trace
  `call-8fa6549dfedc46c8bd90f2ade227e582.db` contains 478 events and closes cleanly.
  The voice greets before delayed lookup, then explicitly uses both blue-filter
  history and the prior Thursday agreement. Caller feedback: the exchange was
  perfect. When asked about identity, it does not invent a name. No delegation
  occurred: these facts came through quiet selected context, not a new GPT-6
  turn. No correction/interruption scenario was performed in this call.
- Timings: first reflected audio 2,455 ms from admission; caller lookup 5,145 ms
  from attachment (includes 5-second fault delay); useful fact speech begins at
  provider offset 10,000 ms after a question ending around 9,800 ms. The caller
  confirms the listening experience; there is no instrumented handset latency.
  Voice reports 38 seconds, estimated USD0.031667; no new backend usage. Two
  completed carrier legs each last 39 seconds, prices 0.00292500 + 0.00273000 =
  0.00565500 account-currency units. Receipt currency is omitted, so no settled
  USD total across providers is asserted. Original historical liabilities remain.
- Actual installed kernel `cs rpc`, authenticated using headless Firebase with
  ID token only in memory/anonymous pipes, changed revision 1→2 between calls.
  Only instructions changed: next greeting should begin “Buongiorno, test memoria
  MrCall”. Readback confirmed revision 2, client exited, temporary workspace was
  removed without an auth cache. No service restart was needed. The second call
  below confirms the new greeting with positive operator feedback.
- Final combined regression on the activated diagnostic implementation: **215
  passed**, covering all voice tests, actual kernel CLI and budget dispatch/ledger.
  The historical M3 failure stage remains unknowable; new successful recall does
  not reconstruct it. Repetition after interruption still needs a reproduced call.


- Real GPT-6 backend-only M4 scenarios exercise unknown caller, ambiguous frozen
  fixture number and injected lookup failure. Each uses a real tool/result turn
  and asks for clarification without inventing identity/order facts. Six Responses
  requests settled at USD0.009026 total; no new unresolved OpenAI hold. These are
  explicitly non-phone traces under the private `M4-backend/voice-diagnostics/`.
- Fresh independent end-to-end review: **REVISE for M4 completion**, with no new
  implementation blocker. Reviewer independently passed 20 diagnostic/conversation/
  runtime tests and read the first phone and backend-only traces. Remaining live
  criteria: revision-2 greeting, autonomous GPT-6 turn after cold start, follow-up
  lookup/missing facts, corrections during backend/speech and repeated-answer
  diagnosis, unknown/ambiguous callers, internal/other-customer exclusion,
  lookup failure/forced closure/late suppression, and corresponding listening,
  latency/cost evidence. M4 stays active; this is not an acceptance downgrade of M3.

- Second real M4 call, 14:13:49 UTC, revision 2, private trace
  `call-28a04137b910483ca25832a0117899c9.db`: caller reports an excellent exchange.
  The revised greeting is spoken. Caller interrupts tracking discussion, corrects
  the subject and then reaffirms blue filters; voice explicitly retracts the
  mismatched subject and follows the new request. No unwanted repeat is observed.
  GPT-6 runs once; later caller input supersedes its draft. Reconciliation is
  pending when normal hangup cancels it, and no backend commentary is sent.
  This proves real backend execution/cancellation, not a completed follow-up
  tool read or reconciled-backend delivery. Voice uses the selected quiet context.
- The new trace motivates a reproduced local repetition defect: output transcript
  changes alone did not invalidate a pending backend result, so an answer already
  provided by the voice could be sent again. A failing regression demonstrates
  this independently of the unavailable M3 transcript. A second failing test shows
  diagnostic delay allowed a run's text snapshot to differ from its labeled input
  revision. Implemented fix: snapshot text/revisions before awaits, reconcile
  voice-output changes as well as caller corrections, and let the backend return
  an internal no-further-response decision when the latest request is already
  correctly answered. Wrong/partial speech and new questions must still receive
  useful answers. Independent activation review is APPROVED with 25 focused tests.
  Four real GPT-6 backend-only replay scenarios pass: complete answer returns the
  silent decision; filler gets the historical facts; wrong Friday is corrected to
  Thursday; new tracking question gets the missing-number clarification. Seven
  Responses requests cost USD0.013170. These are not phone acceptance.
- Second-call timings: first reflected audio 3,704 ms from admission; lookup
  5,012 ms from attachment including the five-second delay. Voice reports 53
  seconds, estimated USD0.044167; carrier legs report 54/55 seconds and prices
  0.00405000 + 0.00385000 = 0.00790000 account units, with currency omitted.
  After replay, five closed calls retain USD5 in voice holds; 31 settled GPT-6
  requests total USD0.055282, no unresolved OpenAI hold. The two historical proxy
  holds still total USD0.110. No reset or manual reimbursement occurred.
- Corrective commit `e745fc5`: all voice tests including actual kernel CLI plus
  budget dispatch/ledger pass (**220 passed**). Production-source Ruff and the
  changed test file pass; a broader test-tree lint also finds three pre-existing
  E701/E702 errors in `tests/evaluation/test_model_quality_runner.py`, outside M4.
  Changed-file Black and diff checks pass. Restarted only the idle smoke service
  with the approved correction, PID 2226989; readiness is available/unlimited
  before any RPC. All five previous call rows hash-match the preactivation copy.
  Tunnel PID 1903954 and both infinite service lifetimes are unchanged. A new
  phone retest has been requested; the correction is not yet phone-accepted.
- Updated independent end-to-end review after the second phone call and correction:
  **APPROVED for activation, REVISE for M4 completion**. Reviewer independently
  passed 25 tests and inspected both the second-call trace and all four real-model
  replays. No new implementation blocker. Remaining evidence: corrected-controller
  continuity/no repetition and corrections during work/speech; GPT-6 after cold
  start before any RPC; follow-up lookup and reconciled backend delivery; live
  unknown/ambiguous callers, internal/other-customer exclusion, lookup failure,
  forced close and late suppression; corresponding listening, timing and costs.

- Third real M4 call, 14:41:51–14:42:37 UTC, after corrected-controller cold start
  before any operator RPC: private trace `call-1141babd9e0743989e7bf361fbead472.db`,
  574 events, complete. Caller feedback: again excellent. Revision-2 greeting and
  blue/Thursday history are spoken; when the caller changes subject, voice stops
  and follows the identity question. A second interruption is also handled without
  returning to the old answer. This supports voice continuity and spoken
  interruption on the corrected runtime. No client delegation or backend run
  occurs: it does **not** exercise the backend race, reconciliation or silent
  decision, nor prove autonomous GPT-6 execution after cold start.
- Third-call first reflected audio is 3,101 ms from admission; lookup 5,141 ms
  from attachment including the five-second delay. Voice reports 45 seconds,
  estimated USD0.037500. Both carrier legs complete at 46 seconds, total price
  0.00322000 + 0.00345000 = 0.00667000 account units (currency omitted).
  Six closed voice calls retain USD6 holds; backend usage remains 31 settled
  requests/USD0.055282, with no unresolved OpenAI hold. Historical proxy holds
  remain USD0.110. No code or runtime change is made in response to this call.
- Independent end-to-end review of the third trace confirms voice continuity and
  no newly demonstrated defect. Activation remains APPROVED; M4 remains REVISE
  because this call does not exercise delegation or the outstanding live scenarios.


- Prepared the next backend-focused call through the actual authenticated kernel
  `cs rpc`: configuration revision 2→3 changes instructions only. Voice is told
  explicitly to delegate order/delivery/color/tracking verification before giving
  business answers and to avoid announcing historical context during the greeting.
  The backend is told to consult the selected-memory tool for that verification.
  This is a test configuration, not evidence that delegation will occur. Revision-2
  backup is private; Firebase ID token stays in memory/pipes, temporary client
  workspace removed without a token cache. No company fixture, limit or ledger
  is changed.
- Restarted only the idle smoke service to prepare the strict cold-start scenario:
  PID 2261401, available/unlimited health before any new RPC; tunnel PID 1903954
  unchanged, both runtime limits infinite. All six closed call rows hash-match
  `M4-revision3-prestart.json`. The caller is unavailable for another phone test
  now. Leave this configuration ready; the next call should ask for tracking,
  correct the request while verification runs, then allow the response to finish.
  No additional call occurred and all remaining M4 criteria stay open.


- Fourth real M4 call, attached 15:27:06 UTC, revision 3, trace
  `call-f896f200b6a043fca6e41a048a7aa8af.db`, 420 events, complete. Caller reports
  greeting only when they started speaking and silence after the agent promised
  to verify the corrected request. This is a failed experience, not acceptance.
  First reflected audio is 2,324 ms from admission, but the greeting transcript
  begins at provider offset 6,200 ms, after lookup at local 5,178 ms. Reflected
  audio arrival cannot certify prompt speech. No audio recording is available
  to establish exact handset onset.
- Backend starts at 16,421 ms; caller correction/new delegation at 22,634 ms.
  After the five-second backend fault delay and provider processing, the obsolete
  tracking run calls memory at 31,724 ms. Its Italian query has no literal match
  against English selected facts; after another five-second injected delay it
  returns empty at 36,735 ms. Hangup at 36,799 ms cancels remaining work. No final
  backend answer, commentary or silent decision occurs. This proves cold-start
  autonomous dispatch and tool execution, but no useful completion. The silence
  was not intentional suppression of an already-answered question.
- Corrective regressions fail on the old code: an obsolete tool round causes an
  unnecessary model dispatch; the Italian query falsely appears to have no facts.
  The implementation now gates each tool/model dispatch by revision, preserving
  settlement of the current paid request and prior completed history while
  dropping only the incomplete obsolete turn. A labeled no-lexical-match fallback
  returns only still-pinned selected facts. An explicit session-start instruction
  requests the greeting independently of lookup; its task is idempotent and closed
  with the conversation. Speech transcript timing is recorded separately from
  reflected audio. No conversation/attempt/spend limits are introduced.
- Real GPT-6 controller replay with the same correction returns blue filters and
  historical Thursday delivery in 10,309 ms, three serial Responses requests,
  maximum paid concurrency one, no failure. Private backend-only trace
  `call-59e8d3e9140c436aa5137320302d4908.db`. It proves controller/tool delivery,
  not telephone speech. Independent activation review is APPROVED with 47 focused
  tests. Full voice/kernel/budget regression: **224 passed**; source/voice-test Ruff,
  changed-file Black and diff checks pass. Commit `293c524` contains the correction.
- Fourth call: voice 36 seconds, estimated USD0.030000; carrier legs both 37
  seconds, price 0.00259000 + 0.00277500 = 0.00536500 account units, currency
  omitted. After the call and replay: seven closed voice calls retain USD7 holds;
  36 settled GPT-6 requests total USD0.067263, no unresolved OpenAI hold. The
  historical two proxy holds remain USD0.110.
- Activated the reviewed correction by restarting only idle smoke, PID 2319803.
  Saved diagnostic lookup/backend delays are now zero; trace capture and unlimited
  mode remain enabled. Cold-start health is available before any operator RPC.
  All seven old call rows hash-match `M4-greeting-prestart.json`. Tunnel PID
  1903954 and both infinite service lifetimes are unchanged. Normal phone retest
  remains pending; neither the delayed-greeting nor useful-response failure is
  accepted as resolved solely from local tests/replay.
- Updated final independent end-to-end review: 40 focused tests pass; APPROVED
  for isolated retest, REVISE for M4 completion, no new implementation blocker.
  The normal phone test must demonstrate greeting and useful corrected answer.
  Separately rerun greeting with deliberately delayed lookup: disabling that delay
  cannot establish the delayed-lookup criterion. Exceptional phone scenarios and
  delivery of the reconciled backend response remain open.


- Fifth real M4 call, 15:40:05–15:41:02 UTC, revision 3, trace
  `call-970acf505c234a8cae5ddfd8fb3186b8.db`, 669 complete events. Initial lookup
  takes 145 ms; both blue/Thursday facts are sent as quiet context at 171 ms and
  acknowledged at 1,190 ms. Greeting transcript starts at provider 1,000 ms
  (arrival 967 ms from attachment). No injected delays. A corrected backend
  answer about blue filters is appended at 27,556 ms, acknowledged and spoken.
  This proves corrected backend/tool-to-voice delivery after cold start. The later
  day question is unanswered before hangup; full continuity still fails.
- Caller finds the repeated checking/listening wording awkward and requests that
  available phone-linked information be loaded immediately. It already is, within
  the selected-fact boundary. The special revision-3 configuration forced fresh
  verification even when initial context answered the question. Restore direct
  use of loaded authorized facts; delegate only missing information/additional
  work and avoid narrating handoffs or listening. Do not expand access merely
  because a phone number matches.
- Fifth-call diagnostics show nine agent runs and seven reconciliations. Runs
  1/5/6/8 stop at a tool boundary solely because voice progress changed, although
  caller revision is unchanged. A new regression fails on the prior controller:
  its acknowledgement discards the required lookup. The correction invalidates
  intermediate work only for caller changes; both revisions still fence final
  delivery, including the silent decision and each commentary fragment. Useful
  tool results survive the agent's own progress. Independent activation review
  APPROVED with 48 tests. Real backend-only replay completes the Thursday answer
  in 6,656 ms, three serial Responses requests, trace
  `call-fadfdc82a5264eeba23a115418d9d2ed.db`. Phone acceptance remains open.
- Fifth-call voice usage: 55 seconds, estimated USD0.045834. Both carrier legs
  complete at 57 seconds, total price 0.00427500 + 0.00399000 = 0.00826500 account
  units, currency omitted. After call and replay, 49 GPT-6 requests settle at
  USD0.113170; no unresolved OpenAI hold. Historical proxy holds remain USD0.110.
- Activated `b89c052` after **225 passed** voice/kernel/budget tests, source/voice
  Ruff, changed-file Black and diff checks. Actual authenticated kernel `cs rpc`
  changed configuration revision 3→4, instructions only: restored the earlier
  greeting/base policy and explicitly allows immediate use of loaded selected
  facts, delegation for missing information/work, no technical handoff narration.
  Private revision-3 backup retained; token only in memory/pipes and temporary
  operator workspace removed. This implements the user's request without changing
  the frozen fixture or widening phone recognition permissions.
- Restarted only idle smoke, PID 2417148, with available/unlimited health before
  further RPC. Tunnel PID 1903954, infinite service lifetimes, capture enabled
  and zero injected delays remain unchanged. Eight closed voice rows hash-match
  `M4-natural-prestart.json`; USD8 voice holds remain. No phone call has yet
  verified the new natural-context configuration.
- Final independent review of the fifth trace, new controller and replay passes
  15 tests: APPROVED for isolated retest, REVISE for M4 completion. No new
  implementation blocker. Verify revision-4 natural answers, completed day
  follow-up, no repetition and no discarded lookup/tool rounds caused solely by
  voice progress. Delayed-lookup
  greeting and exceptional caller/failure/closure scenarios remain open. Also
  verify precise missing-data wording: the fifth answer's broad claim of no other
  order details is misleading when the selected Thursday agreement is available.

### M3 — 2026-09-24

**Integrated GPT-6 telephone retest — 2026-09-24 12:05 UTC:** the caller reports
that interruption happens at the right time. The agent correctly said it had no
tracking number, was interrupted, then repeated that answer; the caller judged
the exchange acceptable. The repetition is an observed quality limitation, not
proof of flawless correction handling. In a later clarification, the caller says
it seemed the agent did not remember the blue filters and requests transcripts
in M4. Thursday recall is not explicitly confirmed either. No transcript/audio
was retained, so the failure stage cannot be reconstructed. Retrieval is verified;
audible recall is not. The earlier M3 integration approval is not acceptance of
memory-grounded spoken answers. M4 must investigate this reported gap using the
correlated transcript requirement above.

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
