import imaplib
import inspect
import multiprocessing
import socket
import threading
import time
from contextlib import contextmanager

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from zylch.email.imap_client import IMAPClient, IMAPError
from zylch.services import task_assignment_evidence as evidence


def native_pair():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    events = []
    done = threading.Event()

    def peer():
        connection, _ = listener.accept()
        with connection:
            connection.sendall(b'* PREAUTH fixture ready\r\n')
            stream = connection.makefile('rb')
            while line := stream.readline():
                tag, command, *_ = line.split()
                events.append(command)
                if command == b'CAPABILITY':
                    connection.sendall(b'* CAPABILITY IMAP4rev1\r\n' + tag + b' OK ready\r\n')
                elif command == b'LOGOUT':
                    stream.read()
                    break
            stream.close()
        listener.close()
        done.set()

    threading.Thread(target=peer, daemon=True).start()
    native = imaplib.IMAP4('127.0.0.1', listener.getsockname()[1])
    client = IMAPClient('owner@example.test', 'fixture', imap_host='127.0.0.1')
    client._conn = native
    return client, native, events, done


def bounded_child(queue):
    client, native, events, done = native_pair()
    started = time.monotonic()
    with evidence.observation('<root@example.test>', started + .2):
        state = evidence._observation.get()
        state.clients['one'] = client
        state.guards.enter_context(client.provider_deadline(started + .2))
    state.close()
    queue.put((time.monotonic() - started, done.wait(.2), events, native.sock.fileno(), client._conn, len(state.clients), evidence._observation.get()))


def test_stalled_logout_has_local_terminal_bound():
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    process = context.Process(target=bounded_child, args=(queue,))
    process.start()
    process.join(2)
    alive = process.is_alive()
    if alive:
        process.terminate()
        process.join()
    assert not alive, 'terminal cleanup exceeded 2-second watchdog on stalled LOGOUT'
    elapsed, eof, events, descriptor, connection, clients, state = queue.get(timeout=1)
    assert elapsed < .2
    assert eof and b'LOGOUT' not in events
    assert descriptor == -1 and connection is None and clients == 0 and state is None


def test_real_closed_socket_rejects_timeout():
    client, native, _, done = native_pair()
    client._discard_connection(native)
    with unittest.TestCase().assertRaises(OSError):
        native.sock.settimeout(1)
    assert done.wait(1)


def test_guard_first_failure_disposes_every_client_and_is_idempotent():
    first, n1, _, done1 = native_pair()
    second, n2, _, done2 = native_pair()
    options = {'reuse_protocol': True} if 'reuse_protocol' in inspect.signature(evidence._Observation).parameters else {}
    state = evidence._Observation('<root@example.test>', time.monotonic() + 1, **options)
    state.clients.update(first=first, second=second)
    failure = RuntimeError('guard failed')

    @contextmanager
    def guard():
        yield
        n1.sock.settimeout(.1)
        n2.sock.settimeout(.1)
        raise failure

    state.guards.enter_context(guard())
    with unittest.TestCase().assertRaises(RuntimeError) as caught:
        state.close()
    assert caught.exception is failure
    state.close()
    assert not state.clients and first._conn is None and second._conn is None
    assert done1.wait(1) and done2.wait(1)


def test_expiry_nested_deadlines_reset_context_and_fail_closed():
    client, native, _, done = native_pair()
    with unittest.TestCase().assertRaisesRegex(IMAPError, 'deadline'):
        with evidence.observation('<root@example.test>', deadline := time.monotonic() + .04):
            state = evidence._observation.get()
            state.clients['one'] = client
            state.guards.enter_context(client.provider_deadline(deadline))
            with client.provider_deadline(deadline + 1):
                time.sleep(.06)
    assert evidence._observation.get() is None
    assert client._conn is None and client._provider_deadline is None
    assert client._deadline_connection is None and done.wait(1)
    assert client._imap_lock.acquire(blocking=False)
    client._imap_lock.release()


