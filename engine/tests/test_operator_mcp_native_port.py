import os
import sys
import time
import types
import unittest
from dataclasses import replace
from unittest.mock import patch

from cs.operator_read import ReadError, ReadGrant
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding


class NativeReadPortTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.binding = ProfileBinding('uid', 'owner@example.test', 'company', frozenset({'mailbox'}))
        self.grant = ReadGrant('uid', 'uid', 'company', 'client', 'https://resource.test/mcp', int(time.time()) + 600, frozenset({'operator.read', 'email.read', 'draft.read'}), frozenset({'mail', 'drafts'}), frozenset({'mailbox'}), 'grant')
        self.calls = []
        self.emails = [{'id': 'source', 'mailbox_id': 'mailbox', 'pec_markers': None, 'original_message_id': None, 'body_plain': 'allowed', 'secret': 'hidden'}]
        self.summaries = [{'thread_id': 'root', 'last_email_id': 'source', 'mailbox_ids': ['mailbox'], 'snippet': 'allowed', 'secret': 'hidden'}]
        self.drafts = [{'id': 'draft', 'owner_id': self.binding.email, 'status': 'draft', 'thread_id': 'root', 'body': 'allowed', 'reply_binding': {'root': 'root', 'source': {'id': 'source', 'mailbox_id': 'mailbox'}}, 'secret': 'hidden'}]
        self.change_binding = False

        async def search(params, notify):
            self.calls.append(('search', params))
            if self.change_binding:
                self.binding = replace(self.binding, company_ref='changed')
            return {'threads': self.summaries}

        async def thread(params, notify):
            self.calls.append(('thread', params))
            return {'emails': self.emails}

        async def drafts(params, notify):
            self.calls.append(('drafts', params))
            return self.drafts

        self.port = NativeReadPort(lambda: self.binding, {'emails.search': search, 'emails.list_by_thread': thread, 'drafts.list': drafts})

    async def test_exact_read_dispatch_and_projection(self):
        result = await self.port.search(self.grant, 'query', 10)
        self.assertNotIn('secret', result['threads'][0])
        self.assertEqual(self.calls[0][1], {'query': 'query', 'folder': 'all', 'limit': 10, 'offset': 0, 'mailbox_id': 'mailbox'})
        self.assertNotIn('secret', (await self.port.thread(self.grant, 'root'))['emails'][0])
        self.assertNotIn('secret', (await self.port.drafts(self.grant, 10))[0])
        self.assertEqual((await self.port.identity(self.grant))['subject'], 'uid')

    async def test_identity_only_grant_needs_no_mailbox(self):
        grant = replace(self.grant, scopes=frozenset({'operator.read'}), source_classes=frozenset(), mailbox_ids=frozenset())
        result = await self.port.identity(grant)
        self.assertEqual(result['capabilities'], ['operator_identity', 'cs_bootstrap', 'cs_bootstrap_hook'])
        with self.assertRaises(ReadError):
            await self.port.search(grant, 'query', 10)
        self.assertEqual(self.calls, [])
        with self.assertRaises(ReadError):
            await self.port.identity(replace(grant, mailbox_ids=frozenset({'foreign'})))

    async def test_denied_grants_never_dispatch(self):
        bad = [replace(self.grant, subject='other'), replace(self.grant, profile_uid='other'), replace(self.grant, company_ref='other'), replace(self.grant, expires_at=0), replace(self.grant, scopes=frozenset({'operator.read'})), replace(self.grant, source_classes=frozenset()), replace(self.grant, mailbox_ids=frozenset()), replace(self.grant, mailbox_ids=frozenset({'mailbox', 'foreign'})), replace(self.grant, mailbox_ids=frozenset({'foreign'}))]
        for grant in bad:
            with self.assertRaises(ReadError):
                await self.port.search(grant, 'query', 10)
        self.assertEqual(self.calls, [])

    async def test_binding_rechecked_after_native_read(self):
        self.change_binding = True
        with self.assertRaisesRegex(ReadError, 'permission denied|binding changed'):
            await self.port.search(self.grant, 'query', 10)

    async def test_search_unknown_mixed_and_excluded_provenance(self):
        for row in [{'thread_id': 'root'}, {'mailbox_ids': ['mailbox', 'foreign']}, {'mailbox_ids': ['mailbox'], 'source_class': 'finance'}, {'mailbox_ids': ['mailbox'], 'pec_markers': ['pec']}]:
            self.summaries = [row]
            with self.assertRaises(ReadError):
                await self.port.search(self.grant, 'query', 10)

    async def test_thread_filters_foreign_and_refuses_unknown_and_pec(self):
        self.emails.append({'id': 'foreign', 'mailbox_id': 'foreign', 'pec_markers': None, 'body_plain': 'never public'})
        self.assertEqual(len((await self.port.thread(self.grant, 'root'))['emails']), 1)
        for row in [{'id': 'unknown'}, {'id': 'unknown', 'mailbox_id': 'mailbox'}, {'id': 'pec', 'mailbox_id': 'mailbox', 'pec_markers': ['pec']}]:
            self.emails = [row]
            with self.assertRaises(ReadError):
                await self.port.thread(self.grant, 'root')

    async def test_drafts_require_exact_native_source_and_owner(self):
        original = self.drafts[0]
        for change in [{'owner_id': 'foreign'}, {'reply_binding': {'root': 'root', 'source': {'id': 'source', 'mailbox_id': 'foreign'}}}]:
            self.drafts = [{**original, **change}]
            self.assertEqual(await self.port.drafts(self.grant, 10), [])
        for change in [{'reply_binding': None}, {'reply_binding': {'root': 'root', 'source': {'id': 'missing', 'mailbox_id': 'mailbox'}}}]:
            self.drafts = [{**original, **change}]
            with self.assertRaisesRegex(ReadError, 'Draft provenance unavailable'):
                await self.port.drafts(self.grant, 10)
        self.drafts = []
        self.assertEqual(await self.port.drafts(self.grant, 10), [])
        with self.assertRaises(ReadError):
            await self.port.drafts(replace(self.grant, scopes=frozenset({'operator.read', 'draft.read'})), 10)

    async def test_search_checks_exact_latest_native_source(self):
        original = self.emails[0]
        for emails in [[{**original, 'pec_markers': ['pec']}], [{**original, 'id': 'different'}], [{**original, 'mailbox_id': 'foreign'}], [original, original]]:
            self.emails = emails
            with self.assertRaises(ReadError):
                await self.port.search(self.grant, 'query', 10)
        self.summaries = [{'thread_id': 'root', 'mailbox_ids': ['mailbox']}]
        with self.assertRaises(ReadError):
            await self.port.search(self.grant, 'query', 10)

    async def test_default_native_owner_uid_checked_before_handler_import(self):
        module = types.ModuleType('zylch.cli.utils')
        module.get_owner_id = lambda: self.binding.email
        port = NativeReadPort(lambda: self.binding)
        with patch.dict(sys.modules, {'zylch.cli.utils': module}), patch.dict(os.environ, {'OWNER_ID': 'other'}):
            with self.assertRaises(ReadError):
                await port.search(self.grant, 'query', 10)
        self.assertEqual(self.calls, [])

    async def test_draft_binding_projection_preserves_only_source_identity(self):
        self.drafts[0]['to_addresses'] = ['recipient@example.test']
        self.drafts[0]['reply_binding']['secret'] = 'hidden'
        self.drafts[0]['reply_binding']['source']['secret'] = 'hidden'
        result = (await self.port.drafts(self.grant, 10))[0]
        self.assertEqual(result['reply_binding'], {'root': 'root', 'target': None, 'source': {'id': 'source', 'mailbox_id': 'mailbox'}})
        self.assertEqual(result['to_addresses'], ['recipient@example.test'])

    async def test_safe_errors_and_exact_handler_allowlist(self):
        with self.assertRaises(ReadError):
            NativeReadPort(lambda: self.binding, {'shell': lambda: None})
        async def failing(params, notify):
            raise RuntimeError('secret-token')
        self.port._handlers['emails.search'] = failing
        with self.assertRaises(ReadError) as caught:
            await self.port.search(self.grant, 'query', 10)
        self.assertNotIn('secret-token', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
