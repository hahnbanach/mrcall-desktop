import base64
import hashlib
import os
import sys
import types
import unittest
from dataclasses import replace
from unittest.mock import patch

from cs.operator_read import ReadError, ReadOperator
from engine.tests import test_operator_mcp_context as context_tests
from engine.tests import test_operator_mcp_http as http_tests
from zylch.operator_mcp.read_port import NativeReadPort
from zylch.services.operator_instructions import PROCEDURES, PROJECT, mail_path


def document(path=PROCEDURES, content=b'Exact published instructions\n', **changes):
    return {'space_id': 'company', 'project': PROJECT, 'path': path, 'revision': 8,
            'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
            'content_base64': base64.b64encode(content).decode('ascii'),
            'author_uid': 'publisher@example.test', **changes}


class PublishedInstructionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixture = context_tests.CustomerContextTests()
        fixture.setUp()
        self.fixture = fixture
        self.binding = replace(fixture.binding, instructions_enabled=True)
        self.paths = frozenset({PROCEDURES, mail_path(self.binding.email)})
        self.grant = replace(fixture.grant, scopes=fixture.grant.scopes | {'instructions.read'},
                             source_classes=fixture.grant.source_classes | {'instructions'}, instruction_paths=self.paths)
        self.rows = [document(), document(mail_path(self.binding.email), b'Own identity\n')]
        self.calls = []

        def read(email):
            self.calls.append(email)
            return self.rows

        self.port = NativeReadPort(lambda: self.binding, fixture.port._handlers, instruction_reader=read)
        self.operator = ReadOperator(self.port)

    async def test_exact_published_bundle_in_partial_customer_context(self):
        result = await self.operator.customer_context(self.grant, 'selected', 'source', 'customer@example.test', 5)
        bundle = result['standing_instructions']
        self.assertEqual(bundle['status'], 'available')
        self.assertEqual(bundle['source'], 'engine_published_copy')
        self.assertEqual(bundle['canonical_clone_freshness'], 'unverified')
        self.assertEqual(bundle['documents'][0]['text'], 'Exact published instructions\n')
        self.assertEqual(bundle['documents'][0]['revision'], 8)
        self.assertEqual(bundle['documents'][0]['sha256'], self.rows[0]['sha256'])
        self.assertEqual(bundle['documents'][0]['publication_author'], 'publisher@example.test')
        self.assertNotIn('author_uid', str(bundle))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['entity_memory']['reason'], 'complete_source_lineage_unavailable')
        self.assertEqual(result['attachments']['status'], 'not_read')
        self.assertEqual(self.calls, ['owner@example.test'])

    async def test_old_grants_missing_scope_source_flag_never_call_reader(self):
        for grant in (self.fixture.grant,
                      replace(self.grant, scopes=self.grant.scopes - {'instructions.read'}),
                      replace(self.grant, source_classes=self.grant.source_classes - {'instructions'})):
            self.assertEqual(await self.operator.instructions(grant), {'status': 'unavailable', 'reason': 'permission_not_granted'})
            with self.assertRaises(ReadError):
                await self.port.instructions(grant)
        self.binding = replace(self.binding, instructions_enabled=False)
        self.assertEqual((await self.operator.instructions(self.grant))['reason'], 'permission_not_granted')
        with self.assertRaises(ReadError):
            await self.port.instructions(self.grant)
        self.assertEqual(self.calls, [])

    async def test_path_authority_mailbox_owner_and_expiry_refuse_before_read(self):
        for paths in (frozenset(), frozenset({PROCEDURES}),
                      frozenset({PROCEDURES, 'mail/other@example.test.md'}),
                      self.paths | {'phone.md'}, set(self.paths)):
            with self.assertRaises(ReadError):
                await self.operator.instructions(replace(self.grant, instruction_paths=paths))
        for changes in ({'company_ref': 'foreign'}, {'profile_uid': 'foreign'}, {'subject': 'foreign'},
                        {'mailbox_ids': frozenset({'foreign'})}, {'expires_at': 0}):
            with self.assertRaises(ReadError):
                await self.operator.instructions(replace(self.grant, **changes))
        self.binding = replace(self.binding, email='other@example.test')
        with self.assertRaises(ReadError):
            await self.operator.instructions(self.grant)
        self.assertEqual(self.calls, [])

    async def test_missing_documents_report_exact_expected_paths(self):
        self.rows = []
        bundle = await self.operator.instructions(self.grant)
        self.assertEqual(bundle['status'], 'not_configured')
        self.assertEqual(bundle['missing_paths'], sorted(self.paths))
        self.rows = [document()]
        bundle = await self.operator.instructions(self.grant)
        self.assertEqual(bundle['status'], 'partial')
        self.assertEqual(bundle['missing_paths'], [mail_path(self.binding.email)])

    async def test_foreign_malformed_integrity_and_size_refuse(self):
        original = document()
        changes = [{'space_id': 'foreign'}, {'project': 'ordinary'}, {'path': 'phone.md'},
                   {'path': 'mail/other@example.test.md'}, {'path': []}, {'revision': True}, {'revision': 0},
                   {'revision': 1.0}, {'size': True}, {'size': -1}, {'size': 65537}, {'size': 0},
                   {'sha256': '0' * 64}, {'sha256': original['sha256'].upper()},
                   {'content_base64': '!'}, {'content_base64': original['content_base64'] + '\n'},
                   {'content_base64': 'A' * 87385}, {'author_uid': 'publisher\nsecret'}]
        for change in changes:
            self.rows = [{**original, **change}]
            with self.subTest(change=change), self.assertRaises(ReadError):
                await self.operator.instructions(self.grant)
        for rows in ([original, original], [original] * 3, {}, [None], [document(content=b'\xff')]):
            self.rows = rows
            with self.assertRaises(ReadError):
                await self.operator.instructions(self.grant)

    async def test_binding_flag_change_and_reader_failure_never_release_content(self):
        def changed(email):
            self.binding = replace(self.binding, instructions_enabled=False)
            return self.rows
        self.port._instruction_reader = changed
        with self.assertRaises(ReadError):
            await self.operator.instructions(self.grant)
        self.binding = replace(self.binding, instructions_enabled=True)
        def failing(email):
            raise RuntimeError('secret-canary')
        self.port._instruction_reader = failing
        with self.assertRaises(ReadError) as caught:
            await self.operator.instructions(self.grant)
        self.assertNotIn('secret-canary', str(caught.exception))

    async def test_default_service_uses_bound_email_and_actual_owner_before_read(self):
        module = types.ModuleType('zylch.cli.utils')
        module.get_owner_id = lambda: self.binding.email
        port = NativeReadPort(lambda: self.binding)
        with patch.dict(sys.modules, {'zylch.cli.utils': module}), patch.dict(os.environ, {'OWNER_ID': 'other'}), \
                patch('zylch.services.operator_instructions.documents') as reader:
            with self.assertRaises(ReadError):
                await port.instructions(self.grant)
            reader.assert_not_called()
        with patch.dict(sys.modules, {'zylch.cli.utils': module}), patch.dict(os.environ, {'OWNER_ID': self.binding.profile_uid}), \
                patch('zylch.services.operator_instructions.documents', return_value=self.rows) as reader:
            await port.instructions(self.grant)
            reader.assert_called_once_with(self.binding.email)

    async def test_document_and_whole_context_bounds_are_preserved(self):
        self.rows = [document(content=b'x' * 65536)]
        self.assertEqual(len((await self.operator.instructions(self.grant))['documents'][0]['text']), 65536)
        self.rows = [document(content=b'x' * 65537)]
        with self.assertRaises(ReadError):
            await self.operator.instructions(self.grant)
        self.rows = [document(content=b'x' * 65536)]
        self.fixture.threads['selected'][0]['body_plain'] = 'x' * 220000
        result = await self.operator.customer_context(self.grant, 'selected', 'source', 'customer@example.test')
        self.assertEqual(result['standing_instructions']['documents'][0]['text'], 'x' * 65536)
        self.assertFalse(result['correspondence'][0]['email']['body_coverage']['complete'])


class PublishedInstructionsHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_requires_new_grant_and_rechecks_slow_results(self):
        fixture = http_tests.OperatorHTTPTests()
        calls = []
        enabled = True
        rows = [document()]
        def read(email):
            calls.append(email)
            return rows
        def port(snapshot, handlers):
            return NativeReadPort(lambda: replace(snapshot(), instructions_enabled=enabled), handlers,
                                  instruction_reader=read)
        from zylch.operator_mcp.auth import GrantVerifier
        def verifier(**kwargs):
            return GrantVerifier(**kwargs, instructions_enabled=True)
        with patch('engine.tests.test_operator_mcp_http.NativeReadPort', port), \
                patch('engine.tests.test_operator_mcp_http.GrantVerifier', verifier):
            await fixture.prepare()
        try:
            session = await fixture.session()
            args = {'thread_key': 'thread', 'source_email_id': 'source', 'customer_email': 'contact@example.test'}
            old = await session.call_tool('customer_context', args)
            self.assertFalse(old.isError)
            self.assertEqual(old.structuredContent['standing_instructions']['reason'], 'permission_not_granted')
            self.assertEqual(calls, [])
            metadata = await fixture.http.get('/.well-known/oauth-protected-resource/mcp/profile')
            self.assertIn('instructions.read', metadata.json()['scopes_supported'])
            fixture.payload.update(scope=fixture.payload['scope'] + ' instructions.read',
                                   source_classes=['mail', 'drafts', 'instructions'],
                                   instruction_paths=sorted({PROCEDURES, mail_path('owner@example.test')}))
            granted = await session.call_tool('customer_context', args)
            self.assertFalse(granted.isError, granted)
            self.assertEqual(granted.structuredContent['standing_instructions']['documents'][0]['text'], 'Exact published instructions\n')
            self.assertEqual(calls, ['owner@example.test'])
            enabled = False
            denied = await session.call_tool('customer_context', args)
            self.assertFalse(denied.isError)
            self.assertEqual(denied.structuredContent['standing_instructions']['reason'], 'permission_not_granted')
            self.assertEqual(len(calls), 1)
            enabled = True
            fixture.revoke_during_read = True
            denied = await session.call_tool('customer_context', args)
            self.assertTrue(denied.isError)
            self.assertNotIn('Exact published instructions', str(denied))
        finally:
            await fixture.stack.aclose()


if __name__ == '__main__':
    unittest.main()
