"""Verify signed Firebase identity before admitting an engine session."""

from __future__ import annotations

import os
import time


class SessionAdmissionError(ValueError):
    """Safe auth outcome; no token or provider diagnostics reach RPC/logs."""

    code = -32011


def verified_claims(id_token: str, *, requested_uid: str | None = None) -> dict:
    """Return verified claims bound to the selected immutable profile owner.

    Before a local profile exists, a verified sign-in may establish identity
    for onboarding. A hosted engine always requires its configured owner.
    Client UID, email and expiry never substitute for signed token claims.
    """
    from zylch.rpc.firebase_auth import FirebaseAuthError, verify_firebase_id_token
    from zylch.runtime import is_serving

    try:
        claims = verify_firebase_id_token(id_token)
    except FirebaseAuthError:
        raise SessionAdmissionError("firebase_token_refused") from None

    uid = claims.get("sub")
    owner = os.environ.get("OWNER_ID", "")
    if is_serving() and not owner:
        raise SessionAdmissionError("profile_owner_required")
    if (owner and uid != owner) or (requested_uid is not None and uid != requested_uid):
        raise SessionAdmissionError("firebase_owner_mismatch")
    expiry = claims.get("exp")
    if type(expiry) not in (int, float) or expiry * 1000 <= int(time.time() * 1000):
        raise SessionAdmissionError("firebase_token_expired")
    return claims
