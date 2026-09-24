# Voice agent configuration and selected caller memory (M2)

<!-- doc-scope:start -->
Scope: authenticated operator configuration, immutable snapshots and read-only
selected-fact retrieval delivered in M2. Telephone/agent orchestration belongs
to M3; M1's isolated smoke and durable ledger remain independent.
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
matching number. Updates affect later snapshots. This is the M3 integration
seam: **M2 does not attach these settings to M1 phone calls**. `voice.status`
reports `configured_enabled` separately from `calls_available: false` and
`runtime: "not_integrated"`.

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
paid inference. `ToolResult.data` contains `recognition`, `facts` (text,
blob/sentence source IDs, `knowledge: "stored_history"`) and `missing`. Errors
return no facts and fixed messages. History is not a fresh external-system check.
Blocking reads/ranking run in a worker with a three-second default timeout.
Cancellation/timeout suppress results; a running read may finish but cannot write
or deliver a late answer. Binding is rechecked before disclosure. This is a
controlled fixture permission, not a general caller authorization system.

## Limits and verification

Settings default to 120 seconds, two calls and USD2, with validation ceilings of
180 seconds, six calls and USD5. They are future admission settings, **not a new
ledger**. M1 independently enforces its existing saved limits and reservations;
M2 updates neither increase nor reset that allowance. There is no service expiry.
M3 must combine settings with durable admission before enabling calls.

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
conversation and live memory audio acceptance remain in M3/M4 under the
[milestone plan](../../../docs/execution-plans/2026-09-23-gpt-live-engine-integration.md).
