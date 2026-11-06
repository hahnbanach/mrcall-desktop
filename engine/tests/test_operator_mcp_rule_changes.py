"""MCP SDK over HTTP into the actual SQLite rule writer; controlled OAuth only."""
import time
import unittest
from contextlib import AsyncExitStack
from dataclasses import replace
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.effects import GrantedEffects
from zylch.operator_mcp.permissions import SCOPES as ALL_SCOPES, RULE_WRITE_SCOPE
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server
from zylch.services import operator_rule_changes as changes


SCOPES = ALL_SCOPES - {'pricing.use', 'projects.read', 'projects.write', 'operator.use'}

class RuleChangeSDKTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_writer_old_grant_refusal_fresh_session_recovery_and_undo(self):
        from engine.tests import test_operator_rule_changes as fixtures
        fixture = fixtures.RuleChangeTests()
        fixture.setUp()
        try:
            payload = {'active': True, 'iss': 'https://auth.example.test', 'sub': 'uid-a',
                'profile_uid': 'uid-a', 'company_ref': 'company-a', 'client_id': 'client-a',
                'resource': 'https://engine.example.test/mcp', 'grant_id': 'grant-a',
                'exp': int(time.time()) + 240, 'scope': ' '.join(sorted(SCOPES)),
                'source_classes': ['mail', 'drafts', 'instructions'], 'mailbox_ids': ['mailbox-a'],
                'instruction_paths': ['procedures.md', fixture.path]}
            async def introspect(request):
                return httpx.Response(200, json=payload)
            async def empty(params, notify):
                return []
            async with AsyncExitStack() as stack:
                auth = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.MockTransport(introspect)))
                verifier = GrantVerifier(issuer=payload['iss'], introspection_url=payload['iss'] + '/introspect',
                    service_client_id='profile', service_client_secret='controlled-test-secret',
                    resource=payload['resource'], profile_uid='uid-a', company_ref='company-a',
                    allowed_client_ids={'client-a'}, http_client=auth,
                    instructions_enabled=True, draft_enabled=True, proposals_enabled=True, rules_write_enabled=True)
                port = NativeReadPort(lambda: ProfileBinding('uid-a', 'owner@example.test', 'company-a', frozenset({'mailbox-a'}), True),
                    {'emails.search': empty, 'emails.list_by_thread': empty, 'drafts.list': empty})
                server = create_server(verifier, port, allowed_hosts=['engine.example.test'])
                app = server.streamable_http_app()
                await stack.enter_async_context(server.session_manager.run())
                http = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url='https://engine.example.test', headers={'Authorization': 'Bearer controlled-rule-token'}))
                async def session():
                    read, write, _ = await stack.enter_async_context(streamable_http_client(payload['resource'], http_client=http))
                    client = await stack.enter_async_context(ClientSession(read, write))
                    await client.initialize()
                    return client
                client = await session()
                names = {t.name for t in (await client.list_tools()).tools}
                self.assertTrue({'read_rules', 'save_rule', 'restore_rule', 'rule_history', 'rule_change_status'} <= names)
                self.assertNotIn('send_mail', names)
                identity = await client.call_tool('operator_identity', {})
                self.assertFalse(identity.isError, str(identity))
                arguments = dict(request_key='sdk-rule-change-0001', target='procedures.md',
                                 content='Never repeat an introduction in the same thread.\n', base_revision=1)
                # A newly deployed server does not confer write on an old grant.
                payload['scope'] = ' '.join(sorted(SCOPES - {RULE_WRITE_SCOPE}))
                refused = await client.call_tool('save_rule', arguments)
                self.assertTrue(refused.isError)
                self.assertEqual(fixture.current()['revision'], 1)
                payload['scope'] = ' '.join(sorted(SCOPES))
                read = await client.call_tool('read_rules', {})
                self.assertFalse(read.isError, str(read))
                self.assertEqual(len(read.structuredContent['documents']), 6)
                first = await client.call_tool('save_rule', arguments)
                self.assertFalse(first.isError, str(first))
                saved = first.structuredContent
                self.assertEqual((saved['state'], saved['revision']), ('saved', 2))
                fresh = await session()
                recovered = await fresh.call_tool('rule_change_status', {'request_key': arguments['request_key']})
                self.assertFalse(recovered.isError, str(recovered))
                self.assertEqual(recovered.structuredContent, saved)
                retry = await fresh.call_tool('save_rule', arguments)
                self.assertEqual(retry.structuredContent, saved)
                latest = await fresh.call_tool('read_rules', {'path': 'procedures.md'})
                self.assertEqual(latest.structuredContent['documents'][0]['content'], arguments['content'])
                stale = await fresh.call_tool('save_rule', {**arguments, 'request_key': 'sdk-conflict-rule-0002'})
                self.assertEqual(stale.structuredContent['state'], 'conflict')
                for invalid in ({**arguments, 'base_revision': True}, {**arguments, 'human': True}):
                    self.assertTrue((await fresh.call_tool('save_rule', invalid)).isError)
                undo = await fresh.call_tool('restore_rule', dict(request_key='sdk-restore-rule-0003',
                    target='procedures.md', source_revision=1, base_revision=2))
                self.assertFalse(undo.isError, str(undo))
                self.assertEqual(undo.structuredContent['revision'], 3)
                history = await fresh.call_tool('rule_history', {'target': 'procedures.md', 'limit': 5})
                self.assertEqual([r['revision'] for r in history.structuredContent['items']], [3, 2, 1])
                payload['active'] = False
                response = await http.post('/mcp', json={'jsonrpc': '2.0', 'id': 99, 'method': 'tools/call',
                    'params': {'name': 'save_rule', 'arguments': {**arguments, 'request_key': 'revoked-rule-0004'}}})
                self.assertEqual(response.status_code, 401)
                self.assertEqual(fixture.current()['revision'], 3)
        finally:
            fixture.tearDown()

    async def test_revocation_after_commit_recovers_without_second_write(self):
        from engine.tests import test_operator_rule_changes as fixtures
        from types import SimpleNamespace
        from cs.operator_read import ReadError
        fixture = fixtures.RuleChangeTests()
        fixture.setUp()
        try:
            grant = SimpleNamespace(subject='uid-a', client_id='client-a', grant_id='grant-a',
                                    scopes={RULE_WRITE_SCOPE})
            binding = SimpleNamespace(profile_uid='uid-a', company_ref='company-a', email='owner@example.test')
            class Verifier:
                calls = 0
                revoked = False
                async def verify_token(self, token):
                    self.calls += 1
                    return None if self.revoked and self.calls == 3 else SimpleNamespace(claims={})
                def grant(self, claims):
                    return grant
            verifier = Verifier()
            effects = GrantedEffects(verifier, SimpleNamespace(context_binding=lambda g: binding))
            verifier.revoked = True
            with self.assertRaises(ReadError):
                await effects.save_rule('token', 'uncertain-write-0001', 'procedures.md', 'Saved before revocation', 1)
            self.assertEqual(fixture.current()['revision'], 2)
            verifier.revoked = False
            recovered = await effects.rule_change_status('token', request_key='uncertain-write-0001')
            self.assertEqual(recovered['revision'], 2)
            retry = await effects.save_rule('token', 'uncertain-write-0001', 'procedures.md', 'Saved before revocation', 1)
            self.assertEqual(retry, recovered)
            self.assertEqual(fixture.current()['revision'], 2)
        finally:
            fixture.tearDown()

    async def _assert_native_role_change_refused(self, change_at):
        from engine.tests import test_operator_rule_changes as fixtures
        from types import SimpleNamespace
        from cs.operator_read import ReadError
        import os
        fixture = fixtures.RuleChangeTests()
        fixture.setUp()
        try:
            grant = SimpleNamespace(client_id='client-a', grant_id='grant-a', scopes={RULE_WRITE_SCOPE})
            # Production ProfileBinding deliberately has no minter field.
            binding = ProfileBinding('uid-a', 'owner@example.test', 'company-a', frozenset({'mailbox-a'}), True)
            class Verifier:
                calls = 0
                async def verify_token(self, token):
                    self.calls += 1
                    if self.calls == change_at:
                        os.environ['MEMORY_KEY_SOURCE'] = 'shared'
                    return SimpleNamespace(claims={})
                def grant(self, claims):
                    return grant
            effects = GrantedEffects(Verifier(), SimpleNamespace(context_binding=lambda g: binding))
            with self.assertRaises(ReadError):
                if change_at == 2:
                    await effects.save_rule('token', 'changed-role-save-0001', 'procedures.md', 'Must refuse', 1)
                else:
                    await effects.read_rules('token')
            # Check company truth without giving this demoted actor owner rights.
            from zylch.services import project_store
            self.assertEqual(project_store.read('operator-instructions', 'procedures.md')['revision'], 1)
        finally:
            fixture.tearDown()

    async def test_role_change_before_admission_refuses_without_a_write(self):
        await self._assert_native_role_change_refused(2)

    async def test_role_change_at_disclosure_withholds_broader_rule_text(self):
        await self._assert_native_role_change_refused(3)
