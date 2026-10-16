# Preserved operator runtime

Scope: the engine's optional read-only MCP listener, exact-draft RPCs, scheduled
reply provenance and email-only sync. Hosted installation and acceptance state
belong to the [effective-runtime plan](../../../docs/execution-plans/2026-10-16-m10-current-runtime-integration.md),
not to this source contract.

## Optional Linux listener

`zylch -p <uid> serve --unix <profile-socket> --operator-config <config.json>`
adds an authenticated MCP resource in the same process. Existing
`--voice-config` remains independently optional. A failed MCP listener retires
the shared daemon lifecycle. Ordinary profiles without the flag keep the
ordinary WebSocket listener; copying source does not enable MCP for them.

`operator_mcp/runtime.py` loads and rechecks its bound profile configuration.
It requires Linux and an absolute, unused Unix-socket path in a private parent
owned by the daemon user. Cleanup removes only the socket identity it created.
The process owns signals; the optional Uvicorn server does not replace that
handler. Protected configuration permissions, real issuer connectivity and
tenant binding must also pass installed acceptance.

The catalog contains exactly five read tools:

| Tool | Evidence boundary |
|---|---|
| `operator_identity` | Verified grant's profile/company identity; no global client session. |
| `search_email` | Bounded ordinary-mail synced evidence for the granted mailbox; no synchronization or model call. |
| `read_email` | Exact selected source and thread; unsupported PEC or unknown provenance refuses. |
| `customer_context` | Partial ordinary correspondence for an exact participant of the selected source. No stored memory, standing instructions or attachment contents. |
| `list_drafts` | Existing unsent drafts with source provenance inside the mailbox grant. |

Each invocation verifies the access token again, obtains a current bound grant
and checks expiry; reads taking more than five seconds revalidate before
delivery. Resource/scope, approved client, profile/company/mailbox and selected
participant/owner checks remain server-side. Unknown arguments and malformed
limits refuse at the actual SDK boundary. Tool read-only annotations alone are
not the authorization boundary. Missing/unavailable evidence grants no action.

Installation needs the `operator-mcp` extra (`mcp==1.30.0`,
`uvicorn>=0.54,<0.55`, `jsonschema>=4.23,<5`) and the actual `cs.operator_read`
contract. The installed dependency includes `ReadOperator.customer_context`
and `customer_address`; its source SHA256 is
`3ab4969b3c3d61af473d418438edd82623cdeda9356337ef342979d9ac79e911`.
Distribution metadata `cs-kernel 0.51.0` alone cannot establish this contract.
Its exact frozen source and the two noncanonical installed MCP implementations
are retained in the [preservation evidence](../../../docs/evaluations/2026-10-15-m10-runtime-preservation.md).
No kernel replacement is published by this engine candidate.

## Exact drafts and scheduled origin

The [IPC contract](../../../docs/ipc-contract.md#preserved-operator-integration)
owns `drafts.inspect`, `drafts.discard_exact` and `drafts.reconcile_external`.
They resolve the authenticated owner/profile, use current persisted snapshots
and preserve private writer/CAS, assignment and read-only authority. Explicit
external reconciliation verifies an already delivered message independently;
it does not infer delivery from a caller label or perform a send.

`system.capabilities.operator_reply_provenance=1` advertises scheduled-origin
support. Validated versioned origin enters before ChatService construction.
Exact source/assignment admission precedes the send claim; the claimed draft
is reread and its matching binding spans transport handoff. Only that genuine
scheduled reply receives automatic provenance. Manual, delayed, failed or
identity-changed requests cannot inherit it. Emitted RFC References are stored;
old incomplete Sent rows are not backfilled.

The [assignment contract](task-assignment.md) retains bounded component ancestry,
the shared provider deadline, complete Sent discovery and refusal on conflicting
or incomplete observations. Component aliases retain the exact reply target and
owner-scoped original source. Exact live ancestry proof may supply missing
historical References; historical rows are not rewritten. Known UNKNOWN
observations precede positive-witness shortcuts, and malformed Sent observations
grant no complete assignment or send authority. These checks complement M10's contextual-email
company authority; they do not replace it or authorize external/manual mailbox
writes.

## Email-only synchronization

`sync.run(days_back?, scope="all")` uses the existing full source-only sync by
default. Explicit `scope="email"` accepts integer history from 1 to 60 days,
excludes WhatsApp and AI preparation, and returns named structured failures for
invalid scope/history or a busy worker. Unknown parameter names refuse at the
RPC dispatcher. Cancellation does not release the single-flight lock while
its worker still runs; the worker owns release on completion. No paid memory
processing is started by this route.

## Acceptance and installation limits

Installed SDK and isolated listener tests establish their fixture cases and
private dependency compatibility. They do not establish live protected
configuration, real issuer introspection, source quality or two-clone operational
acceptance. The [replacement evaluation](../../../docs/evaluations/2026-10-16-m10-current-runtime-integration.md)
binds complete effective-runtime inventories, installed wheel/runtime resources,
copied reopening, per-unit switch/rollback and unrun deployment gates. Earlier
base-only captures and wheels without model JSON cannot authorize a current
switch. Successful operational acceptance and the runtime owner's service-window
release remain prerequisites. A generic shared-checkout or
tenant-helper update is not equivalent to that scoped installation proposal.
