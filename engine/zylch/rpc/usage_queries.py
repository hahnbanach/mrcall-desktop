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


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "usage.today": usage_today,
    "usage.reconcile": usage_reconcile,
}
