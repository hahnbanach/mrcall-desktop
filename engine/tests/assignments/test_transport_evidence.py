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
