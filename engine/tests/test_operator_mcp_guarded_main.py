"""MCP receipts share actual current-main company guards and private writers."""
import asyncio
import base64
from datetime import datetime
import hashlib
import json
import sqlite3
import threading

import pytest
from sqlalchemy import select, update

from assignments.conftest import env, cleanup_test_data
from test_draft_policy import mail
from test_evidence_rpc import assign
from mail_fixture import ROOT
from zylch.services import operator_reply_operations as ops, operator_reply_generation as generation
from zylch.services import operator_instructions, project_store
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage import database as db
from zylch.storage.models import Draft, Email, LlmReservation
from zylch.storage.storage import Storage


@pytest.fixture
def reply(env, mail, monkeypatch):
    raw = base64.b64encode(b'Use confirmed facts.').decode()
    project_store.write(env.space, 'operator-instructions', 'procedures.md', raw, 0, author='alice')
    actor = ops.ActorBinding('alice', 'alice', env.space, mail.box, 'alice@example.test', 'client', 'grant')
    calls = []
    def context(source, versions, current):
        from zylch.services.operator_reply_context import snapshot
        with db.get_engine().connect() as conn:
            rows = [dict(row) for row in conn.execute(select(Email.__table__).where(Email.owner_id == actor.mailbox_address, Email.thread_id == ROOT)).mappings()]
        exact = next(row for row in rows if row['id'] == mail.root_id)
        exact = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in exact.items()}
        return {'source':exact, 'instructions':operator_instructions.documents(actor.mailbox_address), 'correspondence':snapshot(rows, actor, ROOT)}
    async def generator(bundle, request):
        calls.append(request)
        return 'A confirmed fixture answer.'
    service = ops.ReplyOperations(revalidate=lambda value: None, context_reader=context, generator=generator)
    async def prepare(key='guarded-request-0001'):
        return await service.prepare(key, {'source_email_id':mail.root_id}, [], 'Draft using exact evidence', actor)
    return type('ReplyFixture', (), {'actor':actor, 'service':service, 'calls':calls, 'prepare':staticmethod(prepare), 'context':staticmethod(context)})()


def draft_count():
    with db.get_engine().connect() as conn:
        return len(conn.execute(select(Draft.id)).all())


def test_real_guard_create_reuse_saved_recovery(reply):
    first = asyncio.run(reply.prepare())
    assert asyncio.run(reply.prepare()) == first and len(reply.calls) == 1
    second = asyncio.run(reply.prepare('guarded-request-0002'))
    assert first['state'] == second['state'] == 'completed'
    assert first['result']['created'] and not second['result']['created']
    assert first['result']['draft_id'] == second['result']['draft_id'] and draft_count() == 1
    recovered = asyncio.run(reply.prepare())
    assert recovered['result'] == first['result'] and len(reply.calls) == 2
    assert not recovered['current_draft']['matches_original']


@pytest.mark.parametrize('hold', ['assigned', 'missing-trust', 'legacy-unknown'])
def test_actual_native_holds_refuse_draft(reply, env, hold):
    if hold == 'assigned':
        assign(env)
    elif hold == 'missing-trust':
        env.trust_file.unlink()
    else:
        from zylch.storage.assigned_task_models import AssignmentEnrollment
        with env.memory.begin() as conn:
            conn.execute(update(AssignmentEnrollment).values(state='legacy-unknown'))
    with pytest.raises((AssignmentError, FileNotFoundError)):
        asyncio.run(reply.prepare())
    assert draft_count() == 0


def test_never_enabled_remains_native_compatible(reply, env):
    from zylch.storage.assigned_task_models import AssignmentEnrollment
    env.trust_file.unlink()
    with env.memory.begin() as conn:
        conn.execute(update(AssignmentEnrollment).values(state='never-enabled', provenance=[{'kind':'fresh-company-fixture'}]))
    assert asyncio.run(reply.prepare())['state'] == 'completed'


def test_receipt_failure_rolls_back_private_draft_and_result(reply, monkeypatch):
    original = ops.finish_draft_write
    def failure(session, draft):
        original(session, draft)
        raise RuntimeError('injected receipt failure')
    monkeypatch.setattr(ops, 'finish_draft_write', failure)
    with pytest.raises(RuntimeError, match='injected receipt'):
        asyncio.run(reply.prepare())
    value = asyncio.run(reply.service.recover(actor_binding=reply.actor, request_key='guarded-request-0001'))
    assert draft_count() == 0 and value['result'] is None and value['state'] == 'failed_before_dispatch'


