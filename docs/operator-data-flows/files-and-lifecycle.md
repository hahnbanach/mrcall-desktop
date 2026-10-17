# Files and connection lifecycle

<!-- doc-scope:start -->
Scope: English sequence descriptions for files and connection lifecycle; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

Implementation status and transport boundaries: [data-flow index](../operator-data-flows.md#implementation-status-and-navigation). Each case labels existing, candidate or proposed behavior.

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
UI-->>U: Show project and document path
U->>C: Share project/path in the AI conversation and request a read
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

Revoking an AI-client grant and signing out of Desktop are distinct events. Desktop logout does not revoke remote grants in the proposed product; the local candidate revokes on logout. Acknowledged revocation stops new admissions through uncached introspection; return-time checks withhold results when authority has changed. It does not retract data already shown or roll back admitted work.

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
A->>A: Verify active grant, membership, client and company policy
alt Refresh accepted
A-->>C: New opaque access token and rotated refresh token
C->>M: New request with token
M->>A: Authenticated introspection for this profile resource
A-->>M: Current authority or refusal
M-->>C: Result after return-time recheck, or refusal
else Refresh rejected or login required
A-->>C: Refresh refused, authorization required
C-->>UI: Stop tool requests and offer reconnection
UI-->>U: Sign in and authorize again through case 3
end
else Access token expired and refresh unavailable
C-->>UI: Stop tool requests and offer reconnection
UI-->>U: Sign in and authorize again through case 3
else Close conversation or client
U->>UI: Close
UI->>C: Stop using the MCP session
Note over A,M: Conversation closure leaves the grant active
else Sign out of Desktop only
U->>UI: Sign out of Desktop
UI->>UI: End the Desktop Firebase session
Note over C,M: Remote AI connection and grant remain active
else Revoke the client's MrCall authorization
U->>UI: Revoke Claude or ChatGPT
UI->>A: Revoke selected grant with authenticated identity
A->>A: Invalidate grant and renewals
C->>M: Next request with previous token
M->>A: Authenticated introspection of previous token
A-->>M: Inactive grant
M-->>C: Request rejected, new authorization required
end
Note over A,M: No positive grant cache, AS outage refuses MCP access
Note over A,M: Password reset, sign-out-everywhere and membership removal must invalidate central grants
```


Tokens expire after five minutes; grants expire after 90 days without admitted use.
Explicit revocation, company disable and removal of company membership also refuse
refresh. Security-event integration must invalidate the central store; Firebase
session invalidation alone does not invalidate an independently issued MCP grant.
Already-admitted model calls or draft writes may finish after revocation; their
results are withheld if the return-time check fails. Audit and Desktop operation
inspection remain available to the authorized profile user.
