"""A provider's refusal before inference, in ``measure_roles.py``'s run (scripted transport, no network).

OpenRouter answers 429 when an upstream provider's shared pool is saturated
(``rate_limit_error``, ``limit_source: upstream_provider_shared_pool``): no
inference ran and nothing was charged. On the synthetic TASK_DETECTION run of
``test_measure_roles.py``, with the scripted wire raising an error that
carries its HTTP status (as the transport's does), these tests hold:

- a 429 is settled at zero (``refused``) and its cell is sent once more at
  the end of the role's pass, at least ``max(retry_after, 5 s)`` after the
  refusal, as a second intent; the second answer is the one scored and the
  row names the refusal;
- a 503 keeps its intent open at its bound and is never sent again;
- a cell refused twice is not sent a third time: it stays failed, its arm
  incomplete;
- a resumed run sends a cell refused once its second time, and nothing else;
- an agent turn (CHAT) refused at its first dispatch is sent again; one
  refused mid-turn is not, since its first dispatch is paid: the cell stays
  failed;
- a 401 or 403 stops the run (exit 1) and the denied cell is never sent again.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import measure_roles  # noqa: E402
from measurement_runtime import DRY_KEY, measurement_profile  # noqa: E402

from tests.measurement.test_measure_roles import (  # noqa: E402
    FLASH,
    K3,
    SCRIPT,
    SONNET,
    Crash,
    Wire,
    by_cell,
    chat_run,
    chat_turn,
    context,
    runs,
)


class ProviderError(Exception):
    """A non-200 answer as the OpenRouter transport raises it: the HTTP status attached."""

    def __init__(self, status_code: int, retry_after: float | None = None):
        super().__init__(f"OpenRouter request failed (HTTP {status_code}); no automatic retry.")
        self.status_code = status_code
        if retry_after is not None:
            self.retry_after = retry_after


def scripted(failures: dict):
    """``failures[(arm, case)]``: what that cell's successive dispatches get — a status (or
    ``(status, retry_after)``) raised, None for the right answer; every other one is answered."""
    seen: Counter = Counter()

    def answer(cell, body):
        key = (cell.arm, cell.case_id)
        plan, n = failures.get(key, []), seen[key]
        seen[key] += 1
        step = plan[n] if n < len(plan) else None
        if step is not None:
            raise ProviderError(*(step if isinstance(step, tuple) else (step,)))
        return SCRIPT[cell.arm][cell.case_id]

    return answer


def key(case_id, arm=SONNET):
    return f"TASK_DETECTION|{arm}|{case_id}|r1"


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / "run"


def measured(run_dir, wire, sleep=None, role_runs=None):
    """``run_all`` on the synthetic role; the waits recorded (or ``sleep`` called) instead."""
    slept: list[float] = []
    ctx = context(run_dir, wire)
    ctx.sleep = sleep or slept.append
    with measurement_profile(DRY_KEY, Decimal("20")):
        code = measure_roles.run_all(ctx, role_runs or runs(), False)
    return code, ctx, slept


def waited(ctx, cell_key, slept):
    """Seconds from the cell's refusal to its second intent, the tests' sleeps added (they
    return at once): the wait the run would have kept, whatever the machine's load."""
    rows = ctx.ledger.rows()
    refusal = next(
        r for r in rows if r.get("outcome") == "refused" and r["id"].startswith(cell_key)
    )
    again = [r for r in rows if r["event"] == "intent" and r["cell"] == cell_key][1]
    elapsed = datetime.fromisoformat(again["at"]) - datetime.fromisoformat(refusal["at"])
    return elapsed.total_seconds() + sum(slept)


def sent(wire):
    return [cell.key for cell, _body in wire.bodies]


def test_a_429_is_settled_at_zero_and_sent_once_more_after_the_role_s_pass(run_dir):
    wire = Wire(run_dir / "ledger.jsonl", script=scripted({(SONNET, "td-2"): [429]}))
    code, ctx, slept = measured(run_dir, wire)
    order = sent(wire)
    assert code == 0 and len(order) == 9 + 1
    assert order[-1] == key("td-2") and order.index(key("td-2")) < order.index(key("td-3", FLASH))
    rows = ctx.ledger.rows()
    intents = [r["id"] for r in rows if r["event"] == "intent" and r["cell"] == key("td-2")]
    assert intents == [f"{key('td-2')}#d0", f"{key('td-2')}#a2d0"]
    refusal = next(r for r in rows if r["event"] == "settle" and r["id"] == intents[0])
    assert (refusal["outcome"], refusal["cost_micro_usd"], refusal["status_code"]) == (
        "refused",
        0,
        429,
    )
    receipts = sum(r["cost_micro_usd"] for r in rows if r["event"] == "settle")
    assert ctx.ledger.committed() == receipts > 0  # the refused bound is not held
    final = by_cell(ctx)[(SONNET, "td-2", 1)]
    assert final["status"] == "scored" and final["attempt"] == 2
    assert final["scoring"]["label_match"] and final["refusals"][0]["status_code"] == 429
    assert waited(ctx, key("td-2"), slept) >= 5.0  # 5 s after the refusal, at least


def test_a_503_keeps_its_bound_and_is_never_sent_again(run_dir):
    wire = Wire(run_dir / "ledger.jsonl", script=scripted({(SONNET, "td-2"): [503, 503]}))
    code, ctx, slept = measured(run_dir, wire)
    assert code == 0 and sent(wire).count(key("td-2")) == 1 and slept == []
    intent = next(
        r for r in ctx.ledger.rows() if r["event"] == "intent" and r["cell"] == key("td-2")
    )
    assert ctx.ledger.totals()["open_intents"] == intent["bound_micro_usd"]
    assert ctx.ledger.next_attempt(key("td-2")) is None
    row = by_cell(ctx)[(SONNET, "td-2", 1)]
    assert row["status"] == "error" and "HTTP 503" in row["error"] and "refusals" not in row


