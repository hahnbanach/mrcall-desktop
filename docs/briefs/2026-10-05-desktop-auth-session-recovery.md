# Prevent stale desktop authentication after logout, sleep and relogin

The CTO reports Remote Mario Gmail timing out, then refusing its newly logged-in
identity with HTTP 403. The daemon's route, startup owner and read-only live
owner metadata all match the intended Firebase UID. Full desktop exit/reopen
restores the connection. This establishes a desktop session-state discrepancy;
the exact original client race was not captured and must not be invented.

Code has concrete gaps: main's per-window handshake cache survives signout;
remote token getters do not check bound UID or expiration; renderer token
refreshes may finish after their originating auth session changes. A sleeping
window can also miss its proactive refresh interval. Signout currently depends
on an in-band RPC even when the connection is unusable.

Scope: desktop authentication lifecycle, IPC token cache and remote reconnect/
Test connection. Clear tokens and retire the old transport on signout even
when offline; prevent late refreshes from a former session entering the cache;
check token subject against the claimed/bound UID before forwarding or using
it; obtain fresh Firebase credentials on demand when cached credentials are
missing, expiring or inconsistent. Preserve per-window isolation and local
engine token forwarding. Decode JWT claims only for local consistency, never
as a substitute for server signature/ownership checks.

Acceptance:
- Offline logout clears cached credentials and stops the old transport promptly.
- A refresh begun before logout/account change cannot repopulate the new session.
- Account switches and same-account relogin use the correct bound UID without
  needing full app exit. No other window's cache or transport is affected.
- Expired/near-expiry or inconsistent cached tokens are never sent to WebSocket,
  local engine or provisioning; bounded per-window refresh is coalesced and
  checked against current profile/session before use.
- Test connection and reconnect share this freshness/identity path; genuine
  wrong-owner 403 remains an access denial, never bypassed or blindly retried.
- Regression tests exercise the actual lifecycle with synthetic credentials,
  deferred refreshes, offline signout and local WebSocket rejection/success.
  App typecheck and build pass. No real tokens or paid calls are needed.
- Record the user-confirmed recovery and reviewed repair under R5, publish
  scoped changes after pull with rebase. Installed 0.1.52 is not claimed patched
  until a reviewed signed release is delivered; release procedure is assessed
  after source checks, without changing live server identity or policy.

No ID token is persisted or logged; no credentials, mail/call content, voice
values or addresses are emitted. Work only in the clone; preserve concurrent
engine/config/documentation changes. This does not close the other R5 gates.
