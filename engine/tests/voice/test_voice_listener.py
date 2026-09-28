"""Opt-in listener lives and shuts down with RPC; bootstrap cannot load ambient profiles."""

import asyncio
import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.voice.test_conversation import until
from tests.voice.test_engine_runtime import VoiceTransport
from tests.voice.test_agent_config import save
from tests.voice.test_vonage import CARRIER, signed
from tests.voice.helpers import config_for, incoming
from tests.voice.m2_fixture import NUMBER
from zylch.rpc import server_ws
from zylch.services.voice import listener, engine_runtime


def test_company_notes_refresh_requires_remote_business_check(monkeypatch, tmp_path):
    snapshot = object()
    config = SimpleNamespace(
        test_number="+390250552776", profile=tmp_path, company_knowledge_enabled=True
    )
    runtime = SimpleNamespace(_prepare=AsyncMock(side_effect=ValueError("wrong business")))
    convert = AsyncMock()
    monkeypatch.setattr(listener, "snapshot_for_call", lambda _: snapshot)
    monkeypatch.setattr(listener, "prepare_company_notes", convert)

    async def refused():
        with pytest.raises(ValueError, match="wrong business"):
            await listener.refresh_company_notes_once(runtime, config)

    asyncio.run(refused())
    convert.assert_not_awaited()
    runtime._prepare = AsyncMock(return_value=None)
    asyncio.run(listener.refresh_company_notes_once(runtime, config))
    convert.assert_awaited_once_with(tmp_path, snapshot)
    config.company_knowledge_enabled = False
    convert.reset_mock()
    assert asyncio.run(listener.refresh_company_notes_once(runtime, config)) is None
    convert.assert_not_awaited()


def test_listener_shares_daemon_lifecycle(fixture_db, tmp_path, monkeypatch):
    save()
    config = config_for(tmp_path, test_number=NUMBER, **CARRIER)
    transport = VoiceTransport()
    transport.closed = False

    def verify(body, headers):
        import json

        return json.loads(body)

    async def close():
        transport.closed = True

    transport.verify = verify
    transport.close = close
    monkeypatch.setattr(listener, "LiveTransport", lambda _: transport)

    async def prepare(snapshot):
        return None

    monkeypatch.setattr(engine_runtime, "prepare_call", prepare)
    monkeypatch.setattr(server_ws, "_auto_update_loop", lambda: pytest.fail("automatic work"))
    monkeypatch.setattr(server_ws, "_whatsapp_refresh_loop", lambda: pytest.fail("WhatsApp"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    async def scenario():
        task = asyncio.create_task(
            server_ws.serve_ws(
                host="127.0.0.1",
                port=0,
                warmup=False,
                background=False,
                voice_listener=listener.voice_listener(config, port),
            )
        )
        try:
            await until(lambda: listener.active_runtime is not None)
            runtime = listener.active_runtime
            transport.ledger = runtime.ledger
            assert runtime.ready
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
                # Provider HTTP listener exposes neither account nor operator RPC.
                assert (await http.post("/voice.config.update", json={})).status_code == 404
                import json

                body = json.dumps(
                    {"to": NUMBER, "from": "+393330000001", "uuid": "lifecycle"}
                ).encode()
                ncco = (
                    await http.post("/vonage/answer", content=body, headers=signed(body))
                ).json()
                token = ncco[0]["endpoint"][0]["headers"]["Mrcall-Smoke-Attempt"]
                event = incoming(to=config.sip_to_uri)
                event["data"]["sip_headers"].append(
                    {"name": "X-Mrcall-Smoke-Attempt", "value": token}
                )
                assert (await http.post("/openai/live", json=event)).status_code == 200
                await transport.entered.wait()
                call = runtime.call
                runtime.finalization_timeout = 0.01
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert call.conversation.closed
                assert transport.controls[-1][1] == "hangup"
                assert runtime.ledger.rows()[0]["state"] == "stopped"
                assert transport.closed and listener.active_runtime is None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "isolated_m3", Path(__file__).parents[2] / "scripts/voice_engine_isolated.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_scrubs_ambient_configuration(tmp_path, monkeypatch):
    profile = tmp_path / "fixture-uid"
    profile.mkdir()
    (profile / ".env").write_text(
        "VOICE_ENGINE_ISOLATED_PROFILE=fixture-uid\nVOICE_SMOKE_TEST_PROFILE=fixture-uid\nOWNER_ID=fixture-uid\nLLM_PROVIDER=mrcall\n"
    )
    (profile / "voice-engine.db").touch()
    import os

    before = dict(os.environ)
    try:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "personal-sentinel")
        bootstrap().configure(profile)
        assert "ANTHROPIC_API_KEY" not in os.environ
        assert os.environ["ZYLCH_DB_PATH"] == str(profile / "voice-engine.db")
        assert os.environ["MEMORY_DB_DIR"] == str(profile / "memory")
    finally:
        os.environ.clear()
        os.environ.update(before)
    (profile / "zylch.db").touch()
    with pytest.raises(ValueError, match="Populated"):
        bootstrap().configure(profile)
