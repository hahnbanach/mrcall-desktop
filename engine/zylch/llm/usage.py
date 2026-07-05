"""LLM spend metering + the daily hard cap.

Every SUCCESSFUL call at the single :class:`~zylch.llm.client.LLMClient`
chokepoint records one ``llm_usage`` row here — model, transport, token
counts, and an estimated USD cost — and logs a one-line ``[llm-usage]``
summary. :func:`spent_today_usd` / :func:`budget_state` back the
per-profile daily cap (``LLM_DAILY_BUDGET_USD``) that the background
pipeline consults before doing any AI work.

Design rules baked in here:

- **Recording MUST NEVER break an LLM call.** :func:`record` wraps
  everything in a catch-all that degrades to ``logger.warning``.
- **The budget is read from ``os.environ`` at call time**, NOT from the
  frozen pydantic ``settings`` snapshot — that snapshot is captured at
  daemon start, so a live ``settings.update`` (which hot-reloads
  ``os.environ`` via ``settings_io.update_env``) would be invisible until
  a restart. Same precedent as engine commit 06fb766 (SMS_BUSINESS_ID).
- **An UNKNOWN model id bills at Opus prices.** The cap must overestimate,
  never undercount, so a mislabelled/renamed model can't sneak spend
  past the gate.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from datetime import datetime
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# Default daily cap when LLM_DAILY_BUDGET_USD is unset. A value <= 0
# means "no cap" (see daily_budget_usd).
DEFAULT_DAILY_BUDGET_USD = 10.0

# Price table, $ per million tokens, (input, output). Matched by
# substring against the model id (see _price_for). Keep the tiers here
# aligned with Anthropic's published list pricing.
_PRICES: Dict[str, Tuple[float, float]] = {
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}

# Cache-write (prompt-cache creation) tokens bill at 1.25x the input
# rate; cache-read (prompt-cache hit) tokens at 0.10x.
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10

# Call-site tag threaded through the LLM call so recorded rows can be
# attributed to the worker that made them. Default "untagged"; scoped
# via the call_site() context manager.
_current_site: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_call_site", default="untagged"
)


@contextlib.contextmanager
def call_site(tag: str):
    """Tag every LLM call made inside the block with ``tag``.

    The tag lands in ``llm_usage.call_site`` and the ``[llm-usage]`` log
    line, so a spend audit can attribute cost per worker. Nested blocks
    restore the previous tag on exit.

    Note: for calls that cross a thread boundary (the async
    ``LLMClient.create_message`` runs the sync call in an executor), the
    tag survives only because ``create_message`` copies the contextvars
    context into the executor thread.
    """
    token = _current_site.set(tag)
    try:
        yield
    finally:
        _current_site.reset(token)


def current_call_site() -> str:
    """Return the active call-site tag ("untagged" when none is set)."""
    return _current_site.get()


def _utc_midnight() -> datetime:
    """Start of the current UTC day, as a naive datetime.

    ``llm_usage.ts`` is stored via ``datetime.utcnow()`` (naive UTC), so
    the comparison boundary is naive UTC too.
    """
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def _price_for(model: str) -> Tuple[float, float]:
    """``(input, output)`` $/MTok for ``model``, matched by substring.

    Unknown model ids fall back to Opus — the most expensive tier — so
    the estimate can only ever be an over-count, never an under-count.
    """
    m = (model or "").lower()
    for key, price in _PRICES.items():
        if key in m:
            return price
    return _PRICES["opus"]


def _tok(usage_dict: Dict[str, Any], key: str) -> int:
    """Read a token count from an Anthropic usage dict, defaulting to 0."""
    try:
        return int((usage_dict or {}).get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def estimate_cost_usd(model: str, usage_dict: Dict[str, Any]) -> float:
    """Estimated USD cost of one call from its Anthropic usage dict.

    ``input_tokens`` are the plain (uncached) input tokens.
    ``cache_creation_input_tokens`` bill at 1.25x the input rate and
    ``cache_read_input_tokens`` at 0.10x; ``output_tokens`` bill at the
    output rate. Unknown model → Opus pricing (see :func:`_price_for`).
    """
    in_rate, out_rate = _price_for(model)

    input_tokens = _tok(usage_dict, "input_tokens")
    output_tokens = _tok(usage_dict, "output_tokens")
    cache_write = _tok(usage_dict, "cache_creation_input_tokens")
    cache_read = _tok(usage_dict, "cache_read_input_tokens")

    cost = (
        input_tokens * in_rate
        + output_tokens * out_rate
        + cache_write * in_rate * _CACHE_WRITE_MULT
        + cache_read * in_rate * _CACHE_READ_MULT
    ) / 1_000_000.0
    return cost


def record(model: str, transport: str, usage_dict: Dict[str, Any]) -> None:
    """Persist one ``llm_usage`` row for the active owner and log a line.

    Called at the LLMClient chokepoint after a successful provider call.
    MUST NEVER raise — a metering failure can never break an LLM call —
    so the whole body is wrapped in a catch-all that degrades to a
    warning. Also emits one INFO line:

        [llm-usage] site=<tag> model=<m> in=<n> out=<n> cache_w=<n>
        cache_r=<n> est=$<x> today=$<y>
    """
    try:
        from zylch.cli.utils import get_owner_id
        from zylch.storage.database import get_session
        from zylch.storage.models import LlmUsage

        owner_id = get_owner_id()
        site = current_call_site()
        est = estimate_cost_usd(model, usage_dict or {})

        in_tok = _tok(usage_dict, "input_tokens")
        out_tok = _tok(usage_dict, "output_tokens")
        cache_w = _tok(usage_dict, "cache_creation_input_tokens")
        cache_r = _tok(usage_dict, "cache_read_input_tokens")

        with get_session() as session:
            session.add(
                LlmUsage(
                    owner_id=owner_id,
                    call_site=site,
                    transport=transport,
                    model=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cache_creation_input_tokens=cache_w,
                    cache_read_input_tokens=cache_r,
                    est_cost_usd=est,
                )
            )

        # Row is committed by the get_session() context manager above, so
        # today's running total already includes it.
        today = spent_today_usd(owner_id)
        logger.info(
            f"[llm-usage] site={site} model={model} in={in_tok} out={out_tok} "
            f"cache_w={cache_w} cache_r={cache_r} est=${est:.4f} today=${today:.4f}"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[llm-usage] record failed (ignored): {type(e).__name__}: {e}")


def spent_today_usd(owner_id: str) -> float:
    """SUM(``est_cost_usd``) for ``owner_id`` since today's UTC midnight.

    Fail-open: on a DB error this returns 0.0 (logged) rather than
    raising, so a metering-store hiccup can't brick the pipeline. In the
    over-budget case the store is healthy and the real sum is returned.
    """
    try:
        from sqlalchemy import func

        from zylch.storage.database import get_session
        from zylch.storage.models import LlmUsage

        midnight = _utc_midnight()
        with get_session() as session:
            total = (
                session.query(func.coalesce(func.sum(LlmUsage.est_cost_usd), 0.0))
                .filter(LlmUsage.owner_id == owner_id)
                .filter(LlmUsage.ts >= midnight)
                .scalar()
            )
        return float(total or 0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[llm-usage] spent_today_usd failed (treating as $0): " f"{type(e).__name__}: {e}"
        )
        return 0.0


def daily_budget_usd() -> float:
    """Daily USD cap, read LIVE from ``os.environ`` at call time.

    Default :data:`DEFAULT_DAILY_BUDGET_USD` (10.0) when unset/blank. A
    value <= 0 means "no cap". Deliberately NOT read from the pydantic
    ``settings`` object — that snapshot is frozen at daemon start, so a
    ``settings.update`` to the profile ``.env`` would not be seen without
    a restart (see module docstring / engine commit 06fb766).
    """
    raw = os.environ.get("LLM_DAILY_BUDGET_USD")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_DAILY_BUDGET_USD
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"[llm-usage] invalid LLM_DAILY_BUDGET_USD={raw!r} — using default "
            f"${DEFAULT_DAILY_BUDGET_USD}"
        )
        return DEFAULT_DAILY_BUDGET_USD


def budget_state(owner_id: str) -> Dict[str, Any]:
    """Snapshot of today's spend vs the cap for ``owner_id``.

    Returns ``{"spent_usd": float, "budget_usd": float, "exceeded":
    bool}``. ``exceeded`` is True only when a POSITIVE cap is set and
    today's estimated spend has reached it (``spent >= budget``). A cap
    <= 0 disables the gate (``exceeded`` always False).
    """
    budget = daily_budget_usd()
    spent = spent_today_usd(owner_id)
    exceeded = budget > 0 and spent >= budget
    return {"spent_usd": spent, "budget_usd": budget, "exceeded": exceeded}
