"""One ledger contract through production stdio and WebSocket frame handlers.

The isolated subprocess owns a synthetic profile. WebSocket claims are fixtures;
these tests do not verify Firebase tokens or the production handshake.
"""

import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ENGINE = Path(__file__).resolve().parents[2]
FIXTURE_BOOTSTRAP = r'''
import asyncio, json, os, time
from pathlib import Path
from pytest import MonkeyPatch
from tests.assignments.conftest import env as assignment_env
fixture_patch = MonkeyPatch()
fixture_scope = assignment_env.__wrapped__(Path(os.environ['TEST_FIXTURE_ROOT']), fixture_patch)
fixture = next(fixture_scope)
'''
BOOTSTRAP = FIXTURE_BOOTSTRAP + r'''
from zylch.storage.storage import Storage
store = Storage.get_instance()
foreign = {}
for state in ('open', 'closed'):
    event = 'foreign-' + state
    store.store_task_item('other@example.test', {
        'event_type': 'email', 'event_id': event,
        'contact_email': 'foreign-party@example.test', 'title': event,
        'action_required': True, 'sources': {'marker': event},
    })
    task = store.get_task_by_event('other@example.test', 'email', event)
    foreign[state] = task['id']
    if state == 'closed':
        store.complete_task_item('other@example.test', task['id'], actor='human', why='foreign close')
print(json.dumps({'fixture_seed': foreign, 'fixture_db_path': os.environ['ZYLCH_DB_PATH']}), flush=True)
async def main():
    if os.environ['TEST_TRANSPORT'] == 'stdio':
        from zylch.rpc.server import serve
        await serve()
    else:
        from websockets.asyncio.server import serve
        from zylch.rpc.server_ws import _handle_connection
        async def fixture_handshake(connection, request):
            assert request.headers.get('Authorization') == 'Bearer fixture:alice'
            connection._fb_claims = {'sub': 'alice', 'email': 'alice@example.test', 'exp': int(time.time()) + 3600}
            connection._fb_token = 'fixture:alice'
        async with serve(_handle_connection, '127.0.0.1', 0, process_request=fixture_handshake) as server:
            print(json.dumps({'fixture_url': 'ws://127.0.0.1:' + str(server.sockets[0].getsockname()[1])}), flush=True)
            await asyncio.Event().wait()
asyncio.run(main())
'''


def snapshot(db):
    with sqlite3.connect(db) as connection:
        return dict(connection.execute('SELECT id, json_object(' + ', '.join(
            "'%s', %s" % (column[1], column[1])
            for column in connection.execute('PRAGMA table_info(task_items)')
        ) + ') FROM task_items'))


