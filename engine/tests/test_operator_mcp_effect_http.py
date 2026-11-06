"""Real MCP SDK/HTTP routing; controlled auth and effects, no GUI claim."""

import asyncio
from types import SimpleNamespace
import unittest

import httpx

from zylch.operator_mcp.permissions import SCOPES as ALL_SCOPES, RULE_WRITE_SCOPE

# This compatibility test deliberately exercises the historical six-scope grant.
SCOPES = ALL_SCOPES - {RULE_WRITE_SCOPE, 'pricing.use', 'projects.read', 'projects.write', 'operator.use'}
from zylch.operator_mcp.server import create_server


class EffectHTTPTests(unittest.TestCase):
    def test_sdk_effect_catalog_and_strict_arguments(self):
        from engine.tests.test_operator_mcp_http import OperatorHTTPTests
        fixture = OperatorHTTPTests()

        async def exercise():
            fixture.verifier.allowed_scopes = SCOPES
            fixture.payload.update(scope=' '.join(sorted(SCOPES)),
                source_classes=['mail', 'drafts', 'instructions'],
                instruction_paths=['procedures.md', 'mail/owner@example.test.md'])
            calls = []

            async def prepare(*args):
                calls.append(('prepare', args))
                return {'operation_id': 'operation', 'state': 'completed'}

            async def recover(*args):
                calls.append(('recover', args))
                return {'operation_id': 'operation', 'state': 'completed'}

            async def propose(*args):
                calls.append(('propose', args))
                return {'id': 'proposal', 'state': 'pending'}

            async def status(*args):
                calls.append(('status', args))
                return {'id': 'proposal', 'state': 'pending'}

            effects = SimpleNamespace(prepare=prepare, recover=recover, propose=propose, rule_status=status)
            server = create_server(fixture.verifier, None, allowed_hosts=['engine.example.test'], effects=effects)
            app = server.streamable_http_app()
            await fixture.stack.enter_async_context(server.session_manager.run())
            fixture.http = await fixture.stack.enter_async_context(httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url='https://engine.example.test',
                headers={'Authorization': 'Bearer test-opaque-access-token'}))
            client = await fixture.session()
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertEqual(names, {'operator_identity', 'search_email', 'read_email',
                'customer_context', 'list_drafts', 'prepare_reply', 'recover_reply', 'propose_rule', 'rule_status', 'operator_capabilities', 'operator_read', 'operator_action', 'cs_bootstrap', 'cs_bootstrap_hook'})
            self.assertNotIn('confirm_rule', names)
            self.assertNotIn('send_mail', names)
            arguments = {'request_key': 'stable-request-0001', 'thread_key': 'thread',
                'source_email_id': 'source', 'instruction_versions': [], 'request_text': 'Draft a reply'}
            result = await client.call_tool('prepare_reply', arguments)
            self.assertFalse(result.isError)
            self.assertEqual(result.structuredContent['operation_id'], 'operation')
            self.assertFalse((await client.call_tool('recover_reply', {'request_key': arguments['request_key']})).isError)
            self.assertFalse((await client.call_tool('propose_rule', {'target': 'procedures.md', 'content': 'Proposed rule', 'base_revision': 1})).isError)
            self.assertFalse((await client.call_tool('rule_status', {'proposal_id': 'proposal'})).isError)
            before = len(calls)
            for name, args in [('prepare_reply', {**arguments, 'human': True}),
                               ('propose_rule', {'target': 'procedures.md', 'content': 'Text', 'base_revision': True}),
                               ('confirm_rule', {'proposal_id': 'proposal'})]:
                self.assertTrue((await client.call_tool(name, args)).isError)
            self.assertEqual(len(calls), before)
            fixture.payload['active'] = False
            response = await fixture.http.post('/mcp', json={'jsonrpc': '2.0', 'id': 10,
                'method': 'tools/call', 'params': {'name': 'prepare_reply', 'arguments': arguments}})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(len(calls), before)

        fixture.run_case(exercise)
