"""Paid smoke of the one request shape: a two-turn tool loop per model (M10 S1, AC 2).

Per model, two requests through the engine's own ``LLMClient`` — the one
shape, admission and the real transport — in a disposable profile, under one
``RunClock`` (one prefix for the loop):

1. the question needs the ``lookup_order`` tool; the answer must call it,
   reasoning blocks before it where the model reasons;
2. that assistant turn is replayed unchanged with the tool result; the answer
   must be text.

Direct transport (Anthropic, key ``MNEMONIC_ANTHROPIC_API_KEY``):
``claude-sonnet-5-5`` and ``claude-opus-5-5``, with the ``drop_block`` binding
and its beta header; the second answer's ``input_transformations`` must report
no ``prefix_binding_mismatch``. OpenRouter (key ``OPENROUTER_API_KEY``):
``anthropic/claude-sonnet-5.5``, ``anthropic/claude-opus-5.5``,
``qwen/qwen3.8-max-0902``, ``z-ai/glm-5.3-flash``. The credits leg belongs to
the billing server's slice.

Spend: a hard cap (USD 0.50) kept in ``smoke-ledger.jsonl`` in ``--ledger``.
Before each call its reservation bound — the engine's own, on the request the
client will send — is checked against the cap with everything already spent
or still uncertain, and written (fsync) as an intent; a call that would cross
the cap is not sent. The profile's daily budget is the cap too, so the
engine's own ledger refuses the same call. Nothing is retried. Keys come from
the environment only and are never printed or written.

    python scripts/model_smoke.py --ledger DIR            # dry run: plan and bounds
    python scripts/model_smoke.py --ledger DIR --execute  # paid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CAP_USD = 0.50
OWNER = "model-smoke"
KEYS = {"direct": "MNEMONIC_ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
MODELS = {
    "direct": ("claude-sonnet-5-5", "claude-opus-5-5"),
    "openrouter": (
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-opus-5.5",
        "qwen/qwen3.8-max-0902",
        "z-ai/glm-5.3-flash",
    ),
}
TOOL = {
    "name": "lookup_order",
    "description": "Look up an order's status by its number.",
    "input_schema": {
        "type": "object",
        "properties": {"order": {"type": "integer", "description": "The order number."}},
        "required": ["order"],
        "additionalProperties": False,
    },
}
SYSTEM = "You answer questions about orders. Look orders up with the lookup_order tool."
QUESTION = "What is the status of order 7? Look it up, then answer in one sentence."
QUESTION_TURN = {"role": "user", "content": QUESTION}
RESULT = '{"order": 7, "status": "shipped"}'
MAX_TOKENS = 512


class CapReached(RuntimeError):
    """The next call would cross the smoke's cap; it was not sent."""


