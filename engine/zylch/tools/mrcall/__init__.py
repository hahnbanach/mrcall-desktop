"""MrCall integration package.

Re-exports:

- `oauth.py` — legacy CLI OAuth2 PKCE flow (used by `zylch init` /
  `zylch.cli.setup`).
- `starchat_firebase.py` — Firebase-session StarChat client factory
  (used by `zylch.rpc.mrcall_actions`).

The desktop is a consumer of MrCall, not a configurator; assistant
configuration lives in the dashboard / `mrcall-agent` repo.
"""
