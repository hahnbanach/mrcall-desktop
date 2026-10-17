"""The paid smoke script, against scripted transports only (M10 S1, AC 2).

``scripts/model_smoke.py`` runs a two-turn tool loop per model through the
engine's own client; here every provider is a fake, so nothing is paid. What
is pinned: the ledger row of a call is written before the call, a call that
would cross the cap is never sent, nothing is retried, a
``prefix_binding_mismatch`` or a text answer instead of the tool fails the
model, and a dry run prints its plan and never a key.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm import request_shape
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.storage import database

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "model_smoke.py"
REASONING = {
    "reasoning": {"mandatory": True, "efforts": ["low", "high"], "default_enabled": None},
    "parameters": ["reasoning", "tools", "tool_choice", "structured_outputs"],
    "forced_tool": False,
    "structured_outputs": True,
    "context_length": 1_000_000,
    "expiration_date": None,
}
THINKING = {"type": "thinking", "thinking": "Look order 7 up.", "signature": "sig-1"}
CALL = {"type": "tool_use", "id": "tu-1", "name": "lookup_order", "input": {"order": 7}}
ANSWER = [{"type": "text", "text": "Order 7 has shipped."}]
MISMATCH = {
    "type": "thinking_dropped",
    "path": "messages.1.content.0",
    "reason": "prefix_binding_mismatch",
}


@pytest.fixture
def smoke(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("model_smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for key in ("ZYLCH_DB_PATH", "OWNER_ID", "LLM_DAILY_BUDGET_USD"):
        monkeypatch.setenv(key, "placeholder")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.setattr(request_shape, "_metadata", lambda model: REASONING)
    module._profile(tmp_path / "ledger", module.CAP_USD)
    yield module, tmp_path / "ledger"
    database.dispose_engine()


def _message(content, stop, transformations=()):
    from anthropic.types import Message

    return Message.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "input_transformations": list(transformations),
        }
    )


def _direct(ledger_path, answers, sent):
    def create(**kwargs):
        rows = [json.loads(line) for line in ledger_path.read_text().splitlines()]
        assert rows[-1]["event"] == "intent", "a call left before its ledger row"
        sent.append(kwargs)
        return answers.pop(0)

    client = LLMClient("direct", api_key="synthetic", model="claude-sonnet-5-5")
    client._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return client


def _router(ledger_path, model, answers, sent):
    def handler(request):
        rows = [json.loads(line) for line in ledger_path.read_text().splitlines()]
        assert rows[-1]["event"] == "intent", "a call left before its ledger row"
        sent.append(json.loads(request.content))
        content, stop = answers.pop(0)
        usage = {"input_tokens": 100, "output_tokens": 20, "cost": "0.0001"}
        return httpx.Response(
            200, json={"model": model, "content": content, "stop_reason": stop, "usage": usage}
        )

    client = LLMClient("openrouter", api_key="synthetic", model=model)
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client


def test_the_loop_passes_on_both_transports_with_each_call_journaled_first(smoke):
    module, root = smoke
    ledger = module.Ledger(root / "smoke-ledger.jsonl", module.CAP_USD)
    direct_sent, router_sent = [], []
    direct = [_message([THINKING, CALL], "tool_use"), _message(ANSWER, "end_turn")]
    router = [([THINKING, CALL], "tool_use"), (ANSWER, "end_turn")]
    clients = {
        "direct": _direct(ledger.path, direct, direct_sent),
        "openrouter": _router(ledger.path, "z-ai/glm-5.3-flash", router, router_sent),
    }
    plan = {"direct": ("claude-sonnet-5-5",), "openrouter": ("z-ai/glm-5.3-flash",)}
    rows = module.run(plan, lambda transport, model: clients[transport], ledger)
    assert [r["passed"] for r in rows] == [True, True], rows
    assert rows[0]["reasoning_blocks"] == 1 and rows[1]["answer"] == "Order 7 has shipped."
    assert direct_sent[1]["messages"][1]["content"][0] == THINKING
    assert direct_sent[1]["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert router_sent[1]["messages"][1]["content"][0] == THINKING
    events = [(r["event"], r["call"]) for r in ledger.rows()]
    assert [e for e, _ in events] == ["intent", "result"] * 4
    assert 0 < ledger.used() <= ledger.cap


def test_a_prefix_binding_mismatch_fails_the_model(smoke):
    module, root = smoke
    ledger = module.Ledger(root / "smoke-ledger.jsonl", module.CAP_USD)
    answers = [_message([THINKING, CALL], "tool_use"), _message(ANSWER, "end_turn", [MISMATCH])]
    client = _direct(ledger.path, answers, [])
    row = module.smoke_model(client, "direct", ledger)
    assert row["passed"] is False and "prefix_binding_mismatch" in row["failure"]


def test_a_text_answer_instead_of_the_tool_fails_and_is_not_retried(smoke):
    module, root = smoke
    ledger = module.Ledger(root / "smoke-ledger.jsonl", module.CAP_USD)
    sent = []
    client = _direct(ledger.path, [_message(ANSWER, "end_turn")], sent)
    row = module.smoke_model(client, "direct", ledger)
    assert row["passed"] is False and "no lookup_order call" in row["failure"]
    assert len(sent) == 1


def test_a_call_that_would_cross_the_cap_is_never_sent_and_stops_the_run(smoke):
    module, root = smoke
    ledger = module.Ledger(root / "smoke-ledger.jsonl", 0.000001)
    sent = []
    client = _direct(ledger.path, [], sent)
    plan = {"direct": ("claude-sonnet-5-5", "claude-opus-5-5")}
    rows = module.run(plan, lambda transport, model: client, ledger)
    assert len(rows) == 1 and rows[0]["failure"].startswith("not sent")
    assert sent == [] and ledger.rows() == []


def test_a_database_that_is_not_a_smoke_ledger_is_refused(smoke, tmp_path):
    import sqlite3

    module, _ = smoke
    other = tmp_path / "profile-like"
    other.mkdir(mode=0o700)
    with sqlite3.connect(other / "profile.db") as db:
        db.execute("CREATE TABLE emails (id TEXT)")
    with pytest.raises(SystemExit, match="not a smoke ledger"):
        module._profile(other, module.CAP_USD)


def test_a_dry_run_prints_the_plan_and_never_a_key(smoke, monkeypatch, capsys):
    module, root = smoke
    monkeypatch.setenv("MNEMONIC_ANTHROPIC_API_KEY", "sk-SENTINEL-DIRECT")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SENTINEL-ROUTER")
    monkeypatch.setattr(module, "_factory", lambda *a: pytest.fail("a dry run built a client"))
    assert module.main(["--ledger", str(root)]) == 0
    out = capsys.readouterr().out
    assert "SENTINEL" not in out
    assert json.loads(out.splitlines()[0])["plan"]["direct"] == list(module.MODELS["direct"])


def test_execute_refuses_a_model_without_metadata_before_any_call(smoke, monkeypatch, capsys):
    module, root = smoke
    monkeypatch.setenv("MNEMONIC_ANTHROPIC_API_KEY", "sk-SENTINEL-DIRECT")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SENTINEL-ROUTER")
    monkeypatch.setattr(request_shape, "_metadata", lambda model: None)
    monkeypatch.setattr(module, "_factory", lambda *a: pytest.fail("refused run built a client"))
    assert module.main(["--ledger", str(root), "--execute"]) == 1
    assert "SENTINEL" not in capsys.readouterr().out
