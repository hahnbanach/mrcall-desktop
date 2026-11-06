"""Read-boundary regressions: no model, provider or active profile calls."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from cs.operator_read import ReadError, ReadOperator
from engine.tests import test_operator_mcp_context as contexts
from engine.tests import test_operator_mcp_native_port as native
from engine.tests import test_operator_mcp_http as http


class ReadBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = contexts.CustomerContextTests()
        self.f.setUp()

    async def test_html_duplicate_does_not_destroy_realistic_eight_message_context(self):
        self.f.threads['selected'] = [{**self.f.source, 'id': str(i), 'body_plain': 'A real message\n' * 1600,
                                      'body_html': '<div>Quoted history</div>' * 5000} for i in range(8)]
        self.f.threads['selected'][7]['id'] = 'source'
        value = await self.f.context(limit=8)
        self.assertEqual(value['correspondence'][0]['source_email_id'], 'source')
        self.assertEqual(len(value['correspondence']), 8)
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=True).encode()), 262144)
        for message in value['correspondence']:
            email = message['email']
            self.assertNotIn('body_html', email)
            self.assertEqual(email['body_coverage']['omitted_alternative_fields'], ['body_html'])
            self.assertFalse(email['body_coverage']['complete'])
        self.assertFalse(any(name == 'search' for name, _ in self.f.calls))

    async def test_cjk_aggregate_budget_explicitly_shortens_each_body(self):
        self.f.threads['selected'] = [{**self.f.source, 'id': str(i), 'body_plain': '界' * 50000} for i in range(20)]
        self.f.threads['selected'][0]['id'] = 'source'
        value = await self.f.context(limit=20)
        self.assertEqual(len(value['correspondence']), 20)
        self.assertLessEqual(len(json.dumps(value, ensure_ascii=True).encode()), 262144)
        self.assertTrue(all(not x['email']['body_coverage']['complete'] for x in value['correspondence']))

    async def test_hash_bound_unicode_pages_reconstruct_exact_body_and_detect_change(self):
        body = 'à界🙂\n' * 5000
        self.f.threads['selected'][0]['body_plain'] = body
        args = {'thread_key': 'selected', 'source_email_id': 'source'}
        chunks = []
        while args:
            page = await self.f.operator.read(self.f.grant, **args)
            email = page['email']
            chunks.append(email['body_plain'])
            coverage = email['body_coverage']
            self.assertEqual(coverage['sha256'], hashlib.sha256(body.encode()).hexdigest())
            args = coverage['next_read']
        self.assertEqual(''.join(chunks), body)
        self.f.threads['selected'][0]['body_plain'] += ' changed'
        with self.assertRaisesRegex(ReadError, 'body_changed'):
            await self.f.operator.read(self.f.grant, 'selected', 'source', 8192, coverage['sha256'])

    async def test_continuation_offset_hash_and_source_validation(self):
        for offset, sha in [(True, None), (1.0, None), (-1, None), (1, None), (999999, 'a' * 64), (0, 'bad')]:
            with self.assertRaises(ReadError):
                await self.f.operator.read(self.f.grant, 'selected', 'source', offset, sha)
        with self.assertRaises(ReadError):
            await self.f.operator.read(self.f.grant, 'selected', 'foreign', 0)

    async def test_html_only_body_is_labeled_without_inventing_plain_text(self):
        self.f.threads['selected'][0].update(body_plain='', body_html='<p>body</p>' * 5000)
        email = (await self.f.operator.read(self.f.grant, 'selected', 'source'))['email']
        self.assertNotIn('body_plain', email)
        self.assertEqual(email['body_coverage']['field'], 'body_html')
        self.assertIsNotNone(email['body_coverage']['next_read'])

    async def test_large_snippets_are_excerpts_and_internal_search_is_usable(self):
        self.f.search_rows[0]['snippet'] = '界' * 100000
        found = await self.f.operator.search(self.f.grant, 'query', 10)
        self.assertFalse(found['threads'][0]['snippet_coverage']['complete'])
        self.assertEqual(found['threads'][0]['snippet_coverage']['total_characters'], 100000)
        self.assertEqual(len((await self.f.context())['correspondence']), 2)

    async def test_oversized_nonbody_metadata_still_refuses_instead_of_looping(self):
        self.f.threads['selected'][0]['subject'] = 'x' * 300000
        with self.assertRaises(ReadError):
            await self.f.operator.read(self.f.grant, 'selected', 'source')


class NativeDraftCoverageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = native.NativeReadPortTests()
        self.f.setUp()
        self.f.emails[0]['message_id_header'] = '<native-source@example.test>'
        self.original = copy.deepcopy(self.f.drafts[0])

    def legacy(self):
        draft = copy.deepcopy(self.original)
        draft.pop('reply_binding')
        draft['in_reply_to'] = '<native-source@example.test>'
        return draft

    async def test_legacy_source_is_verified_by_exact_native_rfc_header(self):
        self.f.drafts = [self.legacy()]
        value = await ReadOperator(self.f.port).drafts(self.f.grant)
        self.assertTrue(value['coverage']['complete'])
        self.assertEqual(value['drafts'][0]['reply_binding']['source'], {'id': 'source', 'mailbox_id': 'mailbox'})
        self.assertNotIn('secret', str(value))

    async def test_real_native_rpc_projection_preserves_legacy_rfc_proof(self):
        from zylch.rpc.methods import emails_list_by_thread
        raw = {**self.f.emails[0], 'from_email': 'customer@example.test', 'to_email': self.f.binding.email}
        class Store:
            def get_thread_emails(self, **kwargs):
                return [raw]
        self.f.port._handlers['emails.list_by_thread'] = emails_list_by_thread
        self.f.drafts = [self.legacy()]
        with patch('zylch.rpc.methods._owner_id', return_value=self.f.binding.email), \
                patch('zylch.api.token_storage.get_provider', return_value='imap'), \
                patch('zylch.api.token_storage.get_email', return_value=self.f.binding.email), \
                patch('zylch.email.identity.verified_user_addresses', return_value={self.f.binding.email}), \
                patch('zylch.email.mailboxes.for_owner', return_value=[]), \
                patch('zylch.storage.storage.Storage.get_instance', return_value=Store()):
            result = await self.f.port.draft_listing(self.f.grant, 10)
        self.assertEqual(result['drafts'][0]['reply_binding']['source']['id'], 'source')
        self.assertTrue(result['coverage']['complete'])

    async def test_unknown_unlinked_rows_are_partial_without_revealing_content(self):
        self.f.drafts = [self.legacy(), {**self.legacy(), 'id': 'unknown', 'thread_id': None,
                                      'in_reply_to': None, 'body': 'unknown-body-canary'}]
        value = await ReadOperator(self.f.port).drafts(self.f.grant, thread_key='root')
        self.assertFalse(value['coverage']['complete'])
        self.assertFalse(value['coverage']['absence_confirmed'])
        self.assertEqual(value['coverage']['unlinked_count'], 1)
        self.assertEqual(len(value['drafts']), 1)
        self.assertNotIn('unknown-body-canary', str(value))
        self.f.drafts = self.f.drafts[1:]
        value = await ReadOperator(self.f.port).drafts(self.f.grant)
        self.assertEqual(value['drafts'], [])
        self.assertFalse(value['coverage']['absence_confirmed'])

    async def test_conflicting_or_ambiguous_rfc_never_falls_back_to_recipient(self):
        for bad in [{**self.legacy(), 'in_reply_to': '<missing@example.test>'},
                    {**self.legacy(), 'reply_binding': {'root': 'root', 'source': {'id': 'missing', 'mailbox_id': 'mailbox'}}},
                    {**self.original, 'in_reply_to': '<conflicting@example.test>'}]:
            self.f.drafts = [bad]
            value = await self.f.port.draft_listing(self.f.grant, 10)
            self.assertEqual(value['drafts'], [])
            self.assertFalse(value['coverage']['absence_confirmed'])
        self.f.drafts = [self.legacy()]
        self.f.emails.append({**self.f.emails[0], 'id': 'ambiguous'})
        self.assertEqual((await self.f.port.draft_listing(self.f.grant, 10))['drafts'], [])

    async def test_limit_cannot_certify_complete_or_absence(self):
        self.f.drafts = [{**self.legacy(), 'id': str(i)} for i in range(3)]
        value = await self.f.port.draft_listing(self.f.grant, 1)
        self.assertEqual(value['coverage']['verified_count'], 3)
        self.assertTrue(value['coverage']['limit_reached'])
        self.assertFalse(value['coverage']['complete'])
        self.assertFalse(value['coverage']['absence_confirmed'])
        self.f.drafts = []
        self.assertTrue((await self.f.port.draft_listing(self.f.grant, 1, 'root'))['coverage']['absence_confirmed'])

    async def test_malformed_identity_and_unverified_rows_after_limit_remain_unknown(self):
        for changes in [{'owner_id': None}, {'id': None},
                        {'reply_binding': {'root': 'root', 'source': {'id': 'source', 'mailbox_id': []}}}]:
            self.f.drafts = [{**self.original, **changes}]
            value = await self.f.port.draft_listing(self.f.grant, 1)
            self.assertEqual(value['drafts'], [])
            self.assertFalse(value['coverage']['absence_confirmed'])
        self.f.drafts = [self.original, {**self.original, 'id': 'unknown', 'reply_binding': None}]
        value = await self.f.port.draft_listing(self.f.grant, 1)
        self.assertFalse(value['coverage']['complete'])
        self.assertEqual(value['coverage']['unverified_count'], 1)

    async def test_legacy_pec_foreign_or_missing_exact_source_not_exposed(self):
        self.f.drafts = [self.legacy()]
        for changes in [{'pec_markers': ['pec']}, {'mailbox_id': 'foreign'}, {'id': ''}]:
            self.f.emails = [{**self.f.emails[0], **changes}]
            self.assertEqual((await self.f.port.draft_listing(self.f.grant, 10))['drafts'], [])


class ReadBudgetSDKTests(unittest.TestCase):
    def test_real_sdk_continuation_metadata_and_partial_draft_coverage(self):
        fixture = http.OperatorHTTPTests()
        async def exercise():
            client = await fixture.session()
            fixture.emails[0].update(body_plain='界' * 25000, body_html='<div>' * 100000)
            first = await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})
            self.assertFalse(first.isError)
            next_args = first.structuredContent['email']['body_coverage']['next_read']
            second = await client.call_tool('read_email', next_args)
            self.assertFalse(second.isError)
            self.assertEqual(second.structuredContent['email']['body_coverage']['offset'], 8192)
            for invalid in [True, 1.0, -1]:
                before = len(fixture.calls)
                bad = await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source', 'body_offset': invalid})
                self.assertTrue(bad.isError)
                self.assertEqual(len(fixture.calls), before)
            result = await client.call_tool('list_drafts', {'thread_key': 'thread'})
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent['coverage']['scope'], 'recorded_thread')
            self.assertFalse(result.structuredContent['coverage']['absence_confirmed'])
        fixture.run_case(exercise)


if __name__ == '__main__':
    unittest.main()
