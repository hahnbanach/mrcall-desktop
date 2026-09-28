"""Opt-in provider listener owned by the isolated engine WebSocket lifecycle."""

import logging
from contextlib import asynccontextmanager

from aiohttp import web

from zylch.storage.voice_smoke import SmokeLedger

from .engine_runtime import EngineVoiceRuntime
from .live_sip_smoke import create_app
from .smoke_transport import LiveTransport

active_runtime = None


@asynccontextmanager
async def voice_listener(config, port):
    global active_runtime
    for name in (
        "openai",
        "httpx",
        "httpcore",
        "httpx2",
        "httpcore2",
        "aiohttp",
        "zylch.auth.refresh",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    ledger = SmokeLedger(
        config.profile / "voice-smoke.db",
        config.policy_id,
        config.reservation_microusd,
        config.max_calls,
        unlimited=config.unlimited,
    )
    transport = LiveTransport(config)
    runtime = EngineVoiceRuntime(config, ledger, transport)
    runner = None
    try:
        await runtime.recover()
        # Loads memory/config and prepares credentials even with no RPC client.
        await runtime.prepare_carrier()
        app = create_app(runtime, transport.verify)

        async def health(_request):
            return web.json_response(
                {
                    "runtime": "engine_listener",
                    "calls_available": await runtime.available(),
                    "test_limits": "unlimited" if config.unlimited else "bounded",
                }
            )

        app.router.add_get("/healthz", health)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        active_runtime = runtime
        yield runtime
    finally:
        active_runtime = None
        await runtime.shutdown()
        if runner:
            await runner.cleanup()
        await transport.close()
        ledger.close()
