# GPT-Live M1 telephone smoke

<!-- doc-scope:start -->
Scope: local M1 runner, isolated test prerequisites, limits, evidence and teardown.
This is an opt-in experiment, not a deployed customer-service voice channel.
<!-- doc-scope:end -->

The source command is `zylch -p <test-firebase-uid> voice-smoke --port 8787`.
Its webhook listens on **127.0.0.1 only**, at `/openai/live`, separately from
the engine RPC daemon. It returns a fixed test fact on client delegation and
does no company-memory or paid engine reasoning work. cs-operator is not used
during calls. [M2 configuration and selected-fact retrieval](voice-agent-configuration.md)
are shared with the opt-in M3 engine listener described below. This M1 entry
point retains its fixed-response behavior; integrated live acceptance is recorded
in the milestone plan.

The selected path is Vonage SIP → GPT-Live audio, with Python attached to the
Live sideband. The isolated real-call demonstration verifies project access and
the configured TLS/SRTP route; it is not a production certification.
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
| `VOICE_SMOKE_SIP_TO_URI` | Expected SIP destination URI; with Vonage, `sip:<project>@sip.api.openai.com` (optional TLS/SRTP hints) |
| `VOICE_SMOKE_PUBLIC_ENDPOINT` | Verified `https://…/openai/live` endpoint |
| `LLM_PROVIDER` | Explicit `anthropic`, `openrouter` or `mrcall`; no provider change |
| `VOICE_SMOKE_RESERVATION_MICROUSD` | Conservative per-call allowance, integer microdollars |
| `VOICE_SMOKE_VOICE_MICROUSD_PER_MINUTE` | Verified voice rate |
| `VOICE_SMOKE_CARRIER_MICROUSD_PER_MINUTE` | Aggregate verified carrier rate |
| `VOICE_SMOKE_CARRIER_SETUP_MICROUSD` | Aggregate verified setup charge |
| `VOICE_SMOKE_DURATION_SECONDS` | Optional 1–180; default 180 |
| `VOICE_SMOKE_MAX_CALLS` | Optional 1–6; default 6 |
| `VOICE_SMOKE_RESULT_DELAY_SECONDS` | Optional 0–30; default 5 |
| `VONAGE_APPLICATION_ID` | Optional dedicated Voice app UUID; requires both following fields |
| `VONAGE_API_KEY` | Account identifier checked against signed Vonage callbacks |
| `VONAGE_SIGNATURE_SECRET` | Existing account signing secret, **not** its API secret |

USD1 = 1,000,000 microdollars. No price is supplied by default. The minimum
reservation rounds up `(duration + 20 seconds)` to whole minutes, multiplies
by combined declared rates and adds setup charges. With Vonage enabled, another
15 seconds is included before rounding, covering the carrier ringing timeout.
Twenty seconds covers the
bounded hangup/finalization grace; it is not a guarantee against provider
failure. Choose a larger reservation when the actual carrier contract requires
it, and leave allowance for carrier charges from refused calls.

The signed OpenAI webhook authenticates the project event. Matching `To` checks
routing only; SIP caller metadata does not prove caller identity. Use a dedicated
project/secret and inspect the actual test trunk metadata before live acceptance.

With the three Vonage fields present, the same listener provides POST
`/vonage/answer` and `/vonage/event`. Configure the dedicated Voice application's
answer/event webhooks accordingly, enable signed callbacks, and link only the
explicitly authorized test number. The answer verifies HS256, issuer, account,
body SHA-256, and a five-minute timestamp window (30 seconds future skew). An
application claim, when present, must also match. Only the configured destination
number is accepted. It returns one fixed NCCO `connect` to the selected OpenAI
project with `transport=tls;media=srtp`, a 15-second ringing timeout and the saved
call-duration limit. Caller-supplied routing and caller metadata are not copied
into the NCCO. Before returning it, the ledger reserves the complete allowance
and deduplicates the carrier call UUID. A generated one-use correlation nonce
travels in the SIP `X-Mrcall-Smoke-Attempt` header; only its hash is stored.
The signed OpenAI incoming callback must match that pending reservation and
the configured destination; it binds the same hold to the OpenAI session, without
reserving twice. Only the optional `transport=tls` and `media=srtp` URI hints
may be normalized away. Caller identity is still not established by this check.
Retries, busy/stopping states and exhausted capacity receive an empty NCCO.
Missing OpenAI ingress retains its hold and blocks further connections, including
after restart, until supervised reconciliation. Refused calls may still incur
carrier charges. Verified event callbacks are acknowledged and discarded, not
used as billing evidence. No outbound dial API is implemented.

Do not rotate the shared Vonage signing secret or change account-wide signing
settings for this experiment. Retrieve the existing secret through the account's
API Settings; it is distinct from the credential used by the CLI.

## Install and start

In a separate virtual environment for this worktree, install `engine/[voice-smoke]`
(from `engine/`: `python -m pip install -e '.[voice-smoke]'`). The optional extra
includes OpenAI SDK 3.19.0, aiohttp and the required WebSocket client. The normal
engine dependency is unchanged. Start the command shown above after preflight;
it takes the selected profile lock without starting or activating other channels.

