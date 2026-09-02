"""Neither socket in this client is allowed to wait forever.

Both were. `imaplib.IMAP4_SSL(host, port)` and `smtplib.SMTP(host, port)`
inherit the kernel's TCP budget — about fifteen minutes when the peer
dies cleanly, and no bound at all when it accepts the connection and
then stops answering. The 108-second IMAP connect that stalled a whole
chat turn is that socket with nothing to stop it.

The SMTP deadline is load-bearing beyond latency: `storage` derives the
send-claim window — how long a draft may sit in `sending` before another
attempt may take it over — from this exact number. A send that outlives
its claim is a mail delivered twice, so the two must not drift apart,
and the timeout the socket is built with must be *that* constant rather
than a copy of it.

These are construction-site tests: they assert the arguments the client
passes and what it does when a deadline fires. A test against a server
that really stalls would need a socket fixture and minutes of wall
clock to say the same thing; the value is in the argument and in the
cleanup, and both are visible here.
"""

from __future__ import annotations

import socket

import pytest

from zylch.email import imap_client as mod
from zylch.email.imap_client import IMAPClient, IMAPError

ADDR = "owner@example.test"


def _client() -> IMAPClient:
    return IMAPClient(email_addr=ADDR, password="not-a-real-password")


class _FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class _FakeIMAP:
    """Records how imaplib was constructed; never touches a network."""

    calls: list = []
    login_error: Exception | None = None

    def __init__(self, host, port, **kwargs):
        type(self).calls.append({"host": host, "port": port, **kwargs})
        self.sock = _FakeSocket()
        self.shutdown_calls = 0

    def login(self, _user, _password):
        if type(self).login_error is not None:
            raise type(self).login_error
        return ("OK", [b"logged in"])

    def shutdown(self):
        self.shutdown_calls += 1


@pytest.fixture(autouse=True)
def _reset():
    _FakeIMAP.calls = []
    _FakeIMAP.login_error = None
    yield
    _FakeIMAP.calls = []
    _FakeIMAP.login_error = None


# ─── IMAP ─────────────────────────────────────────────────────────────


def test_the_imap_connect_is_bounded(monkeypatch):
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)

    _client().connect()

    assert len(_FakeIMAP.calls) == 1
    assert _FakeIMAP.calls[0]["timeout"] == mod.IMAP_CONNECT_TIMEOUT_SECONDS
    assert mod.IMAP_CONNECT_TIMEOUT_SECONDS > 0


def test_an_authenticated_socket_is_relaxed_for_long_commands(monkeypatch):
    """A SEARCH over a large mailbox may think for a while; a handshake
    may not. The connection carries the tight deadline only while it is
    being established."""
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)

    client = _client()
    client.connect()

    assert client._conn.sock.timeouts == [mod.IMAP_COMMAND_TIMEOUT_SECONDS]
    assert mod.IMAP_COMMAND_TIMEOUT_SECONDS > mod.IMAP_CONNECT_TIMEOUT_SECONDS


def test_a_connect_timeout_is_an_error_not_a_hang(monkeypatch):
    def _stall(host, port, **_kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _stall)
    client = _client()

    with pytest.raises(IMAPError) as excinfo:
        client.connect()

    message = str(excinfo.value)
    assert "IMAP connect" in message
    assert str(mod.IMAP_CONNECT_TIMEOUT_SECONDS) in message
    assert client.imap_host in message


def test_a_failed_connect_caches_no_half_built_connection(monkeypatch):
    """The next call must start over, not inherit a broken socket."""
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)
    _FakeIMAP.login_error = socket.timeout("timed out waiting for login")

    client = _client()
    with pytest.raises(IMAPError):
        client.connect()

    assert client._conn is None

    # And a later attempt succeeds on a fresh connection.
    _FakeIMAP.login_error = None
    client.connect()
    assert client._conn is not None
    assert len(_FakeIMAP.calls) == 2


def test_a_login_failure_closes_the_socket_it_opened(monkeypatch):
    opened = []

    class _Tracking(_FakeIMAP):
        def __init__(self, host, port, **kwargs):
            super().__init__(host, port, **kwargs)
            opened.append(self)

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _Tracking)
    _FakeIMAP.login_error = OSError("refused")

    with pytest.raises(IMAPError):
        _client().connect()

    assert len(opened) == 1
    assert opened[0].shutdown_calls == 1


def test_a_dead_connection_is_released_before_reconnecting(monkeypatch):
    """`_ensure_connected` must not keep probing a corpse forever."""
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)

    client = _client()
    client.connect()
    dead = client._conn

    def _broken_noop():
        raise OSError("connection reset")

    dead.noop = _broken_noop
    client._ensure_connected()

    assert dead.shutdown_calls == 1
    assert client._conn is not dead


# ─── SMTP ─────────────────────────────────────────────────────────────


def test_the_smtp_socket_uses_the_deadline_the_claim_window_is_built_on(monkeypatch):
    from zylch.storage.storage import SMTP_TRANSPORT_TIMEOUT_SECONDS

    seen = {}

    class _FakeSMTP:
        def __init__(self, host, port, timeout=None, **_kwargs):
            seen["host"] = host
            seen["port"] = port
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def ehlo(self):
            return ("OK", b"")

        def starttls(self):
            return ("OK", b"")

        def login(self, _user, _password):
            return ("OK", b"")

        def sendmail(self, *_args, **_kwargs):
            return {}

        def send_message(self, *_args, **_kwargs):
            return {}

    monkeypatch.setattr(mod.smtplib, "SMTP", _FakeSMTP)

    result = _client().send(to="customer@example.test", subject="Hi", body="Body.")

    assert result["status"] == "sent"
    assert seen["timeout"] == SMTP_TRANSPORT_TIMEOUT_SECONDS
    assert seen["timeout"] is not None


@pytest.mark.parametrize("recipients", [1, 3, 10, 50])
def test_the_claim_window_still_covers_the_send_this_socket_allows(recipients):
    """The window and the deadline must keep moving together.

    A send that outlives its claim lets a second caller re-claim the row
    and deliver the same mail again, so the window is derived from the
    deadline the socket above is built with. This is the guard on that
    derivation: change the timeout, or the sequence `IMAPClient.send`
    performs, without revisiting the window, and it fires.

    The worst case is the SUM of the per-step deadlines, and the sequence
    is connect, EHLO, STARTTLS, EHLO, LOGIN, MAIL FROM, one RCPT TO per
    recipient, DATA, end-of-data, QUIT — nine fixed plus one each. The
    step count lives in `storage`; this test does not re-derive it, it
    checks that the window declared for N recipients still stands above
    what N recipients can cost.
    """
    from zylch.storage.storage import (
        SEND_CLAIM_MARGIN,
        SMTP_FIXED_ROUND_TRIPS,
        SMTP_TRANSPORT_TIMEOUT_SECONDS,
        send_claim_window_minutes,
    )

    worst_case_minutes = (SMTP_FIXED_ROUND_TRIPS + recipients) * SMTP_TRANSPORT_TIMEOUT_SECONDS / 60
    assert send_claim_window_minutes(recipients) >= worst_case_minutes * SEND_CLAIM_MARGIN
