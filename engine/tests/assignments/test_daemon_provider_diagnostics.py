import asyncio
import base64
import shutil
import uuid
from contextlib import AsyncExitStack
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re
import socket
import smtplib
import ssl
import time

import pytest

from mail_fixture import MailFixture, ROOT
from test_provider_diagnostics import ProtocolPeer


class MailProtocolPeer(ProtocolPeer):
    def __init__(self, directory, mode, mail):
        self.mail = mail
        self.examinations = 0
        super().__init__(directory, mode)

    def run(self):
        try:
            connection, _ = self.listener.accept()
            with self.server_context.wrap_socket(connection, server_side=True) as stream:
                stream.sendall(b'* OK fixture ready\r\n')
                reader = stream.makefile('rb')
                try:
                    while line := reader.readline():
                        tag, command, *arguments = line.rstrip().split(b' ', 2)
                        self.commands.append(command)
                        if command == b'CAPABILITY':
                            stream.sendall(b'* CAPABILITY IMAP4rev1\r\n')
                        elif command in {b'LOGIN', b'NOOP'}:
                            pass
                        elif command == b'LIST':
                            stream.sendall(b'* LIST (\\Sent) "/" "Sent"\r\n* LIST (\\Archive) "/" "Archive"\r\n')
                        elif command == b'EXAMINE':
                            self.examinations += 1
                            if self.mode in {'stall', 'partial'} or self.mode == 'late_stall' and self.examinations > 1:
                                if self.mode == 'partial':
                                    stream.sendall(b'* 0 EXISTS\r\n')
                                reader.read()
                                break
                            folder = b' '.join(arguments).decode().strip('"')
                            self.mail.selected = 'INBOX' if folder == 'INBOX' else '"' + folder + '"'
                            size = len(self.mail.messages[self.mail.selected])
                            stream.sendall(f'* {size} EXISTS\r\n* OK [UIDVALIDITY {self.mail.uidvalidity}] stable\r\n* OK [UIDNEXT {self.mail.next_uid}] stable\r\n'.encode())
                        elif command == b'UID':
                            verb, rest = b' '.join(arguments).split(b' ', 1)
                            if verb == b'SEARCH':
                                _, values = self.mail.uid('SEARCH', None, rest.decode())
                                stream.sendall(b'* SEARCH ' + values[0] + b'\r\n')
                            elif verb == b'FETCH':
                                uids, fields = rest.decode().split(' ', 1)
                                _, values = self.mail.uid('FETCH', uids, fields)
                                for prefix, payload in values:
                                    stream.sendall(b'* ' + prefix.replace(b' ', b' FETCH ', 1) + b'\r\n' + payload + b')\r\n')
                            else:
                                raise AssertionError('unexpected UID command')
                        else:
                            raise AssertionError('unexpected protocol command')
                        stream.sendall(tag + b' OK done\r\n')
                finally:
                    reader.close()
        finally:
            self.listener.close()
            self.done.set()