If reusing an existing Firebase identity for M1, keep the test configuration
in a separate UID-named directory rather than modifying its populated profile.
On the Linux test host, run from the repository root:
`PYTHONPATH=engine python engine/scripts/voice_smoke_isolated.py --profile-dir <absolute-test-directory> --port 8787`.
This bootstrap uses the same file-only readiness validation, refuses a directory
containing `zylch.db`, and holds that directory's `.lock` across recovery,
serving and shutdown. It never changes HOME, selects a normal profile or invokes
profile activation. Provider secrets must be staged privately in that directory's
`.env`; do not copy the existing customer profile or company-memory capability.

The run ledger is `<test-profile>/voice-smoke.db`, a separate SQLite store.
Each carrier attempt is reserved **before** returning a connection NCCO; without
the optional carrier adapter, each session is reserved before accept dispatch.
The ledger permits at most six funded attempts and USD5 reserved in total,
persists through restarts/midnight, and has no automatic refund/reset. All holds
remain reserved even after final usage arrives. Changing the public configuration
against an existing ledger is refused; secret rotation alone is permitted.
Do not delete or replace the ledger to continue an exhausted experiment.

On restart, any unresolved accept/active/uncertain session receives only a hangup
attempt. It is never accepted again. A confirmed hangup permits later admission
but leaves usage unconfirmed without `session.closed`. A failed/uncertain hangup
blocks new calls. Resolve such cases through the isolated provider controls and
record the outcome before a separate supervised recovery change.
An unresolved carrier-only attempt has no OpenAI session to hang up: restart
marks it uncertain, retains the hold and disables its old correlation nonce.

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
The companion `smoke_carrier` table contains carrier UUID, nonce hash and its
session mapping; pending calls use a `vonage:` placeholder in `smoke_calls`.

The WebSocket uses a private silent wire logger; HTTP/SDK logs are suppressed
for the smoke process. Application logs contain decisions and closure state only.

Stop with SIGINT/SIGTERM: admission stops, active work is cancelled, hangup is
attempted and the receiver remains open briefly for final usage. SIGKILL cannot
run cleanup; the next start recovers the durable uncertain session as above.
Remove only the recorded test routing after confirming carrier-side closure.
Leave production daemons and numbers untouched.

## Verification status

The rebuilt runtime has 68 passing local SQLite, mocked-provider, real
signed-webhook, isolated-bootstrap and localhost WebSocket tests. One real
isolated call on 2026-09-24 passed bidirectional audio, caller-confirmed
interruption and speech during the delayed Python fixed result, client delegation
and confirmed session closure. Both carrier legs have completed receipts;
voice cost uses reported seconds and the recorded rate, not a settled invoice.
Live watchdog failure testing, memory and production operation are not certified.
The final M1 live integration review is approved. The first prototype's approval
was withdrawn; use the current
[M1 review record](../../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md).

API basis checked 2026-09-23: [GPT-Live SIP](https://developers.openai.com/api/docs/guides/voice-sip),
[delegation](https://developers.openai.com/api/docs/guides/live-delegation) and
[finalization](https://developers.openai.com/api/docs/guides/live-conversations).
Carrier contracts: [Vonage NCCO](https://developer.vonage.com/en/voice/voice-api/ncco-reference)
and [Voice webhooks](https://developer.vonage.com/en/voice/voice-api/webhook-reference).

## M3 handoff

The authorized M3 runner uses the same private profile directory and
`voice-smoke.db`, preserving the original policy digest and paid rows.
`scripts/voice_engine_isolated.py` adds a separate `voice-engine.db`, controlled
company memory and authenticated operator RPC. Its listener uses the M1 carrier
admission/closure path with customer-service configuration and memory instead of
the fixed fact. The original smoke entry point remains available for rollback;
see [integrated configuration](voice-agent-configuration.md#integrated-isolated-daemon-m3).
Both the dedicated smoke-named service and tunnel remain without automatic expiry.

The operator subsequently removed all local test ceilings for M3. The saved
`VOICE_ENGINE_UNLIMITED=1` override applies only when `OWNER_ID`,
`VOICE_SMOKE_TEST_PROFILE` and `VOICE_ENGINE_ISOLATED_PROFILE` match the explicit
profile directory name and that directory contains no ordinary `zylch.db`.
An environment variable alone cannot enable it. It removes the attempt count,
aggregate spending, engine daily budget, call duration, transcript and delegation
ceilings. The original bounded mode described above remains the default.
Reservations, receipts, duplicate rejection and unresolved-call handling remain.
Historical per-call reservations are accounting records, not maximum prices for
unlimited calls. The carrier NCCO omits the local duration limit; Vonage still
imposes its own default/maximum of 7,200 seconds (see the linked NCCO reference).
External provider credits and service limits still apply. No ledger reset is needed.


For the current M3 test, `VOICE_ENGINE_PROVIDER=openai` explicitly chooses the
same dedicated OpenAI project/key for backend `gpt-6-sol`; `gpt-live-1` remains
the voice model. This isolated override supersedes the historical MrCall backend
choice without changing the original smoke policy hash or ledger. GPT-6 uses
Responses and the existing paid engine dispatch; real inference/tool verification
is recorded in the plan. Health/model discovery alone does not certify inference.
See [direct backend configuration](voice-agent-configuration.md#dedicated-gpt-6-backend-for-this-experiment).
