"""Real signed HTTP requests and local WebSocket handshake; no paid services."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time

import httpx
from aiohttp.test_utils import TestClient, TestServer
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from zylch.services.voice import smoke_transport
from zylch.services.voice.live_sip_smoke import create_app
from zylch.services.voice.smoke_transport import LiveTransport

from .helpers import config_for, finished, incoming, setup


def signed(body, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    message = b"test_delivery." + timestamp.encode() + b"." + body
    digest = hmac.new(b"signing-test", message, hashlib.sha256).digest()
    return {
        "webhook-id": "test_delivery",
        "webhook-timestamp": timestamp,
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
        "Content-Type": "application/json",
    }


def test_real_sdk_signed_webhook_rejects_tampering_and_replay(tmp_path):
    async def scenario():
        config, ledger, fake, runtime = setup(tmp_path)
        verifier = LiveTransport(config)
        app = create_app(runtime, verifier.verify)
        async with TestClient(TestServer(app)) as client:
            body = json.dumps(incoming()).encode()
            assert (
                await client.post("/openai/live", data=body, headers=signed(body, 1))
            ).status == 400
            assert (
                await client.post("/openai/live", data=body + b" ", headers=signed(body))
            ).status == 400
            assert ledger.rows() == []
            fake.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 1}})
            response = await client.post("/openai/live", data=body, headers=signed(body))
            assert response.status == 200
            await finished(runtime)
            assert (
                await client.post("/openai/live", data=body, headers=signed(body))
            ).status == 200
            assert fake.accept_calls == ["sess_test"]
            assert (await client.post("/openai/live", data=b"x" * 70000)).status == 413
        await verifier.close()
        ledger.close()

    asyncio.run(scenario())


def test_control_contract_and_bodyless_hangup(tmp_path):
    async def scenario():
        transport = LiveTransport(config_for(tmp_path))
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200)

        await transport.http.aclose()
        transport.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        assert await transport.accept("live_test")
        assert await transport.control("live_test", "hangup")
        assert requests[0].url.path == "/v1/live/sessions/live_test/accept"
        session = json.loads(requests[0].content)["session"]
        assert session["model"] == "gpt-live-1"
        assert session["delegation"] == {"type": "client"}
        assert session["store"] is False
        assert requests[1].content == b""
        assert requests[0].headers["OpenAI-Project"] == "proj_test"
        await transport.close()

    asyncio.run(scenario())


def test_actual_websocket_does_not_log_authorization_or_frames(tmp_path, monkeypatch, caplog):
    async def scenario():
        transport = LiveTransport(config_for(tmp_path))
        caplog.set_level(logging.DEBUG)

        async def peer(ws):
            await ws.send(
                json.dumps(
                    {"type": "session.input_transcript.delta", "delta": "private-frame-sentinel"}
                )
            )
            await ws.close()

        # Silence the fake provider's own server log: we test the actual client log.
        async with serve(peer, "127.0.0.1", 0, logger=smoke_transport.WIRE_LOGGER) as server:
            port = server.sockets[0].getsockname()[1]

            def redirected(uri, **kwargs):
                assert uri == "wss://api.openai.com/v1/live/sessions/live_test/attach"
                assert kwargs["additional_headers"]["Authorization"] == "Bearer fake-review-key"
                return connect(f"ws://127.0.0.1:{port}", **kwargs)

            monkeypatch.setattr(smoke_transport, "connect", redirected)
            async with transport.attach("live_test") as ws:
                assert "private-frame-sentinel" in await ws.recv()
        assert "fake-review-key" not in caplog.text
        assert "private-frame-sentinel" not in caplog.text
        await transport.close()

    asyncio.run(scenario())
