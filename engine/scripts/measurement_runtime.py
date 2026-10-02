"""How ``measure_roles.py`` runs one cell against the engine (milestone 10, plan S4b).

A cell is one arm on one case, in one repetition. This module holds what a
cell needs beside the run loop: the disposable profile whose ``.env`` (mode
600, deleted with the profile) holds the provider and the key, the engine's
client for the cell's arm with its transport behind the ledger
(:class:`GuardedTransport`: an intent before each dispatch, the receipt
after), the captured request rebuilt for the arm, the run clock pinned to the
case's capture moment, the answer read off a response, and the results file
(:class:`Results`), append-only and fsync'd like the ledger.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import measurement_common as common
from measurement_ledger import CapExceeded, Ledger, now

logger = logging.getLogger("measure_roles")
KEY_ENV = "OPENROUTER_API_KEY"
DRY_KEY = "measurement-dry-run-no-network"
OWNER = "measurement-owner"
SAMPLING = ("temperature", "top_p", "top_k")
# A cell with one of these rows is done; the others never reached a provider.
FINAL = ("scored", "error", "interrupted")


@dataclass(frozen=True)
class Cell:
    role: str
    arm: str
    case_id: str
    repetition: int

    @property
    def key(self) -> str:
        return f"{self.role}|{self.arm}|{self.case_id}|r{self.repetition}"


@dataclass
class RoleRun:
    """One role to measure: its case document, its captured requests, its arms."""

    role: str
    document: dict
    requests: dict
    arms: list[dict]
    harness: Any = None

    def entry(self, case_id: str) -> dict:
        return next(e for e in self.requests["requests"] if e["case_id"] == case_id)


class Results:
    """``results.jsonl``: one row per cell and repetition, fsync'd, never rewritten."""

    def __init__(self, path: Path, forbidden: tuple[str, ...]):
        self.path, self._forbidden = Path(path), tuple(s for s in forbidden if s)
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
        self.rows = [json.loads(line) for line in lines if line.strip()]

    def done(self) -> set[str]:
        """Cells with a final row: scored, or failed or interrupted after an intent.

        An unpriced, skipped or capped cell never reached a provider and runs
        again when the run is resumed (its newer row is the one that counts).
        """
        return {row["cell"] for row in self.rows if row["status"] in FINAL}

    def append(self, row: dict) -> None:
        line = json.dumps(row, ensure_ascii=False, default=str)
        if any(secret in line for secret in self._forbidden):
            raise RuntimeError("a result row would carry the provider key; not written")
        with self.path.open("a", encoding="utf-8") as out:
            out.write(line + "\n")
            out.flush()
            os.fsync(out.fileno())
        self.rows.append(row)


@dataclass
class Context:
    ledger: Ledger
    results: Results
    key: str
    snapshot_version: str
    http: Callable[[Cell], Any] | None = None
    clocks: dict = field(default_factory=dict)


class GuardedTransport:
    """A cell's OpenRouter transport behind the ledger: intent before, receipt after."""

    def __init__(self, inner: Any, ledger: Ledger, cell: Cell):
        self._inner, self._ledger, self._cell = inner, ledger, cell
        self.messages = self
        self.dispatches: list[dict] = []
        self.cap_hit = False

    def create(self, **request):
        from zylch.llm.budget_pricing import micro_usd
        from zylch.llm.openrouter_pricing import request_bound

        if request.get("model") != self._cell.arm:
            raise RuntimeError(f"{self._cell.key}: a request for {request.get('model')!r}")
        # The engine's own reservation for this exact dict (K3 through its adapter).
        bound = request_bound(request)
        try:
            intent = self._ledger.admit(self._cell.key, len(self.dispatches), bound, self._cell.arm)
        except CapExceeded:
            self.cap_hit = True
            raise
        record: dict[str, Any] = {"intent": intent, "bound_micro_usd": bound}
        self.dispatches.append(record)
        started = time.perf_counter()
        try:
            raw = self._inner.create(**request)
        except BaseException as exc:  # uncertain: the bound stays committed, never retried
            record["error"] = f"{type(exc).__name__}: {exc}"
            self._ledger.fail(intent, record["error"])
            raise
        usage = getattr(raw, "usage", None)
        usage = dict(usage) if isinstance(usage, dict) else {}
        try:
            cost = micro_usd(usage["cost"]) if usage.get("cost") is not None else None
        except Exception:  # noqa: BLE001 - an unreadable receipt counts at the bound
            cost = None
        record.update(latency_ms=round((time.perf_counter() - started) * 1000), cost=cost)
        record["usage"] = {k: v for k, v in usage.items() if k != "cost"}
        self._ledger.settle(intent, cost, record["usage"])
        logger.debug(f"[measure] {intent} bound={bound} cost={cost}")
        return raw


