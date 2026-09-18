# Shared assistant procedures — opt-in pilot integration

The pilot can load the same immutable instruction artifact into StarChat's
phone model and the engine's existing conversational email loop. **Normal
startup without private operator configuration does not install a pilot route.** This is branch integration, not a
deployed customer feature or an automatic inbox classifier.

## Content, authority and execution

StarChat owns the canonical JSON resource
`src/main/resources/assistant-procedures/order-existence.json`. Trusted setup
passes its exact bytes and expected SHA256 revision to `ProcedureArtifact.parse`.
The engine maintains no second procedure copy or new artifact database. A
revision covers instructions, operation allowlist, completion type and reviewed
response messages. A digest verifies integrity, not authorship or permissions.

`assistant.installation.InstallationSpec` parses the separate, non-executable
installation envelope: version, ID, exact business/procedure revision, and named
connection/authority references. It matches StarChat's strict six-field, 4 KiB,
exact-byte SHA256 contract. Reference names do not resolve themselves or confer
authority; credentials and contact grants remain separate trusted inputs.
No production installation file is copied into the engine.

Instructions guide model decisions. The only advertised operations are
`capability_read(operation)` and `procedure_finish(status, include_memory)`.
Neither accepts an endpoint, company, contact, recipient, receipt or answer body.
The model chooses reads and clarification; deterministic code checks the result.
Current order existence requires the latest matching read from this invocation.
Approved memory is optional context, never evidence of a current order.
The runtime prompt also states whether trusted admission bound an authorized
contact, without disclosing its identifiers. A bound contact may finish with
`need_identification` only after the latest accepted `order.exists` result reports
that status. An unbound contact may clarify without a read and receives no read
tool. A new read retires prior evidence before provider IO, including when the
refresh fails. `unavailable` remains a legal safe completion. These host checks
do not change the canonical artifact bytes, revision or invocation budgets.

The initial response renderer is intentionally finite: reviewed artifact messages
plus explicitly approved memory sentences. This does not implement unrestricted
multilingual replies, arbitrary business workflows or identity verification.
Shipping, calendar integrations and memory writes are outside this increment.

## Actual email path

`services.procedure_installation.PilotProcedureInstallation` composes one trusted
spec, artifact and capability binding with supplied provider/memory/scope
dependencies. It owns one scoped service, its existing reserved endpoint and a
shared two-slot email executor. The endpoint retains its separately bounded
transport executor. Preflight checks local agreement without calling the
provider, model or token verifier; readiness explicitly leaves live operation
unverified.

```text
ONE COMPANY INSTALLATION
          |
 explicit source + owner + recipient/contact authorization
          |
     prepare_email
          |
  PreparedEmail.route -> existing ChatService -> controlled draft
          |
     handle.close() -> retire this selection; installation remains
```

Only one email handle may be prepared at a time. Its context-manager/close
lifecycle releases selection admission, not running SDK work: abandoned work
keeps its slot in the installation's shared pool until it actually finishes.
Installation close retires the active handle and denies new preparation and
pending scoped results, including those on the retained remote endpoint.
Selections and contact evidence are never carried into a later handle.

The preparation API is not installed into ordinary owner chat. The opt-in
WebSocket startup below exposes one manual owner RPC. It does not search a
mailbox, identify a customer or create disclosure grants.

`ChatService(pilot_email_route=...)` intercepts at the beginning of
`process_message`, before owner commands, notifications, auto-sync and tools.
The trusted route binds one selected incoming email, its addressing/content
digest, recipient, approved contact and scoped engine service. The request's
`context.email_id` can match this selection; it cannot establish authority.
Wrong selection or changed scope refuses without falling through owner chat.
The ordinary `chat.send` RPC still constructs ChatService **without** this route.

`PilotEmailRoute` creates a fresh `ZylchAIAgent` with `ProcedurePolicy` and no
owner tools/history/private notes. It reuses the existing conversation loop and
guarded `LLMClient.create_message_sync`, including provider policy and durable
budget reservation/settlement. It adds no second reasoning loop or funding path.
The two-slot executor retains admission until abandoned blocking work actually
finishes; no per-invocation executor or unlimited pending queue is created.

