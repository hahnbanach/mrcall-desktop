"""Actual Unix HTTP/SDK lifecycle; controlled identity and native source replies."""

import asyncio
import os
import stat
import tempfile
import time
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.runtime import RuntimeRefused, UnixMCPListener
from zylch.operator_mcp.server import create_server


class RuntimeTests(unittest.TestCase):
    def test_actual_unix_sdk_reads_shutdown_and_refusal(self):
        asyncio.run(self.exercise_unix())

    async def exercise_unix(self):
        resource = 'https://desktop.example.test/operator/owner/mcp'
        revoked = False
        calls = []
        pid = os.getpid()
        async def service(request):
            self.assertTrue(request.headers['authorization'].startswith('Basic '))
            if request.url.path == '/clients/approved':
                return httpx.Response(200, json={'resource': resource, 'profile_uid': 'owner',
                    'company_ref': 'company', 'client_ids': [] if revoked else ['client']})
            return httpx.Response(200, json={'active': not revoked, 'iss': 'https://desktop.example.test',
                'sub': 'owner', 'profile_uid': 'owner', 'company_ref': 'company', 'client_id': 'client',
                'resource': resource, 'grant_id': 'grant', 'scope': 'operator.read email.read',
                'source_classes': ['mail'], 'mailbox_ids': ['box'], 'exp': int(time.time()) + 120})
        async def search(params, notify):
            calls.append(('search', os.getpid()))
            return {'threads': [{'thread_id': 'thread', 'last_email_id': 'source', 'mailbox_ids': ['box']}]}
        async def thread(params, notify):
            calls.append(('thread', os.getpid()))
            return {'emails': [{'id': 'source', 'mailbox_id': 'box', 'pec_markers': None,
                'original_message_id': None, 'subject': 'Controlled source', 'body_plain': 'Controlled native evidence'}]}
        async def drafts(params, notify):
            return []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mcp.sock'
            async with httpx.AsyncClient(transport=httpx.MockTransport(service)) as auth:
                verifier = GrantVerifier(issuer='https://desktop.example.test',
                    introspection_url='https://desktop.example.test/introspect',
                    client_registry_url='https://desktop.example.test/clients/approved',
                    service_client_id='profile-service', service_client_secret='secret-canary',
                    resource=resource, profile_uid='owner', company_ref='company', http_client=auth)
                port = NativeReadPort(lambda: ProfileBinding('owner', 'owner@example.test', 'company', frozenset({'box'})),
                    {'emails.search': search, 'emails.list_by_thread': thread, 'drafts.list': drafts})
                server = create_server(verifier, port, path='/operator/owner/mcp', allowed_hosts=['desktop.example.test'])
                listener = UnixMCPListener(server.streamable_http_app(), path)
                async with listener:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o660)
                    transport = httpx.AsyncHTTPTransport(uds=str(path))
                    async with httpx.AsyncClient(transport=transport, base_url='http://desktop.example.test') as http:
                        refused = await http.post('/operator/owner/mcp', json={})
                        self.assertEqual(refused.status_code, 401)
                        self.assertIn('resource_metadata=', refused.headers['www-authenticate'])
                        metadata = await http.get('/.well-known/oauth-protected-resource/operator/owner/mcp')
                        self.assertEqual(metadata.json()['resource'], resource)
                        self.assertEqual(metadata.json()['scopes_supported'], ['operator.read', 'email.read', 'draft.read'])
                        http.headers['Authorization'] = 'Bearer controlled-access-token'
                        async with streamable_http_client('http://desktop.example.test/operator/owner/mcp', http_client=http) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                tools = await session.list_tools()
                                self.assertEqual({t.name for t in tools.tools}, {'operator_identity', 'search_email', 'read_email', 'customer_context', 'list_drafts', 'operator_capabilities', 'operator_read', 'operator_action', 'cs_bootstrap', 'cs_bootstrap_hook'})
                                identity = await session.call_tool('operator_identity', {})
                                self.assertFalse(identity.isError)
                                source = await session.call_tool('read_email', {'thread_key': 'thread', 'source_email_id': 'source'})
                                self.assertFalse(source.isError)
                                self.assertIn('Controlled native evidence', str(source.content))
                                self.assertTrue(calls and all(value == pid for _, value in calls))
                                revoked = True
                                response = await http.post('/operator/owner/mcp', json={})
                                self.assertEqual(response.status_code, 401)
                self.assertTrue(listener.task.done())
                self.assertFalse(path.exists())

    def test_socket_refusal_and_listener_failure_retires_foreground(self):
        asyncio.run(self.exercise_failure())

    async def exercise_failure(self):
        from starlette.applications import Starlette
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mcp.sock'
            path.write_text('preserve existing file')
            with self.assertRaises(RuntimeRefused):
                async with UnixMCPListener(Starlette(), path):
                    pass
            self.assertEqual(path.read_text(), 'preserve existing file')
            path.unlink()
            async with UnixMCPListener(Starlette(), path) as listener:
                listener.server.should_exit = True
                with self.assertRaises(RuntimeRefused):
                    await listener.serve_with(asyncio.sleep(60))
            self.assertFalse(path.exists())

    def test_failed_lifespan_is_safe_runtime_refusal(self):
        asyncio.run(self.exercise_failed_lifespan())

    async def exercise_failed_lifespan(self):
        from starlette.applications import Starlette
        @asynccontextmanager
        async def failure(app):
            raise RuntimeError('private-startup-canary')
            yield
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mcp.sock'
            listener = UnixMCPListener(Starlette(lifespan=failure), path)
            with self.assertRaises(RuntimeRefused) as refused:
                async with listener:
                    pass
            self.assertNotIn('canary', str(refused.exception))
            self.assertTrue(listener.task.done())
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
