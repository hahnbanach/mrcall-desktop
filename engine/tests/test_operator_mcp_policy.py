import ast
import copy
from dataclasses import dataclass, replace
from datetime import datetime
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zylch import email as email_package, services as services_package
from zylch.operator_mcp import policy


def mailbox_info(**changes):
    path = Path(policy.__file__).parents[1] / 'email' / 'mailboxes.py'
    declaration = next(node for node in ast.parse(path.read_text()).body
                       if isinstance(node, ast.ClassDef) and node.name == 'MailboxInfo')
    namespace = {'dataclass': dataclass, 'datetime': datetime, '__name__': __name__}
    exec(compile(ast.Module(body=[declaration], type_ignores=[]), str(path), 'exec'), namespace)
    value = namespace['MailboxInfo'](id='mailbox-1', owner_id='owner@example.test',
        address='owner@example.test', imap_host='imap.example.test', imap_port=993,
        smtp_host='smtp.example.test', smtp_port=465, preset=None, is_primary=True,
        has_secret=False, created_at=None, last_sync_at=None, last_error=None, removed_at=None)
    return replace(value, **changes)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(profile_uid='owner_1', email='owner@example.test', company_ref='space-1',
                        resource='https://desktop.example.test/operator/owner_1/mcp', mailbox_ids=['mailbox-1'],
                        service_client_id='profile-service-1', service_secret='s' * 32)
        self.broker = dict(version=1, issuer='https://desktop.example.test', firebase_project='firebase-project',
                           native_callbacks=[{'host': '127.0.0.1', 'path': '/callback'}],
                           profiles=[dict(self.row, enabled=True)])
        self.config = dict(self.row, version=1, issuer=self.broker['issuer'],
                           socket_path='/run/mrcalld/owner_1/operator-mcp.sock')

    def load(self, config, broker=True):
        with patch.object(policy.trust, 'protected_read', return_value=json.dumps(config).encode()), \
             patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=0o100640, st_uid=0, st_nlink=1)):
            return (policy.load_broker_config if broker else policy.load_profile_config)('/etc/mrcalld/config.json')

    def test_valid_exact_schema_and_secret_not_in_policy_repr(self):
        self.assertEqual(self.load(self.config, False), self.config)
        self.assertEqual(self.load(self.broker), self.broker)
        with patch.object(policy, 'load_broker_config', return_value=self.broker), \
             patch.object(policy.trust, 'load', return_value={}) as load, \
             patch.object(policy.trust, 'member') as member:
            value = policy.broker_policy('/etc/mrcalld/config.json')(self.row['resource'])
            self.assertNotIn(self.row['service_secret'], repr(value))
            load.assert_called_once_with('space-1')
            member.assert_called_once_with({}, 'owner_1', 'owner@example.test')

    def test_full_operator_policy_is_explicit_and_strictly_boolean(self):
        from zylch.operator_mcp.permissions import BASE_SCOPES, SCOPES, enabled_scopes
        self.assertEqual(enabled_scopes(), BASE_SCOPES)
        self.assertEqual(enabled_scopes(operator_enabled=True), SCOPES)
        for value in [1, 'true', None, []]:
            with self.assertRaises(ValueError):
                enabled_scopes(operator_enabled=value)
            item = copy.deepcopy(self.broker)
            item['profiles'][0]['operator_enabled'] = value
            with self.assertRaises(policy.PolicyError):
                self.load(item)
        item = copy.deepcopy(self.broker)
        item['profiles'][0]['operator_enabled'] = True
        self.assertEqual(self.load(item), item)
        with patch.object(policy, 'load_broker_config', return_value=item), \
             patch.object(policy.trust, 'load', return_value={}), \
             patch.object(policy.trust, 'member'):
            current = policy.broker_policy('/etc/mrcalld/config.json')(self.row['resource'])
            self.assertTrue(current.operator_enabled)
            self.assertEqual(current.allowed_scopes, SCOPES)

    def test_invalid_broker_schema_urls_duplicates_callbacks_and_secrets(self):
        cases = []
        for key, value in [('version', True), ('issuer', 'https://desktop.example.test/'),
                           ('issuer', 'https://user@desktop.example.test'), ('issuer', 'https://desktop.example.test:bad'),
                           ('issuer', 'https://desktop.example.test?x=y'), ('issuer', 'http://desktop.example.test'),
                           ('issuer', 'https://desktop.example.test/issuer'), ('firebase_project', 'bad project'),
                           ('extra', 1), ('native_callbacks', [{'host': 'evil.test', 'path': '/callback'}]),
                           ('native_callbacks', [{'host': 'localhost', 'path': '//evil'}]),
                           ('native_callbacks', [{'host': 'localhost', 'path': '/..'}]),
                           ('native_callbacks', [{'host': 'localhost', 'path': '/cb?next=x'}])]:
            item = copy.deepcopy(self.broker)
            item[key] = value
            cases.append(item)
        for key, value in [('profile_uid', '../other'), ('resource', 'https://other.test/operator/owner_1/mcp'),
                           ('email', 'Owner@example.test'), ('mailbox_ids', []), ('mailbox_ids', ['a', 'b']),
                           ('service_secret', 'short'), ('service_secret', 'x\n' * 16), ('enabled', 1), ('extra', 1)]:
            item = copy.deepcopy(self.broker)
            item['profiles'][0][key] = value
            cases.append(item)
        item = copy.deepcopy(self.broker)
        item['profiles'].append(dict(item['profiles'][0]))
        cases.append(item)
        for item in cases:
            with self.subTest(case=len(str(item))):
                with self.assertRaises(policy.PolicyError) as failure:
                    self.load(item)
                self.assertEqual(str(failure.exception), 'Operator policy unavailable')

    def test_profile_config_socket_schema_binding(self):
        for key, value in [('socket_path', '/tmp/operator.sock'), ('resource', 'https://desktop.example.test/mcp'),
                           ('profile_uid', 'owner/1'), ('enabled', True), ('version', '1')]:
            config = dict(self.config)
            config[key] = value
            with self.assertRaises(policy.PolicyError):
                self.load(config, False)

    def test_policy_reloads_config_and_membership_on_every_call(self):
        resolver = policy.broker_policy('/etc/mrcalld/config.json')
        disabled = copy.deepcopy(self.broker)
        disabled['profiles'][0]['enabled'] = False
        with patch.object(policy, 'load_broker_config', side_effect=[self.broker, disabled, self.broker]) as load, \
             patch.object(policy.trust, 'load', side_effect=[{}, RuntimeError('secret')]), \
             patch.object(policy.trust, 'member'):
            self.assertIsNotNone(resolver(self.row['resource']))
            self.assertIsNone(resolver(self.row['resource']))
            self.assertIsNone(resolver(self.row['resource']))
            self.assertEqual(load.call_count, 3)
        with patch.object(policy, 'load_broker_config', side_effect=RuntimeError('secret')):
            self.assertIsNone(resolver(self.row['resource']))

    def test_private_file_modes_root_traversal_and_duplicate_json(self):
        if os.geteuid() != 0:
            self.skipTest('Root-owned real fixture requires root')
        directory = Path(tempfile.mkdtemp(prefix='operator-policy-', dir='/root'))
        try:
            os.chmod(directory, 0o700)
            path = directory / 'config.json'
            path.write_text(json.dumps(self.broker))
            for mode in (0o600, 0o640):
                path.chmod(mode)
                self.assertEqual(policy.load_broker_config(path), self.broker)
            for mode in (0o644, 0o660, 0o606):
                path.chmod(mode)
                with self.assertRaises(policy.PolicyError):
                    policy.load_broker_config(path)
            path.chmod(0o600)
            link = directory / 'link.json'
            link.symlink_to(path)
            with self.assertRaises(policy.PolicyError):
                policy.load_broker_config(link)
            link.unlink()
            os.link(path, link)
            with self.assertRaises(policy.PolicyError):
                policy.load_broker_config(path)
            link.unlink()
            path.write_text('{"version":1,"version":1}')
            with self.assertRaises(policy.PolicyError):
                policy.load_broker_config(path)
            path.write_text(json.dumps(self.broker))
            directory.chmod(0o777)
            with self.assertRaises(policy.PolicyError):
                policy.load_broker_config(path)
        finally:
            directory.chmod(0o700)
            shutil.rmtree(directory)

    def binding(self, *, mailbox=None, identity_values=None, space='space-1', trust_failure=False, env=None):
        box = mailbox or mailbox_info()
        @contextmanager
        def connection(expected_space):
            self.assertEqual(expected_space, 'space-1')
            yield None, space
        values = identity_values or [('owner_1', '/profile', '/db', 'key', 'engine')] * 2
        project_module = SimpleNamespace(connection=connection)
        mailbox_module = SimpleNamespace(primary=lambda owner: box,
                                         presets=lambda: [{'id': 'gmail.com'}, {'id': 'pec.net'}])
        with patch.dict(os.environ, env or {'OWNER_ID': 'owner_1', 'EMAIL_ADDRESS': 'owner@example.test'}), \
             patch.object(policy.identity, 'binding', side_effect=values), \
             patch('zylch.cli.utils.get_owner_id', return_value='owner@example.test'), \
             patch.dict(sys.modules, {'zylch.services.project_store': project_module,
                                      'zylch.email.mailboxes': mailbox_module}), \
             patch.object(services_package, 'project_store', project_module, create=True), \
             patch.object(email_package, 'mailboxes', mailbox_module, create=True), \
             patch.object(policy.trust, 'load', side_effect=RuntimeError('secret') if trust_failure else None, return_value={}), \
             patch.object(policy.trust, 'member'):
            return policy.profile_binding(self.config)

    def test_dependency_import_failure_has_safe_error(self):
        original_import = __import__
        def unavailable(name, *args, **kwargs):
            if name == 'zylch.email':
                raise ImportError('sensitive_dependency_detail')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=unavailable):
            with self.assertRaises(policy.PolicyError) as failure:
                policy.profile_binding(self.config)
        self.assertEqual(str(failure.exception), 'Operator profile binding unavailable')
        self.assertTrue(failure.exception.__suppress_context__)

    def test_current_profile_company_mailbox_and_trust(self):
        binding = self.binding()
        self.assertEqual(binding.mailbox_ids, frozenset({'mailbox-1'}))
        for changes in [dict(id='other'), dict(owner_id='foreign@example.test'), dict(address='foreign@example.test'),
                        dict(is_primary=False), dict(removed_at='removed'), dict(preset='pec.net'),
                        dict(preset='unknown'), dict(imap_host='imap.pec-email.com')]:
            box = mailbox_info(**changes)
            with self.assertRaises(policy.PolicyError):
                self.binding(mailbox=box)
        for kwargs in [dict(space='other'), dict(trust_failure=True), dict(env={'OWNER_ID': 'other', 'EMAIL_ADDRESS': 'owner@example.test'}),
                       dict(identity_values=[('owner_1', 'path', 'db', 'key', 'engine'), ('owner_1', 'path', 'db', 'other', 'engine')])]:
            with self.assertRaises(policy.PolicyError) as failure:
                self.binding(**kwargs)
            self.assertEqual(str(failure.exception), 'Operator profile binding unavailable')


if __name__ == '__main__':
    unittest.main()
