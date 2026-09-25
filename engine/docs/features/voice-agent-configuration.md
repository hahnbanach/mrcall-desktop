# Voice agent configuration, memory-backed calls and diagnostics (M2–M4)

<!-- doc-scope:start -->
Scope: authenticated operator configuration, immutable snapshots and read-only
selected-fact retrieval from M2, the opt-in M3 engine listener and M4 private
diagnostic capture, the optional clock capability and autonomous diagnostic caller.
The isolated listener reuses M1's durable admission and
closure ledger. The milestone plan owns live acceptance evidence and open criteria.
<!-- doc-scope:end -->

cs-operator configures the agent through the existing **`cs rpc`** command in its
bound workspace. The engine WebSocket verifies Firebase's signature and requires
the token UID to equal the profile's `OWNER_ID`. Stdio retains its trusted-parent
boundary. Provider webhooks expose none of these RPCs. No kernel change or new
auth mechanism is needed.

The engine keeps Firebase ID tokens in memory. The kernel's ordinary `cs rpc`
retains its pre-existing client auth/cache behavior; M2 does not change it.
The acceptance script below explicitly bypasses that client's disk token cache
so the demonstration persists no ID token on either side.

## Operator workflow

1. Run `cs rpc voice.config.get`. It returns `owner_uid`, the non-secret company
   `space_id`, `revision`, `binding_valid` and `config`. New profiles default to
   disabled. Company memory must already be attached through existing setup.
2. Select existing customer blob/sentence IDs from the controlled fixture. The
   operator explicitly approves each sentence's complete text for that customer.
   Internal notes stay unselected. Number recognition is **not verification of
   identity**: select only facts safe for the test caller.
3. Submit the entire configuration with the binding and revision just read:

```bash
cs rpc voice.config.update '{
  "owner_uid": "<UID from get>",
  "space_id": "<space_id from get>",
  "expected_revision": 0,
  "config": {
    "enabled": true,
    "called_number": "+390200000001",
    "instructions": "Use approved stored facts. Ask when information is missing.",
    "caller_context_policy": "selected_facts_only",
    "tools": ["caller_memory"],
    "limits": {"duration_seconds": 120, "max_calls": 2, "budget_microusd": 2000000},
    "customers": [{"blob_id": "<customer blob ID>", "sentence_ids": ["<approved sentence ID>"]}]
  }
}'
cs rpc voice.status
```

The example number is synthetic, not a provisioned route. Updates increment the
revision. Stale revisions return `-32060`; read again before updating. Wrong
binding returns `-32061`. Invalid settings/foreign or missing sentences return
`-32602`. Unknown fields/capabilities, including credentials and `MEMORY_KEY`,
are rejected. Responses contain no server secrets.

The additive profile table `voice_agent_config` stores owner, company space,
revision, settings and sentence fingerprints. It never writes company membership
or memory content. Changed owner/company space hides old settings behind disabled
defaults and `binding_valid: false`; an explicit update can bind new settings.
Missing company memory fails closed (`-32063`). For rollback, resubmit the current
configuration with `enabled: false`, using the current revision, or restore saved
settings. No company-memory or schema rollback is needed.

## Snapshot and retrieval contract

`snapshot_for_call(called_number)` returns immutable settings for an enabled,
matching number. The integrated listener loads this snapshot before emitting the
carrier connection NCCO; updates affect subsequent calls. `voice.status` reports
`configured_enabled` separately from current `calls_available`. `runtime` is
`engine_listener` only inside the opted-in daemon, otherwise `not_integrated`.
The standalone M1 smoke still uses its fixed test response.

`CallerMemory(snapshot, caller_number)` is a read-only `Tool`. The adapter supplies
the phone; model arguments accept only an optional `query`. Initial retrieval and
follow-ups normalize through existing memory-worker rules and reuse
`Storage.find_blobs_by_identifiers`. All company matches count toward ambiguity,
including unselected customers. Unknown, withheld, ambiguous and unselected
numbers receive no customer facts.

Retrieval applies existing company scope and selected customer/sentence IDs
before reading text. Owner rule namespaces cannot be selected. Only approved
sentence columns enter model input: no complete blob, owner prompt, private note
or company capability. Fingerprints of text and creation time reject changed or
replaced sentences; missing/reassigned IDs yield no fact. Keep the fixture frozen
during demonstrations. A configuration update re-approves the selected sentences'
then-current content.

