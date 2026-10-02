"""The measurement's spend ledger: an intent before every paid dispatch, the receipt after.

``ledger.jsonl`` in the run's output directory, one JSON object per line,
each line flushed and fsync'd before the next step:

- ``{"event": "intent", "id", "cell", "dispatch", "model", "bound_micro_usd",
  "committed_before_micro_usd", "cap_micro_usd", "at"}`` — written **before**
  the dispatch, after the cap check. ``bound_micro_usd`` is the engine's own
  reservation bound for the exact request the transport sends
  (``openrouter_pricing.request_bound``; K3's through its adapter).
- ``{"event": "settle", "id", "cost_micro_usd", "source", "usage", "at"}`` —
  after the transport returned: ``source`` ``receipt`` when the provider's
  ``usage.cost`` was readable, else ``bound`` (the cost is then counted at the
  bound).
- ``{"event": "fail", "id", "error", "at"}`` — the dispatch raised; whether it
  cost anything is unknown, so the intent stays open at its bound.

**The cap.** Before each dispatch the ledger refuses (``CapExceeded``) when
the settled costs, plus the bound of every intent without a settlement, plus
this dispatch's bound would exceed the cap. Nothing is retried: a cell (one
arm on one case, one repetition) with any intent is never dispatched again,
so a run resumed after an interruption skips it. A line that does not parse
fails closed — whether it recorded a dispatch cannot be known.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
            else:
                total += int(settlement["cost_micro_usd"])
        return total

    def committed(self) -> int:
        """Micro-USD spent or still uncertain: receipts, plus the bound of every open intent."""
        with self._lock:
            return self._committed()

    def dispatched_cells(self) -> set[str]:
        """The cells with an intent: never dispatched again."""
        with self._lock:
            return {row["cell"] for row in self._rows if row["event"] == "intent"}

    def admit(self, cell: str, dispatch: int, bound_micro_usd: int, model: str) -> str:
        """Check the cap and write the intent of one dispatch; return its id."""
        with self._lock:
            committed = self._committed()
            if committed + int(bound_micro_usd) > self.cap:
                raise CapExceeded(
                    f"{cell}: committed {committed / 1e6:.6f} + bound {bound_micro_usd / 1e6:.6f}"
                    f" > cap {self.cap / 1e6:.2f} USD; not sent"
                )
            intent = f"{cell}#d{dispatch}"
            self._append(
                {
                    "event": "intent",
                    "id": intent,
                    "cell": cell,
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
