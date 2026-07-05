"""Merge-gate canary policy — when to re-verify, not what to verify.

The canary itself (``zylch.memory.llm_merge.merge_gate_selfcheck``)
feeds two unmistakably-distinct entities to the live merge model and
asserts it refuses to merge them — the detector for the 2026-06
broken-open regression. Before support-llm-cost-fix / P3 it ran on
EVERY mail-bearing tick (~30-50 calls/day). This module decides when
``_run_memory`` actually runs it:

a. last definitive verdict missing or UNHEALTHY → run. Sticky: while
   unhealthy the canary runs on every memory pass and merging stays
   DISABLED until a pass flips it back;
b. healthy but the stamp is older than 24h → run;
c. first memory pass since this daemon started → run. Deploys are the
   realistic way the gate breaks (the 2026-06 incident was a prompt
   refactor), so a process restart always re-verifies.

Otherwise skip. Residual risk, accepted: with a healthy + fresh stamp
a mid-day provider-side regression is caught at most ~24h later (or at
the next daemon start). The sticky-unhealthy rule prevents the
catastrophic case — a broken-open gate silently merging contacts away
for weeks — from ever persisting.

State lives in the ``worker_state`` KV: ``merge_canary_healthy``
("1"/"0") and ``merge_canary_at`` (ISO timestamp of the last
definitive verdict).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from zylch.storage.worker_state import get_state, set_state
from zylch.workers.task_gating import _parse_dt

logger = logging.getLogger(__name__)

WS_KEY_CANARY_AT = "merge_canary_at"
WS_KEY_CANARY_HEALTHY = "merge_canary_healthy"

CANARY_INTERVAL_HOURS = 24

# True once a canary produced a DEFINITIVE verdict since this process
# started (rule c above). A transient attempt (healthy=None) does NOT
# set it, so the next memory pass retries.
_canary_verified_since_start = False


def merge_canary_policy(owner_id: str) -> Dict[str, Any]:
    """Decide whether ``_run_memory`` runs the canary now.

    Returns ``{"run": bool, "reason": str}`` and logs the decision —
    rules a/b/c in the module docstring.
    """
    healthy = get_state(owner_id, WS_KEY_CANARY_HEALTHY)
    if healthy == "0":
        decision = {"run": True, "reason": "last verdict unhealthy (sticky)"}
    elif healthy != "1":
        decision = {"run": True, "reason": "no stored verdict"}
    elif not _canary_verified_since_start:
        decision = {"run": True, "reason": "first memory pass since daemon start"}
    else:
        stamp = _parse_dt(get_state(owner_id, WS_KEY_CANARY_AT))
        if stamp is None or datetime.now(timezone.utc) - stamp >= timedelta(
            hours=CANARY_INTERVAL_HOURS
        ):
            decision = {"run": True, "reason": "stamp missing or older than 24h"}
        else:
            decision = {"run": False, "reason": "healthy and fresh"}
    logger.info(
        f"[merge-gate] canary {'running' if decision['run'] else 'skipped'} "
        f"({decision['reason']})"
    )
    return decision


def record_merge_canary(owner_id: str, healthy: Optional[bool]) -> bool:
    """Persist a canary outcome; return whether merging may proceed.

    - ``True`` → gate verified healthy: stamp it, enable merging.
    - ``False`` → BROKEN-OPEN: stamp it, disable merging. Sticky — the
      stored "0" makes every subsequent pass re-run the canary with
      merging off until a pass flips it back.
    - ``None`` → transient (no LLM / API error): state untouched (a
      flaky call neither "heals" an unhealthy record nor poisons a
      healthy one, matching the pre-gating semantics where None left
      merging ON); merging stays disabled only in the sticky state.
    """
    global _canary_verified_since_start
    if healthy is None:
        return get_state(owner_id, WS_KEY_CANARY_HEALTHY) != "0"
    _canary_verified_since_start = True
    set_state(owner_id, WS_KEY_CANARY_HEALTHY, "1" if healthy else "0")
    set_state(owner_id, WS_KEY_CANARY_AT, datetime.now(timezone.utc).isoformat())
    return bool(healthy)
