# Tools and engine RPC mapping

<!-- doc-scope:start -->
Scope: English sequence descriptions for tools and engine rpc mapping; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

**Implementation boundary:** Desktop Firebase authentication and its WSS engine connection exist on `main`. The nine-tool local MCP exists only as an **uncommitted, unreleased candidate in isolated `feat/desktop-operator-mcp-20261008` worktrees** and is **absent from main**. Remote MCP, OAuth, the authorized engine/workspace bridge and company-project file upload in this design are **unimplemented proposals**.

## 5 · All reads: six tools and their RPCs

**Status: LOCAL CANDIDATE MAPPING — remote port unimplemented.**

These are alternative calls, not a mandatory sequence on every request. The checks in case 4 apply to the remote proposal. Mail, tasks and drafts belong to the profile; projects follow company-memory permissions. The AI client does not read Gmail/IMAP directly.

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

W is the workspace on the computer in the candidate; in the remote proposal W would be the server workspace. Canonical files are the procedure source; the engine holds derived, revisioned copies. This tool accepts no arbitrary computer path.

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
alt Unique draft verified
M->>W: Store completed receipt and result
M-->>C: draft + operation_id + sent=false
C-->>U: Draft ready for review
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
