# Shared assistant procedures — inactive pilot integration

The pilot can load the same immutable instruction artifact into StarChat's
phone model and the engine's existing conversational email loop. **Normal
startup does not install a pilot route.** This is branch integration, not a
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

The preparation API is not installed into ordinary owner chat or CLI startup.
It does not search a mailbox, identify a customer or create disclosure grants.

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

Still required before a live pilot: owner-authorized publication/configuration,
actual business/profile/service/contact bindings, source selection/identity policy,
provider installation, supported phone bridge construction, billing readiness,
controlled live call/email rehearsal and normal StarChat PR/team release.
The cross-repo scope and review ledger live in hb's
`docs/execution-plans/2026-09-16-mrcall-shared-procedure.md` and
`docs/execution-plans/2026-09-16-mrcall-pilot-installation.md`.
