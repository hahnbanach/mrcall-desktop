# Files and connection lifecycle

<!-- doc-scope:start -->
Scope: English sequence descriptions for files and connection lifecycle; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

**Implementation boundary:** Desktop Firebase authentication and its WSS engine connection exist on `main`. The nine-tool local MCP exists only as an **uncommitted, unreleased candidate in isolated `feat/desktop-operator-mcp-20261008` worktrees** and is **absent from main**. Remote MCP, OAuth, the authorized engine/workspace bridge and company-project file upload in this design are **unimplemented proposals**.

## 9 · Files on the computer: three separate cases

**Status: LIMITED LOCAL CANDIDATE / UNIMPLEMENTED EXTENSIONS.**

The candidate MCP exposes no read_file, write_file, upload_file, download_file or shell. read_project reads engine documents; operator_context reads only canonical workspace files. The company-project upload and general local-access branches below are proposals, not implemented capabilities of this MCP. Existing Desktop chat attachment-transfer workflows are separate from the proposed company-project upload.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant F as Files on the computer
participant UI as Desktop or AI UI
participant C as AI cloud / client
participant M as MrCall remote MCP
participant E as Engine and server storage
alt Attachment uploaded to AI conversation
U->>UI: Choose file with the AI client picker
UI->>F: Read explicitly selected file
F-->>UI: File bytes
UI->>C: Upload attachment to conversation
Note over C,M: Does not imply upload to MrCall workspace
opt Assistant uses some content in an existing tool
C->>M: ask_operator(question) or prepare_reply(instruction) with selected text
M->>E: Permitted request with that text
E-->>M: Result
M-->>C: MCP result
end
else Document to retain in MrCall — proposed extension
U->>UI: In Desktop, select file and company destination
UI->>F: Read selected file
F-->>UI: Bytes
UI->>E: Authenticated, limited upload remains unimplemented
E-->>UI: Document ID/path, revision and permissions
C->>M: read_project(project, path) if stored as a text project
M->>E: projects.read(project, path)
E-->>M: Stored content and metadata
M-->>C: Verified UTF-8 text, not arbitrary PDF/binary
else Direct local folder access — separate capability
U->>UI: Authorize a local tool supported by the client
UI->>F: Local read/write within granted permissions
F-->>UI: Content or write result
UI->>C: Local tool result according to the client
Note over UI,M: This access is not provided by our remote MCP or the nine candidate tools
end
Note over F,M: A local path or MCP root is a reference, it does not transfer bytes to the server
```

## 10 · Remote connection renewal, closure and revocation

**Status: UNIMPLEMENTED PROPOSAL — revocation policy.**

Revoking an AI-client grant and signing out of Desktop are distinct events. Remote behavior on Desktop logout remains to be decided and implemented; the local candidate revokes on logout. Revocation stops subsequent requests but does not retract data already shown or work already submitted.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant UI as Desktop / AI UI
participant C as AI MCP client
participant A as MrCall authorization
participant M as Remote MCP
alt Access token expired and refresh allowed
C->>A: Connection MCP refresh token
A->>A: Verify grant remains active
A-->>C: New access token or login required
C->>M: New request with valid token
M-->>C: Authorized result
else Close conversation or client
U->>UI: Close
UI->>C: Stop using the MCP session
Note over A,M: Session closure does not revoke the grant
else Revoke the client's MrCall authorization
U->>UI: Revoke Claude or ChatGPT
UI->>A: Revoke selected grant with authenticated identity
A->>A: Invalidate grant and renewals
C->>M: Next request with previous token
M->>M: Check revoked grant
M-->>C: Request rejected, new authorization required
end
Note over A,M: Service must check revocation rather than rely only on JWT expiry
```

