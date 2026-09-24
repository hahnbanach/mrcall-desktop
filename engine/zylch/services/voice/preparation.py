"""Off-loop cold-start credentials and memory preparation, independent of operator RPC."""

import asyncio
import logging

from zylch.auth.refresh import ensure_fresh_session
from zylch.auth.session import get_session
from zylch.llm import make_llm_client
from zylch.llm.budget import budget_snapshot
from zylch.llm.model_policy import resolve_provider
from zylch.services.voice.agent_config import require_binding

logger = logging.getLogger(__name__)


async def prepare_client(snapshot):
    def prepare():
        require_binding(snapshot.binding)
        owner = snapshot.binding.owner_uid
        from zylch.llm.model_policy import (
            profile_values,
            isolated_voice_profile,
            policy_fingerprint,
        )

        values = profile_values()
        voice_provider = values.get("VOICE_ENGINE_PROVIDER")
        if voice_provider:
            if voice_provider != "openai" or not isolated_voice_profile(values):
                raise ValueError("Unsupported voice provider configuration")
            from zylch.llm.client import LLMClient

            if budget_snapshot(owner)["paused"]:
                raise ValueError("Voice engine budget unavailable")
            client = LLMClient(
                "openai_voice",
                api_key=values.get("OPENAI_API_KEY"),
                openai_project=values.get("OPENAI_PROJECT_ID"),
            )
            client._saved_policy_fingerprint = policy_fingerprint(values)
            client._client.ready()
            return client
        if resolve_provider() == "mrcall":
            if not ensure_fresh_session(owner):
                raise ValueError("Voice credentials unavailable")
            session = get_session()
            if session is None or session.uid != owner or session.is_expired():
                raise ValueError("Voice credentials unavailable")
        state = budget_snapshot(owner)
        if state["paused"]:
            raise ValueError("Voice engine budget unavailable")
        client = make_llm_client()
        if client.transport == "proxy":
            from zylch.llm.bounded_proxy import validate_quote

            # A free quote verifies account/business/model compatibility before
            # carrier admission. Never execute inference or reserve a paid hold.
            request = {
                "model": client.model,
                "messages": [{"role": "user", "content": "Voice readiness"}],
                "max_tokens": 1,
            }
            quote = client._client.quote(request)
            validate_quote(request, quote, owner)
        return client

    try:
        async with asyncio.timeout(15):
            client = await asyncio.to_thread(prepare)
        logger.debug("[voice] engine client prepared")
        return client
    except Exception:
        raise ValueError("Voice engine preparation unavailable") from None
