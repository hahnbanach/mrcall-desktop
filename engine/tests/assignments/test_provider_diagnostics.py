import imaplib
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from zylch.email.imap_client import IMAPClient
from zylch.email import provider_diagnostics as diagnostics
from zylch.observability import EventStore, context
from zylch import observability_producers as producers


class ProtocolPeer:
    def __init__(self, directory, mode):
        self.mode = mode
        self.commands = []
        self.done = threading.Event()
        certificate = str(Path(directory) / 'cert.pem')
        key = str(Path(directory) / 'key.pem')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', certificate, '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.server_context.load_cert_chain(certificate, key)
        self.client_context = ssl.create_default_context(cafile=certificate)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            connection, _ = self.listener.accept()
            with self.server_context.wrap_socket(connection, server_side=True) as stream:
                stream.sendall(b'* OK fixture ready\r\n')
                reader = stream.makefile('rb')
                try:
                    while line := reader.readline():
                        tag, command, *_ = line.split()
                        self.commands.append(command)
                        if command == b'CAPABILITY':
                            stream.sendall(b'* CAPABILITY IMAP4rev1\r\n' + tag + b' OK done\r\n')
                        elif command == b'LOGIN':
                            stream.sendall(tag + b' OK authenticated\r\n')
                        elif command == b'NOOP':
                            stream.sendall(tag + b' OK done\r\n')
                        elif command == b'EXAMINE':
                            if self.mode == 'success':
                                stream.sendall(b'* 0 EXISTS\r\n* OK [UIDVALIDITY 1] stable\r\n* OK [UIDNEXT 1] stable\r\n' + tag + b' OK [READ-ONLY] done\r\n')
                            else:
                                if self.mode == 'partial':
                                    stream.sendall(b'* 0 EXISTS\r\n')
                                reader.read()
                                break
                finally:
                    reader.close()
        finally:
            self.listener.close()
            self.done.set()


