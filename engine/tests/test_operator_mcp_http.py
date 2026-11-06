"""Actual SDK HTTP enforcement checks with controlled auth and source replies."""

import asyncio
import copy
import logging
import time
import unittest
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server


class OperatorHTTPTests(unittest.TestCase):
    def run_case(self, exercise):
        async def run():
            await self.prepare()
            try:
                await exercise()
            finally:
                await self.stack.aclose()
        asyncio.run(run())

    def test_sdk_catalog_and_bounded_native_reads(self):
        self.run_case(self.exercise_sdk_catalog_and_bounded_native_reads)

    def test_unauthenticated_and_invalid_grants_refuse_http(self):
        self.run_case(self.exercise_unauthenticated_and_invalid_grants_refuse_http)

    def test_revocation_and_auth_outage_after_initialize(self):
        self.run_case(self.exercise_revocation_and_auth_outage_after_initialize)

    def test_malformed_bounded_auth_and_source_policy(self):
        self.run_case(self.exercise_malformed_bounded_auth_and_source_policy)

    def test_context_revocation_and_identity_only_refusal(self):
        self.run_case(self.exercise_context_revocation_and_identity_only_refusal)

    def test_long_read_revalidates_before_returning_content(self):
        self.run_case(self.exercise_long_read_revalidates_before_returning_content)

    async def prepare(self):
        self.stack = AsyncExitStack()
        self.resource = 'https://engine.example.test/mcp/profile'
        self.payload = {'active': True, 'iss': 'https://auth.example.test', 'sub': 'owner',
                        'profile_uid': 'owner', 'company_ref': 'company', 'client_id': 'native-client',
                        'resource': self.resource, 'grant_id': 'grant-one', 'exp': int(time.time()) + 120,
                        'scope': 'operator.read email.read draft.read',
                        'source_classes': ['mail', 'drafts'], 'mailbox_ids': ['ordinary-mailbox']}
        self.auth_status = 200
        self.auth_body = None
        self.auth_calls = 0
        self.calls = []
        self.admission_elapsed = 0
        self.revoke_during_read = False

        async def introspect(request):
            self.auth_calls += 1
            self.assertEqual(str(request.url), 'https://auth.example.test/introspect')
            self.assertIn('Basic ', request.headers['authorization'])
            if self.auth_body is not None:
                return httpx.Response(self.auth_status, content=self.auth_body)
            return httpx.Response(self.auth_status, json=self.payload)

        auth_client = await self.stack.enter_async_context(httpx.AsyncClient(transport=httpx.MockTransport(introspect)))
        self.verifier = GrantVerifier(issuer='https://auth.example.test',
            introspection_url='https://auth.example.test/introspect',
            service_client_id='profile-service', service_client_secret='service-secret-canary',
            resource=self.resource, profile_uid='owner', company_ref='company',
            allowed_client_ids={'native-client'}, http_client=auth_client)

        self.emails = [{'id': 'source', 'mailbox_id': 'ordinary-mailbox', 'pec_markers': None,
                        'original_message_id': None, 'subject': 'source subject',
                        'from_email': 'Contact <contact@example.test>', 'to_email': 'owner@example.test',
                        'body_plain': 'Untrusted mail source', 'secret': 'hidden-canary'}]

        async def search(params, notify):
            self.calls.append(('emails.search', params))
            return {'threads': [{'thread_id': 'thread', 'last_email_id': 'source',
                     'mailbox_ids': ['ordinary-mailbox'], 'subject': 'source subject'}]}

        async def thread(params, notify):
            self.calls.append(('emails.list_by_thread', params))
            if self.revoke_during_read:
                self.payload['active'] = False
                self.admission_elapsed = 6
            return {'emails': self.emails}

        async def drafts(params, notify):
            self.calls.append(('drafts.list', params))
            return [{'id': 'draft', 'owner_id': 'owner@example.test', 'status': 'draft',
                     'to_addresses': ['contact@example.test'], 'body': 'Existing draft',
                     'thread_id': 'thread', 'reply_binding': {'root': 'thread',
                     'source': {'id': 'source', 'mailbox_id': 'ordinary-mailbox'}}}]

        port = NativeReadPort(lambda: ProfileBinding('owner', 'owner@example.test', 'company',
                              frozenset({'ordinary-mailbox'})),
                              {'emails.search': search, 'emails.list_by_thread': thread, 'drafts.list': drafts})
        self.server = create_server(self.verifier, port, allowed_hosts=['engine.example.test'],
                                    admission_clock=lambda: self.admission_elapsed)
        logging.getLogger().setLevel(logging.ERROR)
        app = self.server.streamable_http_app()
        await self.stack.enter_async_context(self.server.session_manager.run())
        self.http = await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='https://engine.example.test',
            headers={'Authorization': 'Bearer test-opaque-access-token'}))

    async def session(self, client=None):
        read, write, _ = await self.stack.enter_async_context(streamable_http_client(
            'https://engine.example.test/mcp', http_client=client or self.http))
        session = await self.stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def exercise_sdk_catalog_and_bounded_native_reads(self):
        client = await self.session()
        catalog = (await client.list_tools()).tools
        self.assertEqual([t.name for t in catalog], ['cs_bootstrap', 'cs_bootstrap_hook', 'operator_identity', 'search_email', 'read_email', 'customer_context', 'list_drafts', 'operator_capabilities', 'operator_read', 'operator_action'])
        self.assertTrue(all(t.annotations.readOnlyHint for t in catalog if t.name != 'operator_action'))
        self.assertFalse(next(t for t in catalog if t.name == 'operator_action').annotations.readOnlyHint)
        context_tool = next(t for t in catalog if t.name == 'customer_context')
        limit_schema = context_tool.inputSchema['properties']['limit']
        self.assertEqual((limit_schema['type'], limit_schema['minimum'], limit_schema['maximum'], limit_schema['default']),
                         ('integer', 1, 20, 10))
        identity = await client.call_tool('operator_identity', {})
        self.assertFalse(identity.isError)
        self.assertEqual(identity.structuredContent['profile_uid'], 'owner')
        found = await client.call_tool('search_email', {'query': 'source', 'limit': 5})
        self.assertFalse(found.isError)
        self.assertEqual(found.structuredContent['threads'][0]['last_email_id'], 'source')
        source = await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})
        self.assertFalse(source.isError)
        self.assertEqual(source.structuredContent['email']['body_plain'], 'Untrusted mail source')
        self.assertNotIn('secret', source.structuredContent['email'])
        context = await client.call_tool('customer_context', {'thread_key': 'thread', 'source_email_id': 'source', 'customer_email': 'contact@example.test'})
        self.assertFalse(context.isError)
        self.assertEqual(context.structuredContent['correspondence'][0]['source_email_id'], 'source')
        self.assertEqual(context.structuredContent['status'], 'partial')
        explicit = await client.call_tool('customer_context', {'thread_key': 'thread', 'source_email_id': 'source',
                                        'customer_email': 'contact@example.test', 'limit': 5})
        self.assertFalse(explicit.isError)
        self.assertEqual(explicit.structuredContent['coverage']['limit'], 5)
        for invalid in (0, 21, 100, True, 1.0, '5'):
            before = len(self.calls)
            refused = await client.call_tool('customer_context', {'thread_key': 'thread', 'source_email_id': 'source',
                                            'customer_email': 'contact@example.test', 'limit': invalid})
            self.assertTrue(refused.isError)
            self.assertIn('integer from 1 to 20', str(refused))
            self.assertEqual(len(self.calls), before)
        for change in ({'limit': True}, {'limit': 1.0}, {'limit': 21}, {'customer_email': 'a@example.test,b@example.test'}, {'mailbox_id': 'foreign'}, {'source_email_id': 'missing'}):
            arguments = {'thread_key': 'thread', 'source_email_id': 'source', 'customer_email': 'contact@example.test', **change}
            self.assertTrue((await client.call_tool('customer_context', arguments)).isError)
        drafts = await client.call_tool('list_drafts', {'limit': 5})
        self.assertFalse(drafts.isError)
        self.assertEqual(drafts.structuredContent['drafts'][0]['to_addresses'], ['contact@example.test'])
        self.assertFalse(drafts.structuredContent['sent'])
        for tool in ('prepare_reply', 'send_mail', 'propose_rule', 'shell'):
            self.assertTrue((await client.call_tool(tool, {})).isError)
        self.assertTrue((await client.call_tool('operator_identity', {'actor': 'other'})).isError)
        self.assertTrue((await client.call_tool('search_email', {'query': 'source', 'limit': True})).isError)
        self.assertTrue((await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'absent'})).isError)
        self.assertEqual((await client.list_resources()).resources, [])
        self.assertEqual((await client.list_prompts()).prompts, [])
        self.assertTrue(all(name in {'emails.search', 'emails.list_by_thread', 'drafts.list'} for name, _ in self.calls))

    async def exercise_unauthenticated_and_invalid_grants_refuse_http(self):
        response = await self.http.post('/mcp', headers={'Authorization': ''}, json={})
        self.assertEqual(response.status_code, 401)
        original = copy.deepcopy(self.payload)
        changes = [{'active': False}, {'sub': 'other'}, {'profile_uid': 'other'}, {'company_ref': 'other'},
                   {'client_id': 'unknown'}, {'resource': 'https://other.example.test/mcp'},
                   {'exp': 0}, {'exp': True}, {'exp': int(time.time()) + 3600},
                   {'iss': 'https://evil.example.test'}, {'scope': 'operator.read send'},
                   {'scope': 'email.read'}, {'source_classes': ['finance']}, {'mailbox_ids': ['a', 'b']}]
        for change in changes:
            self.payload = {**original, **change}
            response = await self.http.post('/mcp', json={})
            self.assertEqual(response.status_code, 401, change)
        self.assertEqual(self.calls, [])

    async def exercise_revocation_and_auth_outage_after_initialize(self):
        client = await self.session()
        before = self.auth_calls
        self.assertFalse((await client.call_tool('operator_identity', {})).isError)
        self.assertGreaterEqual(self.auth_calls - before, 2)
        self.payload['active'] = False
        response = await self.http.post('/mcp', json={'jsonrpc': '2.0', 'id': 99,
            'method': 'tools/call', 'params': {'name': 'read_email',
            'arguments': {'thread_key': 'thread', 'source_email_id': 'source'}}})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.calls, [])
        self.payload['active'] = True
        self.auth_status = 503
        self.assertIsNone(await self.verifier.verify_token('test-opaque-access-token'))

    async def exercise_malformed_bounded_auth_and_source_policy(self):
        for body in (b'not-json', b'x' * 65537, b'null'):
            self.auth_body = body
            self.assertIsNone(await self.verifier.verify_token('test-opaque-access-token'))
        self.auth_body = None
        client = await self.session()
        self.emails[0]['pec_markers'] = ['pec']
        result = await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})
        self.assertTrue(result.isError)
        self.assertNotIn('hidden-canary', str(result))
        self.emails[0]['pec_markers'] = None
        self.emails.append(dict(self.emails[0]))
        self.assertTrue((await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})).isError)

    async def exercise_context_revocation_and_identity_only_refusal(self):
        client = await self.session()
        self.payload['scope'] = 'operator.read'
        self.payload['source_classes'] = []
        self.payload['mailbox_ids'] = []
        identity = await client.call_tool('operator_identity', {})
        self.assertEqual(identity.structuredContent['capabilities'], ['operator_identity', 'cs_bootstrap', 'cs_bootstrap_hook'])
        arguments = {'thread_key': 'thread', 'source_email_id': 'source', 'customer_email': 'contact@example.test'}
        self.assertTrue((await client.call_tool('customer_context', arguments)).isError)
        self.assertEqual(self.calls, [])
        self.payload['scope'] = 'operator.read email.read draft.read'
        self.payload['source_classes'] = ['mail', 'drafts']
        self.payload['mailbox_ids'] = ['ordinary-mailbox']
        self.revoke_during_read = True
        result = await client.call_tool('customer_context', arguments)
        self.assertTrue(result.isError)
        self.assertNotIn('Untrusted mail source', str(result))

    async def exercise_long_read_revalidates_before_returning_content(self):
        client = await self.session()
        self.revoke_during_read = True
        before = self.auth_calls
        result = await client.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})
        self.assertTrue(result.isError)
        self.assertNotIn('Untrusted mail source', str(result))
        self.assertGreaterEqual(self.auth_calls - before, 3)


if __name__ == '__main__':
    unittest.main()
