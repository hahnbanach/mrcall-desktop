"""Validate the isolated call's company binding before carrier admission."""

import asyncio

from zylch.services.voice.agent_config import require_binding


async def prepare_call(snapshot):
    try:
        async with asyncio.timeout(15):
            await asyncio.to_thread(require_binding, snapshot.binding)
    except Exception:
        raise ValueError("Voice call preparation unavailable") from None
