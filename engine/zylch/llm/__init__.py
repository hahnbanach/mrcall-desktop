"""LLM abstraction layer.

Single provider (Anthropic), two transports (``direct`` BYOK and
``proxy`` MrCall credits). See :mod:`zylch.llm.client` for the
:class:`LLMClient` and the :func:`make_llm_client` factory most
callers use.
"""

import os
from typing import Optional

from .client import LLMClient, LLMResponse, TextBlock, ToolUseBlock, make_llm_client, try_make_llm_client


def routed_model(env_key: str) -> Optional[str]:
    """Per-worker model override read LIVE from ``os.environ``, or ``None``.

    Each background worker can be pinned to a specific Anthropic model via a
    ``MODEL_*`` profile setting (e.g. ``MODEL_MEMORY_EXTRACT=claude-haiku-…``)
    so extraction-shaped jobs can drop to a cheaper tier while judgment-shaped
    jobs stay strong — see support-llm-cost-fix P4 / FIX 3. Passed straight to
    :func:`make_llm_client` / :func:`try_make_llm_client` as ``model=``; the
    default (unset/blank → ``None``) preserves the engine default exactly.

    Read from ``os.environ`` at call time, NOT the frozen pydantic ``settings``
    snapshot, so a live ``settings.update`` to the profile ``.env`` applies on
    the next call with no daemon restart — same precedent as
    ``LLM_DAILY_BUDGET_USD`` (engine commit 06fb766). A blank/whitespace value
    is treated as unset.
    """
    raw = os.environ.get(env_key)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


__all__ = [
    "LLMClient",
    "LLMResponse",
    "TextBlock",
    "ToolUseBlock",
    "make_llm_client",
    "try_make_llm_client",
    "routed_model",
]
