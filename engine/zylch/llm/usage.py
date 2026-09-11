"""Historical usage helpers and call-site tags.

New engine dispatch uses budget.reserve/settle for durable admission and atomic
accounting. record() remains a best-effort compatibility telemetry helper only;
its fail-open behavior never authorizes an LLM call. Daily snapshots delegate to
the fail-closed reservation ledger.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from datetime import datetime
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# Default daily cap when LLM_DAILY_BUDGET_USD is unset; zero pauses AI.
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

    A database failure refuses the read. It must never look like zero spend.
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
    except Exception:
        from zylch.llm.budget import BudgetError

        raise BudgetError("AI spending cannot be read; no new paid call is authorized.") from None


def daily_budget_usd() -> float:
    """Configured daily USD limit; zero pauses AI and invalid values refuse."""
    from zylch.llm.budget import _budget

    return _budget() / 1_000_000


def budget_state(owner_id: str) -> Dict[str, Any]:
    """Fail-closed daily snapshot including durable outstanding reservations."""
    from zylch.llm.budget import budget_snapshot

    return budget_snapshot(owner_id)
