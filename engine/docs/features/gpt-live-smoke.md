# GPT-Live M1 telephone smoke

<!-- doc-scope:start -->
Scope: local M1 runner, isolated test prerequisites, limits, evidence and teardown.
This is an opt-in experiment, not a deployed customer-service voice channel.
<!-- doc-scope:end -->

The source command is `zylch -p <test-firebase-uid> voice-smoke --port 8787`.
Its webhook listens on **127.0.0.1 only**, at `/openai/live`, separately from
the engine RPC daemon. It returns a fixed test fact on client delegation and
does no company-memory or paid engine reasoning work. cs-operator is not used
during calls. M2 configuration and M3 memory/agent integration are not implemented.

The candidate path is Vonage SIP → GPT-Live audio, with Python attached to the
Live sideband. TLS/SRTP interoperability and project access remain **unverified**.
No fallback to Realtime or another carrier is implemented.

## Before enabling

Use a separate Firebase-UID profile with no customer mail or company memory,
a dedicated OpenAI test project/webhook secret, and an explicitly identified
Vonage test application/trunk/number. Establish HTTPS forwarding to this
loopback endpoint and verify its reachability. This code configures none of
those external resources and never reassigns a phone number.

Record a private, non-secret preflight note with:

- Test number, expected SIP `To` URI, HTTPS endpoint and OpenAI project ID.
- Evidence of GPT-Live access and enabled SIP, Vonage TLS/SRTP compatibility,
  and isolation of the test routing. A model listing alone does not prove SIP.
- Secret references (never values), saved engine payment mode and verified
  headless credential source. M1 does not exercise engine credentials itself.
- Current voice and **all carrier leg/setup rates**, billing rounding and rate
  sources/date. Rejecting calls can still incur carrier charges; supervise the
  number and include these in the total test allowance. No backend API here
  can guarantee the carrier's final bill or a hard hangup during an outage.

Only after those checks, populate the selected profile's private `.env`.
The smoke reads that file directly without shell fallback or interpolation:

| Key | Required value |
| --- | --- |
| `OWNER_ID` | Firebase UID, exactly equal to the profile directory name |
| `VOICE_SMOKE_TEST_PROFILE` | That same UID; ambient variables cannot enable it |
| `VOICE_SMOKE_READY` | `1`, after the external preflight above |
| `VOICE_SMOKE_PREFLIGHT_REFERENCE` | Non-secret reference to that recorded preflight |
| `OPENAI_PROJECT_ID` | Dedicated project ID beginning with `proj_` |
| `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET` | Private test credentials |
| `VOICE_SMOKE_TEST_NUMBER` | Isolated number in E.164 format |
| `VOICE_SMOKE_SIP_TO_URI` | Exact expected SIP destination URI; no display name/tag |
| `VOICE_SMOKE_PUBLIC_ENDPOINT` | Verified `https://…/openai/live` endpoint |
| `LLM_PROVIDER` | Explicit `anthropic`, `openrouter` or `mrcall`; no provider change |
| `VOICE_SMOKE_RESERVATION_MICROUSD` | Conservative per-call allowance, integer microdollars |
| `VOICE_SMOKE_VOICE_MICROUSD_PER_MINUTE` | Verified voice rate |
| `VOICE_SMOKE_CARRIER_MICROUSD_PER_MINUTE` | Aggregate verified carrier rate |
| `VOICE_SMOKE_CARRIER_SETUP_MICROUSD` | Aggregate verified setup charge |
| `VOICE_SMOKE_DURATION_SECONDS` | Optional 1–180; default 180 |
| `VOICE_SMOKE_MAX_CALLS` | Optional 1–6; default 6 |
| `VOICE_SMOKE_RESULT_DELAY_SECONDS` | Optional 0–30; default 5 |

USD1 = 1,000,000 microdollars. No price is supplied by default. The minimum
reservation rounds up `(duration + 20 seconds)` to whole minutes, multiplies
by combined declared rates and adds setup charges. Twenty seconds covers the
bounded hangup/finalization grace; it is not a guarantee against provider
failure. Choose a larger reservation when the actual carrier contract requires
it, and leave allowance for carrier charges from refused calls.

The signed OpenAI webhook authenticates the project event. Matching `To` checks
routing only; SIP caller metadata does not prove caller identity. Use a dedicated
project/secret and inspect the actual test trunk metadata before live acceptance.

## Install and start

In a separate virtual environment for this worktree, install `engine/[voice-smoke]`
(from `engine/`: `python -m pip install -e '.[voice-smoke]'`). The optional extra
includes OpenAI SDK 3.19.0, aiohttp and the required WebSocket client. The normal
engine dependency is unchanged. Start the command shown above after preflight;
it takes the selected profile lock without starting or activating other channels.

The run ledger is `<test-profile>/voice-smoke.db`, a separate SQLite store.
Each unique session is committed with a reservation **before** accept dispatch.
The ledger permits at most six attempted accepts and USD5 reserved in total,
persists through restarts/midnight, and has no automatic refund/reset. All holds
remain reserved even after final usage arrives. Changing the public configuration
against an existing ledger is refused; secret rotation alone is permitted.
Do not delete or replace the ledger to continue an exhausted experiment.

On restart, any unresolved accept/active/uncertain session receives only a hangup
attempt. It is never accepted again. A confirmed hangup permits later admission
but leaves usage unconfirmed without `session.closed`. A failed/uncertain hangup
blocks new calls. Resolve such cases through the isolated provider controls and
record the outcome before a separate supervised recovery change.

## Exercise and collect evidence

Call the isolated number with cs-operator stopped. Ask for the test fact, speak
during the five-second delay, then speak while the agent answers. Listen for
intelligible bidirectional audio and continuity; a passing local suite cannot
prove either. Exercise normal hangup and a short configured duration watchdog.

The reader stays active while the fixed result waits. On closure, pending
results are cancelled. EOF or exceptions before a final event trigger a hangup
attempt. The duration deadline starts before accept and sideband attachment.

SQLite `smoke_calls` holds session ID, state, reservation and sanitized JSON
evidence: event counts, reflected first-audio timing when observed, result count,
closure trigger, finalization, reported voice seconds, estimated voice cost,
and explicitly unverified carrier cost. No audio, transcript text, credentials,
SIP headers or final session configuration is retained. Reflected first-audio
timing is not handset playback latency. Carrier receipts, listening observations
and actual combined cost must be added to the plan's live acceptance record.

The WebSocket uses a private silent wire logger; HTTP/SDK logs are suppressed
for the smoke process. Application logs contain decisions and closure state only.

Stop with SIGINT/SIGTERM: admission stops, active work is cancelled, hangup is
attempted and the receiver remains open briefly for final usage. SIGKILL cannot
run cleanup; the next start recovers the durable uncertain session as above.
Remove only the recorded test routing after confirming carrier-side closure.
Leave production daemons and numbers untouched.

## Verification status

The rebuilt runtime has local SQLite, mocked-provider, real signed-webhook and
localhost WebSocket tests. Real Vonage audio, live project entitlement, carrier
metadata and measured combined charges remain unverified. The first prototype's
approval was withdrawn; use the current
[M1 review record](../../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md).

API basis checked 2026-09-23: [GPT-Live SIP](https://developers.openai.com/api/docs/guides/voice-sip),
[delegation](https://developers.openai.com/api/docs/guides/live-delegation) and
[finalization](https://developers.openai.com/api/docs/guides/live-conversations).
