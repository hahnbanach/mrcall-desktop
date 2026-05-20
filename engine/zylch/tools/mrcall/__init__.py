"""MrCall integration package.

Re-exports:

- `starchat_firebase.py` — Firebase-session StarChat client factory
  (used by `zylch.rpc.mrcall_actions`). This is the only supported
  StarChat auth path: the renderer signs in with Firebase and pushes
  the JWT to the engine, which calls StarChat on the plain `{realm}`
  path.

The legacy CLI OAuth2/PKCE "delegated" flow (loopback :19274,
`OAuthToken provider='mrcall'`, `delegated_{realm}` paths) was removed
in 2026-05; the Firebase identity introduced in 2026-05-02 replaced it.

The desktop is a consumer of MrCall, not a configurator; assistant
configuration lives in the dashboard / `mrcall-agent` repo.
"""
