import hashlib
import json
import os
import sqlite3
import stat
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from zylch.operator_mcp.broker_store import BrokerStore, StorageError


class BrokerStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'broker.sqlite'
        self.store = BrokerStore(self.path)

    def test_restart_persistence_and_copied_payloads(self):
        original = {'client_id': 'public', 'nested': {'values': [1]}, 'client_secret': None}
        self.store.put('clients', 'public', original)
        original['nested']['values'].append(2)
        fetched = self.store.get('clients', 'public')
        fetched['nested']['values'].append(3)
        restarted = BrokerStore(self.path)
        self.assertEqual(restarted.get('clients', 'public')['nested'], {'values': [1]})
        self.assertEqual(restarted.list('clients')[0]['client_id'], 'public')
        self.assertEqual(restarted.count('clients'), 1)

    def test_atomic_consume_with_independent_thread_connections(self):
        self.store.put('codes', 'random-secret-code', {'grant_id': 'grant'})
        barrier = threading.Barrier(8)

        def consume(_):
            independent = BrokerStore(self.path)
            barrier.wait(timeout=10)
            return independent.consume('codes', 'random-secret-code')

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(consume, range(8)))
        self.assertEqual(results.count({'grant_id': 'grant'}), 1)
        self.assertEqual(results.count(None), 7)
        self.assertIsNone(self.store.get('codes', 'random-secret-code'))
        self.assertEqual(self.store.get('codes', 'random-secret-code', include_consumed=True),
                         {'grant_id': 'grant', '_consumed': True})
        self.assertEqual(self.store.list('codes'), [])
        self.assertEqual(self.store.count('codes'), 1)

    def test_transaction_rollback_restores_consumption_and_insertion(self):
        self.store.put('refresh', 'first-secret', {'grant_id': 'grant'})
        with self.assertRaisesRegex(RuntimeError, 'abort'):
            with self.store.transaction() as connection:
                self.assertEqual(self.store.consume('refresh', 'first-secret', connection), {'grant_id': 'grant'})
                self.store.put('refresh', 'next-secret', {'grant_id': 'grant'}, connection)
                self.store.update('refresh', 'next-secret', {'grant_id': 'changed'}, connection)
                self.assertEqual(self.store.get('refresh', 'next-secret', connection=connection), {'grant_id': 'changed'})
                self.assertEqual(self.store.count('refresh', connection=connection), 2)
                self.assertEqual(self.store.list('refresh', connection=connection), [{'grant_id': 'changed'}])
                raise RuntimeError('abort')
        self.assertEqual(self.store.get('refresh', 'first-secret'), {'grant_id': 'grant'})
        self.assertIsNone(self.store.get('refresh', 'next-secret'))
        with self.store.transaction() as connection:
            self.store.consume('refresh', 'first-secret', connection)
            self.store.put('refresh', 'next-secret', {'grant_id': 'grant'}, connection)
        self.assertIsNone(BrokerStore(self.path).get('refresh', 'first-secret'))
        self.assertEqual(self.store.get('refresh', 'next-secret'), {'grant_id': 'grant'})

    def test_namespaced_hashes_without_durable_token_bytes(self):
        raw = 'RAW-TOKEN-CANARY-VERY-SECRET'
        for namespace in ['codes', 'access', 'refresh']:
            self.store.put(namespace, raw, {'grant_id': 'public-grant'})
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute('SELECT namespace,keyhash,payload FROM records').fetchall()
        self.assertEqual(len({row[1] for row in rows}), 3)
        for namespace, keyhash, payload in rows:
            self.assertEqual(keyhash, hashlib.sha256((namespace + '\x00' + raw).encode()).hexdigest())
            self.assertEqual(json.loads(payload), {'grant_id': 'public-grant'})
        self.assertNotIn(raw.encode(), self.path.read_bytes())
        self.store.consume('codes', raw)
        self.assertIsNotNone(self.store.get('access', raw))

    def test_duplicate_refusal_explicit_update_and_no_consumption_reset(self):
        self.store.put('codes', 'secret', {'grant_id': 'first'})
        with self.assertRaisesRegex(StorageError, '^record already exists$'):
            self.store.put('codes', 'secret', {'grant_id': 'second'})
        with self.assertRaisesRegex(StorageError, '^record not found$'):
            self.store.update('codes', 'missing', {})
        self.store.update('codes', 'secret', {'grant_id': 'updated'})
        self.assertEqual(self.store.consume('codes', 'secret'), {'grant_id': 'updated'})
        self.store.put('codes', 'secret', {'grant_id': 'replacement'}, overwrite=True)
        self.assertIsNone(self.store.consume('codes', 'secret'))
        self.assertEqual(self.store.get('codes', 'secret', True), {'grant_id': 'replacement', '_consumed': True})

    def test_recursive_secret_keys_json_type_and_size_refusal(self):
        denied = [{key: 'SECRET-CANARY'} for key in ['token', 'code', 'access_token', 'refresh_token', 'client_secret', '_consumed']]
        denied += [{'nested': [{'token': 'SECRET-CANARY'}]}, {'bad': float('nan')}, {'bad': float('inf')},
                   {'bad': object()}, {'bad': (1, 2)}, {1: 'bad'}, [], {'oversized': 'x' * 65536}]
        recursive = {}
        recursive['loop'] = recursive
        denied.append(recursive)
        for payload in denied:
            with self.subTest(kind=type(payload).__name__):
                with self.assertRaises(StorageError) as caught:
                    self.store.put('grants', 'public', payload)
                self.assertNotIn('SECRET-CANARY', str(caught.exception))
        self.store.put('pending', 'public', {'code_challenge': 'public-s256', 'client_secret': None})
        self.assertEqual(self.store.count('grants'), 0)

    def test_private_file_parent_symlink_owner_and_hardlink_refusal(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.path.stat().st_uid, os.getuid())
        with self.store.transaction() as connection:
            self.store.put('grants', 'public', {}, connection)
            journal = Path(str(self.path) + '-journal')
            self.assertTrue(journal.is_file())
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(StorageError, '^unsafe store file$'):
            BrokerStore(self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)
        os.chmod(self.path, 0o600)
        with patch('zylch.operator_mcp.broker_store.os.getuid', return_value=os.getuid() + 1):
            with self.assertRaises(StorageError):
                BrokerStore(self.path)
        symlink = self.path.parent / 'symlink.sqlite'
        symlink.symlink_to(self.path)
        with self.assertRaises(StorageError):
            BrokerStore(symlink)
        hardlink = self.path.parent / 'hardlink.sqlite'
        os.link(self.path, hardlink)
        with self.assertRaisesRegex(StorageError, '^unsafe store file$'):
            BrokerStore(hardlink)
        hardlink.unlink()
        os.chmod(self.path.parent, 0o755)
        with self.assertRaisesRegex(StorageError, '^unsafe store directory$'):
            BrokerStore(self.path)
        os.chmod(self.path.parent, 0o700)
        with tempfile.TemporaryDirectory() as directory:
            parent_link = Path(directory) / 'link'
            parent_link.symlink_to(self.path.parent, target_is_directory=True)
            with self.assertRaisesRegex(StorageError, '^unsafe store directory$'):
                BrokerStore(parent_link / 'other.sqlite')

    def test_invalid_namespace_key_foreign_transaction_and_corruption(self):
        for namespace, key in [('unknown', 'key'), ('grants', ''), ('grants', 'x' * 4097), ('grants', '\ud800')]:
            with self.assertRaises(StorageError):
                self.store.get(namespace, key)
        with sqlite3.connect(':memory:') as foreign:
            with self.assertRaisesRegex(StorageError, '^invalid store transaction$'):
                self.store.put('grants', 'public', {}, connection=foreign)
        self.store.put('grants', 'public', {})
        with sqlite3.connect(self.path) as connection:
            connection.execute('UPDATE records SET payload=?', ('{"token":"SECRET-CANARY"}',))
        with self.assertRaises(StorageError) as caught:
            self.store.get('grants', 'public')
        self.assertNotIn('SECRET-CANARY', str(caught.exception))
        with sqlite3.connect(self.path) as connection:
            connection.execute('UPDATE records SET payload=?', ('{"large":"' + 'x' * 65536 + '"}',))
        with self.assertRaisesRegex(StorageError, '^invalid stored record$'):
            self.store.get('grants', 'public')


if __name__ == '__main__':
    unittest.main()
