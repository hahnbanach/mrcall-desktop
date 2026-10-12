"""The daily model-table job's wall-clock budget: no paid check crosses the run's deadline.

The workflow kills the job at 120 minutes (`timeout-minutes`), and a run
killed mid-way publishes nothing and settles nothing. So a run has a
deadline, `--deadline-minutes` after it starts (90 by default, passed
explicitly by `.github/workflows/model-resolution.yml`): the 30 minutes
left cover the runner's setup before the job and the decisions, gates and
push after its last check. A paid check is started only when its time limit
ends before the deadline; one that would cross it is deferred, unpaid and
reported, and the run then decides on what it has, publishes what the gates
allow and settles its reservation.

**Time limits** (`LIMIT_MINUTES`), from the first live run (2026-10-12): a
smoke took 1 to 31 s (median 7), a harness role's measurement 10 to 53 s
(median 25), a memory roles' corpus run 53 s to 14.6 min (median 2.3 min),
and one corpus run had recorded two cases in eight minutes when it was
killed. A measurement runs in a process of its own and is stopped at its
limit (`model_table_edges.Measurement`): interrupted first, so it removes
its key file, then killed; what its ledger recorded is charged, open
intents at their bound. A smoke runs in the job's process, two calls each
bounded by the engine's own HTTP timeouts; its limit is a projection only.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import measurement_common as common

DEADLINE_MINUTES = 90
LIMIT_MINUTES = {"smoke": 3, "measure": 10, "corpus": 20}


def limit_minutes(kind: str, role: str | None) -> int:
    """The most a check of `kind` on `role` may take (module docstring)."""
    if kind == "measure" and role in common.CORPUS_ROLES:
        return LIMIT_MINUTES["corpus"]
    return LIMIT_MINUTES[kind]


class Deadline:
    """The run's deadline and which checks may still start before it."""

    def __init__(self, start: datetime, minutes: float):
        self.minutes = minutes
        self.at = start + timedelta(minutes=minutes)

    def late(self, kind: str, role: str | None, now: datetime) -> str | None:
        """None when a check of `kind` on `role` started `now` ends before the
        deadline, else why it is deferred."""
        limit = limit_minutes(kind, role)
        if now + timedelta(minutes=limit) <= self.at:
            return None
        left = max(0, int((self.at - now).total_seconds() // 60))
        return (
            f"deferred: the run's deadline ({self.at.strftime('%H:%M:%SZ')}, {self.minutes:g} "
            f"min after its start) is {left} min away, and this check may take {limit} min"
        )
