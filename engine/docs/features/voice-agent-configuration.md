# Voice agent configuration, memory-backed calls and diagnostics (M2–M4)

<!-- doc-scope:start -->
Scope: authenticated operator configuration, immutable snapshots and read-only
selected-fact retrieval from M2, supervised production on-demand review,
the opt-in M3 engine listener and M4 private diagnostic/transcript capture,
the optional clock capability and autonomous diagnostic caller.
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

In `selected_facts_only` mode, retrieval applies existing company scope and
selected customer/sentence IDs before reading text. Owner rule namespaces
cannot be selected. Only approved sentence columns enter model input: no
complete blob, owner prompt, private note or company capability. Fingerprints
of text and creation time reject changed or
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

### Production on-demand review (supervised pilot)

`caller_context_policy: "on_demand_review"` is available only in production
with one configured customer, an approved display name, `caller_memory`, and no
pinned sentences. The initial lookup resolves recognition and name only. A
caller utterance and GPT-Live client delegation are required before a history
read. The server uses the current caller transcript and the carrier-bound
number; the model cannot supply a different phone, blob or owner.

The read is limited to that uniquely matched contact's company-scoped sentence
rows. It refuses more than 24 rows or 12,000 bytes rather than returning a
partial history. Explicit internal/confidential markers and common credential
formats are excluded;
email addresses and international phone numbers are replaced before model
input. Obvious requests for credentials or another person's private data are
declined before reading memory. GPT-Live receives remaining sentences as
untrusted historical candidates and decides what relevant, appropriate part
answers the caller. A broad question such as “what do you know about me?” may
return several candidates; it does not require a verbatim inventory. This mode
does not promise that model judgment can reliably classify every mixed note.

The production diagnostic event table records recognition, candidate counts,
byte lengths and event timing in this mode, without source text, caller
questions or appended content. A separate private `transcript_deltas` table
retains exact provider transcription for both sides of the call. It is a call
record, not a memory candidate or debug event; its text is not scrubbed, and
the file is mode 0600 under a mode 0700 directory. Selected-fact mode retains
its original pin behavior. The production binding and config revision are
rechecked before client commentary leaves the engine; an invalidated call
suppresses further results. Supervised handset listening is still required to
assess what GPT-Live actually said.

## Limits and verification

Settings default to 120 seconds, two calls and USD2, with validation ceilings of
180 seconds, six calls and USD5. In bounded mode the listener intersects these settings
with M1's saved duration, call count and retained reservations. Configuration can
restrict but cannot increase or reset the original allowance. Current telephone
delegations do not dispatch engine LLM requests; voice/carrier reservations remain
separate. There is no service expiry.

For the explicitly authorized isolated M3 test, saved `VOICE_ENGINE_UNLIMITED=1`
overrides these numeric test ceilings and the engine daily budget. The mode is
restricted to the marked isolated profile without an ordinary `zylch.db`; see
[the smoke guide](gpt-live-smoke.md#m3-handoff). Budget/remaining values are `null`
in this mode, while usage and reservations stay recorded. `/healthz` exposes
`test_limits: "unlimited"`. This does not alter external provider billing.

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

### Current telephone runtime: GPT-Live with selected context (M4)

The active isolated listener uses `gpt-live-1` as its sole conversational model.
The per-call engine GPT-6 agent, paid dispatch, tool-selection loop and fallback
are removed from `services/voice/`. Other engine LLM workflows and the historical
usage ledger remain intact. Admission validates the company binding and the
existing carrier reservation; it does not initialize an engine LLM client or
reserve a telephone backend inference. The isolated profile's old
`VOICE_ENGINE_PROVIDER` setting is historical and ignored by this listener.

The signed carrier callback supplies the phone used for recognition, not proof of
identity. Each call loads one immutable configuration snapshot. Live receives the
configured greeting and conversation rules in the initial session instructions;
a one-shot instruction after `session.started` requests immediate speech. The
engine starts a read-only selected-fact lookup concurrently. Only matched,
selected, pinned customer sentences enter `session.thinking.append` with a null
delegation ID; unknown and ambiguous callers receive an explicit no-facts
context. The reviewed isolated configuration revision contains no
customer-specific example facts; saved instructions require the same check on
later revisions. Stored history
is labeled as historical, not a current order or shipment check. Neither a
transcript event nor a context append starts paid reasoning.

Live answers ordinary questions directly from available selected context. For a
client delegation, the engine joins any initial lookup already running and
associates the delegation ID with accumulated caller transcript. It supplies
question-bound `session.commentary.append` only for missing context, an enabled
fresh clock read, or explicit unavailability. `get_current_time` uses the existing
read-only `CurrentTime` tool with a valid IANA zone, ISO timestamp and UTC offset.
The configured Europe/Rome default applies when the question omits a zone. No
shipment/tracking or booking tool is exposed; a delegated request for those
functions receives an unavailable result. Opening-hours/open-now requires a
verified schedule, timezone and exceptions; this isolated configuration has no
such input, so the engine reports it unavailable. There is no speculative
anti-repetition controller.

Caller corrections invalidate an in-flight result by input revision. Hangup and
shutdown cancel pending work and suppress late appends. Binding is checked again
before commentary disclosure. Provider acknowledgements are recorded separately
from output transcript and human listening. The shared M1 ledger retains every
old and new hold; service and tunnel have unlimited lifetime in the authorized
isolated mode. The [completed plan](../../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md#current-m4-plan--live-uses-selected-context-engine-supplies-new-results)
records carrier tests, observed failures, operator acceptance and evidence
limits.

M3 used a dedicated `gpt-6-sol` Responses backend; its approval, usage rows and
old reservations are historical evidence. The adapter code remains available to
settle/read that historical transport but no telephone runtime imports it.

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
times, provider timeline offsets, call/config revision, input revision
and delegation IDs. Separate records hold selected memory results, delegated
tool results, suppressed stale appends, attempted/sent append content, server acknowledgements,
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
Its output includes private dialogue: keep reports outside Git. For new calls,
the renderer reads exact fragments and provider timing from the private
`transcript_deltas` table. Older isolated traces can still use transcript text
in diagnostic events. The production capture is prepared before Live accepts a
call, and the greeting is held until sideband attachment. A failed transcript
write stops the call and marks capture incomplete. A call with no provider text
is marked `no_provider_text`, not transcribed. This records provider transcript
events, not a verified verbatim audio recording. The current Cloudflare route
does not create a StarChat conversation; the available StarChat API cannot
import one, so remote archival remains a separate backend integration.


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
