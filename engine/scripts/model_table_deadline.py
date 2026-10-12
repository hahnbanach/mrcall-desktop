"""The daily model-table job's wall-clock budget: no paid check crosses the run's deadline.

The workflow kills the job at 120 minutes (`timeout-minutes`), and a run
killed mid-way publishes nothing. So a run has a deadline,
`--deadline-minutes` after it starts (90 by default, passed explicitly by
`.github/workflows/model-resolution.yml`). A paid check is started only when
its time limit ends before the deadline; one that would cross it is
deferred, unpaid and reported, and the run then decides on what it has,
publishes what the gates allow and settles its reservation.

**The budget.** Every check that starts ends by the deadline, and a
measurement stopped at its limit is killed `GRACE_SECONDS` (0.5 min) later.
After the deadline come the decisions, the gates and one push (about a
minute; the first run read its sources in 96 s). Before the job, the
runner's checkout and `pip install` (a few minutes). 90 + 0.5 + about 1 +
setup stays well under 120.

**Time limits** (`limit_minutes`). A measurement runs in a process of its
own and is stopped at its limit (`model_table_process.limited_run`): a
harness role's at 10 minutes (the first live run, 2026-10-12: 10 to 53 s,
median 25), a memory roles' corpus run at 20 (53 s to 14.6 min, median 2.3;
one was killed with a case open for 6.5 min). A smoke runs in the job's own
process and is not stopped; its limit is its worst case, which the engine's
HTTP timeouts bound: two calls, each with a read timeout of 180 s on
OpenRouter's Messages path (`zylch/llm/openrouter_client.py`), 600 s on the
K3 Chat path. So 7 minutes (2 x 3 min plus a minute of setup and pricing),
and 21 on the K3 path (2 x 10 min plus one). The first run's smokes took 1
to 31 s.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import measurement_common as common

DEADLINE_MINUTES = 90
LIMIT_MINUTES = {"smoke": 7, "smoke-k3": 21, "measure": 10, "corpus": 20}


def _k3() -> str | None:
    """The id the engine sends on its K3 Chat path (600 s read timeout)."""
    try:
        from zylch.llm import k3_reasoning
    except ImportError:
        return None
    return k3_reasoning.MODEL


def limit_minutes(kind: str, role: str | None, model: str | None = None) -> int:
    """The most a check of `kind` on `role` (and `model`) may take (module docstring)."""
    if kind == "measure":
        return LIMIT_MINUTES["corpus" if role in common.CORPUS_ROLES else "measure"]
    if model is None or model == _k3() or _k3() is None:
        return LIMIT_MINUTES["smoke-k3"]  # unknown: the worst case
    return LIMIT_MINUTES["smoke"]


class Deadline:
    """The run's deadline and which checks may still start before it."""

    def __init__(self, start: datetime, minutes: float):
        self.minutes = minutes
        self.at = start + timedelta(minutes=minutes)

    def late(self, kind: str, role: str | None, now: datetime, model: str | None = None):
        """None when a check of `kind` on `role` (`model`) started `now` ends
        before the deadline, else why it is deferred."""
        limit = limit_minutes(kind, role, model)
        if now + timedelta(minutes=limit) <= self.at:
            return None
        left = max(0, int((self.at - now).total_seconds() // 60))
        return (
            f"deferred: the run's deadline ({self.at.strftime('%H:%M:%SZ')}, {self.minutes:g} "
            f"min after its start) is {left} min away, and this check may take {limit} min"
        )
