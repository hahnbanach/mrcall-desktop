import asyncio
import base64
import time
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import update

from test_operator_mcp_guarded_main import reply, env, mail, cleanup_test_data, draft_count
from test_evidence_rpc import assign, result
from mail_fixture import ROOT
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.permissions import SCOPES as ALL_SCOPES, RULE_WRITE_SCOPE
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server
from zylch.rpc.methods import emails_list_by_thread
from zylch.services import operator_instructions, operator_reply_generation, project_store
from zylch.storage import database as db
from zylch.storage.models import Email
from zylch.storage.storage import Storage

SCOPES = ALL_SCOPES - {RULE_WRITE_SCOPE, 'pricing.use', 'projects.read', 'projects.write', 'operator.use'}


def test_sdk_native_draft_fresh_session_recovery(reply, env, mail, monkeypatch):
    source_body = 'Real stored source\n\nOn Monday Customer wrote:\n> Quoted earlier message'
    with db.get_engine().begin() as conn:
        conn.execute(update(Email).where(Email.id == mail.root_id).values(body_plain=source_body,
            from_email='  customer@example.test  ', body_html=None))
    project_store.write(env.space, 'operator-instructions', 'mail/alice@example.test.md',
        base64.b64encode(b'Reply as the owner').decode(), 0, author='alice')
    _, _, assigned = assign(env)
    held_projection = result('project', thread_key=ROOT)
    assert held_projection['state'] == 'assigned' and held_projection['hold_auto_reply']
    monkeypatch.setattr('zylch.api.token_storage.get_provider', lambda owner: 'imap')
    monkeypatch.setattr('zylch.api.token_storage.get_email', lambda owner: reply.actor.mailbox_address)
    calls = []

    async def generate(context, request):
        calls.append((context, request))
        return 'One bounded SDK answer'

    monkeypatch.setattr(operator_reply_generation, 'generate', generate)

    def close_and_receive():
        intent = result('preview', operation='close', thread_key=ROOT, expected_revision=1,
            task_id=assigned['task_id'], reason='Handled personally', handled_ref='sdk-held-source')
        result('commit', intent=intent, grant=env.sign(intent))
        source_id = mail.add('<sdk-later-inbound@example.test>', 'customer@example.test',
            reply.actor.mailbox_address, reply=ROOT, body=source_body)
        with db.get_engine().begin() as conn:
            conn.execute(update(Email).where(Email.id == source_id).values(from_email='  customer@example.test  ', body_html=None))
        return source_id

    async def exercise():
        rows = operator_instructions.documents(reply.actor.mailbox_address)
        payload = {'active': True, 'iss': 'https://auth.example.test', 'sub': reply.actor.actor_uid,
            'profile_uid': reply.actor.profile_uid, 'company_ref': env.space, 'client_id': 'client',
            'resource': 'https://engine.example.test/mcp', 'grant_id': 'grant',
            'exp': int(time.time()) + 240, 'scope': ' '.join(sorted(SCOPES)),
            'source_classes': ['mail', 'drafts', 'instructions'], 'mailbox_ids': [mail.box],
            'instruction_paths': [doc['path'] for doc in rows]}

        async def introspect(request):
            return httpx.Response(200, json=payload)

        async def search(params, notify):
            return {'threads': []}

        async def drafts(params, notify):
            return Storage.get_instance().list_drafts(reply.actor.mailbox_address)

        async with AsyncExitStack() as stack:
            auth = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.MockTransport(introspect)))
            verifier = GrantVerifier(issuer=payload['iss'], introspection_url=payload['iss'] + '/introspect',
                service_client_id='profile', service_client_secret='controlled-test-secret',
                resource=payload['resource'], profile_uid=reply.actor.profile_uid, company_ref=env.space,
                allowed_client_ids={'client'}, http_client=auth,
                instructions_enabled=True, draft_enabled=True, proposals_enabled=True)
            port = NativeReadPort(lambda: ProfileBinding(reply.actor.profile_uid, reply.actor.mailbox_address,
                env.space, frozenset({mail.box}), True),
                {'emails.search': search, 'emails.list_by_thread': emails_list_by_thread, 'drafts.list': drafts})
            server = create_server(verifier, port, allowed_hosts=['engine.example.test'])
            app = server.streamable_http_app()
            await stack.enter_async_context(server.session_manager.run())
            http = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='https://engine.example.test', headers={'Authorization': 'Bearer test-opaque-causal-token'}))

            async def session():
                read, write, _ = await stack.enter_async_context(streamable_http_client('https://engine.example.test/mcp', http_client=http))
                client = await stack.enter_async_context(ClientSession(read, write))
                await client.initialize()
                return client

            arguments = {'request_key': 'sdk-stable-request-0001', 'thread_key': ROOT,
                'source_email_id': mail.root_id, 'request_text': 'Please draft a grounded reply',
                'instruction_versions': [{key: doc[key] for key in ('path', 'revision', 'sha256')} for doc in rows]}
            client = await session()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert 'prepare_reply' in names
            assert 'confirm_rule' not in names
            assert 'send_mail' not in names
            read = await client.call_tool('read_email', {'thread_key': ROOT, 'source_email_id': arguments['source_email_id']})
            assert not read.isError, str(read)
            assert read.structuredContent['email']['body_plain'] == 'Real stored source'
            held = await client.call_tool('prepare_reply', arguments)
            assert held.isError
            assert 'operator_operation_unavailable_recover_with_same_request_key' in str(held)
            assert len(calls) == 0 and draft_count() == 0
            with db.get_engine().connect() as conn:
                admitted = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='operator_reply_operations'").all()
            assert admitted == []
            arguments['source_email_id'] = await asyncio.to_thread(close_and_receive)
            first = await client.call_tool('prepare_reply', arguments)
            assert not first.isError, str(first)
            saved = first.structuredContent
            assert saved['state'] == 'completed'
            assert saved['source']['id'] == arguments['source_email_id']
            assert saved['source']['thread_id'] == arguments['thread_key']
            assert saved['result']['snapshot']['body'] == 'One bounded SDK answer'
            assert draft_count() == 1
            fresh = await session()
            recovered = await fresh.call_tool('recover_reply', {'request_key': arguments['request_key']})
            assert not recovered.isError, str(recovered)
            assert recovered.structuredContent['result'] == saved['result']
            again = await fresh.call_tool('prepare_reply', arguments)
            assert not again.isError, str(again)
            assert again.structuredContent['operation_id'] == saved['operation_id']
            changed = await fresh.call_tool('prepare_reply', {**arguments, 'request_text': 'Changed payload'})
            assert changed.isError
            assert 'payload_conflict' in str(changed)
            payload['active'] = False
            response = await http.post('/mcp', json={'jsonrpc': '2.0', 'id': 99, 'method': 'tools/call',
                'params': {'name': 'prepare_reply', 'arguments': {**arguments, 'request_key': 'sdk-other-request-0002'}}})
            assert response.status_code == 401
            assert len(calls) == 1
            assert 'Quoted earlier message' in calls[0][0]['source']['body_plain']
            assert draft_count() == 1
    asyncio.run(exercise())
