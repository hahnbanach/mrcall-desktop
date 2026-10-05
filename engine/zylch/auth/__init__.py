"""Firebase auth session held in-memory by the sidecar.

The renderer (Electron + Firebase JS SDK) supplies the ID token. The
engine verifies its signature, UID and expiry before admission over
JSON-RPC (`account.set_firebase_token`) and caches it for the lifetime of
the process. We do not persist the token to disk:

  - Firebase ID tokens expire after 60 minutes; the renderer refreshes
    proactively at 50 min and re-pushes via the same RPC.
  - On sidecar restart the renderer pushes again automatically (its
    onAuthStateChanged listener fires right after window mount).
  - Persisting would risk leaking a Bearer token if the disk is shared
    or backed up; in-memory keeps the blast radius to a running process.

Verification uses Firebase's fetched/cached public certificates. Hosted
sessions must match the immutable profile owner. The engine also forwards
the token to MrCall services, which retain their own authentication gates.
"""

from .refresh import ensure_fresh_session, exchange_refresh_token
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
    "ensure_fresh_session",
    "exchange_refresh_token",
    "get_session",
    "require_session",
    "set_session",
]
