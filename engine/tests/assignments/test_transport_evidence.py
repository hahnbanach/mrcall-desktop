"""Production stdio frame and authenticated WebSocket assignment lifecycle."""

import asyncio
import io
import json

import pytest

from mail_fixture import MailFixture, ROOT


@pytest.mark.parametrize("transport", ["stdio", "websocket"])
def test_actual_transport_lifecycle(env, monkeypatch, transport):
    mail = MailFixture(monkeypatch)

    async def journey():
        from zylch.rpc import server, server_ws
        from websockets.asyncio.server import serve
        from websockets.asyncio.client import connect
        from contextlib import AsyncExitStack

        counter = 0
        output = io.StringIO()
        monkeypatch.setattr(server, "_REAL_STDOUT", output)
        async with AsyncExitStack() as stack:
            socket = None
            if transport == "websocket":
                listener = await stack.enter_async_context(
                    serve(
                        server_ws._handle_connection,
                        "127.0.0.1",
                        0,
                        process_request=server_ws._process_request,
                    )
                )
                address = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
                with pytest.raises(Exception):
                    await connect(
                        address, additional_headers={"Authorization": "Bearer fixture:bob"}
                    )
                socket = await stack.enter_async_context(
                    connect(address, additional_headers={"Authorization": "Bearer fixture:alice"})
                )

            async def rpc(method, **params):
                nonlocal counter
                counter += 1
                raw = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": counter,
                        "method": "tasks.assignment." + method,
                        "params": params,
                    }
                )
                if socket:
                    await socket.send(raw)
                    response = json.loads(await asyncio.wait_for(socket.recv(), 10))
                else:
                    await server._handle_request(raw + "\n")
                    response = json.loads(output.getvalue().splitlines()[-1])
                assert response["id"] == counter
                return response

            response = await rpc("reply_evidence", source_id=mail.reply_id, thread_key=ROOT)
            assert response["result"]["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
            intent = (
                await rpc(
                    "preview",
                    operation="assign",
                    thread_key=ROOT,
                    expected_revision=0,
                    assignee_uid="bob",
                )
            )["result"]
            assert "error" in await rpc("commit", intent=intent, grant={"approved": True})
            receipt = (await rpc("commit", intent=intent, grant=env.sign(intent)))["result"]
            assert receipt["acknowledged"] and receipt["basis"] == "explicit_manual"
            projection = (await rpc("project", thread_key=ROOT))["result"]
            assert projection["state"] == "assigned" and projection["hold_auto_reply"]
            close = (
                await rpc(
                    "preview",
                    operation="close",
                    thread_key=ROOT,
                    expected_revision=1,
                    reason="Handled",
                    handled_ref="exact-ack",
                )
            )["result"]
            receipt = (await rpc("commit", intent=close, grant=env.sign(close)))["result"]
            assert receipt["state"] == "closed" and receipt["covered_inbound"]
            mail.add(
                "<transport-later@example.test>",
                "customer@example.test",
                "alice@example.test",
                reply=ROOT,
            )
            projection = (await rpc("project", thread_key=ROOT))["result"]
            assert projection["state"] == "later-inbound" and not projection["hold_auto_reply"]
            assert projection["task"]["state"] == "closed" and len(projection["events"]) == 2

    asyncio.run(journey())


class SocketMailFixture(MailFixture):
    def __init__(self, monkeypatch):
        super().__init__(monkeypatch)
        self.clients = []
        self.sockets = []

    def client(self, mailbox):
        import socket
        from zylch.email.imap_client import IMAPClient

        class Connection:
            def __init__(connection, owner):
                connection.owner = owner
                connection.sock, connection.remote = socket.socketpair()
                owner.sockets.extend([connection.sock, connection.remote])

            def __getattr__(connection, name):
                return getattr(connection.owner, name)

            def shutdown(connection):
                connection.sock.close()
                connection.remote.close()

            def logout(connection):
                connection.owner.closed += 1
                connection.shutdown()
                return "BYE", []

        client = IMAPClient(mailbox.address, "fixture-only")
        connection = Connection(self)
        client._conn = connection
        if hasattr(client, "_deadline_connection"):
            client._deadline_connection = connection
        self.clients.append(client)
        return client

    def assert_clean(self):
        assert self.clients
        assert all(client._conn is None for client in self.clients)
        assert all(sock.fileno() == -1 for sock in self.sockets)
        for client in self.clients:
            if hasattr(client, "_provider_deadline"):
                assert client._provider_deadline is None
                assert client._deadline_connection is None
                assert client._imap_lock.acquire(blocking=False)
                client._imap_lock.release()


@pytest.mark.parametrize("operation", ["reply", "snapshot"])
def test_socket_provider_cleanup_preserves_valid_evidence(env, monkeypatch, operation):
    from zylch.services import task_assignment_evidence as evidence

    mail = SocketMailFixture(monkeypatch)
    try:
        if operation == "reply":
            result = evidence.reply(mail.reply_id, ROOT)
            assert result["complete"] is True
            assert result["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE"
            assert result["source"] and result["digest"]
        else:
            result = evidence.snapshot(ROOT)
            assert result["covered_inbound"] and result["digest"]
    finally:
        mail.assert_clean()


@pytest.mark.parametrize("operation", ["reply", "snapshot"])
@pytest.mark.parametrize("failure", ["fetch", "metadata", "expiry"])
def test_socket_provider_cleanup_keeps_failures_closed(env, monkeypatch, operation, failure):
    import time
    from zylch.email.imap_client import IMAPError
    from zylch.services import task_assignment_evidence as evidence
    from zylch.services.task_assignment_types import AssignmentError

    target = evidence.reply if operation == "reply" else evidence.snapshot
    mail = SocketMailFixture(monkeypatch)
    kwargs = {}
    if failure == "fetch":
        mail.fail_fetch = True
    elif failure == "metadata":
        from email import message_from_bytes

        folder = '"Sent"' if operation == "reply" else '"Archive"'
        uid, raw = next(iter(mail.messages[folder].items()))
        message = message_from_bytes(raw)
        message.replace_header("From", "intruder@example.test")
        mail.messages[folder][uid] = message.as_bytes()
    else:
        original_uid = mail.uid

        def expire_fetch(command, *args):
            if command == "FETCH":
                time.sleep(0.30)
            return original_uid(command, *args)

        monkeypatch.setattr(mail, "uid", expire_fetch)
        kwargs["deadline"] = time.monotonic() + 0.25
    try:
        if operation == "reply":
            result = target(mail.reply_id, ROOT, **kwargs)
            assert result["complete"] is False
            assert result["judgement"] == "UNKNOWN"
            assert result["reason"] == "SOURCE_UNAVAILABLE"
            assert result["source"] is None and result["digest"] is None
        else:
            with pytest.raises((AssignmentError, IMAPError)):
                target(ROOT, **kwargs)
    finally:
        mail.assert_clean()
