# Local connector candidate

<!-- doc-scope:start -->
Scope: English sequence descriptions for local connector candidate; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

**Implementation boundary:** Desktop Firebase authentication and its WSS engine connection exist on `main`. The nine-tool local MCP exists only as an **uncommitted, unreleased candidate in isolated `feat/desktop-operator-mcp-20261008` worktrees** and is **absent from main**. Remote MCP, OAuth, the authorized engine/workspace bridge and company-project file upload in this design are **unimplemented proposals**.

## 2 · Workspace preparation and procedure saving

**Status: LOCAL CANDIDATE ONLY — uncommitted and unreleased, absent from main.**

Here canonical files live on the user’s computer. The proposed remote architecture would host them on the server; transfer and provisioning remain unimplemented. Mailbox settings remain engine-owned.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant D as Desktop
participant K as Local cs-kernel runtime
participant W as Local workspace files
participant E as Linux engine
U->>D: Create company workspace
D->>K: desktop-init(descriptor, workspace, company)
K->>E: Firebase connection + account.who_am_i
E-->>K: Verified identity
K->>E: projects.list(limit=1, offset=0)
E-->>K: Company space_id
K->>W: Canonical templates + UID, endpoint, space_id binding
W-->>K: Files created or compatible workspace reconnected
K-->>D: Workspace status
D-->>U: Procedures form and mailbox identity
U->>D: Edit text and press Save
D->>K: desktop-configure(procedures, mailbox_identity)
K->>W: Write company/customer-service-playbook.md and mailbox-identity.md
W-->>K: Canonical text
K->>K: Compile procedures.md, phone.md and own mailbox identity
loop For each compiled document
K->>E: projects.read(operator-instructions, path)
E-->>K: Current revision or missing document
K->>E: instructions.store(space_id, path, base64 content, expected_revision)
E-->>K: Stored revision, hash and size
K->>E: projects.read(path, stored revision)
E-->>K: Content and metadata for read-back verification
K->>K: Compare bytes, SHA256, revision and space_id
end
alt Complete publication verified
K-->>D: instructions_ready = true
D-->>U: Procedures available to the engine
else Incomplete publication or error
K-->>D: Local files retained, publication unverified
D-->>U: Retry Save, MCP draft preparation not ready
end
```

## 11 · Comparison: the implemented local MCP candidate

**Status: LOCAL CANDIDATE ONLY — client installation acceptance unverified.**

The client launches cs-operator on the computer. It does not use remote OAuth. The exported package contains the command and executable without tokens; the program reads the private local descriptor. The nine-tool mapping in cases 5–8 is implemented on this transport only in the isolated candidate.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant D as Desktop
participant C as Compatible local AI client
participant H as Local cs-operator
participant W as Local descriptor and workspace
participant F as Firebase Auth
participant E as Linux engine through WSS
U->>D: Export Claude / ChatGPT connector
D-->>U: MCPB / ZIP with executable and workspace path, no included token
U->>C: Install in supported client (acceptance remains unverified)
C->>H: Start mcp --workspace process through STDIO
C->>H: initialize and tools/list
H-->>C: Guidance and nine tools
loop Every tool or guidance read
C->>H: tools/call(name, arguments)
H->>W: Check binding/generation, read current descriptor
W-->>H: UID, endpoint, Firebase refresh token and public API key
H->>F: Exchange refresh token for Firebase ID token
F-->>H: ID token and verifiable UID
H->>E: WSS /ws/UID with Bearer Firebase ID token
H->>E: account.who_am_i and projects.list(limit=1)
E-->>H: Identity and space_id
H->>E: Tool-specific RPCs
E-->>H: Result
H->>W: Recheck descriptor and generation
H->>E: projects.list(limit=1) to recheck company
E-->>H: Current space_id
H->>E: Close this call's WSS connection
H-->>C: Limited result with known secrets redacted
end
alt Revocation or Desktop logout/profile/backend change
U->>D: Revoke or change identity/backend
D->>W: Invalidate generation / remove descriptor
C->>H: Next call
H->>W: Local authorization check
W-->>H: Invalid authorization
H-->>C: Call rejected
else Close Desktop only
U->>D: Close window/app
Note over C,E: Local grant retained, powered-on computer and reachable engine required
end
```

