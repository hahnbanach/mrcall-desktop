"""Live-socket tests: the real `AF_UNIX` server, driven with a real HTTP
client over the unix socket.

`handle_provision` / `handle_status` (test_handler_provision.py /
test_handler_status.py) never touch this HTTP glue at all — this file
covers what only exists at the wire level: the Authorization gate (no
internals leaked on a 401), and the request body's own robustness
(missing Content-Length, an oversized declared Content-Length), plus one
full round trip proving the pieces are wired together correctly end to
end.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading

import pytest

from zylch.provisiond import handler
from zylch.provisiond.__main__ import _UnixHTTPServer

from .conftest import PROJECT_ID, make_id_token


class _UnixHTTPConnection(http.client.HTTPConnection):
    """`http.client.HTTPConnection` dialled over an `AF_UNIX` path instead
    of TCP host:port — stdlib has no built-in for this."""

    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    """Run the real handler on a real unix socket in a background thread."""
    monkeypatch.setenv("MRCALL_PROFILES_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda uid: False)
    monkeypatch.setattr(handler, "_systemctl_is_failed", lambda uid: False)

    socket_path = str(tmp_path / "provisiond.sock")
    server = _UnixHTTPServer(socket_path, handler.ProvisiondRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield socket_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(socket_path, method, path, headers=None, body=None):
    conn = _UnixHTTPConnection(socket_path)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, raw
    finally:
        conn.close()


def test_no_bearer_401_no_internals(live_server):
    status, raw = _request(live_server, "GET", "/api/provision/status")
    assert status == 401
    text = raw.decode("utf-8")
    assert json.loads(raw) == {"error": "unauthorized"}
    assert "Traceback" not in text
    assert ".py" not in text


def test_garbage_bearer_401_no_internals(live_server):
    status, raw = _request(
        live_server,
        "POST",
        "/api/provision",
        headers={"Authorization": "Bearer not-a-real-jwt", "Content-Length": "2"},
        body=b"{}",
    )
    assert status == 401
    text = raw.decode("utf-8")
    assert json.loads(raw) == {"error": "unauthorized"}
    assert "Traceback" not in text
    assert "jwt" not in text.lower()


def test_malformed_auth_header_401(live_server):
    status, raw = _request(
        live_server,
        "GET",
        "/api/provision/status",
        headers={"Authorization": "NotBearer sometoken"},
    )
    assert status == 401
    assert json.loads(raw) == {"error": "unauthorized"}


def test_unknown_path_404(live_server):
    status, _raw = _request(live_server, "GET", "/nope")
    assert status == 404


def test_auth_crash_is_500_not_a_dropped_connection(live_server, monkeypatch):
    # A non-FirebaseAuthError exception from the auth path (a bug, or a
    # future failure mode nobody wrapped) must still land on the same
    # 500-no-internals taxonomy as everything else, not escape uncaught.
    def _boom(headers):
        raise RuntimeError("boom")

    monkeypatch.setattr(handler, "authenticate", _boom)
    status, raw = _request(live_server, "GET", "/api/provision/status")
    assert status == 500
    text = raw.decode("utf-8")
    assert json.loads(raw) == {"error": "internal error"}
    assert "boom" not in text
    assert "RuntimeError" not in text


def test_post_missing_content_length_400(live_server, fake_google_certs, rsa_keypair, monkeypatch):
    private_key, _ = rsa_keypair
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT_ID)
    token = make_id_token(private_key, sub="uid-cl")

    conn = _UnixHTTPConnection(live_server)
    try:
        conn.putrequest("POST", "/api/provision", skip_host=True, skip_accept_encoding=True)
        conn.putheader("Authorization", f"Bearer {token}")
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 400
        payload = json.loads(resp.read())
        assert "Content-Length" in payload["error"]
    finally:
        conn.close()


def test_post_oversized_body_400(live_server, fake_google_certs, rsa_keypair, monkeypatch):
    private_key, _ = rsa_keypair
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT_ID)
    token = make_id_token(private_key, sub="uid-big")

    # Declares a body far past MAX_BODY_BYTES; the server must reject on
    # the DECLARED size before ever calling rfile.read(), so the actual
    # bytes sent here can (and should, for a fast test) stay tiny.
    status, raw = _request(
        live_server,
        "POST",
        "/api/provision",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Length": str(handler.MAX_BODY_BYTES + 1),
        },
        body=b"{}",
    )
    assert status == 400
    assert "too large" in json.loads(raw)["error"]


def test_full_provision_then_status_roundtrip(
    live_server, fake_google_certs, rsa_keypair, monkeypatch
):
    private_key, _ = rsa_keypair
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT_ID)
    token = make_id_token(private_key, sub="uid-roundtrip")
    body = json.dumps({"EMAIL_ADDRESS": "a@b.com"}).encode("utf-8")

    status, raw = _request(
        live_server,
        "POST",
        "/api/provision",
        headers={"Authorization": f"Bearer {token}", "Content-Length": str(len(body))},
        body=body,
    )
    assert status == 200
    assert json.loads(raw) == {"uid": "uid-roundtrip", "state": "preparing"}

    status, raw = _request(
        live_server,
        "GET",
        "/api/provision/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == 200
    assert json.loads(raw) == {"state": "preparing"}


def test_a_token_for_uid_a_cannot_touch_uid_b(
    live_server, fake_google_certs, rsa_keypair, monkeypatch
):
    private_key, _ = rsa_keypair
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT_ID)
    token_a = make_id_token(private_key, sub="uid-a")
    body = json.dumps({}).encode("utf-8")
    status, _raw = _request(
        live_server,
        "POST",
        "/api/provision",
        headers={"Authorization": f"Bearer {token_a}", "Content-Length": str(len(body))},
        body=body,
    )
    assert status == 200

    # uid B's own (validly signed) token reading status only ever sees
    # its OWN state — never uid A's — because the uid is derived from
    # the caller's own verified `sub`, not from anything in the request.
    token_b = make_id_token(private_key, sub="uid-b")
    status, raw = _request(
        live_server,
        "GET",
        "/api/provision/status",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert status == 200
    assert json.loads(raw) == {"state": "not_provisioned"}
