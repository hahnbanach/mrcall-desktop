"""In-memory Firebase session singleton for the sidecar process.

Thread-safe: RPC handlers run concurrently via asyncio, but the lock is
also visible to any sync thread (e.g. SyncService callbacks) that needs
to read the active token.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirebaseSession:
    """Snapshot of the renderer's Firebase signin pushed to the engine.

    `id_token` is the Firebase ID token (a signed JWT); `expires_at_ms`
    is the absolute Unix-ms timestamp at which the token becomes invalid
    on the issuer side.
    """

    uid: str
    email: Optional[str]
    id_token: str
    expires_at_ms: int

    def is_expired(self, now_ms: Optional[int] = None) -> bool:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        return now_ms >= self.expires_at_ms


class NoActiveSession(RuntimeError):
    """Raised by `require_session()` when no Firebase token is cached.

    Mapped to JSON-RPC application error code -32010 by handlers that
    catch it explicitly; bare uses surface as -32603 (internal error)
    via the dispatcher's default error path.
    """

    code = -32010


_lock = threading.Lock()
_session: Optional[FirebaseSession] = None


def set_session(uid: str, email: Optional[str], id_token: str, expires_at_ms: int) -> None:
    """Replace the cached session. Called by `account.set_firebase_token`.

    `uid` is the Firebase immutable UID; `email` is a display attribute
    only. We do not silently merge with the previous session — a
    different uid replaces the prior one wholesale (signing out and back
    in as a different user is the intended path).
    """
    global _session
    if not isinstance(uid, str) or not uid:
        raise ValueError("uid is required and must be a non-empty string")
    if not isinstance(id_token, str) or not id_token:
        raise ValueError("id_token is required and must be a non-empty string")
    if not isinstance(expires_at_ms, int) or expires_at_ms <= 0:
        raise ValueError("expires_at_ms must be a positive int (Unix ms)")
    with _lock:
        previous = _session
        _session = FirebaseSession(
            uid=uid,
            email=email if isinstance(email, str) and email else None,
            id_token=id_token,
            expires_at_ms=expires_at_ms,
        )
    if previous is None:
        logger.info(f"[auth] firebase session set: uid={uid} email={email!r}")
    elif previous.uid != uid:
        logger.info(
            f"[auth] firebase session replaced: prev_uid={previous.uid} -> uid={uid}"
        )
    else:
        # Same uid, just a token refresh — keep the log quiet.
        logger.debug(f"[auth] firebase token refreshed for uid={uid}")


def clear_session() -> None:
    """Drop the cached session (signout)."""
    global _session
    with _lock:
        previous = _session
        _session = None
    if previous is not None:
        logger.info(f"[auth] firebase session cleared (was uid={previous.uid})")


def get_session() -> Optional[FirebaseSession]:
    """Return the current session, or None if not signed in."""
    with _lock:
        return _session


def require_session() -> FirebaseSession:
    """Like `get_session()` but raises `NoActiveSession` when missing.

    Callers that need a token to proceed (StarChat client, MrCall
    integration) use this so the JSON-RPC error surfaces a clear
    "not signed in" message back to the renderer.
    """
    s = get_session()
    if s is None:
        raise NoActiveSession("No active Firebase session — sign in first.")
    return s