Limits: 15 seconds per invocation, four model requests, six tool calls, four
reads and 4,000 reply characters. The loop requests 1,024 output tokens per model
request; the shared guarded client's model-specific reasoning policy applies.
Each scoped read keeps its existing three-second horizon. The route owner must
call `close()` at shutdown; closure refuses further output/admission.

For K3 over OpenRouter or MrCall credits, the shared client promotes the request
to adaptive/max reasoning with an 8,192-token **combined reasoning/final-output**
ceiling, exactly as for ordinary engine workers. The restricted policy supplies
no model-specific override. Quotation and reservation see this final ceiling;
settlement uses actual receipt cost. Truncation does not authorize tools or
trigger a larger retry. This compatibility is checked through the actual guarded
client with synthetic HTTP/quote edges, not certified as live K3 quality or
latency within the unchanged 15-second invocation deadline.
See the [budget correction record](../../../docs/execution-plans/2026-09-16-pilot-k3-upstream-budget.md).

Only an accepted controlled completion reaches the existing `CreateDraftTool`.
The adapter rereads source and scope, checks deadline and delivers cancellation
before persistence. Recipient, subject and threading come from the pinned source,
not model arguments. A failed refresh invalidates earlier successful evidence.
Raw model prose becomes a controlled inability-to-verify draft, never an order
assertion. Expired/cancelled/rebound invocations create no draft. No send tool is
exposed, and existing later send approval remains unchanged.

## Private startup and manual invocation

`zylch serve` (TCP or Unix WebSocket mode) reads `MRCALL_PILOT_CONFIG` only when
explicitly set. The value must be an absolute path to a private regular JSON file
(no group/other permissions, owned by the service UID or root). An absent variable
preserves ordinary startup. An empty value, missing file, malformed configuration,
expired grant or mismatched profile aborts startup before listening.

The strict object has exactly these fields; identifiers and paths below are
placeholders, never deployment values:

```json
{
  "version": 1,
  "installation_path": "/private/installation.json",
  "installation_revision": "<sha256 of exact installation bytes>",
  "procedure_path": "/private/order-existence.json",
  "procedure_revision": "<sha256 of exact canonical procedure bytes>",
  "profile_uid": "<actual owner Firebase UID>",
  "company_key": "<actual profile MEMORY_KEY>",
  "service_uid": "<dedicated Firebase service UID, different from owner>",
  "contact_ref": "<bounded rehearsal contact reference>",
  "contact_email": "customer@example.com",
  "owner_email": "operator@example.com",
  "issued_at_ms": 0,
  "expires_at_ms": 0,
  "clone_dir": "/private/selected-clone"
}
```

Replace both timestamps with epoch milliseconds: issuance must be at or before
now, expiry after now, and the activation window at most 24 hours. The pinned
installation supplies the business ID and connection/authority reference names;
its canonical schema and the canonical procedure are unchanged. Runtime grants
permit only `order.exists`; memory interfaces remain available to other trusted
compositions, but this activation supplies no memory grant.

The actual daemon profile must match `OWNER_ID`, `MEMORY_KEY` and `EMAIL_ADDRESS`.
The selected clone's `manifest.toml` is loaded through the installed cs-kernel
config resolver, and its resolved `engine_owner_uid` and `email_address` must
match, including raw manifest declarations before environment overrides.
Startup passes an explicit manifest path without changing process environment or
working directory. Kernel environment layers use the service user's home and
the selected manifest's sibling `.env`; prepare those layers or its private environment rather
than copying another owner's engine profile/session. The kernel must include
`cs.shopify_client`. Each read resolves the existing cached/renewable Shopify
token and uses the existing customer fetch; no provider secret belongs in this
JSON, a request, a model argument or logs.

The reserved `/assistant-capabilities/v1` WebSocket endpoint verifies the
dedicated service bearer independently from owner RPC. For email, authenticate
as the real profile owner and explicitly select one stored inbound email:

