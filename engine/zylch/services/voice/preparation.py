"""Validate the isolated call's company binding before carrier admission."""

import asyncio

from zylch.services.voice.agent_config import require_binding
from zylch.services.voice.business_binding import ExpectedBusiness, verify_business


async def prepare_call(snapshot, expected: ExpectedBusiness | None = None,
                       previous_version: int | None = None):
    try:
        async with asyncio.timeout(15):
            await asyncio.to_thread(require_binding, snapshot.binding)
            if expected is not None:
                if snapshot.binding.owner_uid != expected.owner_uid:
                    raise ValueError("wrong profile")
                return await verify_business(expected, previous_version)
    except Exception:
        raise ValueError("Voice call preparation unavailable") from None
