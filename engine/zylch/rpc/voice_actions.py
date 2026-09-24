"""Operator settings on the existing owner-authenticated RPC transport."""

import asyncio

from zylch.services.voice import agent_config


async def config_get(params, notify):
    """voice.config.get() -> bound settings; credentials are never returned."""
    return await asyncio.to_thread(agent_config.get_config)


async def config_update(params, notify):
    """voice.config.update(owner_uid, space_id, expected_revision, config) -> settings."""
    return await asyncio.to_thread(agent_config.update_config, **params)


async def status(params, notify):
    """voice.status() -> configuration state and M2 runtime boundary."""
    saved = await asyncio.to_thread(agent_config.get_config)
    return {
        "owner_uid": saved["owner_uid"],
        "space_id": saved["space_id"],
        "revision": saved["revision"],
        "binding_valid": saved["binding_valid"],
        "configured_enabled": saved["config"]["enabled"],
        "runtime": "not_integrated",
        "calls_available": False,
    }


METHODS = {
    "voice.config.get": config_get,
    "voice.config.update": config_update,
    "voice.status": status,
}
