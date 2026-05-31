"""Server-side verification of Firebase ID tokens.

The stdio sidecar trusts its parent (the Electron renderer) and never
verifies the pushed token. The cross-machine WebSocket backend cannot —
anyone can open a socket — so it must cryptographically verify the
Firebase ID token presented at connect.

Firebase ID tokens are RS256 JWTs signed by Google. Verification:
  - signature against Google's rotating public x509 certs, keyed by the
    token header ``kid``;
  - ``aud`` == firebase project id;
  - ``iss`` == ``https://securetoken.google.com/<project id>``;
  - ``exp`` in the future (PyJWT enforces);
  - ``sub`` present and non-empty (the Firebase uid).

Certs are cached in-process honouring their HTTP ``max-age`` so we do
not hit Google on every connect.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx
import jwt
from cryptography.x509 import load_pem_x509_certificate

logger = logging.getLogger(__name__)

# Google's x509 certs for Firebase ID tokens (the "securetoken" service
# account). Keyed by `kid`; rotated ~daily.
_GOOGLE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/" "securetoken@system.gserviceaccount.com"
)


class FirebaseAuthError(Exception):
    """Raised when an ID token fails verification.

    Carries JSON-RPC application error code -32011 (the companion to
    ``NoActiveSession`` = -32010) so handlers that surface it produce a
    clean protocol-level error rather than a generic internal error.
    """

    code = -32011


# (public_keys_by_kid, expiry_epoch_seconds)
_certs_cache: Tuple[Dict[str, Any], float] = ({}, 0.0)


def _fetch_google_certs(force: bool = False) -> Dict[str, Any]:
    """Return ``{kid: public_key}``, cached until the HTTP max-age expires.

    ``force=True`` bypasses the cache (used once on an unknown ``kid`` to
    cover key rotation before giving up).
    """
    global _certs_cache
    cached, exp = _certs_cache
    now = time.time()
    if cached and not force and now < exp:
        return cached

    resp = httpx.get(_GOOGLE_CERTS_URL, timeout=10.0)
    resp.raise_for_status()
    pem_by_kid = resp.json()  # {kid: "-----BEGIN CERTIFICATE----- ..."}
    keys: Dict[str, Any] = {}
    for kid, pem in pem_by_kid.items():
        cert = load_pem_x509_certificate(pem.encode("utf-8"))
        keys[kid] = cert.public_key()

    # Honour Cache-Control max-age (Google rotates ~daily); fall back to
    # 1h if the header is missing or malformed.
    ttl = 3600.0
    cc = resp.headers.get("cache-control", "") or ""
    for part in cc.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                ttl = float(part.split("=", 1)[1])
            except ValueError:
                pass
    _certs_cache = (keys, now + ttl)
    logger.debug(f"[firebase_auth] fetched {len(keys)} Google certs, ttl={ttl:.0f}s")
    return keys


def verify_firebase_id_token(id_token: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Verify a Firebase ID token; return its decoded claims.

    Raises :class:`FirebaseAuthError` on any problem (bad signature,
    wrong aud/iss, expired, unknown kid, malformed, or unreachable cert
    endpoint). Never leaks the raw PyJWT exception type to callers.
    """
    from zylch.config import settings

    project_id = project_id or settings.firebase_project_id
    if not isinstance(id_token, str) or not id_token:
        raise FirebaseAuthError("empty id_token")

    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise FirebaseAuthError(f"malformed token header: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise FirebaseAuthError("token header missing 'kid'")

    try:
        certs = _fetch_google_certs()
    except Exception as e:
        # Transient: cannot reach Google. Surface clearly so the client
        # retries rather than treating it as "bad credentials".
        raise FirebaseAuthError(f"could not fetch Google signing certs: {e}") from e

    public_key = certs.get(kid)
    if public_key is None:
        # kid not in the current set — likely rotation; force one refresh.
        try:
            certs = _fetch_google_certs(force=True)
        except Exception as e:
            raise FirebaseAuthError(f"could not refresh Google signing certs: {e}") from e
        public_key = certs.get(kid)
    if public_key is None:
        raise FirebaseAuthError(f"unknown signing key id (kid={kid})")

    issuer = f"https://securetoken.google.com/{project_id}"
    try:
        claims = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise FirebaseAuthError("token expired") from e
    except jwt.InvalidTokenError as e:
        raise FirebaseAuthError(f"invalid token: {e}") from e

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise FirebaseAuthError("token missing 'sub' (uid)")
    logger.debug(f"[firebase_auth] verified token uid={sub} aud={project_id}")
    return claims
