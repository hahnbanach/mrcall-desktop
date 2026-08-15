"""Shared fixtures for tests/provisiond.

Isolates this package from the Supabase-requiring autouse fixture in
tests/conftest.py (these are unit tests; none need storage) and provides
a locally generated RSA keypair + a `verify_firebase_id_token`-shaped
Firebase ID token builder so tests never touch the network or a real
Google cert endpoint.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from zylch.rpc import firebase_auth as firebase_auth_mod

PROJECT_ID = "test-project-1234"
KID = "test-kid-1"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override parent autouse fixture; no-op here (mirrors tests/rpc/conftest.py)."""
    yield


@pytest.fixture
def rsa_keypair():
    """A fresh 2048-bit RSA keypair, standing in for Google's signing key."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def fake_google_certs(monkeypatch, rsa_keypair):
    """Serve `rsa_keypair`'s public key under `KID` instead of Google's.

    Resets `firebase_auth._certs_cache` before AND after so no test's
    cache state can leak into the next (the module caches certs in a
    process-global, and these are the FIRST tests this function has ever
    had — nothing enforced that isolation before).
    """
    _, public_key = rsa_keypair

    def _fake_fetch(force: bool = False) -> dict[str, Any]:
        return {KID: public_key}

    monkeypatch.setattr(firebase_auth_mod, "_fetch_google_certs", _fake_fetch)
    firebase_auth_mod._certs_cache = ({}, 0.0)
    yield
    firebase_auth_mod._certs_cache = ({}, 0.0)


def make_id_token(
    private_key,
    *,
    kid: str = KID,
    project_id: str = PROJECT_ID,
    sub: str | None = "user123",
    exp_delta: int = 3600,
    iat_delta: int = 0,
    issuer: str | None = None,
    audience: str | None = None,
    include_sub: bool = True,
) -> str:
    """Sign a Firebase-ID-token-shaped JWT with `private_key`.

    Defaults produce a token `verify_firebase_id_token` accepts for
    `project_id`; override one field at a time to build the negative
    cases (expired, wrong audience, wrong issuer, missing sub).
    """
    now = int(time.time())
    claims: dict[str, Any] = {
        "iat": now + iat_delta,
        "exp": now + exp_delta,
        "aud": audience if audience is not None else project_id,
        "iss": (issuer if issuer is not None else f"https://securetoken.google.com/{project_id}"),
    }
    if include_sub:
        claims["sub"] = sub
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