@pytest.mark.parametrize('mode', ['stall', 'partial', 'late_stall', 'success'])
def test_actual_daemon_native_provider_failure(env, monkeypatch, tmp_path, mode, request):
    from zylch.email import mailboxes
    from zylch.email.imap_client import IMAPClient
    from zylch.rpc import server_ws, firebase_auth
    from zylch.services import task_assignment_projection as projection
    from zylch.storage import database as db
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect

    issuer = firebase_auth.verify_firebase_id_token
    claims = base64.urlsafe_b64encode(json.dumps({'sub': 'alice', 'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
    fixture_token = 'fixture.' + claims + '.offline'
    monkeypatch.setattr(firebase_auth, 'verify_firebase_id_token', lambda token: issuer('fixture:alice') if token == fixture_token else issuer(token))
    mail = MailFixture(monkeypatch)
    peer = MailProtocolPeer(tmp_path, mode, mail)
    native = imaplib.IMAP4_SSL
    class TrustedSSL(native):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, ssl_context=peer.client_context, **kwargs)
    monkeypatch.setattr(imaplib, 'IMAP4_SSL', TrustedSSL)
    allowed_ports = {peer.port}
    original_connect = socket.socket.connect
    forbidden = []
    def connect_only_fixture(sock, address):
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'} or address[1] not in allowed_ports:
            forbidden.append('network')
            raise AssertionError('External network refused by fixture')
        return original_connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect_only_fixture)
    def refuse_effect(*args, **kwargs):
        forbidden.append('effect')
        raise AssertionError('Model or SMTP refused by fixture')
    monkeypatch.setattr(smtplib, 'SMTP', refuse_effect)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', refuse_effect)
    from zylch.llm import client as llm_client
    monkeypatch.setattr(llm_client, 'make_llm_client', refuse_effect)
    clients = []
    def client(box):
        value = IMAPClient(box.address, 'PRIVATE_PASSWORD_SENTINEL', imap_host='127.0.0.1', imap_port=peer.port)
        clients.append(value)
        return value
    monkeypatch.setattr(mailboxes, 'build_imap_client', client)
    monkeypatch.setattr(projection, '_read_deadline', lambda started: started + 3)
    baseline = db.get_engine().connect()
    before = baseline.exec_driver_sql('SELECT * FROM emails ORDER BY id').fetchall()
    baseline.close()
    trace = uuid.uuid4().hex
    from sqlalchemy import event, inspect
    def business_snapshot(engine):
        with engine.connect() as connection:
            return {table: sorted(repr(tuple(row)) for row in connection.exec_driver_sql('SELECT * FROM "' + table.replace('"', '""') + '"').fetchall()) for table in inspect(engine).get_table_names()}
    engines = [db.get_engine(), env.memory]
    business_before = [business_snapshot(engine) for engine in engines]
    def forbid_business_write(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
            forbidden.append('business_write')
            raise AssertionError('Business write refused by fixture')
    for engine in engines:
        event.listen(engine, 'before_cursor_execute', forbid_business_write)
        request.addfinalizer(lambda engine=engine: event.remove(engine, 'before_cursor_execute', forbid_business_write))

    async def journey():
        async with AsyncExitStack() as stack:
            listener = await stack.enter_async_context(serve(server_ws._handle_connection, '127.0.0.1', 0, process_request=server_ws._process_request))
            allowed_ports.add(listener.sockets[0].getsockname()[1])
            address = f'ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}'
            with pytest.raises(Exception) as rejected:
                await connect(address, additional_headers={'Authorization': 'Bearer fixture:bob'})
            assert getattr(getattr(rejected.value, 'response', None), 'status_code', None) == 403
            ws = await stack.enter_async_context(connect(address, additional_headers={'Authorization': 'Bearer fixture:alice'}))
            async def call(method, params, number):
                await ws.send(json.dumps({'jsonrpc': '2.0', 'id': number, 'method': method, 'params': params, 'diagnostics': {'version': 1, 'trace_id': trace}}))
                response = json.loads(await asyncio.wait_for(ws.recv(), 8))
                assert response['id'] == number
                assert 'error' not in response, response
                return response['result']
            result = await call('tasks.assignment.project', {'thread_key': ROOT}, 1)
            rows, cursor = [], None
            for number in range(2, 100):
                params = {'trace_id': trace, 'limit': 5}
                if cursor:
                    params['cursor'] = cursor
                page = await call('diagnostics.events', params, number)
                rows.extend(page['events'])
                cursor = page.get('next_cursor')
                if not cursor:
                    break
            else:
                raise AssertionError('diagnostic paging did not terminate')
            ordinary = None
            kernel_root = os.environ.get('MRCALL_TEST_KERNEL_ROOT')
            kernel_python = os.environ.get('MRCALL_TEST_KERNEL_PYTHON')
            if kernel_root and kernel_python:
                slug = 'provider-' + uuid.uuid4().hex[:12]
                state = Path.home() / ('.' + slug + '-cs')
                manifest = tmp_path / 'manifest.toml'
                manifest.write_text('[company]\nslug=' + json.dumps(slug) + '\n[engine]\nowner_uid="alice"\nws_url=' + json.dumps(address) + '\n')
                cache = tmp_path / 'fixture-token.json'
                cache.write_text(json.dumps({'uid': 'alice', 'id_token': fixture_token}))
                cache.chmod(0o600)
                child_env = {**os.environ, 'CS_MANIFEST': str(manifest), 'TOKEN_CACHE_PATH': str(cache), 'FIREBASE_WEB_API_KEY': 'offline-fixture', 'PYTHONPATH': kernel_root}
                async def cli(*arguments):
                    child = await asyncio.create_subprocess_exec(kernel_python, '-m', 'cs', *arguments, cwd=tmp_path, env=child_env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await asyncio.wait_for(child.communicate(), 15)
                    assert child.returncode in (0, 1), (child.returncode, stderr.decode())
                    return child.returncode, json.loads(stdout)
                try:
                    pages, cursor = [], None
                    for _ in range(100):
                        arguments = ['logs', 'trace', '--trace-id', trace, '--limit', '5', '--json']
                        if cursor:
                            arguments += ['--cursor', cursor]
                        code, page = await cli(*arguments)
                        assert code == 0, page
                        pages.append(page)
                        remote = page['remote']
                        assert 'events' in remote, remote
                        cursor = remote.get('next_cursor')
                        if not cursor:
                            break
                    else:
                        raise AssertionError('ordinary CLI paging did not terminate')
                    observed = [event for page in pages for event in page['remote']['events']]
                    assert all("level" not in event for event in rows)
                    assert [{key: value for key, value in event.items() if key != "level"} for event in observed] == rows
                    assert all(event["level"] in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} for event in observed)
                    monitor = tmp_path / 'monitor'
                    configuration = tmp_path / 'monitor.json'
                    configuration.write_text(json.dumps({'monitor_id': 'b' * 32, 'owner_uid': 'alice', 'state_dir': str(monitor), 'mode': 'filesystem', 'scan_seconds': 600, 'expected_start_utc': int(time.time()), 'components': [{'id': 'engine', 'kind': 'engine', 'local_root': str(Path(os.environ['ZYLCH_PROFILE_DIR']) / 'observability')}]}))
                    configuration.chmod(0o600)
                    monitor_code, monitor_result = await cli('monitor', 'once', '--config', str(configuration))
                    inbox = json.loads((monitor / 'problems.json').read_text())
                    if mode != 'success':
                        assert any(problem['evidence'].get('provider_diagnostic', {}).get('command') == 'EXAMINE' for problem in inbox['problems'])
                    assert (monitor / 'problems.json').stat().st_mode & 0o777 == 0o600
                    ordinary = {'cli_pages': pages, 'monitor_exit': monitor_code, 'monitor_result': monitor_result, 'inbox': inbox}
                finally:
                    if state.exists():
                        shutil.rmtree(state)
            return result, rows, ordinary

    try:
        result, events, ordinary = asyncio.run(journey())
    finally:
        for value in clients:
            value._discard_connection(value._conn)
            value._conn = None
    assert peer.done.wait(2)
    peer.thread.join(1)
    assert not peer.thread.is_alive()
    with db.get_engine().connect() as connection:
        assert connection.exec_driver_sql('SELECT * FROM emails ORDER BY id').fetchall() == before
    assert clients
    assert not forbidden
    assert [business_snapshot(engine) for engine in engines] == business_before
    assert b'LOGOUT' not in peer.commands
    assert all(client._conn is None and client._provider_deadline is None for client in clients)
    safe = json.dumps(events)
    assert 'PRIVATE_' not in safe and ROOT not in safe
    start = next(event for event in events if event.get('command') == 'assignment.projection.start')
    assert start['deadline_seconds'] == 3
    typed = [event for event in events if 'provider_diagnostic' in event]
    assert typed
    if mode == 'success':
        assert result['state'] == 'needs-assignment' and result['hold_auto_reply']
        assert not any(event['provider_diagnostic']['phase'] == 'failed' for event in typed)
    else:
        assert result['state'] == 'unknown' and result['complete'] is False and result['hold_auto_reply']
        terminal = next(event for event in events if event.get('command') == 'assignment.projection.terminal')
        fault = terminal['provider_diagnostic']
        assert fault['command'] == 'EXAMINE' and fault['phase'] == 'failed'
        assert fault['inbound_progress_count'] > 0 if mode == 'partial' else fault['inbound_progress_count'] == 0
        assert any(event['provider_diagnostic']['phase'] == 'fired' for event in typed) or fault['cause'] == 'deadline'
    destination = os.environ.get('MRCALL_DAEMON_DIAGNOSTIC_EVIDENCE')
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.chmod(0o700)
        private = target / (mode + '.json')
        temporary = target / (uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(json.dumps({'result': {'state': result['state'], 'complete': result['complete'], 'hold_auto_reply': result['hold_auto_reply']}, 'events': events, 'ordinary': ordinary, 'protocol_commands': [verb.decode() for verb in peer.commands]}, indent=2))
        os.replace(temporary, private)
        assert private.stat().st_mode & 0o777 == 0o600
        if ordinary is not None:
            anonymous = target / ('ordinary-' + trace + '.json')
            fd = os.open(anonymous, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as output:
                output.write(json.dumps({'cli_pages': ordinary['cli_pages'], 'inbox': ordinary['inbox']}, indent=2))
            assert anonymous.stat().st_mode & 0o777 == 0o600
