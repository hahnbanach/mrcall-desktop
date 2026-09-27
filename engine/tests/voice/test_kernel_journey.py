"""Real RS256 verification and actual installed kernel CLI; Google key is synthetic."""

import asyncio
import os
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.voice.m2_fixture import OWNER, seed
from tests.voice.m2_journey import journey
from zylch.auth import clear_session
from zylch.config import settings
from zylch.rpc import firebase_auth
from zylch.storage import database as db


@pytest.mark.skipif(not os.environ.get("CS_VOICE_KERNEL_PYTHON"), reason="Supply kernel Python")
def test_real_kernel_cli_authenticated_configuration(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        firebase_auth, "_fetch_google_certs", lambda **_: {"fixture": key.public_key()}
    )
    token = jwt.encode(
        {
            "sub": OWNER,
            "aud": settings.firebase_project_id,
            "iss": f"https://securetoken.google.com/{settings.firebase_project_id}",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        key,
        algorithm="RS256",
        headers={"kid": "fixture"},
    )
    try:
        report = asyncio.run(journey(tmp_path, os.environ["CS_VOICE_KERNEL_PYTHON"], token))
        assert report["authenticated_read_update"] == "passed"
    finally:
        clear_session()
        db.dispose_engine()
