# Authentication and sessions

<!-- doc-scope:start -->
Scope: English sequence descriptions for authentication and sessions; existing behavior, isolated candidate behavior and unimplemented proposals are explicitly distinguished.
<!-- doc-scope:end -->

[Back to the data-flow index](../operator-data-flows.md).

Implementation status and transport boundaries: [data-flow index](../operator-data-flows.md#implementation-status-and-navigation). Each case labels existing, candidate or proposed behavior.

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
Note over C,A: Allowlisted client identity and exact verified redirect URI, no unrestricted DCR
C-->>UI: Start authorization URL with state, PKCE challenge, resource and scope
UI->>B: Open MrCall page
B->>A: OAuth authorization request
A-->>B: MrCall login page
U->>B: Sign in with the selected MrCall account
B->>F: Login through the same identity system as Desktop
F-->>B: Firebase login proof
B->>A: Present login proof
A->>A: Verify identity, selected profile/company membership and connector policy
A-->>B: Show verified client name, profile/company, scopes and data classes
alt User grants consent
U->>B: Confirm authorization for the AI client
B->>A: Explicit consent
A-->>B: Redirect to provider callback with code, state and issuer
B->>C: OAuth callback with single-use code
C->>C: Verify state and issuer
C->>A: Exchange code + PKCE verifier + resource
A-->>C: Opaque five-minute MCP token and rotating refresh token
Note over C: MCP token belongs to this connection, not Desktop Firebase token
C->>M: MCP request + Authorization: Bearer MCP token
M->>A: Authenticated introspection for this profile resource
A-->>M: Active grant and current profile/company/data authority
M->>M: Validate resource, profile, company and required scopes
M-->>C: Access allowed to the MrCall profile tools
C-->>UI: Authorized connector
UI-->>U: MrCall available in enabled conversations
else User declines consent
U->>B: Decline authorization
B->>A: Consent denied
A-->>B: Redirect to provider callback with access_denied and state
B->>C: OAuth error callback
C->>C: Validate state, create no connection
C-->>UI: Authorization declined, no MCP grant
UI-->>U: MrCall remains disconnected
end
```

## 4 · MCP session and per-call checks

**Status: UNIMPLEMENTED REMOTE PROPOSAL — tool design based on the local candidate.**

The profile's MCP endpoint and engine methods share one Linux process and Unix user.
They dispatch internally through engine policies, without passing MCP tokens to
Firebase WSS. The central authorization service owns the grant store. Streamable
HTTP session IDs identify protocol sessions, never authorization. Every request
requires a valid resource-bound token; version negotiation is independent of identity.

```mermaid
sequenceDiagram
autonumber
actor U as User
participant UI as AI UI
participant C as Provider MCP client
participant A as Central MrCall authorization
participant M as Profile MCP endpoint
participant E as Profile engine
U->>UI: Open conversation and enable MrCall
UI->>C: Use selected profile connection
C->>M: initialize(version, capabilities) with opaque MCP token
M->>A: Authenticated introspection for this resource
A-->>M: Grant status and current policy
alt Initialization admission refused
M-->>C: Authentication or resource error, session not initialized
else Initialization authorized
M->>M: Validate resource/profile/company binding and negotiated version
M-->>C: Compatible initialize result
C->>M: notifications/initialized with token
C->>M: tools/list with token
Note over A,M: Initialization and discovery also require admission checks
M-->>C: Scope-permitted tools and argument schemas
loop Every tools/call or authorized guidance resource read
C->>M: Name, arguments and opaque MCP token
M->>A: Introspect token, membership and current company/data policy
alt Inactive grant, wrong resource or authorization unavailable
A-->>M: Inactive or invalid authority, or unavailable
M-->>C: Admission refused, no engine operation
else Active authorization
A-->>M: Trusted profile/company, scopes and permitted data classes
M->>M: Validate scope and arguments, attach trusted caller context
M->>E: In-process dispatch through engine policy methods
E->>E: Enforce data classes, operation access, quotas and minimal audit
E-->>M: Result or structured tool error
M->>A: Recheck authority immediately before business result release
alt Authority remains valid
A-->>M: Current grant and data policy
M->>M: Bound and filter content under the current policy
M-->>C: Permitted result
C-->>UI: Tool result
UI-->>U: Assistant response
else Revoked, policy changed or authorization unavailable
A-->>M: Refusal or unavailable
M-->>C: Result withheld, admitted work may already have occurred
end
end
end
end
Note over M,E: Same process and Unix user, both components are proposed
Note over C,M: Mcp-Session-Id never replaces per-request authorization
```