def test_missing_and_mismatched_effect_binding_refuse(reply):
    from zylch.services import task_assignment_email_effect as effect
    source = reply.context({}, [], reply.actor)['source']
    with db.get_session() as session:
        with pytest.raises(ops.ReplyRefusal, match='matching_native_email_effect'):
            ops._native_effect_source(session, reply.actor, source)
        with effect.effect(reply.actor.mailbox_address, ops.reply_headers(source)):
            with pytest.raises(ops.ReplyRefusal, match='matching_native_email_effect'):
                ops._native_effect_source(session, reply.actor, {**source, 'message_id_header':'<wrong@example.test>'})
            with pytest.raises(ops.ReplyRefusal, match='native_effect_source_changed'):
                ops._native_effect_source(session, reply.actor, {**source, 'in_reply_to':'<changed@example.test>'})


@pytest.mark.parametrize('change', ['source', 'recipient', 'rules', 'correspondence'])
def test_change_after_context_before_persistence_refuses(reply, monkeypatch, env, change):
    original = generation.persist
    def race(source, body, actor):
        if change == 'rules':
            project_store.write(env.space, 'operator-instructions', 'procedures.md', base64.b64encode(b'Changed rule').decode(), 1, author='alice')
        elif change == 'recipient':
            return Storage.get_instance().create_draft(actor.mailbox_address, 'wrong@example.test', 'Reply', body, **ops.reply_headers(source))
        else:
            with db.get_engine().begin() as conn:
                if change == 'source':
                    conn.execute(update(Email).where(Email.id == source['id']).values(body_plain='Changed source'))
                else:
                    conn.execute(Email.__table__.insert().values(id='later', owner_id=actor.mailbox_address, mailbox_id=actor.mailbox_id, gmail_id='later', thread_id=ROOT, from_email=actor.mailbox_address, to_email='customer@example.test', body_plain='Later answer', date=datetime.now()))
        return original(source, body, actor)
    monkeypatch.setattr(generation, 'persist', race)
    with pytest.raises((ops.ReplyRefusal, AssignmentError)):
        asyncio.run(reply.prepare())
    assert draft_count() == 0


@pytest.mark.parametrize('database', ['company', 'private'])
def test_company_rule_writer_excluded_during_actual_receipt(reply, env, monkeypatch, database):
    original = ops._published_locked
    outcomes = []
    entered, completed = threading.Event(), threading.Event()
    filename = env.memory.url.database if database == 'company' else db.get_engine().url.database
    statement = 'UPDATE project_space SET space_id=space_id WHERE id=1' if database == 'company' else 'UPDATE emails SET body_plain=body_plain'
    def writer():
        entered.wait(2)
        with sqlite3.connect(filename, timeout=0.05) as conn:
            try:
                conn.execute(statement)
                conn.commit()
                outcomes.append('unexpected commit')
            except sqlite3.OperationalError as error:
                outcomes.append(str(error))
        completed.set()
    thread = threading.Thread(target=writer)
    thread.start()
    def reader(session, actor):
        entered.set()
        assert completed.wait(2)
        return original(session, actor)
    reply.service.locked_instruction_reader = reader
    assert asyncio.run(reply.prepare())['state'] == 'completed'
    thread.join(2)
    assert outcomes == ['database is locked'] and not thread.is_alive()


def test_review_uses_native_guard_private_receipt_without_draft(reply):
    async def review(context, request):
        reply.calls.append(request)
        return ops.ReviewRequired('Missing confirmed price', ['Current price'])
    reply.service.generator = review
    first = asyncio.run(reply.prepare())
    assert first['state'] == 'needs_review' and first['result'] is None and draft_count() == 0
    assert asyncio.run(reply.prepare()) == first and len(reply.calls) == 1


def test_one_actual_reservation_and_no_second_generation(reply, monkeypatch):
    from zylch.llm import budget
    monkeypatch.setattr(budget, 'request_bound', lambda *args: 123)
    async def generator(context, request):
        reply.calls.append(request)
        budget.reserve({'model':'controlled-fixture'}, 'direct')
        with pytest.raises(budget.BudgetError, match='no new paid call'):
            budget.reserve({'model':'controlled-fixture'}, 'direct')
        return 'Reserved controlled answer'
    reply.service.generator = generator
    result = asyncio.run(reply.prepare())
    assert asyncio.run(reply.prepare()) == result and len(reply.calls) == 1
    with db.get_engine().connect() as conn:
        ids = list(conn.execute(select(LlmReservation.id)).scalars())
    assert len(ids) == 1 and result['reservation_ids'] == ids