Follow-ups rank word overlap **inside the permitted set**, without embeddings or
paid inference. If no permitted fact overlaps the query (including a language
mismatch), retrieval returns all still-pinned selected facts with
`retrieval: "selected_facts_fallback_no_lexical_match"`. This avoids a false absence
and another model/tool round; it does not claim that the returned facts answer the
query. Exact lexical matches still filter/rank as before. Unknown, ambiguous and
unselected callers still receive no facts. `ToolResult.data` contains `recognition`, `facts` (text,
blob/sentence source IDs, `knowledge: "stored_history"`) and `missing`. Errors
return no facts and fixed messages. History is not a fresh external-system check.
Blocking reads/ranking run in a worker with a three-second default timeout.
Cancellation/timeout suppress results; a running read may finish but cannot write
or deliver a late answer. Binding is rechecked before disclosure. This is a
controlled fixture permission, not a general caller authorization system.

## Limits and verification

Settings default to 120 seconds, two calls and USD2, with validation ceilings of
180 seconds, six calls and USD5. In bounded mode the listener intersects these settings
with M1's saved duration, call count and retained reservations. Configuration can
restrict but cannot increase or reset the original allowance. Engine requests use
the existing profile LLM budget and selected provider; voice/carrier reservations
remain separate. There is no service expiry.

