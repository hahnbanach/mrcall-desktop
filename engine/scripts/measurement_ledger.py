"""The measurement's spend ledger: an intent before every paid dispatch, the receipt after.

``ledger.jsonl`` in the run's output directory, one JSON object per line,
each line flushed and fsync'd before the next step:

- ``{"event": "intent", "id", "cell", "attempt", "dispatch", "model",
  "bound_micro_usd", "committed_before_micro_usd", "cap_micro_usd", "at"}`` —
  written **before** the dispatch, after the cap check. ``bound_micro_usd`` is
  the engine's own reservation bound for the exact request the transport
  sends (``openrouter_pricing.request_bound``; K3's through its adapter).
  ``id`` is ``<cell>#d<dispatch>`` in a cell's first attempt and
  ``<cell>#a<attempt>d<dispatch>`` in its second.
- ``{"event": "settle", "id", "cost_micro_usd", "source", "usage", "at"}`` —
  after the transport returned: ``source`` ``receipt`` when the provider's
  ``usage.cost`` was readable, else ``bound`` (the cost is then counted at the
  bound).
- ``{"event": "settle", "id", "cost_micro_usd": 0, "source": "refused",
  "outcome": "refused", "status_code", "retry_after", "error", "at"}`` — the
  provider refused the dispatch before inference
  (``zylch.llm.client._rejected_before_inference``: a status of no work, such
  as 429, as OpenRouter answers when an upstream provider's pool is
  saturated): nothing was spent, so it is settled at zero.
- ``{"event": "fail", "id", "error", "at"}`` — any other failure (a 5xx, a
  timeout, a lost connection, an answer that cannot be read): whether it cost
  anything is unknown, so the intent stays open at its bound.

**The cap.** Before each dispatch the ledger refuses (``CapExceeded``) when
the settled costs (a refused settlement counts zero), plus the bound of every
intent without a settlement, plus this dispatch's bound would exceed the cap.

**Attempts** (``next_attempt``). A cell (one arm on one case, one repetition)
is dispatched at most ``MAX_ATTEMPTS`` (2) times, and a second time only when
its first attempt ended in a refusal before inference, with every intent of
the attempt settled: ``measure_roles.py`` sends it once more at the end of
the role's pass, at least the provider's ``retry_after`` or ``RETRY_WAIT_S``
seconds after the refusal, whichever is longer. Nothing else is ever
re-sent: a cell with an open, failed or settled intent, or refused twice, is
never dispatched again, so a run resumed after an interruption skips it. A
line that does not parse fails closed — whether it recorded a dispatch cannot
be known.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_ATTEMPTS = 2
RETRY_WAIT_S = 5.0
REFUSED = "refused"


class CapExceeded(RuntimeError):
    """The next dispatch would cross the cap; it was not sent."""


class LedgerCorrupt(RuntimeError):
    """A ledger line does not parse; nothing more is dispatched against it."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    """Append-only JSONL of intents and settlements, checked against a cap in micro-USD."""

    def __init__(self, path: Path, cap_micro_usd: int, forbidden: tuple[str, ...] = ()):
        self.path = Path(path)
        self.cap = int(cap_micro_usd)
        self._forbidden = tuple(secret for secret in forbidden if secret)
        self._lock = threading.Lock()
        self._rows: list[dict] = []
        if self.path.exists():
            for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    self._rows.append(json.loads(line))
                except ValueError:
                    raise LedgerCorrupt(f"{self.path.name}:{number} does not parse") from None

    def rows(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def _append(self, row: dict) -> None:
        line = json.dumps(row, ensure_ascii=False, default=str)
        if any(secret in line for secret in self._forbidden):
            raise RuntimeError("a ledger row would carry the provider key; not written")
        with self.path.open("a", encoding="utf-8") as out:
            out.write(line + "\n")
            out.flush()
            os.fsync(out.fileno())
        self._rows.append(row)

    def _committed(self) -> int:
        settled = {r["id"]: r for r in self._rows if r["event"] == "settle"}
        total = 0
        for row in self._rows:
            if row["event"] != "intent":
                continue
            settlement = settled.get(row["id"])
            if settlement is None or settlement.get("cost_micro_usd") is None:
                total += int(row["bound_micro_usd"])
            elif settlement.get("outcome") == REFUSED:
                continue  # refused before inference: nothing was spent
            else:
                total += int(settlement["cost_micro_usd"])
        return total

    def committed(self) -> int:
        """Micro-USD spent or still uncertain: receipts, plus the bound of every open intent."""
        with self._lock:
            return self._committed()

    def attempts(self, cell: str) -> list[dict]:
        """The cell's attempts, in order: ``{"attempt", "refusal"}``.

        ``refusal`` is the settlement of the attempt's last dispatch when the
        provider refused it before inference and every dispatch of the attempt
        is settled; None for any other attempt (an open or failed intent, an
        answer).
        """
        with self._lock:
            settled = {r["id"]: r for r in self._rows if r["event"] == "settle"}
            by_attempt: dict[int, list[dict]] = {}
            for row in self._rows:
                if row["event"] == "intent" and row["cell"] == cell:
                    by_attempt.setdefault(int(row.get("attempt", 1)), []).append(row)
        out = []
        for attempt, intents in sorted(by_attempt.items()):
            last = settled.get(intents[-1]["id"]) or {}
            whole = all(intent["id"] in settled for intent in intents)
            refusal = last if whole and last.get("outcome") == REFUSED else None
            out.append({"attempt": attempt, "refusal": refusal})
        return out

    def refusals(self, cell: str) -> list[dict]:
        """The refusals before inference that ended the cell's attempts (for its result)."""
        keep = ("status_code", "retry_after", "error", "at")
        return [
            {"attempt": made["attempt"], **{k: made["refusal"].get(k) for k in keep}}
            for made in self.attempts(cell)
            if made["refusal"] is not None
        ]

    def next_attempt(self, cell: str) -> int | None:
        """1 for a cell never dispatched; 2 when its one attempt was refused before inference.

        None otherwise: the cell is never dispatched again (module docstring).
        """
        made = self.attempts(cell)
        if not made:
            return 1
        if len(made) < MAX_ATTEMPTS and all(a["refusal"] is not None for a in made):
            return len(made) + 1
        return None

    def admit(
        self, cell: str, dispatch: int, bound_micro_usd: int, model: str, attempt: int = 1
    ) -> str:
        """Check the cap and write the intent of one dispatch; return its id."""
        with self._lock:
            committed = self._committed()
            if committed + int(bound_micro_usd) > self.cap:
                raise CapExceeded(
                    f"{cell}: committed {committed / 1e6:.6f} + bound {bound_micro_usd / 1e6:.6f}"
                    f" > cap {self.cap / 1e6:.2f} USD; not sent"
                )
            intent = f"{cell}#d{dispatch}" if attempt == 1 else f"{cell}#a{attempt}d{dispatch}"
            self._append(
                {
                    "event": "intent",
                    "id": intent,
                    "cell": cell,
                    "attempt": attempt,
                    "dispatch": dispatch,
                    "model": model,
                    "bound_micro_usd": int(bound_micro_usd),
                    "committed_before_micro_usd": committed,
                    "cap_micro_usd": self.cap,
                    "at": now(),
                }
            )
            return intent

    def settle(self, intent: str, cost_micro_usd: int | None, usage: Any) -> None:
        source = "receipt" if cost_micro_usd is not None else "bound"
        row = {"event": "settle", "id": intent, "cost_micro_usd": cost_micro_usd}
        with self._lock:
            self._append({**row, "source": source, "usage": usage, "at": now()})

    def refuse(
        self, intent: str, error: str, status_code: int | None, retry_after: float | None
    ) -> None:
        """Settle a dispatch the provider refused before inference: at zero, outcome refused."""
        row = {"event": "settle", "id": intent, "cost_micro_usd": 0, "source": REFUSED}
        row.update(outcome=REFUSED, status_code=status_code, retry_after=retry_after)
        with self._lock:
            self._append({**row, "error": error, "usage": None, "at": now()})

    def fail(self, intent: str, error: str) -> None:
        with self._lock:
            self._append({"event": "fail", "id": intent, "error": error, "at": now()})

    def totals(self) -> dict:
        """Micro-USD by kind: receipts, bounds standing for missing receipts, open intents."""
        with self._lock:
            settled = {r["id"]: r for r in self._rows if r["event"] == "settle"}
            out = {"receipts": 0, "bounds_for_missing_receipts": 0, "open_intents": 0}
            for row in self._rows:
                if row["event"] != "intent":
                    continue
                settlement = settled.get(row["id"])
                if settlement is None:
                    out["open_intents"] += int(row["bound_micro_usd"])
                elif settlement.get("cost_micro_usd") is None:
                    out["bounds_for_missing_receipts"] += int(row["bound_micro_usd"])
                else:
                    out["receipts"] += int(settlement["cost_micro_usd"])
            return out
