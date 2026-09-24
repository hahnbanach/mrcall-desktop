# Voice agent configuration and memory-backed calls (M2–M3)

<!-- doc-scope:start -->
Scope: authenticated operator configuration, immutable snapshots and read-only
selected-fact retrieval from M2 and the opt-in M3 engine listener. The isolated
listener reuses M1's durable admission and closure ledger. Live M3 acceptance
is recorded in the milestone plan; M4 is separate.
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
paid inference. A query with no overlap (including a language mismatch) is not
proof of absent knowledge: tool instructions require an empty-query read of all
selected facts before claiming absence. `ToolResult.data` contains `recognition`, `facts` (text,
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
M3 integration acceptance and the unstarted M4 audio matrix are recorded under the
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
only `caller_memory` function calls. GPT-Live remains `gpt-live-1`. This short
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
The greeting can start before caller lookup completes. Selected late context uses
quiet `session.thinking.append`; delegated answers use `session.commentary.append`.
Append content is split without loss within a conservative 480-byte bound, below
the provider's 500-token limit. Official contracts:
[delegation](https://developers.openai.com/api/docs/guides/live-delegation) and
[transcripts](https://developers.openai.com/api/docs/guides/live-conversations).

Each call owns one customer-service agent using the existing LLM/tool loop and
budget admission. It gets only configured instructions and `CallerMemory`; owner
persona, preferences, channel status, triggers, slash routing and general tools
are excluded. Transcript fragments accumulate without dispatch. Delegation starts
one request; new input while it runs triggers reconciliation before delivery.
Actual spoken transcript distinguishes a draft from an answer already said, so
corrections can explicitly rectify stale speech. M3 listening confirms timely interruption; the complete spoken-correction and
duplex scenario matrix remains part of unstarted M4.

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
missing tracking, with a repeated answer after interruption. Audible delivery of
both historical facts is not explicitly confirmed. Deterministic tests cover
follow-ups and corrections arriving during backend execution. Real backend-only
demonstrations cover sequential follow-up/correction content; this one live call
does not certify M4's complete audio matrix. M4
remains unstarted. Detailed evidence, usage and independent review are in the
milestone plan. The operator authorizes unrestricted local retests; no further
spending or attempt approval is required.
