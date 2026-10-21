"""Request-owned reuse exercised through the real IMAP client and deadline timers."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.email.fake_imap import FakeFolder, FakeIMAPConn
from zylch.email.imap_client import IMAPClient, IMAPError


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


@pytest.fixture
def transport(monkeypatch):
    client = IMAPClient("fixture@example.test", "disposable")
    conn = FakeIMAPConn({"INBOX": FakeFolder()})
    counts = {"connect": 0, "noop": 0}

    def connect():
        counts["connect"] += 1
        client._conn = conn

    def noop():
        counts["noop"] += 1
        return "OK", []

    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(conn, "noop", noop)
    return client, conn, counts


def test_one_connection_and_no_repeated_health_probe(transport):
    client, conn, counts = transport
    with client.provider_deadline(deadline := time.monotonic() + 2):
        with client.projection_connection(deadline):
            for _ in range(3):
                assert client.examine_existing("INBOX", deadline=deadline).exists == 0
                assert client._ensure_connected() is conn
    assert counts == {"connect": 1, "noop": 0}
    assert (
        client._projection_connection
        is client._provider_deadline
        is client._deadline_connection
        is None
    )
    client._ensure_connected()
    assert counts == {"connect": 1, "noop": 1}


@pytest.mark.parametrize("fault", ["missing-deadline", "different-deadline", "nested"])
def test_missing_mismatched_and_nested_projection_scopes_refuse(transport, fault):
    client, _, counts = transport
    deadline = time.monotonic() + 2
    if fault == "missing-deadline":
        with pytest.raises(IMAPError):
            with client.projection_connection(deadline):
                pass
    else:
        with client.provider_deadline(deadline):
            if fault == "different-deadline":
                with pytest.raises(IMAPError):
                    with client.projection_connection(deadline + 1):
                        pass
            else:
                with client.projection_connection(deadline):
                    with pytest.raises(IMAPError):
                        with client.projection_connection(deadline):
                            pass
    assert counts["connect"] == 0
    assert client._projection_connection is client._provider_deadline is None


@pytest.mark.parametrize("fault", ["lost", "replaced", "deadline", "thread"])
def test_projection_cannot_reconnect_or_change_ownership(transport, fault):
    client, conn, counts = transport
    with client.provider_deadline(deadline := time.monotonic() + 2):
        with client.projection_connection(deadline):
            assert client._ensure_connected() is conn
            if fault == "lost":
                client._conn = None
            elif fault == "replaced":
                client._conn = FakeIMAPConn({})
            elif fault == "deadline":
                client._provider_deadline = deadline - 1
            if fault == "thread":
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with pytest.raises(IMAPError, match="scope changed"):
                        pool.submit(client._ensure_connected.__wrapped__, client).result()
            else:
                with pytest.raises(IMAPError):
                    client._ensure_connected()
            client._provider_deadline = deadline
    assert counts["connect"] == 1
    assert client._projection_connection is client._provider_deadline is None


def test_provider_failure_clears_projection_and_discards_connection(transport, monkeypatch):
    client, conn, _ = transport
    calls = []
    monkeypatch.setattr(conn, "shutdown", lambda: calls.append("discard"), raising=False)
    with pytest.raises(OSError, match="provider failed"):
        with client.provider_deadline(deadline := time.monotonic() + 2):
            with client.projection_connection(deadline):
                client._ensure_connected()
                raise OSError("provider failed")
    assert calls == ["discard"]
    assert (
        client._projection_connection
        is client._provider_deadline
        is client._deadline_connection
        is client._conn
        is None
    )
    assert client._imap_lock.acquire(blocking=False)
    client._imap_lock.release()


def test_real_timeout_aborts_blocked_protocol_and_joins_every_timer(transport, monkeypatch):
    client, conn, _ = transport
    released = threading.Event()
    timers = []
    native = threading.Timer

    class Socket:
        def settimeout(self, timeout):
            assert timeout > 0

        def shutdown(self, how):
            released.set()

    conn.sock = Socket()
    monkeypatch.setattr(conn, "shutdown", lambda: released.set(), raising=False)

    def timer(*args, **kwargs):
        value = native(*args, **kwargs)
        timers.append(value)
        return value

    def select(*args, **kwargs):
        assert released.wait(1), "deadline did not abort the protocol"
        raise OSError("socket interrupted")

    monkeypatch.setattr(threading, "Timer", timer)
    monkeypatch.setattr(conn, "select", select)
    started = time.monotonic()
    with pytest.raises((IMAPError, OSError)):
        with client.provider_deadline(deadline := started + 0.05):
            with client.projection_connection(deadline):
                client.examine_existing("INBOX", deadline=deadline)
    assert time.monotonic() - started < 1
    assert released.is_set() and timers and all(not timer.is_alive() for timer in timers)
    assert (
        client._projection_connection
        is client._provider_deadline
        is client._deadline_connection
        is client._conn
        is None
    )


def test_projection_manager_cannot_be_entered_on_another_thread(transport):
    client, _, counts = transport
    with client.provider_deadline(deadline := time.monotonic() + 2):
        manager = client.projection_connection(deadline)

        def enter():
            with manager:
                pass

        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(IMAPError, match="scope unavailable"):
                pool.submit(enter).result()
    assert counts["connect"] == 0
    assert client._projection_connection is client._provider_thread is None
