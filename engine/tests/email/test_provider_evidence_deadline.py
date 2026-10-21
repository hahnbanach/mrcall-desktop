import socket
import threading
import time

import pytest

from zylch.email.imap_client import IMAPClient, IMAPError


def test_provider_deadline_aborts_blocked_socket_and_retires_connection():
    released = threading.Event()

    class Socket:
        def settimeout(self, value):
            assert value > 0

        def shutdown(self, direction):
            assert direction == socket.SHUT_RDWR
            released.set()

    class Connection:
        sock = Socket()

        def shutdown(self):
            released.set()

    client = IMAPClient("owner@example.test", "disposable-fixture")
    client._conn = Connection()
    started = time.monotonic()
    with pytest.raises(IMAPError, match="deadline"):
        with client.provider_deadline(started + 0.05):
            assert released.wait(1)
    assert time.monotonic() - started < 1
    assert client._conn is None and client._deadline_connection is None
    assert client._provider_deadline is None


def test_already_expired_provider_deadline_refuses_before_io():
    client = IMAPClient("owner@example.test", "disposable-fixture")
    with pytest.raises(IMAPError, match="deadline"):
        with client.provider_deadline(time.monotonic() - 1):
            pytest.fail("Expired evidence entered provider")
    assert client._conn is None
