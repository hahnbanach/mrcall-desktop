"""Opt-in provider listener owned by the isolated engine WebSocket lifecycle."""

import asyncio
import logging
import inspect
from contextlib import asynccontextmanager

from aiohttp import web

from zylch.storage.voice_smoke import SmokeLedger
from zylch.storage.voice_production import ProductionVoiceLedger

from .engine_runtime import EngineVoiceRuntime
from .agent_config import snapshot_for_call
from .company_notes import prepare_company_notes
from .live_sip_smoke import create_app
from .smoke_transport import LiveTransport

active_runtime = None


async def refresh_company_notes_once(runtime, config):
    """Verify the remote business before an offline note may reach the LLM."""
    snapshot = await asyncio.to_thread(snapshot_for_call, config.test_number)
    await runtime._prepare(snapshot)
    return await prepare_company_notes(config.profile, snapshot)


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
    production = hasattr(config, "expected_business")
    ledger = (
        ProductionVoiceLedger(
            config.profile / "voice-production.db", config.policy_id,
            config.reservation_microusd,
            config.voice_per_minute_microusd + config.carrier_per_minute_microusd,
        )
        if production else SmokeLedger(
            config.profile / "voice-smoke.db", config.policy_id,
            config.reservation_microusd, config.max_calls, unlimited=config.unlimited,
        )
    )
    transport = LiveTransport(config)
    runtime = EngineVoiceRuntime(config, ledger, transport)
    if production:
        logging.getLogger(__name__).info(
            "[voice] production runtime module=%s",
            inspect.getfile(EngineVoiceRuntime),
        )
    runner = None
    notes_task = None
    try:
        if production:
            runtime.sessions.recover(ledger.rows())
        await runtime.recover()
        # Loads memory/config and prepares credentials even with no RPC client.
        prepared = await runtime.prepare_carrier()
        if production and prepared is None:
            raise RuntimeError("Production voice admission is not ready")
        app = create_app(runtime, transport.verify)

        async def health(_request):
            return web.json_response(
                {
                    "runtime": "engine_listener",
                    "calls_available": await runtime.available(),
                    "test_limits": None if production else (
                        "unlimited" if config.unlimited else "bounded"
                    ),
                }
            )

        app.router.add_get("/healthz", health)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        active_runtime = runtime
        if production:
            async def refresh_notes():
                while True:
                    try:
                        result = await refresh_company_notes_once(runtime, config)
                        logging.getLogger(__name__).info(
                            "[voice] company notes preparation status=%s", result.status
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "[voice] company notes preparation unavailable"
                        )
                    await asyncio.sleep(60)

            notes_task = asyncio.create_task(refresh_notes())
        yield runtime
    finally:
        active_runtime = None
        if notes_task:
            notes_task.cancel()
            await asyncio.gather(notes_task, return_exceptions=True)
        await runtime.shutdown()
        if runner:
            await runner.cleanup()
        await transport.close()
        ledger.close()
        if production:
            runtime.sessions.close()