def test_a_cell_refused_twice_is_not_sent_a_third_time(run_dir):
    plan = {(SONNET, "td-2"): [(429, 8), 429, None]}  # a third answer would be right
    wire = Wire(run_dir / "ledger.jsonl", script=scripted(plan))
    code, ctx, slept = measured(run_dir, wire)
    assert code == 0 and sent(wire).count(key("td-2")) == 2
    assert waited(ctx, key("td-2"), slept) >= 8.0  # the provider's retry_after: longer
    final = by_cell(ctx)[(SONNET, "td-2", 1)]
    assert final["status"] == "error" and final["error"].startswith(
        "refused twice before inference"
    )
    assert [r["attempt"] for r in final["refusals"]] == [1, 2]
    assert ctx.ledger.next_attempt(key("td-2")) is None and ctx.ledger.committed() > 0


def crash(_seconds):
    raise Crash("the run dies while waiting to send a refused cell again")


def test_a_resumed_run_sends_a_cell_refused_once_its_second_time_and_nothing_else(run_dir):
    plan = {(SONNET, "td-1"): [429], (SONNET, "td-2"): [503], (SONNET, "td-3"): [429]}
    first = Wire(run_dir / "ledger.jsonl", script=scripted(plan))
    with pytest.raises(Crash):
        measured(run_dir, first, sleep=crash)
    assert len(first.bodies) == 9  # every cell once; no second attempt yet
    second = Wire(run_dir / "ledger.jsonl", script=scripted({(SONNET, "td-3"): [429]}))
    code, ctx, slept = measured(run_dir, second)
    assert code == 0 and sorted(sent(second)) == sorted([key("td-1"), key("td-3")])
    rows = by_cell(ctx)
    assert rows[(SONNET, "td-1", 1)]["status"] == "scored"
    assert rows[(SONNET, "td-1", 1)]["attempt"] == 2
    assert rows[(SONNET, "td-2", 1)]["status"] == "error"  # the 503: never again
    assert rows[(SONNET, "td-3", 1)]["error"].startswith("refused twice before inference")
    third = Wire(run_dir / "ledger.jsonl", script=scripted({}))
    code, ctx, slept = measured(run_dir, third)
    assert code == 0 and third.bodies == [] and slept == []


def chat_refusing(refused: dict):
    """CHAT's scripted turn (search, then answer); ``refused[arm]``: the arm's dispatches,
    counted over the run, answered 429."""
    seen: Counter = Counter()

    def answer(cell, body):
        n = seen[cell.arm]
        seen[cell.arm] += 1
        if n in refused.get(cell.arm, ()):
            raise ProviderError(429)
        return chat_turn(cell, body)

    return answer


def test_an_agent_turn_refused_at_its_first_dispatch_is_sent_again(run_dir):
    wire = Wire(run_dir / "ledger.jsonl", script=chat_refusing({SONNET: {0}}))
    code, ctx, _slept = measured(run_dir, wire, role_runs=[chat_run()])
    cell = f"CHAT|{SONNET}|chat-01|r1"
    assert code == 0 and sent(wire).count(cell) == 3  # refused, then the whole turn
    row = by_cell(ctx)[(SONNET, "chat-01", 1)]
    assert row["status"] == "scored" and row["attempt"] == 2
    assert row["refusals"][0]["dispatch"] == 0


def test_an_agent_turn_refused_mid_turn_is_not_sent_again(run_dir):
    wire = Wire(run_dir / "ledger.jsonl", script=chat_refusing({SONNET: {1}}))
    code, ctx, slept = measured(run_dir, wire, role_runs=[chat_run()])
    cell = f"CHAT|{SONNET}|chat-01|r1"
    assert code == 0 and sent(wire).count(cell) == 2 and slept == []
    row = by_cell(ctx)[(SONNET, "chat-01", 1)]
    assert row["status"] == "error" and "mid-turn" in row["error"]
    assert row["refusals"][0]["dispatch"] == 1 and ctx.ledger.next_attempt(cell) is None
    paid = [r for r in ctx.ledger.rows() if r["event"] == "settle" and r["source"] == "receipt"]
    assert any(r["id"] == f"{cell}#d0" and r["cost_micro_usd"] > 0 for r in paid)
    assert by_cell(ctx)[(K3, "chat-01", 1)]["status"] == "scored"


@pytest.mark.parametrize("status", [401, 403])
def test_a_denied_key_stops_the_run_and_its_cell_is_never_sent_again(run_dir, status, capsys):
    wire = Wire(run_dir / "ledger.jsonl", script=scripted({(SONNET, "td-1"): [status]}))
    code, ctx, slept = measured(run_dir, wire)
    assert code == measure_roles.EXIT_DENIED == 1 and slept == []
    assert sent(wire)[-1] == key("td-1") and len(sent(wire)) == 3 + 1  # nothing after it
    assert "denied the key" in capsys.readouterr().err
    denial = ctx.ledger.denial(key("td-1"))
    assert denial["outcome"] == "denied" and denial["cost_micro_usd"] == 0
    assert by_cell(ctx)[(SONNET, "td-1", 1)]["status"] == "denied"
    again = Wire(run_dir / "ledger.jsonl", script=scripted({}))
    code, ctx, _slept = measured(run_dir, again)
    assert code == 0 and key("td-1") not in sent(again) and len(sent(again)) == 5