For the explicitly authorized isolated M3 test, saved `VOICE_ENGINE_UNLIMITED=1`
overrides these numeric test ceilings and the engine daily budget. The mode is
restricted to the marked isolated profile without an ordinary `zylch.db`; see
[the smoke guide](gpt-live-smoke.md#m3-handoff). Budget/remaining values are `null`
in this mode, while usage and reservations stay recorded. `/healthz` exposes
`test_limits: "unlimited"`. Paid provider credit requirements still apply.

From `engine/`, using the voice-extra test environment:

```bash
CS_VOICE_KERNEL_PYTHON=<installed-kernel-python> python -m pytest tests/voice -q
```

The fixture creates separate temporary profile/company databases, two customers,
a shared number, approved request/delivery facts, an internal note and foreign
company rows. Tests use real SQLite and RS256 with a synthetic signing key. The
journey runs the actual installed `cs rpc` CLI against the real engine WebSocket
handshake/dispatcher, including wrong-profile refusal.

For live authentication, use credential references from the private preflight:

```bash
PYTHONPATH=. python scripts/voice_m2_demo.py \
  --kernel-python <installed-kernel-python> \
  --firebase-sa <private-service-account-file> \
  --firebase-env <private-file-with-FIREBASE_WEB_API_KEY> \
  --owner-uid <authorized-UID>
```

This source acceptance script needs engine test dependencies and the installed
kernel. It reuses kernel headless mint/exchange and real Firebase verification.
Anonymous pipes supply the CLI's in-memory auth source, bypassing its ordinary
disk ID-token cache; CLI configuration, transport, dispatch and SQLite are real.
Memory is synthetic/temporary. No personal profile is activated, token persisted,
paid call/model invoked, or service/number changed. The report proves M2 only;
M3 integration acceptance and the active M4 audio matrix are recorded under the
[milestone plan](../../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md).

## Integrated isolated daemon (M3)

`engine/scripts/voice_engine_isolated.py` takes an explicit `--profile-dir`,
`--port` (provider HTTP, default 8787) and `--rpc-port` (authenticated WebSocket,
default 8788). It requires the UID-matching `VOICE_ENGINE_ISOLATED_PROFILE` and
M1 test markers, an existing `voice-engine.db`, isolated company memory and no
ordinary populated profile database. It scrubs ambient configuration before
importing engine settings, holds the profile lock and runs `serve_ws` with an
opt-in listener and automatic channels disabled. Never invoke the normal CLI
against a personal UID to start this experiment.

The source-only `scripts/voice_m3_provision.py` creates the frozen M2 synthetic
facts in that private skeleton. It binds the caller from the completed authorized
M1 carrier receipt, creates a separate company store, persists membership through
`memory.join`, and stores a freshly minted Firebase refresh token encrypted through
the existing OAuth table. Credentials are supplied by private file references;
ID tokens travel in anonymous pipes and memory only. It refuses an existing
fixture instead of replacing data. It does not alter the original smoke ledger.

### Dedicated GPT-6 backend for this experiment

The isolated M3 profile explicitly saves `VOICE_ENGINE_PROVIDER=openai`; its
`OPENAI_API_KEY` and `OPENAI_PROJECT_ID` come from the dedicated private test env.
This voice-only selection requires matching OWNER/SMOKE/ISOLATED profile markers
and no ordinary populated database. Ordinary engine provider selection remains
unchanged; its legacy `LLM_PROVIDER` value is retained for the original smoke
ledger's policy identity and does **not** choose this voice backend.

`openai_voice` translates the existing agent/tool loop to Responses with
`model=gpt-6-sol`, `reasoning.effort=none`, `store=false`, standard processing and
only the approved `caller_memory` and `get_current_time` function names.
Each call exposes only its configured subset; unknown tools cannot execute. GPT-Live remains `gpt-live-1`. This short
selected-fact workload uses no hidden reasoning state or provider conversation
storage. Unknown models/options/response shapes fail closed, without fallback.
The common LLM ledger reserves before dispatch and settles actual input, cache
read/write and output usage at verified GPT-6 prices, including the >272K tier.
Uncertain responses retain holds; proved provider refusals release only their own
undispatched-cost reservation. Earlier MrCall liabilities remain untouched.

Preparation checks model access without paid inference. Health is availability,
not evidence of successful reasoning. Activation also requires a separate real
inference/tool demonstration with this dedicated project and the frozen fixture.
No Firebase session, StarChat business or CALLCREDIT is used for this backend.
The unlimited override also bypasses the generic agent's ten-round, local prompt
and tool-result bounds only for isolated customer-service calls; Responses still
has its physical model window and 128,000 output-token capacity.

Official contracts checked 2026-09-24: [GPT-6 Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[functions](https://developers.openai.com/api/docs/guides/function-calling).
The test uses the latest verified generation, never an older model merely to fit
an existing adapter.

Before listening and before each carrier admission, memory/configuration and the
engine client are prepared off the event loop. MrCall uses `ensure_fresh_session`
with the isolated encrypted refresh token even when automatic preparation is off.
A free validated bounded quotation also checks account/business/model compatibility.
The selected saved `SMS_BUSINESS_ID` is forwarded on quotation and execution for
accounts with multiple businesses; a quote for another business is refused.
Quotation does not guarantee a funded credit balance: paid execution may still
refuse insufficient credits. Missing/expired credentials, failed refresh/quotation,
disabled configuration, exhausted engine budget or exhausted call allowance
refuse admission. Personal-key clients
use the saved provider/key without fallback. Direct OpenAI authentication,
inference and selected-memory tools have passed the isolated diagnostic; live
Anthropic/OpenRouter voice-backend authentication has not been demonstrated. `/healthz` reports only runtime availability,
allowing cold-start readiness checks before connecting an operator client.

Only the signed Vonage callback supplies caller recognition metadata. International
digits without a `+` are canonicalized at this carrier boundary. The number stays
in memory behind the one-use carrier nonce; arbitrary SIP `From` metadata is ignored.
After `session.started`, a tracked one-shot `session.instructions.append` requests
an immediate greeting in the configured language/wording, without waiting for
lookup or caller speech. The command asks not to repeat an already-spoken greeting;
acknowledgement is not proof of speech or playback. This explicit start instruction
follows the [official greeting flow](https://developers.openai.com/api/docs/guides/live-conversations#greet-before-the-caller-speaks).
The task is canceled on close. Selected caller context is supplied to GPT-6;
delegated answers use `session.commentary.append`.
Append content is split without loss within a conservative 480-byte bound, below
the provider's 500-token limit. Official contracts:
[delegation](https://developers.openai.com/api/docs/guides/live-delegation) and
[transcripts](https://developers.openai.com/api/docs/guides/live-conversations).

At attachment, initial lookup loads all selected, still-authorized facts for the
recognized caller asynchronously, independently of the greeting. GPT-6 receives
these facts with the accumulated transcript before its first semantic run. The
three-second read timeout or a lookup failure produces empty facts plus missing
information; it does not prevent an answer. Diagnostic delays are explicit test
controls and normally zero. Full facts are no longer independently forwarded as
quiet voice context. GPT-Live is instructed to delegate substantive questions,
follow-ups and every correction, then present the new backend result.
GPT-6 chooses whether the preloaded facts suffice or an enabled tool is needed.
Role-specific rules follow shared configuration in both model instruction paths.
GPT-6 is instructed not to greet; greeting configuration belongs to GPT-Live. Before backend
commentary, GPT-Live may only remain quiet or give a neutral acknowledgement,
except for its initial greeting; it must not claim access, facts or operations.
Backend instructions attribute caller statements and preserve weekday granularity;
a clock alone cannot establish an order date. These are model instructions, not
a deterministic output validator. The 2026-09-24 carrier retest delegates a spoken
correction correctly, but obsolete speech continues during the interruption.
The 2026-09-25 filler experiments fail overall acceptance and are withdrawn;
repetitive waiting announcements and reliable speech ownership remain open.
There is no live shipment/tracking lookup; absent tracking is stated specifically,
without promising a check that an order number would supposedly enable.

Each call owns one GPT-6 customer-service agent using the existing LLM/tool loop
and budget admission. Only configured tools are supplied: `caller_memory` and,
optionally, `get_current_time`. Owner persona, preferences, channel status,
triggers, slash routing and general tools are excluded. No intent keyword router
selects tools. Clock calls require an explicit valid IANA `timezone` and return
`datetime` (ISO timestamp), `timezone`, `utc_offset_seconds` and
`source: "system_clock"`. Invalid arguments return a fixed error without echoing
them. The tool uses Python's system clock/ZoneInfo, executes no shell and reads no
customer/profile data. Configuration may set a default timezone; otherwise GPT-6
asks when the location is unclear. Prompt timestamps and earlier clock results
are not a current reading. Existing configurations remain memory-only unless
explicitly updated; duplicate/unknown capability names are refused.

Transcript fragments accumulate without dispatch. Delegation starts one semantic
run. Each run snapshots transcript text and caller/voice counters before awaiting
work; counters remain diagnostic evidence. Only caller changes invalidate tools,
model dispatch and final answer delivery. Voice acknowledgement alone never
restarts GPT-6 or discards its answer. Every answer fragment checks caller revision
and closure; binding is revalidated before delivery. In-flight paid requests
finish normal accounting; at the next boundary an obsolete caller task stops,
incomplete history is removed and the latest transcript is processed serially.
Completed history is retained. No backend requests run in parallel. After a
superseded run or interrupted answer append, the controller waits for a fresh
delegation at the latest caller revision or 1.2 seconds of input quiet. Further
caller fragments reset that interval; voice output does not. This coalescing is a
cancellable scheduling heuristic, not a provider turn-complete event or a local
conversation ceiling; initial dispatch stays immediate. Diagnostics record the
wait and whether delegation or quiet released it.

The backend can return `[NO_FURTHER_RESPONSE]` when the actual transcript already
fully answers the latest request correctly; this decision is consumed without
commentary. It requires no extra voice-only reconciliation run. GPT-Live must
preserve material missing-information clauses and avoid repeating already-spoken
content. These model behaviors still require telephone evidence: a successful
append is not proof of exact wording or handset playback. M4 remains open.

Hangup, deadline and daemon shutdown cancel asynchronous work and suppress late
results. A dispatched blocking LLM request may finish and settle in its original
worker; uncertain outcomes retain their normal durable hold. It cannot resume the
agent tool loop after cancellation. The call ledger records counts, revision,
lookup timing and failures, never raw transcript/facts or a false zero engine cost;
engine charges remain in the profile's existing LLM ledger. Shutdown allows the
executor to drain; forced termination still retains unresolved reservations.

M3 isolated integration acceptance is **approved**: the telephone demonstration
confirms selected caller recognition, a real GPT-6 tool/result turn and clean
closure. The caller reports timely interruption and correct acknowledgement of
missing tracking, with a repeated answer after interruption. The caller later
reports that the agent seemed not to recall the blue filters; Thursday recall is
unconfirmed. Retrieval success is not evidence that the voice used those facts.
M4 adds opt-in private correlated test transcripts to diagnose this gap (below). Deterministic tests cover
follow-ups and corrections arriving during backend execution. Real backend-only
demonstrations cover sequential follow-up/correction content; this one live call
does not certify M4's complete audio matrix. M4
is active, with live criteria still open. Detailed evidence, usage and independent review are in the
milestone plan. The operator authorizes unrestricted local retests; no further
spending or attempt approval is required.

## M4 private diagnostics

`first_voice_transcript_ms` measures arrival of the first nonempty voice transcript
relative to attachment; `first_voice_provider_start_ms` preserves its provider
speech offset. These are distinct from `first_audio_ms`, the first reflected audio
packet, which may precede speech. None is instrumented handset latency.

The isolated listener supports saved `VOICE_DIAGNOSTICS=1` in its explicit private
profile `.env`. It requires matching OWNER/SMOKE/ISOLATED UID markers, no ordinary
profile database, and a profile outside any Git checkout. Shell flags alone cannot
enable it. Default is off. This setting does not affect the smoke policy digest,
reservation ledger, unlimited mode, normal profiles or provider storage (`false`).

Each attached call creates a randomly named SQLite file under private
`<isolated-profile>/voice-diagnostics/` (directory 0700, file 0600). The call ledger
contains only its basename and capture status. The trace records UTC/local receipt
times, provider timeline offsets, call/config revision, backend run/input revision
and delegation IDs. Separate records hold selected memory results, final backend
answers, superseded answers, attempted/sent append content, server acknowledgements,
caller/voice transcript deltas, clock arguments/results, audio timing ranges and closure. Audio bytes,
hidden reasoning, provider payloads, credential configuration and unselected memory
are never supplied to the sink. Known saved secret values and recognizable token
strings are redacted defensively. Raw traces remain outside Git; retain them until
the operator explicitly requests removal. No new trace reconstructs an old call.

Append acknowledgement establishes provider acceptance, not exact spoken wording
or playback. Transcript/audio overlaps are candidates for interruption diagnosis,
not proof of what reached the handset. Capture starts at sideband attachment;
anything before attachment is not observed. Always pair these observations with
caller listening feedback. A capture error marks evidence `incomplete`; it must
not prevent hangup, accounting or release of the active call. SQLite WAL/NORMAL
keeps per-event diagnostic writes short; unlike the financial ledger this trace
is not a guarantee against power-loss evidence loss.

Explicit test-only fault controls require capture plus the isolated markers:
`VOICE_DIAGNOSTIC_LOOKUP_DELAY` delays each memory invocation asynchronously;
`VOICE_DIAGNOSTIC_BACKEND_DELAY` delays each delegated engine run;
`VOICE_DIAGNOSTIC_FAIL_LOOKUP=1` returns a safe unavailable result without reading
facts. Delays are seconds, finite/nonnegative, and default to zero. They are
scenario controls, not conversation/duration/spending limits. Saved changes take
effect after restarting only the isolated listener while idle. Do not restart the
tunnel. Use service shutdown during a supervised call for forced-closure testing;
restore the listener afterwards and preserve every reservation.

Official event semantics: [transcripts](https://developers.openai.com/api/docs/guides/live-conversations)
and [client delegation](https://developers.openai.com/api/docs/guides/live-delegation),
checked 2026-09-24 against SDK 3.19.0. Live M4 results and unresolved criteria belong
in the existing milestone plan, not in a passing-test claim here.

Read a trace without activating any profile:
`python engine/scripts/voice_diagnostic_report.py /private/path/call-uuid.db`.
Its output includes private dialogue: keep reports outside Git. The renderer
preserves complete transcript text; the underlying SQLite events retain every
original fragment and timing for overlap/repetition analysis.


### Autonomous diagnostic caller

`scripts/voice_m4_auto_call.py` originates scripted carrier TTS calls exclusively
from and to `+390289047081`, with an explicitly marked isolated profile and a
private Vonage application-key path. Scenarios use NCCO `wait`/`talk`; they do not
record audio, modify routing or call an operator handset. The standalone driver
is not registered as an engine/model tool. Its private `M4-autocaller.db` records
intent and a retained reservation before POST, then carrier UUID/status/price.
An uncertain create/closure blocks another origination across restarts; no request
is automatically retried. Known UUIDs receive cleanup and receipt reconciliation.
Currency absent from carrier receipts stays unknown. Incoming voice/model ledgers
continue independently; do not merge provider units into a fictitious USD total.

Automated caller identity is whatever the signed carrier callback supplies. The
test number is not substituted for the frozen customer's phone; unknown caller
handling does not certify known-customer recognition. Exact scripted utterances,
incoming transcripts, tools and commentary establish reproducible provider-path
evidence, not human handset listening. Driver lifecycle tests use mocked HTTP.
Official carrier actions: [NCCO reference](https://developer.vonage.com/en/voice/voice-api/ncco-reference).