class Ledger:
    """Every paid call of the smoke, recorded before it is sent (JSONL, fsync)."""

    def __init__(self, path: Path, cap_usd: float):
        self.path, self.cap = path, int(round(cap_usd * 1_000_000))

    def rows(self) -> List[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def used(self) -> int:
        """Micro-USD spent, plus the full bound of every call without a settled cost."""
        rows = self.rows()
        settled = {
            r["call"]: r["spent_micro_usd"]
            for r in rows
            if r["event"] == "result" and "spent_micro_usd" in r
        }
        return sum(
            settled.get(r["call"], r["bound_micro_usd"]) for r in rows if r["event"] == "intent"
        )

    def _write(self, row: dict) -> None:
        with self.path.open("a") as out:
            out.write(json.dumps(row) + "\n")
            out.flush()
            os.fsync(out.fileno())

    def admit(self, name: str, model: str, bound: int) -> str:
        """Record the intent of one call and return its id; refuse one past the cap."""
        used = self.used()
        if used + bound > self.cap:
            raise CapReached(f"{name}: bound {bound} + used {used} > cap {self.cap} micro-USD")
        call = f"{sum(r['event'] == 'intent' for r in self.rows()) + 1}:{name}"
        at = datetime.now(timezone.utc).isoformat()
        self._write(
            {"event": "intent", "call": call, "model": model, "bound_micro_usd": bound, "at": at}
        )
        return call

    def settle(self, call: str, spent: Optional[int], outcome: str) -> None:
        row = {"event": "result", "call": call, "outcome": outcome}
        if spent is not None:
            row["spent_micro_usd"] = spent
        self._write(row)


def _profile(ledger_dir: Path, cap_usd: float) -> None:
    """The disposable profile: a private directory whose database holds only the
    budget ledger, its own owner and a daily budget equal to the cap. A database
    holding anything else is refused: the smoke never runs on a real profile."""
    ledger_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ.update(
        ZYLCH_DB_PATH=str(ledger_dir / "profile.db"),
        OWNER_ID=OWNER,
        LLM_DAILY_BUDGET_USD=str(cap_usd),
    )
    os.environ.pop("ZYLCH_PROFILE_DIR", None)
    sys.path.insert(0, str(ENGINE_ROOT))
    import sqlalchemy

    from zylch.storage import database
    from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

    tables = [LlmReservation.__table__, LlmUsage.__table__, LlmBillingAuthorization.__table__]
    database.dispose_engine()
    engine = database.get_engine()
    if set(sqlalchemy.inspect(engine).get_table_names()) - {table.name for table in tables}:
        raise SystemExit("refused: the ledger directory's database is not a smoke ledger")
    database.Base.metadata.create_all(engine, tables=tables)


def _bound(client, transport: str, request: Dict[str, Any], clock) -> int:
    """The engine's own reservation bound for the request the client will send."""
    from zylch.llm.budget_pricing import request_bound
    from zylch.llm.client import _with_datetime
    from zylch.llm.request_shape import shaped
    from zylch.llm.response import _coerce_messages

    sent = {
        "model": client.model,
        "messages": _coerce_messages(request["messages"]),
        "max_tokens": MAX_TOKENS,
        "service_tier": "standard_only",
        "system": _with_datetime(SYSTEM, clock),
        "tools": [TOOL],
    }
    return request_bound(shaped(sent), transport)


def _spent() -> int:
    from zylch.llm.budget import budget_snapshot

    return int(round(budget_snapshot(OWNER)["spent_usd"] * 1_000_000))


def _call(client, transport, ledger, name, messages, clock):
    """One paid request: admitted against the cap and journaled first; never retried."""
    request = {"messages": messages}
    call = ledger.admit(name, client.model, _bound(client, transport, request, clock))
    before = _spent()
    try:
        response = client.create_message_sync(
            messages=messages, system=SYSTEM, tools=[TOOL], max_tokens=MAX_TOKENS, run_clock=clock
        )
    except Exception:
        ledger.settle(call, None, "uncertain")  # its full bound stays counted
        raise
    ledger.settle(call, _spent() - before, "returned")
    return response


def _reason(entry: Any) -> Optional[str]:
    return entry.get("reason") if isinstance(entry, dict) else getattr(entry, "reason", None)


def _mismatches(response) -> List[Any]:
    """``input_transformations`` entries that dropped a block for an edited prefix."""
    found = getattr(getattr(response, "_raw", None), "input_transformations", None) or []
    return [entry for entry in found if _reason(entry) == "prefix_binding_mismatch"]


def smoke_model(client, transport: str, ledger: Ledger) -> dict:
    """The two-turn loop on one model; a dict that says whether it passed and why not."""
    from zylch.llm.client import RunClock

    clock, model = RunClock(), client.model
    row = {"model": model, "transport": transport, "passed": False}
    messages = [QUESTION_TURN]
    try:
        first = _call(client, transport, ledger, f"{transport}:{model}:1", messages, clock)
        turn = first.assistant_content
        row["reasoning_blocks"] = sum(
            b.get("type") in ("thinking", "redacted_thinking") for b in turn
        )
        uses = [b for b in turn if b.get("type") == "tool_use" and b.get("name") == TOOL["name"]]
        if first.stop_reason != "tool_use" or not uses:
            row["failure"] = f"no lookup_order call (stop_reason={first.stop_reason})"
            return row
        messages = messages + [
            {"role": "assistant", "content": turn},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": uses[0]["id"], "content": RESULT}
                ],
            },
        ]
        second = _call(client, transport, ledger, f"{transport}:{model}:2", messages, clock)
    except CapReached as exc:
        row["failure"] = f"not sent: {exc}"
        return row
    except Exception as exc:  # noqa: BLE001 - recorded, never retried
        row["failure"] = f"{type(exc).__name__}: {exc}"
        return row
    text = "".join(getattr(b, "text", "") for b in second.content)
    row["answer"] = text
    if second.stop_reason != "end_turn" or not text.strip():
        row["failure"] = f"no text answer (stop_reason={second.stop_reason})"
    elif transport == "direct" and _mismatches(second):
        row["failure"] = f"prefix_binding_mismatch: {_mismatches(second)}"
    else:
        row["passed"] = True
    return row


def run(plan: Dict[str, tuple], factory: Callable[[str, str], Any], ledger: Ledger) -> List[dict]:
    """Every model of ``plan`` in order; a cap reached stops the run."""
    rows = []
    for transport, models in plan.items():
        for model in models:
            row = smoke_model(factory(transport, model), transport, ledger)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if row.get("failure", "").startswith("not sent"):
                return rows
    return rows


def _factory(transport: str, model: str):
    from zylch.llm.client import LLMClient

    return LLMClient(transport, api_key=os.environ[KEYS[transport]], model=model)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, required=True, help="disposable profile directory")
    parser.add_argument("--execute", action="store_true", help="send the paid requests")
    parser.add_argument("--cap-usd", type=float, default=CAP_USD)
    args = parser.parse_args(argv)
    if not 0 < args.cap_usd <= CAP_USD:
        parser.error(f"the cap is at most USD {CAP_USD}")
    _profile(args.ledger, args.cap_usd)
    from zylch.llm.request_shape import _metadata

    ledger = Ledger(args.ledger / "smoke-ledger.jsonl", args.cap_usd)
    plan = {t: m for t, m in MODELS.items() if os.environ.get(KEYS[t], "").strip()}
    missing = [t for t in MODELS if t not in plan]
    unknown = [m for models in plan.values() for m in models if _metadata(m) is None]
    # Each loop's first request, bounded as the engine will reserve it; the second
    # (the replayed turn and the tool result) is bounded before it is sent.
    first_bounds = {
        model: _bound(SimpleNamespace(model=model), transport, {"messages": [QUESTION_TURN]}, None)
        for transport, models in plan.items()
        for model in models
    }
    print(
        json.dumps(
            {
                "plan": plan,
                "keys_missing": missing,
                "metadata_missing": unknown,
                "first_call_bound_micro_usd": first_bounds,
                "cap_micro_usd": ledger.cap,
                "used_micro_usd": ledger.used(),
            }
        )
    )
    if not args.execute:
        return 0
    if missing or unknown:
        print("refused: every transport needs its key and every model its metadata", flush=True)
        return 1
    rows = run(plan, _factory, ledger)
    complete = len(rows) == sum(len(models) for models in plan.values())
    return 0 if complete and all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