class ProviderDiagnostics(unittest.TestCase):
    def exercise(self, mode, sink_failure=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        peer = ProtocolPeer(directory.name, mode)
        store = EventStore(Path(directory.name) / 'events', 'owner')
        native = imaplib.IMAP4_SSL
        class TrustedSSL(native):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, ssl_context=peer.client_context, **kwargs)
        with patch.object(imaplib, 'IMAP4_SSL', TrustedSSL), patch.object(producers, 'store', return_value=store), context({'trace_id': 'a' * 32}), diagnostics.scope('<fixture@example.test>', time.monotonic() + .5) as recorder:
            client = IMAPClient('owner@example.test', 'PRIVATE_PASSWORD_SENTINEL', imap_host='127.0.0.1', imap_port=peer.port)
            if sink_failure:
                self.addCleanup(patch.stopall)
                patch.object(store, 'emit', side_effect=OSError('PRIVATE_LOGGING_SENTINEL')).start()
            def examine():
                with ExitStack() as guards:
                    guards.enter_context(client.provider_deadline(recorder.deadline))
                    if hasattr(client, "projection_connection"):
                        guards.enter_context(client.projection_connection(recorder.deadline))
                    return client.examine_existing("PRIVATE_FOLDER_SENTINEL", deadline=recorder.deadline)
            try:
                if mode == 'success':
                    result = examine()
                    self.assertEqual(result.exists, 0)
                else:
                    with self.assertRaises(Exception):
                        examine()
            finally:
                client._discard_connection(client._conn)
                client._conn = None
        self.assertTrue(peer.done.wait(1))
        peer.thread.join(1)
        self.assertFalse(peer.thread.is_alive())
        events = [json.loads(line) for path in store.root.glob('events-*.jsonl') for line in path.read_text().splitlines()]
        self.assertNotIn('PRIVATE_', json.dumps(events))
        self.assertTrue(all(row['trace_id'] == 'a' * 32 for row in events))
        self.assertEqual(peer.commands.count(b'EXAMINE'), 1)
        self.assertNotIn(b'LOGOUT', peer.commands)
        self.assertIsNone(client._provider_deadline)
        self.assertIsNone(client._deadline_connection)
        self.assertTrue(client._imap_lock.acquire(blocking=False))
        client._imap_lock.release()
        return recorder, events

    def test_real_tls_stalled_command_retains_first_fault_and_state(self):
        recorder, events = self.exercise('stall')
        fault = recorder.first_fault
        self.assertEqual(fault['operation'], 'examine')
        self.assertEqual(fault['command'], 'EXAMINE')
        self.assertEqual(fault['phase'], 'failed')
        self.assertEqual(fault['inbound_progress_count'], 0)
        self.assertIn(fault['tls_state'], {'established', 'closed', 'absent'})
        self.assertGreaterEqual(fault['duration_ms'], 100)
        self.assertEqual(fault['cause'], 'deadline')
        self.assertTrue(fault['connection_id'])
        timeline = [row['provider_diagnostic'] for row in events]
        self.assertTrue(any(row['operation'] == 'tls' for row in timeline))
        self.assertTrue(any(row['operation'] == 'abort' for row in timeline))
        self.assertEqual([row['sequence'] for row in timeline], sorted(row['sequence'] for row in timeline))
        self.assertEqual(recorder.first_fault, fault)

    def test_partial_untagged_progress_remains_failure(self):
        recorder, _ = self.exercise('partial')
        self.assertEqual(recorder.first_fault['command'], 'EXAMINE')
        self.assertGreater(recorder.first_fault['inbound_progress_count'], 0)
        self.assertIsNotNone(recorder.first_fault['last_inbound_progress_offset_ms'])

    def test_unexpired_success_has_no_first_fault(self):
        recorder, events = self.exercise('success')
        self.assertIsNone(recorder.first_fault)
        self.assertFalse(any(row['status'] == 'failed' for row in events))

    def test_timer_target_change_preserves_actual_connection_identity_and_state(self):
        class Connection:
            def __init__(self, state, pending):
                self.state = state
                self.tagged_commands = {str(index): None for index in range(pending)}
                self.sock = socket.socket()
        class Client:
            _conn = _deadline_connection = None
        first = Connection('AUTH', 1)
        second = Connection('SELECTED', 2)
        try:
            client = Client()
            client._conn = client._deadline_connection = first
            recorder = diagnostics.Recorder('<fixture@example.test>')
            first_identity = recorder.attach(first)
            second_identity = recorder.attach(second)
            targets = []
            callback, _ = recorder.timer(client, lambda: targets.append(client._conn))
            client._conn = client._deadline_connection = second
            callback()
            armed = next(row for row in recorder.records if row['phase'] == 'armed')
            fired = next(row for row in recorder.records if row['phase'] == 'fired')
            self.assertEqual((armed['connection_id'], armed['generation']), first_identity)
            self.assertEqual(armed['imap_state'], 'AUTH')
            self.assertEqual((fired['connection_id'], fired['generation']), second_identity)
            self.assertEqual(fired['imap_state'], 'SELECTED')
            self.assertEqual(fired['socket_state'], 'open')
            self.assertEqual(fired['pending_tags'], 2)
            self.assertIs(fired['deadline_match'], False)
            self.assertEqual(targets, [second])
            self.assertIsNone(recorder.first_fault)
        finally:
            first.sock.close()
            second.sock.close()

    def test_timer_thread_retains_context_without_inventing_a_fault(self):
        class Client:
            _conn = _deadline_connection = None
        client = Client()
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory), 'owner')
            with patch.object(producers, 'store', return_value=store), context({'trace_id': 'b' * 32}), diagnostics.scope('<fixture@example.test>') as recorder:
                with recorder.operation(client, None, 'examine', 'EXAMINE'):
                    callback, _ = recorder.timer(client, lambda: None)
                    timer = threading.Timer(.001, callback)
                    timer.start()
                    timer.join(1)
                    self.assertFalse(timer.is_alive())
                self.assertIsNone(recorder.first_fault)
            rows = [json.loads(line) for path in store.root.glob('events-*.jsonl') for line in path.read_text().splitlines()]
            self.assertTrue(rows)
            self.assertTrue(all(row['trace_id'] == 'b' * 32 for row in rows))
            self.assertTrue(any(row['provider_diagnostic']['phase'] == 'fired' for row in rows))
            self.assertFalse(any(row['status'] == 'failed' for row in rows))
        self.assertIsNone(diagnostics.current())

    def test_bounded_concurrent_capture_and_immutable_first_fault(self):
        class Client:
            _conn = _deadline_connection = None
        client = Client()
        recorder = diagnostics.Recorder('<fixture@example.test>', time.monotonic() + 1)
        threads = [threading.Thread(target=lambda: [recorder.record(client, None, 'guard', 'enter') for _ in range(400)]) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertTrue(recorder.overflow)
        self.assertLessEqual(recorder.total, 2048)
        self.assertTrue(any(row['overflow'] for row in recorder.records))
        self.assertEqual(len({row['sequence'] for row in recorder.records}), len(recorder.records))
        recorder.record(client, None, 'examine', 'failed', cause='socket_error')
        first = dict(recorder.first_fault)
        recorder.record(client, None, 'dispose', 'failed', cause='cleanup')
        self.assertEqual(recorder.first_fault, first)

    def test_unavailable_sink_keeps_native_failure_and_cleanup(self):
        recorder, events = self.exercise('stall', sink_failure=True)
        self.assertEqual(recorder.first_fault['command'], 'EXAMINE')
        self.assertFalse(events)


if __name__ == '__main__':
    unittest.main()
