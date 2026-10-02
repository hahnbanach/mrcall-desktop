"""``measure_roles.py`` on a small synthetic case set, through the scripted transport (no network).

The run is the script's own (``measure``/``run_all``): the disposable profile,
``make_llm_client`` for each arm, the one shape, the engine's reservation, the
OpenRouter transport with only its HTTP scripted (``measurement_dry``), K3
through its Chat adapter, the ledger guard and the scoring. These tests hold:

- the ledger records each intent before the call, and refuses a dispatch that
  would cross the cap (nothing sent, the run stops);
- a resumed run never repeats a dispatched intent;
- the model is the arm's, never the captured placeholder, sampling is dropped
  and the datetime line is the case's capture moment;
- every scoring reading bites: the tool not called, the wrong language, the
  wrong label, a critical outcome, and a case whose ``critical_on`` is empty is
  never critical;
- ``--repeat-disagreements`` runs the reference a second time on exactly the
  cases where an arm's label result disagrees with it — not the whole role, and
  no arm again.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import measure_roles  # noqa: E402
import measurement_common as common  # noqa: E402
import measurement_dry as dry  # noqa: E402
from measurement_ledger import Ledger  # noqa: E402
from measurement_runtime import (  # noqa: E402
    DRY_KEY,
    Context,
    Results,
    RoleRun,
    measurement_profile,
)

K3 = "moonshotai/kimi-k3"
SONNET = "anthropic/claude-sonnet-5.5"
FLASH = "xiaomi/mimo-v2.6-flash"
NOW = "2026-10-01T09:00:00Z"
IT_REASON = "Il cliente chiede un preventivo per le finestre e aspetta la nostra risposta entro la settimana."
EN_REASON = (
    "The customer asks for a quote for the windows and waits for our answer within the week."
)


def case(case_id, lang, label, critical_on, open_tasks=()):
    return {
        "id": case_id,
        "lang": lang,
        "expect_lang": lang,
        "call_site": "task.detect",
        "input": {"now": NOW, "open_tasks": list(open_tasks)},
        "label": label,
        "critical_on": critical_on,
        "critical": bool(critical_on),
    }


CASES = [
    case("td-1", "it", {"task_action": "create", "action_required": True}, ["none"]),
    case("td-2", "en", {"task_action": "none"}, []),
    case(
        "td-3",
        "it",
        {"task_action": "update", "target_task_id": "t-1"},
        ["none", "close"],
        [{"id": "t-1"}],
    ),
]


def answer(action, reason=IT_REASON, target=None):
    given = {
        "action_required": action == "create",
        "task_action": action,
        "urgency": "medium",
        "suggested_action": "Rispondere con il preventivo delle finestre",
        "title": "Preventivo finestre",
        "reason": reason,
    }
    if target:
        given["target_task_id"] = target
    return {"text": None, "tool": ("task_decision", given), "stop": "tool_use"}


TEXT_ONLY = {"text": "Il cliente chiede un preventivo.", "tool": None, "stop": "end_turn"}
RIGHT = {
    "td-1": answer("create"),
    "td-2": answer("none", EN_REASON),
    "td-3": answer("update", target="t-1"),
}
SCRIPT = {
    K3: RIGHT,
    SONNET: {
        "td-1": TEXT_ONLY,
        "td-2": answer("none", EN_REASON),
        "td-3": answer("close", target="t-1"),
    },
    FLASH: {
        "td-1": answer("create", EN_REASON),
        "td-2": answer("create", EN_REASON),
        "td-3": RIGHT["td-3"],
    },
}


def request(case_id):
    from zylch.workers.task_creation import TASK_DECISION_TOOL

    return {
        "case_id": case_id,
        "capture_now": NOW,
        "request": {
            "model": "measurement/capture",
            "temperature": 0,
            "system": "You decide whether the owner has a task. Write reasons in the email's language.",
            "messages": [{"role": "user", "content": f"Case {case_id}: an email arrived."}],
            "tools": [TASK_DECISION_TOOL],
            "tool_choice": {"type": "auto"},
            "max_tokens": 2048,
        },
    }


def runs():
    document = {"schema": 1, "role": "TASK_DETECTION", "cases": CASES}
    requests = {"case_set_sha256": "c" * 64, "prompt_sha256": "p" * 64}
    requests["requests"] = [request(c["id"]) for c in CASES]
    arms = [
        {"id": K3, "score": 43.6, "index": "intelligence", "reference": True},
        {"id": SONNET, "score": 56.0, "index": "intelligence", "reference": False},
        {"id": FLASH, "score": 37.9, "index": "intelligence", "reference": False},
    ]
    return [RoleRun("TASK_DETECTION", document, requests, arms)]


class Wire:
    """The scripted answers; notes every body and whether its intent preceded it."""

    def __init__(self, ledger_path, script=SCRIPT, crash_on=None):
        self.ledger_path, self.script, self.crash_on = ledger_path, script, crash_on
        self.bodies, self.intent_first = [], []

    def __call__(self, cell, body):
        lines = self.ledger_path.read_text().splitlines() if self.ledger_path.exists() else []
        last = json.loads(lines[-1]) if lines else {}
        self.intent_first.append(last.get("event") == "intent" and last.get("cell") == cell.key)
        self.bodies.append((cell, body))
        if self.crash_on == cell.key:
            raise Crash(cell.key)
        if callable(self.script):
            return self.script(cell, body)
        return self.script[cell.arm][cell.case_id]


class Crash(BaseException):
    """A process dying mid-dispatch: nothing after it runs."""


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path / "run"


def context(run_dir, wire, cap="20"):
    run_dir.mkdir(exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl", int(Decimal(cap) * 1_000_000), (DRY_KEY,))
    results = Results(run_dir / "results.jsonl", (DRY_KEY,))
    return Context(ledger, results, DRY_KEY, "test-snapshot", dry.scripted_http(wire))


def measured(run_dir, wire, cap="20", repeat=False, role_runs=None):
    ctx = context(run_dir, wire, cap)
    with measurement_profile(DRY_KEY, Decimal(cap)):
        code = measure_roles.run_all(ctx, role_runs or runs(), repeat)
    return code, ctx


def by_cell(ctx):
    return {(r["arm"], r["case_id"], r["repetition"]): r for r in ctx.results.rows}


def test_every_intent_is_written_before_its_call_and_every_call_settles(run_dir):
    wire = Wire(run_dir / "ledger.jsonl")
    code, ctx = measured(run_dir, wire)
    assert code == 0 and len(wire.bodies) == 9
    assert all(wire.intent_first), wire.intent_first
    rows = ctx.ledger.rows()
    intents = [r for r in rows if r["event"] == "intent"]
    settled = {r["id"] for r in rows if r["event"] == "settle" and r["source"] == "receipt"}
    assert len(intents) == 9 and {r["id"] for r in intents} == settled
    assert ctx.ledger.totals()["open_intents"] == 0


def earlier_spend(run_dir, micro_usd):
    """An earlier run's settled dispatch in the ledger: the engine's fresh profile never saw it."""
    run_dir.mkdir(exist_ok=True)
    rows = [
        {"event": "intent", "id": "earlier#d0", "cell": "earlier", "bound_micro_usd": micro_usd},
        {"event": "settle", "id": "earlier#d0", "cost_micro_usd": micro_usd, "source": "receipt"},
    ]
    (run_dir / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_the_ledger_refuses_a_dispatch_that_would_cross_the_cap_and_stops_the_run(run_dir):
    earlier_spend(run_dir, 999_000)  # USD 0.999 of a USD 1 cap; one K3 bound is far more
    wire = Wire(run_dir / "ledger.jsonl")
    code, ctx = measured(run_dir, wire, cap="1")
    assert code == measure_roles.EXIT_CAP and wire.bodies == []
    assert [r["event"] for r in ctx.ledger.rows()] == ["intent", "settle"]
    row = ctx.results.rows[0]
    assert len(ctx.results.rows) == 1 and row["status"] == "cap"
    assert "> cap 1.00 USD; not sent" in row["error"]


def test_a_cap_below_one_request_sends_nothing(run_dir):
    wire = Wire(run_dir / "ledger.jsonl")
    code, ctx = measured(run_dir, wire, cap="0.000001")
    assert code == measure_roles.EXIT_CAP
    assert wire.bodies == [] and not [r for r in ctx.ledger.rows() if r["event"] == "intent"]
    assert [r["status"] for r in ctx.results.rows] == ["cap"]


def test_an_unpriced_arm_sends_nothing_and_runs_again_when_resumed(run_dir):
    unpriced = "acme/model-without-a-price"
    role_runs = runs()
    role_runs[0].arms.append(
        {"id": unpriced, "score": 30.0, "index": "intelligence", "reference": False}
    )
    wire = Wire(run_dir / "ledger.jsonl")
    code, ctx = measured(run_dir, wire, role_runs=role_runs)
    rows = [r for r in ctx.results.rows if r["arm"] == unpriced]
    assert code == 0 and [r["status"] for r in rows] == ["unpriced"] * 3
    assert "price" in rows[0]["error"] and len(wire.bodies) == 9
    assert not [r for r in ctx.ledger.rows() if unpriced in r.get("cell", "")]
    assert not ctx.results.done() & {r["cell"] for r in rows}  # tried again on a resume


def test_a_row_sums_its_usage_and_cost_from_the_receipts(run_dir):
    _code, ctx = measured(run_dir, Wire(run_dir / "ledger.jsonl"))
    row = by_cell(ctx)[(SONNET, "td-2", 1)]
    receipts = [r for r in ctx.ledger.rows() if r["event"] == "settle" and row["cell"] in r["id"]]
    assert row["cost_micro_usd"] == sum(r["cost_micro_usd"] for r in receipts) > 0
    assert row["usage"]["input_tokens"] > 0 and row["usage"]["output_tokens"] == 64
    assert row["latency_ms"] >= 0 and row["answer"]["calls"][0]["name"] == "task_decision"


def test_a_resumed_run_does_not_repeat_a_dispatched_intent(run_dir):
    crashed = f"TASK_DETECTION|{SONNET}|td-2|r1"
    first = Wire(run_dir / "ledger.jsonl", crash_on=crashed)
    with pytest.raises(Crash):
        measured(run_dir, first)
    again = Wire(run_dir / "ledger.jsonl")
    code, ctx = measured(run_dir, again)
    assert code == 0
    sent_again = [cell.key for cell, _body in again.bodies]
    assert crashed not in sent_again and len(sent_again) == 9 - len(first.bodies)
    assert by_cell(ctx)[(SONNET, "td-2", 1)]["status"] == "interrupted"
    intents = [r["id"] for r in ctx.ledger.rows() if r["event"] == "intent"]
    assert len(intents) == len(set(intents)) == 9


def test_the_model_is_the_arm_s_the_sampling_goes_and_the_clock_is_the_case_s(run_dir):
    wire = Wire(run_dir / "ledger.jsonl")
    measured(run_dir, wire)
    line = common.datetime_line(NOW)
    for cell, body in wire.bodies:
        assert body["model"] == cell.arm
        if cell.arm == K3:  # Chat adapter: max effort, the pinned provider, its own temperature
            assert body["reasoning"] == {"effort": "max"} and body["provider"]["only"]
            assert body["temperature"] == 1 and body["messages"][0]["content"].endswith(line)
        else:
            system = body["system"]
            assert "temperature" not in body and "tool_choice" in body
            assert (system if isinstance(system, str) else system[-1]["text"]).endswith(line)


def test_each_scoring_reading_bites(run_dir):
    _code, ctx = measured(run_dir, Wire(run_dir / "ledger.jsonl"))
    rows = by_cell(ctx)
    good = rows[(K3, "td-1", 1)]["scoring"]
    assert good["label_match"] and good["bars_ok"] and good["language"]["ok"] is True
    no_tool = rows[(SONNET, "td-1", 1)]["scoring"]
    assert no_tool["bars"]["tool_called"] is False and not no_tool["bars_ok"]
    assert not no_tool["label_match"] and not no_tool["critical"]  # invalid is never critical
    wrong_language = rows[(FLASH, "td-1", 1)]["scoring"]
    assert wrong_language["label_match"] and wrong_language["bars"]["language"] is False
    assert wrong_language["language"]["detected"] == "en" and not wrong_language["bars_ok"]
    critical = rows[(SONNET, "td-3", 1)]["scoring"]
    assert critical["outcome"] == "close" and critical["critical"]
    harmless = rows[(FLASH, "td-2", 1)]["scoring"]
    assert not harmless["label_match"] and not harmless["critical"]  # critical_on is empty


def test_repeat_disagreements_reruns_only_the_reference_on_the_disputed_cases(run_dir):
    # td-2: every arm's label agrees with the reference's; td-1 and td-3: Sonnet's does not.
    script = {**SCRIPT, FLASH: {**SCRIPT[FLASH], "td-2": answer("none", EN_REASON)}}
    wire = Wire(run_dir / "ledger.jsonl", script=script)
    _code, ctx = measured(run_dir, wire, repeat=True)
    second = sorted((r["arm"], r["case_id"]) for r in ctx.results.rows if r["repetition"] == 2)
    assert second == [(K3, "td-1"), (K3, "td-3")]
    assert len(wire.bodies) == 9 + 2


def chat_run():
    """CHAT's first committed case, its turn continued through the harness's ``run_case``."""
    document = common.load_document("CHAT")
    document["cases"] = [c for c in document["cases"] if c["id"] == "chat-01"]
    arms = [
        {"id": K3, "score": 50.0, "index": "agentic", "reference": True},
        {"id": SONNET, "score": 57.7, "index": "agentic", "reference": False},
    ]
    harness = common.load_harness("CHAT")
    return RoleRun("CHAT", document, common.load_requests("CHAT"), arms, harness)


def chat_turn(cell, body):
    """Search the memory first, then answer with what it found."""
    if dry.continuing(body):
        return {"text": "Edil Ferretti è il cliente: ultimo ordine a settembre.", "tool": None}
    return {
        "text": None,
        "tool": ("search_local_memory", {"query": "Ferretti"}),
        "stop": "tool_use",
    }


def test_a_chat_turn_runs_every_dispatch_behind_its_intent_on_the_capture_clock(run_dir):
    wire = Wire(run_dir / "ledger.jsonl", script=chat_turn)
    _code, ctx = measured(run_dir, wire, role_runs=[chat_run()])
    rows = by_cell(ctx)
    for arm in (K3, SONNET):
        row = rows[(arm, "chat-01", 1)]
        assert row["status"] == "scored" and len(row["dispatches"]) == 2
        assert row["scoring"]["label_match"], row["scoring"]
    assert all(wire.intent_first) and len(wire.bodies) == 4
    line = common.datetime_line(common.default_capture_now())
    for cell, body in wire.bodies:
        system = body["messages"][0]["content"] if cell.arm == K3 else body["system"][-1]["text"]
        assert system.endswith(line), (cell.arm, system[-120:])
