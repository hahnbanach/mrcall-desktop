"""Firebase auth session held in-memory by the sidecar.

The renderer (Electron + Firebase JS SDK) is the source of truth for the
user's identity and ID token. The sidecar receives the token over
JSON-RPC (`account.set_firebase_token`) and caches it for the lifetime of
the process. We do not persist the token to disk:

  - Firebase ID tokens expire after 60 minutes; the renderer refreshes
    proactively at 50 min and re-pushes via the same RPC.
  - On sidecar restart the renderer pushes again automatically (its
    onAuthStateChanged listener fires right after window mount).
  - Persisting would risk leaking a Bearer token if the disk is shared
    or backed up; in-memory keeps the blast radius to a running process.

We do NOT verify the JWT here. StarChat is the authority that verifies
Firebase tokens (it already does so for the dashboard); the engine only
forwards the token in `Authorization: Bearer …`. Local verification
would be defense-in-depth but would require shipping Firebase's public
keys; it is out of scope for the initial integration.
"""

from .session import (
    FirebaseSession,
    NoActiveSession,
    clear_session,
    get_session,
    require_session,
    set_session,
)

__all__ = [
    "FirebaseSession",
    "NoActiveSession",
    "clear_session",
    "get_session",
    "require_session",
    "set_session",
]
