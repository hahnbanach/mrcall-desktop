import copy
import time
import unittest
from dataclasses import replace

from cs.operator_read import ReadError, ReadGrant, ReadOperator
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding


class CustomerContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.binding = ProfileBinding('uid', 'owner@example.test', 'company', frozenset({'mailbox'}))
        self.grant = ReadGrant('uid', 'uid', 'company', 'client', 'https://resource.test/mcp', int(time.time()) + 600,
                               frozenset({'operator.read', 'email.read'}), frozenset({'mail'}), frozenset({'mailbox'}), 'grant')
        self.source = {'id': 'source', 'mailbox_id': 'mailbox', 'pec_markers': None,
                       'original_message_id': None, 'from_email': 'Customer <customer@example.test>',
                       'to_email': 'Owner <owner@example.test>', 'cc_email': '', 'date': '2026-10-14T15:00:00',
                       'body_plain': 'Selected source exact body', 'has_attachments': True, 'secret': 'private-canary'}
        self.threads = {'selected': [copy.deepcopy(self.source)],
                        'history': [{**self.source, 'id': 'older', 'from_email': 'owner@example.test',
                                     'to_email': 'customer@example.test', 'date': '2026-10-10', 'body_plain': 'Older correspondence'},
                                    {**self.source, 'id': 'substring', 'from_email': 'prefixcustomer@example.test',
                                     'to_email': 'owner@example.test', 'body_plain': 'Not this customer'}]}
        self.calls = []
        self.search_rows = [{'thread_id': 'history', 'last_email_id': 'older', 'mailbox_ids': ['mailbox']}]
        self.mutate_binding = False

        async def search(params, notify):
            self.calls.append(('search', params))
            if self.mutate_binding:
                self.binding = replace(self.binding, email='changed@example.test')
            return {'threads': self.search_rows}

        async def thread(params, notify):
            self.calls.append(('thread', params))
            return {'emails': self.threads.get(params['thread_id'], [])}

        async def drafts(params, notify):
            self.fail('Context must not read drafts')

        self.port = NativeReadPort(lambda: self.binding, {'emails.search': search, 'emails.list_by_thread': thread, 'drafts.list': drafts})
        self.operator = ReadOperator(self.port)

    async def context(self, **overrides):
        arguments = {'thread_key': 'selected', 'source_email_id': 'source', 'customer_email': 'customer@example.test', **overrides}
        return await self.operator.customer_context(self.grant, **arguments)

    async def test_selected_first_exact_participants_projection_and_honest_coverage(self):
        result = await self.context(customer_email=' CUSTOMER@EXAMPLE.TEST ')
        rows = result['correspondence']
        self.assertEqual([row['source_email_id'] for row in rows], ['source', 'older'])
        self.assertEqual([row['thread_key'] for row in rows], ['selected', 'history'])
        self.assertEqual(rows[0]['email']['body_plain'], self.source['body_plain'])
        self.assertEqual(rows[1]['email']['date'], '2026-10-10')
        self.assertNotIn('private-canary', str(result))
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(result['attachments']['status'], 'not_read')
        self.assertEqual(result['entity_memory']['reason'], 'complete_source_lineage_unavailable')
        self.assertEqual(result['standing_instructions']['reason'], 'permission_not_granted')
        searches = [params for name, params in self.calls if name == 'search']
        self.assertEqual([params['query'] for params in searches], ['from:"customer@example.test"', 'to:"customer@example.test"', 'cc:"customer@example.test"'])
        self.assertTrue(all(params['limit'] == 10 and params['mailbox_id'] == 'mailbox' for params in searches))

    async def test_apostrophe_addr_spec_stays_inside_fixed_query(self):
        customer = "o'brien@example.test"
        self.threads['selected'][0]['from_email'] = customer
        self.search_rows = []
        result = await self.context(customer_email=customer)
        self.assertEqual(result['customer_email'], customer)
        self.assertEqual([params['query'] for name, params in self.calls if name == 'search'],
                         [f'{field}:"{customer}"' for field in ('from', 'to', 'cc')])

    async def test_cc_participant_and_profile_self_exclusion(self):
        self.threads['selected'][0].update(from_email='owner@example.test', to_email='other@example.test', cc_email='Customer <CUSTOMER@example.test>')
        self.assertEqual((await self.context())['customer_email'], 'customer@example.test')
        with self.assertRaises(ReadError):
            await self.context(customer_email='owner@example.test')

    async def test_mismatch_ambiguous_source_and_malformed_header_stop_before_search(self):
        original = copy.deepcopy(self.threads['selected'])
        changes = [[], original + original, [{**self.source, 'from_email': 'prefixcustomer@example.test'}],
                   [{**self.source, 'from_email': 'customer@example.test\nBcc: hidden@example.test'}],
                   [{**self.source, 'from_email': 'broken <customer@example.test'}]]
        for rows in changes:
            self.calls.clear()
            self.threads['selected'] = rows
            with self.assertRaises(ReadError):
                await self.context()
            self.assertFalse(any(name == 'search' for name, _ in self.calls))

    async def test_lists_display_names_and_query_injection_rejected_before_dispatch(self):
        for address in ['a@example.test,b@example.test', 'Customer <customer@example.test>',
                        'customer@example.test" OR from:"other@example.test', 'customer@example.test\n',
                        'café@example.test', 'a' * 65 + '@example.test', 'a..b@example.test']:
            self.calls.clear()
            with self.assertRaises(ReadError):
                await self.context(customer_email=address)
            self.assertEqual(self.calls, [])

    async def test_source_foreign_unknown_pec_and_finance_refuse(self):
        for changes in [{'mailbox_id': 'foreign'}, {'mailbox_id': None}, {'pec_markers': ['pec']},
                        {'source_class': 'finance'}, {'original_message_id': 'derived'}]:
            self.threads['selected'] = [{**self.source, **changes}]
            with self.assertRaises(ReadError):
                await self.context()
        self.threads['selected'] = [{key: value for key, value in self.source.items() if key != 'pec_markers'}]
        with self.assertRaises(ReadError):
            await self.context()

    async def test_related_foreign_never_returned_and_unknown_pec_refuse(self):
        self.threads['history'].append({**self.source, 'id': 'foreign', 'mailbox_id': 'foreign', 'body_plain': 'foreign-canary'})
        result = await self.context()
        self.assertNotIn('foreign-canary', str(result))
        for changes in [{'pec_markers': ['pec']}, {'mailbox_id': None}, {'source_class': 'finance'}]:
            self.threads['history'] = [{**self.source, 'id': 'older', **changes}]
            with self.assertRaises(ReadError):
                await self.context()

    async def test_binding_change_between_reads_refuses(self):
        self.mutate_binding = True
        with self.assertRaises(ReadError):
            await self.context()

    async def test_limits_full_bodies_and_native_collection_bounds(self):
        for limit in [True, 0, 21, 1.0, '10']:
            self.calls.clear()
            with self.assertRaises(ReadError):
                await self.context(limit=limit)
            self.assertEqual(self.calls, [])
        result = await self.context(limit=1)
        self.assertEqual(len(result['correspondence']), 1)
        self.assertTrue(result['coverage']['limit_reached'])
        self.threads['selected'][0]['body_plain'] = 'x' * 262145
        result = await self.context()
        self.assertFalse(result['correspondence'][0]['email']['body_coverage']['complete'])
        self.assertEqual(result['correspondence'][0]['email']['body_coverage']['total_characters'], 262145)
        self.threads['selected'] = [self.source] * 1001
        with self.assertRaises(ReadError):
            await self.context()
        self.threads['selected'] = [self.source]
        self.search_rows *= 11
        with self.assertRaises(ReadError):
            await self.context()

    async def test_duplicate_ids_cannot_contradict_or_change_thread(self):
        self.search_rows[0]['last_email_id'] = 'substring'
        self.threads['history'].append({**self.threads['history'][0], 'body_plain': 'Contradictory body'})
        with self.assertRaisesRegex(ReadError, 'contradictory_source_identity'):
            await self.context()
        self.threads['history'] = [{**self.source, 'id': 'source'}]
        self.search_rows[0]['last_email_id'] = 'source'
        with self.assertRaisesRegex(ReadError, 'contradictory_source_identity'):
            await self.context()


if __name__ == '__main__':
    unittest.main()
