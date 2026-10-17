# Tools and engine RPC mapping

<!-- doc-scope:start -->
Scope: sequence descriptions for candidate tools and engine RPC mapping, plus proposed remote governance, budgets, audit, procedure authority and native draft identity. Existing, candidate and proposed behavior remain separate.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

Implementation status and transport boundaries: [data-flow index](../operator-data-flows.md#implementation-status-and-navigation). Each case labels existing, candidate or proposed behavior.

## 5 · All reads: six tools and their RPCs

**Status: LOCAL CANDIDATE MAPPING — remote port unimplemented.**

M is the adapter and E the engine method layer; in the remote design they share one profile process. These are alternative calls, not a mandatory sequence on every request. The checks in case 4 apply to the remote proposal. Mail, tasks and drafts belong to the profile; projects follow company-memory permissions. The remote design adds source-class filtering, with Qonto/finance and PEC excluded by default, including derived content. The AI client does not read Gmail/IMAP directly.

```mermaid
sequenceDiagram
autonumber
participant C as AI MCP client
participant M as MCP adapter
participant E as Engine
alt list_tasks(limit)
C->>M: tools/call list_tasks
M->>E: tasks.list(include_completed=false, limit)
E-->>M: Authorized tasks
M-->>C: Tasks
else list_drafts(limit)
C->>M: tools/call list_drafts
M->>E: drafts.list(status=draft)
E-->>M: Profile draft list
M->>M: Apply limit to the response
M-->>C: Limited drafts
else search_email(query, limit)
C->>M: tools/call search_email
M->>E: emails.search(query, folder=all, limit, offset=0)
E-->>M: Threads and synchronized mail results
M-->>C: Search results
else read_email(thread_key, source_email_id)
C->>M: tools/call read_email
M->>E: emails.list_by_thread(thread_id=thread_key)
E-->>M: Emails in the permitted thread
M->>M: Select exactly one email by source_email_id
M-->>C: Exact email or missing/ambiguous error
else list_projects(limit)
C->>M: tools/call list_projects
M->>E: projects.list(limit, offset=0)
E-->>M: Accessible project metadata
M-->>C: Project metadata
else read_project(project, path)
C->>M: tools/call read_project
M->>E: projects.read(project, path)
E-->>M: Base64 content + metadata, revision, size and SHA256
M->>M: Verify metadata/hash, 64 KiB limit and UTF-8 decoding
M-->>C: Verified text document or error
end
```

## 6 · operator_context: procedures and file authority

**Status: LOCAL CANDIDATE MAPPING — local files; server workspace unimplemented.**

W is the canonical workspace on the computer in this candidate only; the engine holds derived, revisioned copies. The proposed remote product instead makes revisioned engine records canonical, as shown in case 14. This tool accepts no arbitrary computer path.

```mermaid
sequenceDiagram
autonumber
participant C as AI MCP client
participant M as MCP adapter
participant W as Canonical workspace files
participant E as Engine
C->>M: tools/call operator_context or resources/read guidance
M->>W: Read AGENTS.md and permitted company/*
W-->>M: Charter and canonical text
M->>M: Compile instructions, calculate hashes and missing slots
loop For each compiled document
M->>E: projects.read(operator-instructions, path)
E-->>M: Published base64 document + metadata
M->>M: Verify bytes/hash, compare with compilation
end
M-->>C: Identity, company, charter, content and publication current/stale/unverifiable
Note over M: A read does not publish or change procedures
Note over W,E: Canonical files and engine copy are distinct authorities, Save verifies alignment
```

## 7 · ask_operator: a company-memory question

**Status: LOCAL CANDIDATE MAPPING — engine-enforced read-only policy.**

The ChatGPT/Claude conversation model and the engine API model are separate processing steps with separate credentials and costs. Internal reads depend on the question; the engine-model arrow represents selected context, not the entire memory.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant C as AI UI / client
participant M as MCP adapter
participant E as Engine
participant S as Profile and company data
participant L as Engine LLM provider
U->>C: Question about the company
C->>M: tools/call ask_operator(question)
M->>E: system.capabilities
E-->>M: Policy versions
alt chat_read_only_policy differs from 1
M-->>C: policy_missing, no chat.send
else Supported policy
M->>E: chat.send(message, new conversation_id, mutation_policy=read_only, policy_version=1)
E->>E: Enforce read-only policy and spending control
opt Context and generation required
E->>S: Permitted relevant reads
S-->>E: Selected context
E->>L: API request with question and selected context
L-->>E: Response / tool requests subject to engine policy
end
E-->>M: Read-only response or refusal/error
M-->>C: MCP result
C-->>U: Response in the conversation
end
Note over E,L: May consume engine budget in addition to the ChatGPT/Claude subscription
```

## 8 · prepare_reply: exact draft, retries and uncertain outcomes

**Status: LOCAL CANDIDATE MAPPING — no MCP email sending.**

Capabilities, procedures and source checks also precede returning a completed result. operation_id is an adapter idempotency key; it is not forwarded as native chat.send idempotency. An uncertain outcome requires draft inspection.

**Attribution limit:** matching source/thread/reply_binding and a before/after difference identifies a matching draft, not necessarily the draft caused by this call. A concurrent Desktop or connector operation may change the same source-bound draft. The flow does not establish a request-specific correlation or exclusion of competing writers; that design requirement remains unresolved. A completed adapter receipt prevents repeat submission but does not prove causal ownership of the draft.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant C as AI MCP client
participant M as MCP adapter
participant W as Workspace and receipts
participant E as Engine
participant L as Engine LLM provider
U->>C: Prepare a reply to this email
C->>M: prepare_reply(thread_key, source_email_id, instruction, operation_id)
M->>E: system.capabilities
E-->>M: contextual_email_policy=1 and assignment_draft_policy=1 required
M->>W: Read canonical instructions
W-->>M: Compilable text
M->>E: projects.read to compare published procedures
E-->>M: Published copies for verification
M->>E: emails.list_by_thread(thread_id=thread_key)
E-->>M: Thread email collection
M->>M: Select exactly one email by source_email_id
Note over M: Missing policy/procedures/source: error before generation
M->>W: Under lock, find operation_id receipt and compare payload
W-->>M: Absent, completed, pending or different payload
alt completed with the same payload
M-->>C: Stored result, no new chat.send
else ID reused for a different payload
M-->>C: operation_conflict
else pending receipt or previous uncertain outcome
M-->>C: outcome_unknown, use list_drafts to inspect
else New operation
M->>E: drafts.list(status=draft) before
E-->>M: Initial draft state
M->>W: Store pending receipt with payload hash
M->>E: chat.send(instruction, email_context, contextual policy 1, assignment_thread_key, assignment policy 1)
E->>E: Apply contextual, source and assignment policies
opt Generation permitted
E->>L: Email context and relevant instructions to create draft
L-->>E: Draft proposal / tool requests
E->>E: Create or update permitted engine draft
end
opt Approval request arrives
E-->>M: chat.pending_approval(tool_use_id) notification
M->>E: chat.approve(tool_use_id, mode=deny)
E-->>M: Refusal recorded
end
alt Success response received and connection valid
E-->>M: chat.send result
M->>E: drafts.list(status=draft) after
E-->>M: Final draft state
M->>M: Require exactly one changed draft with exact source/thread/reply_binding
alt Unique matching draft found
M->>W: Store completed receipt and result
M-->>C: draft + operation_id + sent=false
C-->>U: Matching draft available for review, causal attribution unproven
else No unique verified draft
M-->>C: draft_unverified, receipt remains pending
end
else RPC error, disconnect or timeout after pending
opt RPC error response received
E-->>M: JSON-RPC error
end
M->>M: Detect error or missing response, retain pending
M-->>C: Unverified outcome, no blind retry
end
end
Note over M,E: chat.approve is only an internal denial RPC, not an exposed send tool
Note over M,E: Source binding is not request attribution, concurrent writers remain an unresolved boundary
```

## Nine-tool mapping

This table describes the isolated local candidate, not a released or main-branch MCP service.

| Tool | Source / engine RPC | Result boundary |
|------|---------------------|-----------------|
| `operator_context` | `AGENTS.md + permitted company/* files; projects.read(operator-instructions, path)` | Read and compare publication |
| `list_tasks` | `tasks.list(include_completed=false, limit)` | Private profile tasks |
| `list_drafts` | `drafts.list(status=draft); adapter applies limit` | Private engine drafts |
| `search_email` | `emails.search(query, folder=all, limit, offset=0)` | Synchronized profile mail |
| `read_email` | `emails.list_by_thread(thread_id); exact selection by ID` | One exact email |
| `list_projects` | `projects.list(limit, offset=0)` | Permitted company metadata |
| `read_project` | `projects.read(project, path); metadata/SHA256 and UTF-8 verification` | Text document up to 64 KiB |
| `ask_operator` | `system.capabilities + chat.send with read_only and policy 1` | Response; engine cost possible |
| `prepare_reply` | `capabilities + context + source + drafts.list before/after + chat.send; chat.approve only deny` | Persistent draft, sent=false |

## Remote access, cost and errors

**Status: UNIMPLEMENTED REMOTE REQUIREMENTS.** Cases 5–8 describe the local
candidate; the requirements below must be built before remote beta.

| Scope | Tools | Independent limits |
|---|---|---|
| `operator.read` | context and six read tools | current company policy and source classes |
| `operator.ask` | `ask_operator` | source classes, paid MCP pool and grant quota |
| `operator.draft` | `prepare_reply` | source classes, paid MCP pool, native draft identity |

All tools carry accurate effect annotations. `readOnlyHint` and `destructiveHint`
are descriptions, not permission checks or guaranteed confirmation prompts.
Email and document text never grants additional authority. Preparing without
sending reduces action damage; read results already disclose data to the AI provider.

| Outcome | Response boundary |
|---|---|
| Invalid/expired token or revoked grant | HTTP authentication refusal, no admitted operation |
| Insufficient OAuth scope | HTTP 403 with insufficient_scope challenge, no admitted operation |
| AS unavailable | Service unavailable, no admitted operation or business result |
| `data_class_denied`, `company_disabled` | current data-policy refusal, no permitted data or model dispatch |
| `policy_missing` | unsupported exact engine policy contract, no generation |
| `budget_exhausted`, `rate_limited` | no model dispatch, no daemon-budget fallback |
| `operation_conflict` | native key reused for a different payload |
| `outcome_unknown`, `draft_unverified` | inspect operation/draft, no blind regeneration |
| Grant revoked during admitted work | result withheld, recorded work/cost may remain |

Admitted tool failures use `isError=true` with a structured code, retry guidance
and a nonsecret correlation reference. Authentication/admission failures retain
HTTP semantics. Never expose token, raw provider error or private payload in errors.

## 12 · Company policy and connected-client management

**Status: UNIMPLEMENTED REMOTE REQUIREMENT.**

```mermaid
sequenceDiagram
autonumber
actor U as Company admin or profile user
participant D as Desktop
participant A as Central MrCall authorization
participant C as Provider MCP client
participant M as Profile MCP endpoint
U->>D: Open connected clients and authorized activity
D->>A: Authenticated request with actor/company rights
A-->>D: Permitted grant metadata, last use and scopes
D-->>U: Client, company, data classes and revoke controls
U->>D: Revoke own grant or change authorized company policy
D->>A: Actor-authorized revocation or policy update
A->>A: Atomically persist grant/policy change
A-->>D: Change acknowledged
C->>M: Next request with previous token
M->>A: Introspection for this resource and current company policy
A-->>M: Inactive grant or reduced authority
M-->>C: Refusal or only currently permitted operation
Note over D,A: Admin grant metadata never grants access to private mail content
```

## 13 · Engine-enforced quota, source filtering and audit

**Status: UNIMPLEMENTED REMOTE REQUIREMENT.**

Case 4 token checks apply before and after this sequence. Every tool is rate-limited;
only admitted paid work reserves model cost. Audit is required before execution and
business-result release; unsettled quota reservations remain held for recovery.

```mermaid
sequenceDiagram
autonumber
participant M as Profile MCP endpoint
participant E as Profile engine
participant S as Authorized source data
participant L as Engine LLM provider
participant R as Profile operation and audit store
participant A as Central authorization and MCP quota ledger
M->>E: Tool with trusted grant context and permitted data classes
E->>R: Record admitted request metadata, no tokens or content
E->>E: Enforce tool scope, data provenance and rate limit
alt Scope, source class or rate check refuses
E->>R: Record refusal
E-->>M: Structured refusal, no model dispatch
else Checks pass
opt Paid ask or draft generation
E->>A: Profile-authenticated atomic grant/profile/company reservation
A-->>E: Reservation, quota refusal or service unavailable
end
alt Paid reservation refused or quota service unavailable
E->>R: Record budget_exhausted
E-->>M: Budget or service refusal, no daemon allocation used
else Read or reserved paid operation
E->>S: Read only allowed source classes and derived content
S-->>E: Permitted bounded context
opt Paid generation
E->>L: Selected permitted context with cost reservation
L-->>E: Result or policy-checked tool requests
end
opt Paid reservation exists
E->>A: Settle actual cost or release unused reservation
A-->>E: Durable quota settlement
end
E->>R: Record outcome, references and actual cost, settle reservation
E-->>M: Bounded result for case 4 authority recheck
end
end
```

## 14 · Remote procedures: one canonical revision

**Proposed authority change; existing clone files are not migrated by this design.**
A Save uses the revision from the editor's original read, not an automatically
refetched revision that could silently overwrite another colleague's changes.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant D as Desktop editor
participant E as Profile engine
participant P as Revisioned company procedure project
participant K as Server-side operator compiler
D->>E: Read canonical procedures with ordinary Desktop authority
E->>P: Read authorized canonical revision
P-->>E: Text and revision
E-->>D: Editor text and base revision
U->>D: Edit and Save
D->>E: Store canonical text with original expected_revision
E->>P: Compare revision and authorize writer
alt Revision conflict
P-->>E: Conflict with current revision
E-->>D: Conflict, no overwrite
D-->>U: Review differences and explicitly merge or reload
else Expected revision matches
E->>K: Compile canonical text for this company/profile
K-->>E: Derived procedures, phone and mailbox documents
E->>P: CAS-publish canonical and derived set using original expected_revision
P-->>E: Committed revision or commit-time conflict
alt Commit-time revision conflict
E-->>D: Conflict, no overwrite
D-->>U: Explicit merge or reload required
else Publication committed
E-->>D: Verified saved revision
D-->>U: Procedures available
end
end
Note over E,P: Remote operator_context reads this authority, local files are working copies
```

## 15 · Remote draft result and native retry identity

**Required contract, not an existing RPC schema:** fields and lookup names describe requirements. Grant-scoped keys prevent retry duplication, not other writers to the same draft; draft revisions preserve that distinction.

```mermaid
sequenceDiagram
autonumber
participant C as Provider MCP client
participant M as Profile MCP endpoint
participant E as Profile engine
participant R as Durable operation and draft store
C->>M: prepare_reply with operation_id and exact source
M->>E: Policy-checked preparation with native caller-bound idempotency key
E->>R: Atomically claim key and compare payload hash
alt Key belongs to a different payload
R-->>E: Conflict
E-->>M: operation_conflict
else Existing same-payload operation
R-->>E: Completed result or pending operation
E-->>M: Exact stored draft ID/revision or outcome_unknown
else Newly claimed operation
E->>E: Generate under source/assignment policy and reserved quota
E->>R: Persist exact draft ID/revision and recoverable operation outcome
R-->>E: Durable result for this turn
E-->>M: draft_id, draft_revision, operation reference and sent=false
end
M-->>C: Result only after case 4 return-time authority check
opt Response lost or transport outcome uncertain
C->>M: Retry the same operation_id and payload
M->>E: Look up or resume the same native operation under current authority
E->>R: Resolve durable outcome without a second generation
R-->>E: Exact result or still pending
E-->>M: Result or outcome_unknown
M-->>C: Authorized result or explicit uncertainty
end
Note over E,R: Another writer may create a later revision, never relabel it as this turn's result
```
