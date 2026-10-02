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

    # On credits the snapshot reads the billing server's served set (a 5 s
    # read, cached one hour): off the event loop.
    policy = await asyncio.to_thread(policy_snapshot)
    supported = (
        policy["provider"] in {"anthropic", "openrouter"} and policy["credential_configured"]
    )
    reason = ""
    if policy["provider"] == "mrcall":
        try:
            await asyncio.to_thread(_credit_client().capabilities)
            supported = True
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, RuntimeError)
                else "MrCall billing availability could not be verified."
            )
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
    from zylch.llm.model_policy import profile_values, proxy_url

    return BoundedProxyClient(proxy_url(profile_values()), get_session())


async def usage_reconcile(params, notify):
    """usage.reconcile(cursor?) -> recovered and unresolved credit reservations."""
    from zylch.llm.billing_reconciliation import reconcile

    cursor = params.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("cursor must be a string")
    return await asyncio.to_thread(reconcile, _credit_client(), cursor=cursor)


async def llm_models(params, notify):
    """Free catalog for a proposed billing selection; never changes saved policy.

    The models proposed are the rankings of the table in force (`roles/table.py`,
    downloaded daily by `roles/distribution.py`): on a personal Anthropic key
    their direct ids, on OpenRouter their catalogue ids; on MrCall credits the
    list of the billing server's v2 capabilities (`roles/served.py`, read at
    most once an hour: its published rankings plus K3). No excluded family is
    offered. A model the profile saved (its base model, DEFAULT_MODEL or a role
    override) that can run on the provider stays listed after them, so a saved
    choice stays visible and selected; one that cannot run there is not listed,
    and the Settings view shows it as saved but unavailable."""
    from zylch.llm.budget_pricing import BudgetError
    from zylch.llm.model_policy import profile_values, proxy_url, resolve_provider
    from zylch.llm.roles import excluded, served
    from zylch.llm.roles.table import NO_TABLE, document, listed

    provider = params.get("provider") or resolve_provider()
    if provider not in ("anthropic", "openrouter", "mrcall"):
        raise ValueError("Unsupported billing provider")
    try:
        values = profile_values()
    except BudgetError:  # unreadable saved settings: the rankings alone
        values = {}
    if provider == "mrcall":
        try:
            client = _credit_client()
            entries = await asyncio.to_thread(served.served, proxy_url(values), client=client)
            if not entries:
                raise ValueError("The MrCall billing server serves no model at the moment.")
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, (RuntimeError, ValueError))
                else "Billing catalog unavailable."
            )
            return {"provider": provider, "models": [], "available": False, "reason": reason}
        models = [dict(entry) for entry in entries if not excluded(entry["id"])]
    elif document() is None:  # no table in force: say so rather than list nothing
        return {"provider": provider, "models": [], "available": False, "reason": NO_TABLE}
    else:
        models = [
            {"id": key, "label": label, "provider": provider} for key, label in listed(provider)
        ]
    return {
        "provider": provider,
        "models": models + _saved_models(values, provider, {m["id"] for m in models}),
        "available": True,
        "reason": "",
    }


def _saved_models(values, provider, listed_ids):
    """The models the profile saved that can run on `provider` and are not
    listed yet: on a personal key those its transport prices (the price
    source, `roles/prices.py`); on credits those the snapshot prices on either
    transport, since the billing server accepts any model its snapshot prices."""
    from zylch.llm.model_policy import BASE_KEYS, ROLES
    from zylch.llm.roles import catalogue, label
    from zylch.llm.roles.prices import price

    found = []
    for key in (BASE_KEYS[provider], "DEFAULT_MODEL", *ROLES):
        model = str(values.get(key) or "").strip()
        if not model or model in listed_ids:
            continue
        if provider == "mrcall":
            runs = any(catalogue.pricing(model, t) for t in catalogue.TRANSPORTS)
            owner = "openrouter" if "/" in model else "anthropic"
        else:
            runs = price(model, "direct" if provider == "anthropic" else "openrouter")
            owner = provider
        if runs:
            listed_ids.add(model)
            found.append({"id": model, "label": label(model), "provider": owner})
    return found


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "usage.today": usage_today,
    "llm.models": llm_models,
    "usage.reconcile": usage_reconcile,
}