def fixture_environment(transport, tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    db = tmp_path / 'ledger.db'
    environment = {
        'PATH': os.environ.get('PATH', ''), 'HOME': str(home),
        'PYTHONPATH': str(ENGINE), 'ZYLCH_DB_PATH': str(db),
        'ZYLCH_PROFILE_DIR': str(tmp_path), 'ZYLCH_HOME': str(home),
        'EMAIL_ADDRESS': 'owner@example.test', 'EMAIL_PASSWORD': 'fixture-only',
        'OWNER_ID': 'fixture-owner', 'TEST_TRANSPORT': transport,
        'TEST_FIXTURE_ROOT': str(tmp_path),
        'SYSTEM_LLM_PROVIDER': 'anthropic', 'AUTO_UPDATE_ENABLED': 'n',
    }
    return environment


async def exercise(transport, tmp_path):
    environment = fixture_environment(transport, tmp_path)
    with (tmp_path / 'server.stderr').open('wb') as stderr:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', BOOTSTRAP, cwd=tmp_path, env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
        )
        socket = None
        try:
            async def line():
                raw = await asyncio.wait_for(process.stdout.readline(), 30)
                assert raw, (tmp_path / 'server.stderr').read_text()
                return json.loads(raw)

            seed = await line()
            foreign = seed['fixture_seed']
            db = Path(seed['fixture_db_path'])
            if transport == 'stdio':
                assert (await line())['method'] == 'engine.ready'
            else:
                from websockets.asyncio.client import connect
                socket = await connect((await line())['fixture_url'], additional_headers={
                    'Authorization': 'Bearer fixture:alice',
                })
            serial = 0

            async def rpc(method, params):
                nonlocal serial
                serial += 1
                request = json.dumps({'jsonrpc': '2.0', 'id': serial, 'method': method, 'params': params})
                if socket:
                    await socket.send(request)
                else:
                    process.stdin.write((request + '\n').encode())
                    await process.stdin.drain()
                while True:
                    response = json.loads(await asyncio.wait_for(socket.recv(), 10)) if socket else await line()
                    if response.get('id') == serial:
                        assert 'error' not in response, response
                        return response['result']

            foreign_before = snapshot(db)
            assert await rpc('tasks.get', {'task_id': foreign['open']}) is None
            assert await rpc('tasks.list', {'include_completed': True}) == []
            for method, params in (
                ('tasks.complete', {'task_id': foreign['open'], 'actor': 'operator', 'why': 'attack'}),
                ('tasks.snooze', {'task_id': foreign['open'], 'days': 1}),
                ('tasks.pin', {'task_id': foreign['open'], 'pinned': True}),
                ('tasks.skip', {'task_id': foreign['open']}),
                ('tasks.reopen', {'task_id': foreign['closed']}),
            ):
                assert (await rpc(method, params))['ok'] is False, method
                assert snapshot(db) == foreign_before, method
            payload = {
                'event_id': 'owner-event', 'contact_email': 'alice@example.test',
                'title': 'Answer Alice', 'reason': 'Unanswered request',
                'sources': {'thread_id': 'alice-thread'},
            }
            first = await rpc('tasks.create', payload)
            assert first['ok'] and first['created']
            task_id = first['task_id']
            second = await rpc('tasks.create', {
                'event_id': 'unrelated-event', 'contact_email': 'bob@example.test',
                'title': 'Answer Bob', 'sources': {'thread_id': 'bob-thread'},
            })
            assert second['created']
            unrelated_before = snapshot(db)
            assert (await rpc('tasks.create', payload))['task_id'] == task_id
            snoozed = await rpc('tasks.snooze', {'task_id': task_id, 'days': 1, 'actor': 'operator', 'why': 'wait'})
            assert snoozed['ok'] and snoozed['due_at'] > 0
            due_rows = await rpc('tasks.list', {'due_filter': 'due_now'})
            assert [row['id'] for row in due_rows] == [second['task_id']]
            assert due_rows[0]['source_root_state'] == 'unresolved'
            assert await rpc('tasks.complete', {'task_id': task_id, 'actor': 'human', 'why': 'Handled personally', 'note': 'Done'}) == {'ok': True}
            closed = await rpc('tasks.get', {'task_id': task_id})
            assert closed['completed_at'] and closed['close_actor'] == 'human'
            assert closed['sources']['closes'][-1]['why'] == 'Handled personally'
            closed_snapshot = snapshot(db)
            stale = dict(payload, title='Stale overwrite', reason='Incorrect stale view', sources={'thread_id': 'wrong-thread'})
            refusal = await rpc('tasks.create', stale)
            assert refusal['ok'] is False and refusal['closed'] is True
            assert refusal['task_id'] == task_id and refusal['close_actor'] == 'human'
            assert snapshot(db) == closed_snapshot
            assert (await rpc('tasks.snooze', {'task_id': task_id, 'days': 2}))['ok'] is False
            assert snapshot(db) == closed_snapshot
            assert await rpc('tasks.reopen', {'task_id': task_id}) == {'ok': True}
            reopened = await rpc('tasks.get', {'task_id': task_id})
            assert reopened['completed_at'] is None and reopened['title'] == payload['title']
            assert reopened['sources']['closes'] == closed['sources']['closes']
            assert reopened['sources']['snoozes'] == closed['sources']['snoozes']
            after = snapshot(db)
            assert {key: value for key, value in after.items() if key != task_id} == {
                key: value for key, value in unrelated_before.items() if key != task_id
            }
        finally:
            if socket:
                await socket.close()
            if process.returncode is None:
                process.terminate()
            await asyncio.wait_for(process.wait(), 10)


@pytest.mark.parametrize('transport', ['stdio', 'websocket'])
def test_task_contract_across_production_transports(transport, tmp_path):
    asyncio.run(exercise(transport, tmp_path))


@pytest.mark.parametrize('session_state', ['missing', 'foreign'])
def test_email_task_listing_refuses_unadmitted_session_without_mutation(tmp_path, session_state):
    script = FIXTURE_BOOTSTRAP + r'''
from zylch.auth import clear_session, set_session
from zylch.rpc.dispatch import dispatch_raw
from zylch.storage.storage import Storage
store = Storage.get_instance()
owner = 'alice@example.test'
store.store_task_item(owner, {
    'event_type': 'email', 'event_id': 'unresolved-source',
    'contact_email': 'fixture@example.test', 'title': 'Answer fixture',
    'action_required': True,
})
before = repr(store.get_task_items(owner, include_completed=True))
if os.environ['TEST_SESSION_STATE'] == 'missing':
    clear_session()
else:
    set_session('bob', 'bob@example.test', 'fixture:bob', int(time.time() * 1000) + 3600000)
async def check():
    for method in ('tasks.list', 'operator.rules.list'):
        response = await dispatch_raw(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {},
        }), lambda *_: None)
        assert response['error']['code'] == -32060, response
        assert repr(store.get_task_items(owner, include_completed=True)) == before
    print(json.dumps({'typed_refusals': 2, 'task_mutations': 0}), flush=True)
asyncio.run(check())
'''
    environment = fixture_environment('dispatch', tmp_path)
    environment['TEST_SESSION_STATE'] = session_state
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {'typed_refusals': 2, 'task_mutations': 0}


@pytest.mark.asyncio
async def test_task_assignment_refusal_redacts_untrusted_exception_text(monkeypatch):
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.rpc.methods import METHODS
    from zylch.services.task_assignment_types import AssignmentError

    async def fail(_params, _notify):
        raise AssignmentError('private-source-material')

    monkeypatch.setitem(METHODS, 'tasks.list', fail)
    response = await dispatch_raw(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'tasks.list', 'params': {},
    }), lambda *_: None)
    assert response['error'] == {'code': -32060, 'message': 'Task source authority is unavailable'}
    assert 'private-source-material' not in repr(response)
