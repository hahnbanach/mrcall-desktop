"""RPC handler for LLM spend visibility — ``usage.today``.

Kept out of ``rpc/methods.py`` (per the 500-line per-module guideline).
Backs the desktop's spend readout and, more importantly, the
post-incident audit: one call returns today's estimated spend, the daily
cap, whether the cap tripped, and a per-call-site breakdown — so "what
did the engine spend today" is a single RPC instead of a multi-day log
reconstruction (support-llm-cost-fix / P1).
"""

from __future__ import annotations

import logging
import asyncio
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def usage_today(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """usage.today() -> today's spend snapshot + per-call-site breakdown.

    Returns::

        {
          "spent_usd": float,     # SUM(est_cost_usd) since UTC midnight
          "budget_usd": float,    # live LLM_DAILY_BUDGET_USD (0 pauses AI)
          "exceeded": bool,       # cap set AND reached
          "calls_today": int,     # rows recorded since UTC midnight
          "by_site": {            # per call_site aggregation
              "<site>": {"calls": int, "est_usd": float}, ...
          },
        }
    """
    from sqlalchemy import func

    from zylch.llm.usage import _utc_midnight, budget_state
    from zylch.storage.database import get_session
    from zylch.storage.models import LlmUsage

    owner_id = _owner_id()
    state = budget_state(owner_id)

    calls_today = 0
    by_site: Dict[str, Dict[str, Any]] = {}
    try:
        midnight = _utc_midnight()
        with get_session() as session:
            rows = (
                session.query(
                    LlmUsage.call_site,
                    func.count(LlmUsage.id),
                    func.coalesce(func.sum(LlmUsage.est_cost_usd), 0.0),
                )
                .filter(LlmUsage.ts >= midnight)
                .group_by(LlmUsage.call_site)
                .all()
            )
        for site, count, est in rows:
            key = site or "untagged"
            n = int(count or 0)
            calls_today += n
            by_site[key] = {"calls": n, "est_usd": float(est or 0.0)}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[rpc:usage.today] breakdown failed: {type(e).__name__}: {e}")

    from zylch.llm.model_policy import policy_snapshot

    policy = policy_snapshot()
    supported = policy["provider"] in {"anthropic", "openrouter"} and policy["credential_configured"]
    reason = ""
    if policy["provider"] == "mrcall":
        try:
            await asyncio.to_thread(_credit_client().capabilities)
            supported = True
        except Exception as exc:
            reason = str(exc) if isinstance(exc, RuntimeError) else "MrCall billing availability could not be verified."
    result = {
        **state,
        "billing_reason": reason,
        "billing_supported": supported,
        "model_policy": policy,
        "paused": state["paused"] or not supported,
        "calls_today": calls_today,
        "by_site": by_site,
    }
    logger.debug(f"[rpc:usage.today] owner_id={owner_id} -> {result}")
    return result



def _credit_client():
    from zylch.auth import get_session
    from zylch.llm.bounded_proxy import BoundedProxyClient
    from zylch.llm.model_policy import profile_value
    return BoundedProxyClient(profile_value("MRCALL_PROXY_URL") or "https://zylch.mrcall.ai", get_session())


async def usage_reconcile(params, notify):
    """usage.reconcile(cursor?) -> recovered and unresolved credit reservations."""
    from zylch.llm.billing_reconciliation import reconcile
    cursor = params.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("cursor must be a string")
    return await asyncio.to_thread(reconcile, _credit_client(), cursor=cursor)


async def llm_models(params, notify):
    """Free catalog for a proposed billing selection; never changes saved policy."""
    from zylch.llm.model_policy import resolve_provider
    from zylch.llm.openrouter_pricing import LABELS
    provider = params.get("provider") or resolve_provider()
    if provider not in ("anthropic", "openrouter", "mrcall"):
        raise ValueError("Unsupported billing provider")
    if provider == "mrcall":
        try:
            capabilities = await asyncio.to_thread(_credit_client().capabilities)
            models = capabilities.get("models")
            if not isinstance(models, list) or not models:
                raise ValueError("Billing server does not publish a model catalog; update it.")
            if any(not isinstance(m, dict) or not all(isinstance(m.get(k), str) and m[k]
                   for k in ("id", "label", "provider")) for m in models):
                raise ValueError("Billing server returned an invalid model catalog.")
            models = [{k: m[k] for k in ("id", "label", "provider")} for m in models]
        except Exception as exc:
            reason = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else "Billing catalog unavailable."
            return {"provider": provider, "models": [], "available": False, "reason": reason}
    elif provider == "openrouter":
        models = [{"id": key, "label": label, "provider": "openrouter"} for key, label in LABELS.items()]
    else:
        models = [{"id": key, "label": label, "provider": "anthropic"} for key, label in (
            ("claude-opus-5", "Claude Opus 5"), ("claude-sonnet-5", "Claude Sonnet 5"),
            ("claude-haiku-4-5", "Claude Haiku 4.5"))]
    return {"provider": provider, "models": models, "available": True, "reason": ""}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "usage.today": usage_today,
    "llm.models": llm_models,
    "usage.reconcile": usage_reconcile,
}
