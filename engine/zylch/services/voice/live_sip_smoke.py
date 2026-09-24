"""Opt-in M1 HTTP runner. Provider webhook only; no owner RPC surface."""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web
from openai import InvalidWebhookSignatureError

from zylch.storage.voice_smoke import SmokeLedger

from .smoke_config import SmokeConfig
from .smoke_runtime import SmokeRuntime
from .smoke_transport import LiveTransport
from .smoke_vonage import add_vonage_routes


def create_app(runtime: SmokeRuntime, verify) -> web.Application:
    async def webhook(request: web.Request) -> web.Response:
        try:
            async with asyncio.timeout(5):
                body = await request.read()
            # Small bounded payload, local signature verification, no network.
            event = verify(body, dict(request.headers))
        except (InvalidWebhookSignatureError, ValueError):
            return web.Response(status=400)
        except TimeoutError:
            return web.Response(status=408)
        try:
            runtime.incoming(event)
        except ValueError:
            return web.Response(status=422)
        except Exception:
            # No raw exception rendering: signed metadata still isn't safe to log.
            return web.Response(status=503)
        return web.Response(status=200)

    async def cleanup(_app: web.Application) -> None:
        await runtime.shutdown()

    app = web.Application(client_max_size=65536)
    app.router.add_post("/openai/live", webhook)
    add_vonage_routes(app, runtime)
    app.on_shutdown.append(cleanup)
    return app


def run_smoke_server(config: SmokeConfig, port: int) -> None:
    """Bind loopback only; supervise HTTPS routing outside this process."""
    # Suppress SDK internals too. Our own logs never contain request/response data.
    for name in ("openai", "httpx", "httpcore", "httpx2", "httpcore2", "aiohttp"):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    ledger = SmokeLedger(
        config.profile / "voice-smoke.db",
        config.policy_id,
        config.reservation_microusd,
        config.max_calls,
        unlimited=config.unlimited,
    )

    async def application() -> web.Application:
        transport = LiveTransport(config)
        runtime = SmokeRuntime(config, ledger, transport)
        try:
            await runtime.recover()
        except BaseException:
            await transport.close()
            raise
        app = create_app(runtime, transport.verify)

        async def close(_app: web.Application) -> None:
            await transport.close()

        app.on_cleanup.append(close)
        return app

    try:
        web.run_app(application(), host="127.0.0.1", port=port, access_log=None, print=None)
    finally:
        ledger.close()
