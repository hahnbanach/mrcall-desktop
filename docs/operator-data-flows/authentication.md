# Authentication and sessions

<!-- doc-scope:start -->
Scope: English sequence descriptions for authentication and sessions; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

**Implementation boundary:** Desktop Firebase authentication and its WSS engine connection exist on `main`. The nine-tool local MCP exists only as an **uncommitted, unreleased candidate in isolated `feat/desktop-operator-mcp-20261008` worktrees** and is **absent from main**. Remote MCP, OAuth, the authorized engine/workspace bridge and company-project file upload in this design are **unimplemented proposals**.

## 1 · First MrCall Desktop login

**Status: EXISTING ON MAIN — verified code.**

This case assumes a remote backend is already activated. Login identifies the profile; it does not automatically provision a hosted tenant. Firebase UID is the identity, not the email. Google and email/password login are alternative paths.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant D as Desktop on the computer
participant F as Firebase Auth / Google
participant E as Linux profile engine
U->>D: Sign in to your MrCall account
D->>F: Firebase login (password or Google credential)
F-->>D: Firebase UID, email, ID token and refresh token
Note over D: ID token in memory, private local session
D->>E: WSS /ws/UID · Authorization: Bearer Firebase ID token
E->>E: Verify signature, issuer, audience, expiry and sub = OWNER_ID
alt Invalid token or unauthorized profile
E-->>D: 401 / 403 · connection rejected
D-->>U: Login error or account activation required
else Authorized profile
E-->>D: Authenticated WebSocket opened
D->>E: Profile configuration and read JSON-RPC
E-->>D: Profile results and permitted company memory
D-->>U: Setup, mail and tasks available
loop Desktop session renewal
D->>F: Renew the Firebase session
F-->>D: Updated ID token
D->>E: auth.refresh(id_token, refresh_token if available)
E-->>D: Renewal accepted
end
end
Note over D,E: The refresh token may reach the daemon through auth.refresh, the login password does not
```

## 3 · Connecting ChatGPT or Claude to MrCall

**Status: UNIMPLEMENTED PROPOSAL — remote MCP and OAuth.**

AI UI means the app/web interface; MCP client means the provider component making remote requests. Browser login and token exchange are separate flows. The MrCall password and Firebase session are not handed to the AI client. Claude explicitly documents connections from its cloud infrastructure.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant UI as ChatGPT / Claude UI
participant C as Provider MCP client
participant B as User browser
participant A as MrCall authorization
participant F as Firebase Auth
participant M as MrCall remote MCP
U->>UI: Add / connect MrCall
UI->>C: Selected MCP URL
C->>M: HTTP request without valid authorization
M-->>C: 401 + reference to OAuth metadata
C->>M: Read protected resource metadata
M-->>C: Authorization server and available scopes
C->>A: Read OAuth metadata, identify the client
A-->>C: OAuth endpoints and configuration
Note over C,A: Client identity through CIMD, DCR or supported registration
C-->>UI: Start authorization URL with state, PKCE challenge, resource and scope
UI->>B: Open MrCall page
B->>A: OAuth authorization request
A-->>B: MrCall login page
U->>B: Sign in with the selected MrCall account
B->>F: Login through the same identity system as Desktop
F-->>B: Firebase login proof
B->>A: Present login proof
A->>A: Verify identity, UID and company membership
A-->>B: Show account, company and requested permissions
U->>B: Confirm authorization for the AI client
B->>A: Explicit consent
A-->>B: Redirect to provider callback with code, state and issuer
B->>C: OAuth callback with single-use code
C->>C: Verify state and issuer
C->>A: Exchange code + PKCE verifier + resource
A-->>C: MCP access token, refresh token if supported and authorized
Note over C: MCP token belongs to this connection, not Desktop Firebase token
C->>M: MCP request + Authorization: Bearer MCP token
M->>M: Verify issuer, MCP audience, expiry, grant and scopes
M-->>C: Access allowed to the MrCall profile tools
C-->>UI: Authorized connector
UI-->>U: MrCall available in enabled conversations
```

## 4 · MCP session and per-call checks

**Status: UNIMPLEMENTED REMOTE PROPOSAL — tool design based on the local candidate.**

The authorized engine bridge remains unimplemented. It cannot forward an MCP token to the existing WebSocket, which requires Firebase. M and E are logical components and could share a daemon using authorized internal calls. Later M→E arrows describe methods and payloads, not an implemented remote transport. The handshake is the SDK 1.x candidate pattern with negotiated 2025 compatibility, not a universal claim about current remote clients.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant UI as AI UI
participant C as Provider MCP client
participant M as Remote MCP in Linux service
participant E as Profile engine
U->>UI: Open conversation and enable MrCall
UI->>C: Use selected MrCall connection
C->>M: initialize(version and capabilities) + MCP token
M-->>C: Compatible version, capabilities and guidance
C->>M: notifications/initialized
C->>M: tools/list
M-->>C: Nine tools with names and argument schemas
opt Client uses MCP resources
C->>M: resources/list
M-->>C: operator://guidance
C->>M: resources/read(operator://guidance)
M->>M: Run operator_context with the same checks
M-->>C: Context and instructions
end
loop Every tools/call
C->>M: Tool name + arguments + MCP token
M->>M: Verify token, active grant and argument schema
M->>M: Resolve UID and company from server-side grant
M->>E: Internal dispatch with authorized profile identity
E->>E: Check data and operation access
E-->>M: Result or refusal
M->>M: Recheck company scope and grant, limit and filter response
M-->>C: MCP result or error
C-->>UI: Tool result in the conversation
UI-->>U: Assistant response
end
Note over M,E: Authenticated remote bridge remains unimplemented, MCP token does not reach Firebase WSS
Note over C,M: Handshake represents the candidate SDK 1.x protocol, real clients must negotiate a version
```