@pytest.mark.parametrize('admission', ['allowed', 'held', 'source-mismatch'])
def test_actual_http_granted_effect_native_causal_edge(reply, env, mail, monkeypatch, admission):
    import time
    from contextlib import AsyncExitStack
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from zylch.operator_mcp.auth import GrantVerifier
    from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
    from zylch.operator_mcp.server import create_server
    from zylch.rpc.methods import emails_list_by_thread

    project_store.write(env.space, 'operator-instructions', 'mail/alice@example.test.md',
        base64.b64encode(b'Reply as Alice.').decode(), 0, author='alice')
    if admission == 'held':
        assign(env)
    monkeypatch.setattr('zylch.api.token_storage.get_provider', lambda owner: 'imap')
    monkeypatch.setattr('zylch.api.token_storage.get_email', lambda owner: 'alice@example.test')
    calls = []
    async def model(context, request):
        calls.append((context, request))
        return 'One controlled HTTP answer'
    monkeypatch.setattr(generation, 'generate', model)

    async def exercise():
        rows = operator_instructions.documents('alice@example.test')
        payload = {'active':True, 'iss':'https://auth.example.test', 'sub':'alice',
            'profile_uid':'alice', 'company_ref':env.space, 'client_id':'client',
            'resource':'https://engine.example.test/mcp', 'grant_id':'http-grant',
            'exp':int(time.time())+240, 'scope':'operator.read email.read draft.read instructions.read draft.prepare',
            'source_classes':['mail','drafts','instructions'], 'mailbox_ids':[mail.box],
            'instruction_paths':['procedures.md','mail/alice@example.test.md']}
        async def introspect(request):
            return httpx.Response(200, json=payload)
        async def search(params, notify):
            return {'threads':[]}
        async def drafts(params, notify):
            return Storage.get_instance().list_drafts('alice@example.test')
        async with AsyncExitStack() as stack:
            auth = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.MockTransport(introspect)))
            verifier = GrantVerifier(issuer=payload['iss'], introspection_url=payload['iss']+'/introspect',
                service_client_id='profile', service_client_secret='fixture-only', resource=payload['resource'],
                profile_uid='alice', company_ref=env.space, allowed_client_ids={'client'}, http_client=auth,
                instructions_enabled=True, draft_enabled=True)
            port = NativeReadPort(lambda:ProfileBinding('alice','alice@example.test',env.space,frozenset({mail.box}),True),
                {'emails.search':search,'emails.list_by_thread':emails_list_by_thread,'drafts.list':drafts})
            server = create_server(verifier, port, allowed_hosts=['engine.example.test'])
            app = server.streamable_http_app()
            await stack.enter_async_context(server.session_manager.run())
            http = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='https://engine.example.test', headers={'Authorization':'Bearer native-http-fixture-token'}))
            async def session():
                read, write, _ = await stack.enter_async_context(streamable_http_client('https://engine.example.test/mcp',http_client=http))
                client = await stack.enter_async_context(ClientSession(read,write))
                await client.initialize()
                return client
            client = await session()
            arguments = {'request_key':'native-http-request-0001','thread_key':ROOT,
                'source_email_id':'foreign-source' if admission == 'source-mismatch' else mail.root_id,
                'request_text':'Draft from this exact source',
                'instruction_versions':[{k:doc[k] for k in ('path','revision','sha256')} for doc in rows]}
            first = await client.call_tool('prepare_reply',arguments)
            if admission != 'allowed':
                assert first.isError, str(first)
                assert calls == [] and draft_count() == 0
                with db.get_engine().connect() as conn:
                    assert conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='operator_reply_operations'").all() == []
                return
            assert not first.isError, str(first)
            saved = first.structuredContent
            assert saved['state'] == 'completed' and saved['result']['snapshot']['body'] == 'One controlled HTTP answer'
            assert draft_count() == 1 and len(calls) == 1
            fresh = await session()
            recovered = await fresh.call_tool('recover_reply',{'request_key':arguments['request_key']})
            assert not recovered.isError, str(recovered)
            assert recovered.structuredContent['result'] == saved['result']
            again = await fresh.call_tool('prepare_reply',arguments)
            assert not again.isError, str(again)
            assert again.structuredContent['operation_id'] == saved['operation_id']
            assert len(calls) == 1 and draft_count() == 1
            payload['active'] = False
            denied = await http.post('/mcp',json={'jsonrpc':'2.0','id':99,'method':'tools/call',
                'params':{'name':'prepare_reply','arguments':arguments}})
            assert denied.status_code == 401 and len(calls) == 1 and draft_count() == 1
    asyncio.run(exercise())
