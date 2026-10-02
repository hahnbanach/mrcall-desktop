"""K3's adapter decides its whole request: its wire bodies are pinned to 40b84ed's (brief D3).

K3 (``k3_reasoning.py``) is the one per-model protocol adapter the brief keeps,
and the one request shape never touches it. The bodies in
``tests/fixtures/llm/k3_bodies_40b84ed.json`` were captured on
``model-selection-m10a`` 40b84ed, before the shape existed, through the real
``LLMClient.create_message_sync`` with the clock fixed: the OpenRouter Chat
body, and the ``request`` part of the MrCall credits quote body (pinning only
``request`` keeps the pin valid when a protocol marker joins it). One key
differs by design: the client's ``temperature`` 1.0 default went with the one
shape, so the Chat body carries the adapter's own default (``1``) and the
credits request carries none.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm import client as client_mod
from zylch.llm.bounded_proxy import BoundedProxyClient
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.k3_reasoning import MODEL
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage

GOLDEN = json.loads(
    (
        Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "k3_bodies_40b84ed.json"
    ).read_text()
)
TOOL = {
    "name": "lookup",
    "description": "Look up an order.",
    "input_schema": {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    },
}
LOOP = [
    {"role": "user", "content": "Find order 7."},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Searching."},
            {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {"q": "order 7"}},
        ],
    },
    {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "shipped"}],
    },
]
SCENARIOS = {
    "loop_auto": dict(
        system=[
            {"type": "text", "text": "You are a fixture.", "cache_control": {"type": "ephemeral"}}
        ],
        messages=LOOP,
        tools=[{**TOOL, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "auto"},
        max_tokens=512,
    ),
    "forced_tool": dict(
        system="Decide.",
        messages=[{"role": "user", "content": "Order 7?"}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "lookup"},
        max_tokens=300,
    ),
    "no_system": dict(messages=[{"role": "user", "content": "ping"}], max_tokens=40),
}


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "fixture")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.setattr(client_mod, "current_datetime_line", lambda: GOLDEN["clock"])
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmReservation.__table__, LlmUsage.__table__]
    )
    yield
    database.dispose_engine()


def _captured(transport, args):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(500)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    if transport == "openrouter":
        client = client_mod.LLMClient("openrouter", api_key="fixture", model=MODEL)
        client._client = OpenRouterClient("fixture", http_client=http)
    else:
        session = SimpleNamespace(id_token="fixture")
        client = client_mod.LLMClient("proxy", firebase_session=session, model=MODEL)
        client._client = BoundedProxyClient("https://synthetic.test", session, http_client=http)
    with pytest.raises(BudgetError):
        client.create_message_sync(**copy.deepcopy(args))
    return seen


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_k3_openrouter_body_is_40b84ed_s(pinned, name):
    seen = _captured("openrouter", SCENARIOS[name])
    assert seen["path"] == "/api/v1/chat/completions"
    body, golden = seen["body"], copy.deepcopy(GOLDEN["bodies"][name]["openrouter"])
    assert golden.pop("temperature") == 1.0
    assert body.pop("temperature") == 1
    assert body == golden


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_k3_credits_quote_request_is_40b84ed_s(pinned, name):
    seen = _captured("proxy", SCENARIOS[name])
    assert seen["path"].endswith("/quote")
    request, golden = seen["body"]["request"], copy.deepcopy(
        GOLDEN["bodies"][name]["quote_request"]
    )
    assert golden.pop("temperature") == 1.0
    assert "temperature" not in request
    assert request == golden