def test_snapshot_success_and_provider_failure_use_local_disposal():
    for fail in (False, True):
        client, native, events, done = native_pair()
        actor = SimpleNamespace(uid='owner', binding='fixture', mailbox='owner')
        box = SimpleNamespace(id='box')
        def archive():
            if fail:
                raise RuntimeError('provider failed')
            return 'Archive'
        client.find_archive_folder = archive
        with patch.object(evidence, 'admission', return_value=(actor, 'space', {'members': {'owner': []}})), patch.object(evidence.trust, 'delivery_routes_digest', return_value='routes'), patch.object(evidence.mail, 'rows', return_value=[]), patch.object(evidence.mail, 'configured', return_value=[box]), patch.object(evidence.mail, 'mailbox_digest', return_value='boxdigest'), patch.object(evidence.mail, 'component', return_value=(['<root@example.test>'], None, None)), patch.object(evidence.mail, 'fetch', return_value=([], {'folder': 'Archive', 'uidvalidity': 1})), patch.object(evidence.mail, 'row_digest', return_value='rows'), patch.object(evidence.identity, 'recheck'), patch.object(evidence.mailboxes, 'build_imap_client', return_value=client):
            if fail:
                with unittest.TestCase().assertRaisesRegex(RuntimeError, 'provider failed'):
                    evidence.snapshot('<root@example.test>')
            else:
                assert evidence.snapshot('<root@example.test>')['covered_inbound'] == []
        assert client._conn is None and native.sock.fileno() == -1
        assert done.wait(1) and b'LOGOUT' not in events


def test_partial_provider_construction_preserves_error_and_releases_all_clients():
    first, first_native, first_events, first_done = native_pair()
    second, second_native, second_events, second_done = native_pair()
    actor = SimpleNamespace(uid='owner', mailbox='owner')
    failure = RuntimeError('second guard entry failed')
    sequence = []
    root = '<root@example.test>'
    deadline = time.monotonic() + 1

    @contextmanager
    def fail_entry(limit):
        second_native.sock.settimeout(.1)
        raise failure
        yield

    @contextmanager
    def check_retained_sockets():
        yield
        first_native.sock.settimeout(.1)
        second_native.sock.settimeout(.1)
        sequence.append('guards')

    discard = second._discard_connection
    def dispose(connection):
        assert sequence == ['guards']
        sequence.append('dispose')
        discard(connection)

    second.provider_deadline = fail_entry
    second._discard_connection = dispose
    with patch.object(evidence.mail, 'mailbox_digest', return_value='stable'), patch.object(evidence.mailboxes, 'build_imap_client', side_effect=[first, second]):
        with unittest.TestCase().assertRaises(RuntimeError) as caught:
            with evidence.observation(root, deadline):
                state = evidence._observation.get()
                with evidence.provider_client(actor, SimpleNamespace(id='first'), root, deadline):
                    pass
                state.guards.enter_context(check_retained_sockets())
                with evidence.provider_client(actor, SimpleNamespace(id='second'), root, deadline):
                    raise AssertionError('failed provider must not yield a success result')
    assert caught.exception is failure
    assert evidence._observation.get() is None and state.closed and not state.clients
    assert sequence == ['guards', 'dispose']
    for client, native, events, done in [(first, first_native, first_events, first_done), (second, second_native, second_events, second_done)]:
        assert client._conn is None and native.sock.fileno() == -1
        assert client._provider_deadline is None and client._deadline_connection is None
        assert done.wait(1) and b'LOGOUT' not in events
        assert client._imap_lock.acquire(blocking=False)
        client._imap_lock.release()


class TerminalDisposalTests(unittest.TestCase):
    pass


for name, function in list(globals().items()):
    if name.startswith("test_"):
        setattr(TerminalDisposalTests, name, lambda self, function=function: function())

del function

if __name__ == "__main__":
    unittest.main()
