"""The daily job's smoke: admitted against USD 0.20, expected to cost USD 0.05 (brief D8).

Brief D8 puts a smoke at "at most USD 0.05": the spend a smoke is expected to
settle at. The engine admits a call on its conservative bound instead (the
full output budget at the model-level price times the margin), and for a
call of a smoke of a model at the balanced ceiling that bound comes to about
USD 0.1 (the second call is admitted on the first's settled spend, not its
bound), so the job admits a smoke against a per-smoke cap of USD 0.20
(`decide.SMOKE_CAP_USD`) and flags one whose settled spend is above USD 0.05
(`decide.SMOKE_EXPECTED_USD`); the monthly cap is unchanged. Here the job's
own `Smoke` adapter runs the real `model_smoke.py` loop and journal, priced
by the engine on the committed fixture snapshot (`price_snapshot`), against
a scripted OpenRouter transport: nothing is paid. The flag is pinned on a run
of the job with fake edges (`model_table_world.py`).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal

import httpx
import pytest
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.llm.roles import catalogue
from zylch.storage import database

from .model_table_world import GENIUS, SCRIPTS, load_job
from .price_fixture import SONNET, fixture, priced_at
from .test_model_table_job import CHALLENGER, Rig

job = load_job()
OPUS = "anthropic/claude-opus-5.5"  # at the balanced ceiling: 20 per million output tokens
CAP = 200_000  # micro-USD: decide.SMOKE_CAP_USD
EXPECTED = 50_000  # micro-USD: decide.SMOKE_EXPECTED_USD
THINKING = {"type": "thinking", "thinking": "Look order 7 up.", "signature": "sig-1"}
CALL = {"type": "tool_use", "id": "tu-1", "name": "lookup_order", "input": {"order": 7}}
ANSWER = [{"type": "text", "text": "Order 7 has shipped."}]


@pytest.fixture
def loop(tmp_path, monkeypatch, price_snapshot):
    """The job's smoke adapter over the real `model_smoke`, whose client posts
    to a scripted OpenRouter; `sent` holds each body that reached it."""
    spec = importlib.util.spec_from_file_location("model_smoke", SCRIPTS / "model_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "model_smoke", module)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for key in ("ZYLCH_DB_PATH", "OWNER_ID", "LLM_DAILY_BUDGET_USD"):
        monkeypatch.setenv(key, "placeholder")  # restored after the profile sets them
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    sent: list[dict] = []

    def factory(transport: str, model: str):
        answers = [([THINKING, CALL], "tool_use"), (ANSWER, "end_turn")]

        def handler(request):
            sent.append(json.loads(request.content))
            content, stop = answers.pop(0)
            usage = {"input_tokens": 300, "output_tokens": 40, "cost": "0.002"}
            body = {"model": model, "content": content, "stop_reason": stop, "usage": usage}
            return httpx.Response(200, json=body)

        client = LLMClient(transport, api_key="synthetic", model=model)
        http = httpx.Client(transport=httpx.MockTransport(handler))
        client._client = OpenRouterClient("synthetic", http_client=http)
        return client

    monkeypatch.setattr(module, "_factory", factory)
    smoke = job.edges_of.Smoke(tmp_path / "work", job.decide.SMOKE_CAP_USD, Decimal(10))
    yield smoke, sent
    database.dispose_engine()


def journal(smoke) -> list[dict]:
    """The rows of the last smoke's journal (intent before each call, result after)."""
    path = smoke.work / f"smoke-{smoke.count}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def bounds(smoke) -> list[int]:
    """The bound each call of the last smoke was admitted at, from its journal."""
    return [row["bound_micro_usd"] for row in journal(smoke) if row["event"] == "intent"]


def test_the_job_admits_a_smoke_against_twenty_cents_and_expects_five():
    assert job.decide.SMOKE_CAP_USD == Decimal(CAP) / 10**6
    assert job.decide.SMOKE_EXPECTED_USD == Decimal(EXPECTED) / 10**6


def test_a_sonnet_class_smoke_is_admitted(loop):
    smoke, sent = loop
    out = smoke(SONNET)
    assert out["passed"] is True and len(sent) == 2
    first, second = bounds(smoke)
    assert 0 < first <= CAP and 0 < second <= CAP
    assert out["spent_usd"] == Decimal("0.004") <= job.decide.SMOKE_EXPECTED_USD


def test_a_smoke_at_the_balanced_ceiling_is_admitted_though_its_bound_is_above_five_cents(loop):
    smoke, sent = loop
    out = smoke(OPUS)
    assert out["passed"] is True and len(sent) == 2
    first, second = bounds(smoke)
    assert first > EXPECTED  # USD 0.05 as the admission cap would never send it
    # Each call is admitted on its bound plus what the smoke already spent: the
    # second on the first's settled spend, which the journal records after it.
    settled = [row["spent_micro_usd"] for row in journal(smoke) if row["event"] == "result"]
    assert first <= CAP and settled[0] + second <= CAP
    assert out["spent_usd"] == Decimal("0.004") <= job.decide.SMOKE_EXPECTED_USD


def test_a_call_whose_bound_would_cross_the_cap_is_not_sent(loop):
    smoke, sent = loop
    catalogue.set_layers(priced_at(fixture(), OPUS, input="12", output="60"), build=False)
    out = smoke(OPUS)
    assert sent == [] and bounds(smoke) == []  # nothing journaled, nothing sent
    assert out["passed"] is None and out["spent_usd"] == 0  # no result, never a failure
    assert out["detail"].startswith("not sent") and f"> cap {CAP} micro-USD" in out["detail"]


def test_a_smoke_settled_above_its_expected_spend_is_flagged(tmp_path):
    rig = Rig(tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run(smoke_costs={GENIUS: Decimal("0.08")}) == 0
    flag = "settled at USD 0.08, above the USD 0.05 expected"
    assert f"## Flags: smokes settled above their expected spend\n\n- smoke {GENIUS}: {flag}" in (
        rig.report
    )
    assert f"| smoke {GENIUS} | pick of economy / CHAT / ranking | 0.2 | 0.08 | passed |" in (
        rig.report
    )
    calls = rig.doc("ledger.json")["months"]["2026-10"][0]["calls"]
    assert calls[0]["spent_usd"] == "0.08" and calls[0]["flag"] == flag
    assert all("flag" not in call for call in calls[1:])  # measurements are not smokes