```bash
cs rpc pilot.email.draft '{"source_id":"<stored inbound email ID>"}'
```

Run from the configured clone using its existing authenticated owner RPC client.
Only `source_id` is accepted. Sender must equal the granted contact; recipient
must equal the configured owner mailbox. Owner, source ID and addressing/content
are pinned and rechecked throughout. No arbitrary recipient or caller email can
grant access. Connection token expiry and activation expiry are checked during
reads/output; the normal owner-connection expiry grace is not used for this RPC.
It returns the controlled response and draft ID, and never sends or starts inbox
processing. Firebase UID remains the invocation identity, while the frozen
selection separately binds storage ownership to the configured mailbox, matching
the engine's existing `get_owner_id()` and ordinary email/draft RPC. The mailbox
binding is checked again throughout the invocation; a changed active mailbox
refuses pending output. Trusted offline compositions that omit this storage
binding retain UID ownership.

The result is an engine SQLite draft, visible through ordinary `drafts.list`.
`CreateDraftTool` does not append it to IMAP/Gmail Drafts. Such publication is a
separate mailbox operation, not part of this pilot RPC.
Other `chat.send` requests retain their normal path. Shutdown and
failed socket startup close the installation; remove the activation environment
variable and restart to retire it (leaving it pointed at a missing file fails
closed).

## Verification and remaining work

`tests/services/test_procedure_email.py` exercises the actual ChatService/core,
real guarded LLM budget ledger, scoped memory/order projection and temporary
SQLite draft rows. Only outbound model/provider responses are fixtures. Tests
also cover bypasses, source/binding changes, no-order versus unavailable, private
context exclusion and cancellation. `tests/assistant/test_procedure_policy.py`
covers deadline, duplicate/tool/read bounds and invalid memory evidence.

Standalone engine tests use a deliberately synthetic contract fixture. Set
`MRCALL_PROCEDURE_SOURCE` to StarChat's canonical resource to run the same tests
against the real shared artifact. This proves protocol composition and revision
loading, not live model quality, phone latency or deployed reachability.

`tests/services/test_procedure_installation.py` is the runnable preparation
example: it constructs the installation, prepares two different contacts and an
unidentified source in turn, runs actual ChatService/core/scoped reads and checks
real temporary SQLite drafts. Its lifecycle cases cover pending remote reads,
closed handles, source-fetch revocation and occupied shared worker slots.
`test_procedure_installation_readiness.py` checks local-only preflight and
resource ownership. To use the canonical installation fixture too, set
`MRCALL_INSTALLATION_SOURCE` to StarChat's
`src/test/resources/assistant-procedures/installation-example.json` alongside
`MRCALL_PROCEDURE_SOURCE`. Neither environment variable activates runtime code.

`tests/services/test_live_pilot.py` reaches actual `serve_ws`, authenticated owner
RPC, reserved capability transport and the existing restricted ChatService/draft
tool against temporary SQLite. It checks opt-out, invalid grants, connection
authority, recipient/sender mismatch, expiry during model work, shutdown, and the
kernel credential/fetch boundary with synthetic external edges.

The isolated Cafe124 hosted engine has a private, expiring pilot activation.
Dedicated service authentication, hosted capability connectivity and scoped
Shopify reads pass live probes. The selected real email produces an unsent
`order_exists` engine draft in 12.02 seconds through the configured K3 client.
The kernel can mirror that draft into the mailbox for review; this is an explicit
operator step, not an automatic effect of `pilot.email.draft`. Desktop's Drafts
tab is a placeholder and does not display engine draft rows.
Controlled phone acceptance, general latency and broader quality remain open;
one email rehearsal does not certify them. The current activation work trace is hb's
`docs/execution-plans/2026-09-17-mrcall-live-pilot.md`.
The cross-repo scope and review ledger live in hb's
`docs/execution-plans/2026-09-16-mrcall-shared-procedure.md` and
`docs/execution-plans/2026-09-16-mrcall-pilot-installation.md`.