@contextmanager
def measurement_profile(key: str, cap: Decimal):
    """A disposable profile: ``.env`` mode 600 with the provider and key, all deleted after.

    The profile's daily budget is twice the cap. The engine reserves before
    the transport, so an equal budget would refuse first and the run would
    record refusals instead of stopping; the measurement's ledger — whose
    intents outlive the run — must be the cap that binds, and the engine's
    budget stays the backstop should the ledger ever fail to.
    """
    from zylch.storage import database

    root = Path(tempfile.mkdtemp(prefix="measurement-profile-"))
    saved = dict(os.environ)
    try:
        fd = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                f"LLM_PROVIDER=openrouter\n{KEY_ENV}={key}\nLLM_DAILY_BUDGET_USD={2 * cap}\n"
                f"OWNER_ID={OWNER}\nEMAIL_ADDRESS={OWNER}@example.invalid\n"
            )
        os.environ.update(
            ZYLCH_PROFILE_DIR=str(root),
            ZYLCH_DB_PATH=str(root / "zylch.db"),
            ZYLCH_HOME=str(root / "home"),
            MEMORY_DB_DIR=str(root / "memory"),
            OWNER_ID=OWNER,
            EMAIL_ADDRESS=f"{OWNER}@example.invalid",
        )
        database.dispose_engine()
        database.init_db()
        yield root
    finally:
        database.dispose_engine()
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(root, ignore_errors=True)


def cell_client(ctx: Context, cell: Cell, *, other_profile: bool) -> tuple[Any, GuardedTransport]:
    """The engine's client for the cell's arm, its transport behind the ledger."""
    from zylch.llm import make_llm_client

    client = make_llm_client(model=cell.arm)
    if other_profile:
        # The agent harness runs the turn in its own throwaway profile; the
        # fingerprint guards a profile's settings changing under a live client,
        # which this deliberate use from another profile is not.
        client._saved_policy_fingerprint = None
    if ctx.http is not None:
        client._client._http = ctx.http(cell)
    guard = GuardedTransport(client._client, ctx.ledger, cell)
    client._client = guard
    return client, guard


def replay_kwargs(entry: dict, arm: str) -> dict:
    """The captured request for ``arm``: no captured model or sampling, the arm's model."""
    request = {k: v for k, v in entry["request"].items() if k not in ("model", *SAMPLING)}
    request["model"] = arm
    return request


def clock_for(ctx: Context, capture_now: str):
    """The run clock of a replay: the client's datetime line at the case's capture moment."""
    from zylch.llm.client import RunClock

    if capture_now not in ctx.clocks:
        ctx.clocks[capture_now] = RunClock(line=common.datetime_line(capture_now))
    return ctx.clocks[capture_now]


def answer_of(response: Any) -> dict:
    """The answer of one response: its calls, its text, its stop reason, its block kinds."""
    blocks = getattr(response, "content", None) or []
    calls = [{"name": b.name, "input": dict(b.input or {})} for b in blocks if b.type == "tool_use"]
    text = "".join(b.text for b in blocks if b.type == "text")
    kinds = [b.get("type") for b in getattr(response, "assistant_content", []) or []]
    return {
        "calls": calls,
        "text": text,
        "stop_reason": getattr(response, "stop_reason", None),
        "first": calls,
        "later": [],
        "blocks": kinds,
    }


def price_refusal(model: str) -> str | None:
    """The engine's refusal to reserve for ``model`` on OpenRouter, or None when it prices it."""
    from zylch.llm.budget_pricing import BudgetError
    from zylch.llm.openrouter_pricing import request_bound

    probe = {"model": model, "messages": [{"role": "user", "content": "probe"}], "max_tokens": 1}
    try:
        request_bound(probe)
    except BudgetError as refused:
        return str(refused)
    return None


def base_row(
    run: RoleRun, arm: dict, case: dict, repetition: int, status: str, error: str | None = None
) -> dict:
    """The fields every result row carries; a cell that sent nothing has only these."""
    return {
        "schema": 1,
        "cell": Cell(run.role, arm["id"], case["id"], repetition).key,
        "role": run.role,
        "arm": arm["id"],
        "reference": arm["reference"],
        "arm_index": arm["index"],
        "arm_score": arm["score"],
        "case_id": case["id"],
        "repetition": repetition,
        "status": status,
        "error": error,
        "case_set_sha256": run.requests["case_set_sha256"],
        "prompt_sha256": run.requests["prompt_sha256"],
        "at": now(),
    }
