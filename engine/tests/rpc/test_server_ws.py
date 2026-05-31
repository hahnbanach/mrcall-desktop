"""Integration test for the WebSocket JSON-RPC transport (Phase 1).

Exercises the real ``server_ws`` handler + handshake auth gate over a
loopback WebSocket, with the Firebase verifier monkeypatched (so no
network / real token is needed). Verifies:

  - a valid owning token round-trips ``account.who_am_i`` and the
    identity comes from the VERIFIED claims;
  - a missing token is rejected at the handshake with HTTP 401;
  - a valid token whose uid does NOT own the profile is rejected 403;
  - a malformed/invalid token is rejected 401;
  - ``auth.refresh`` round-trips and reinstalls the session.

Runnable two ways:
  - as a script:  ``python tests/rpc/test_server_ws.py``  (bypasses the
    pytest conftest, which is the reliable path while that conftest is
    out of sync with config);
  - under pytest: ``def test_server_ws_transport`` wraps the same checks.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

OWNER_UID = "test-uid-abc"


def _install_fakes() -> None:
    """Point the WS auth at a fake verifier and bind the profile owner."""
    os.environ["OWNER_ID"] = OWNER_UID

    import zylch.rpc.firebase_auth as fa

    now = int(time.time())

    def fake_verify(token, project_id=None):
        if token == "GOOD":
            return {
                "sub": OWNER_UID,
                "email": "owner@example.com",
                "exp": now + 3600,
                "iat": now,
                "aud": "talkmeapp-e696c",
                "iss": "https://securetoken.google.com/talkmeapp-e696c",
            }
        if token == "OTHERUSER":
            return {
                "sub": "someone-else-uid",
                "email": "other@example.com",
                "exp": now + 3600,
                "iat": now,
                "aud": "talkmeapp-e696c",
                "iss": "https://securetoken.google.com/talkmeapp-e696c",
            }
        raise fa.FirebaseAuthError("bad token (fake verifier)")

    fa.verify_firebase_id_token = fake_verify


def _server_port(server) -> int:
    socks = getattr(server, "sockets", None)
    if not socks:
        socks = getattr(getattr(server, "server", None), "sockets", None)
    return socks[0].getsockname()[1]


def _status_of(exc) -> int | None:
    """Best-effort HTTP status from a websockets handshake-rejection."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        return getattr(resp, "status_code", None)
    return None


async def _call(port: int, token, method="account.who_am_i", params=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with connect(f"ws://127.0.0.1:{port}", additional_headers=headers) as ws:
        await ws.send(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        )
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                return msg


async def _run_all() -> list[str]:
    _install_fakes()
    from zylch.rpc import server_ws

    server = await serve(
        server_ws._handle_connection,
        "127.0.0.1",
        0,
        process_request=server_ws._process_request,
    )
    port = _server_port(server)
    failures: list[str] = []

    # 1) valid owning token -> who_am_i returns the verified identity
    try:
        resp = await _call(port, "GOOD")
        res = resp.get("result", {})
        assert res.get("signed_in") is True, resp
        assert res.get("uid") == OWNER_UID, resp
        assert res.get("email") == "owner@example.com", resp
        print(f"PASS  who_am_i over WS with valid bearer -> {res}")
    except Exception as e:
        failures.append(f"valid who_am_i: {type(e).__name__}: {e}")

    # 2) missing token -> handshake rejected 401
    try:
        await _call(port, None)
        failures.append("missing token was NOT rejected")
    except Exception as e:
        code = _status_of(e)
        if code == 401:
            print("PASS  missing token rejected at handshake (401)")
        else:
            failures.append(f"missing token: expected 401, got {code} ({type(e).__name__}: {e})")

    # 3) valid token, wrong owner -> 403
    try:
        await _call(port, "OTHERUSER")
        failures.append("non-owning uid was NOT rejected")
    except Exception as e:
        code = _status_of(e)
        if code == 403:
            print("PASS  non-owning uid rejected at handshake (403)")
        else:
            failures.append(f"wrong uid: expected 403, got {code} ({type(e).__name__}: {e})")

    # 4) malformed token -> 401
    try:
        await _call(port, "GARBAGE")
        failures.append("bad token was NOT rejected")
    except Exception as e:
        code = _status_of(e)
        if code == 401:
            print("PASS  malformed token rejected at handshake (401)")
        else:
            failures.append(f"bad token: expected 401, got {code} ({type(e).__name__}: {e})")

    # 5) auth.refresh round-trips
    try:
        resp = await _call(port, "GOOD", method="auth.refresh", params={"id_token": "GOOD"})
        res = resp.get("result", {})
        assert res.get("ok") is True and res.get("uid") == OWNER_UID, resp
        print(f"PASS  auth.refresh over WS -> {res}")
    except Exception as e:
        failures.append(f"auth.refresh: {type(e).__name__}: {e}")

    server.close()
    await server.wait_closed()
    return failures


def test_server_ws_transport():
    failures = asyncio.run(_run_all())
    assert not failures, "; ".join(failures)


if __name__ == "__main__":
    fails = asyncio.run(_run_all())
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("\nALL PASS")
    sys.exit(0)
