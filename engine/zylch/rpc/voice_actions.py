"""Operator settings on the existing owner-authenticated RPC transport."""

import asyncio
import os

from zylch.services.voice import agent_config
from zylch.services.voice.business_binding import ExpectedBusiness, verify_business


async def config_get(params, notify):
    """voice.config.get() -> bound settings; credentials are never returned."""
    return await asyncio.to_thread(agent_config.get_config)


async def config_update(params, notify):
    """voice.config.update(owner_uid, space_id, expected_revision, config) -> settings."""
    proposed = agent_config.parse_config(params.get("config"))
    if proposed.policy == "production" and proposed.enabled:
        expected = ExpectedBusiness(
            os.environ.get("VOICE_PRODUCTION_BUSINESS_ID", ""),
            os.environ.get("VOICE_PRODUCTION_OWNER_UID", ""),
            os.environ.get("VOICE_PRODUCTION_NUMBER", ""),
        )
        if not all((expected.business_id, expected.owner_uid, expected.called_number)):
            raise agent_config.VoiceError(-32061, "Production voice binding is unavailable")
        try:
            await verify_business(expected)
        except ValueError:
            raise agent_config.VoiceError(
                -32061, "Production voice binding is unavailable"
            ) from None
    return await asyncio.to_thread(agent_config.update_config, **params)


async def status(params, notify):
    """voice.status() -> configuration state and opt-in runtime availability."""
    saved = await asyncio.to_thread(agent_config.get_config)
    import sys

    listener = sys.modules.get("zylch.services.voice.listener")
    runtime = getattr(listener, "active_runtime", None)
    return {
        "owner_uid": saved["owner_uid"],
        "space_id": saved["space_id"],
        "revision": saved["revision"],
        "binding_valid": saved["binding_valid"],
        "configured_enabled": saved["config"]["enabled"],
        "runtime": "engine_listener" if runtime else "not_integrated",
        "calls_available": await runtime.available() if runtime else False,
    }


METHODS = {
    "voice.config.get": config_get,
    "voice.config.update": config_update,
    "voice.status": status,
}
