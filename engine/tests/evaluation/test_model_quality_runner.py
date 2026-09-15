"""Exercise the paid runner against a real isolated SQLite ledger and fake HTTP."""
import importlib.util
import io
import json
import logging
import os
import threading
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from zylch.llm import budget
from zylch.llm import client as llm
from zylch.llm import openrouter_pricing as pricing
from zylch.storage import database
from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

SCRIPT = Path(__file__).parents[2] / 'scripts/evaluate_model_quality.py'
MODEL = 'z-ai/glm-5.2'


@pytest.fixture
def rig(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('quality_runner', SCRIPT)
    monkeypatch.setattr(pricing, "RATES", dict(pricing.RATES))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    root = tmp_path / 'ledger'
    root.mkdir(mode=0o700)
    (root / '.env').write_text('OWNER_ID=synthetic\nLLM_DAILY_BUDGET_USD=1\n')
    marker = {'purpose': 'isolated-model-evaluation', 'owner': 'synthetic',
              'accounting_time': '2026-09-15T00:00:00', 'cap_usd': 1}
    (root / 'evaluation-ledger.json').write_text(json.dumps(marker))
    for key, value in {'ZYLCH_DB_PATH': str(root/'ledger.db'), 'ZYLCH_PROFILE_DIR': str(root),
                       'OWNER_ID': 'synthetic', 'EMAIL_ADDRESS': 'evaluation@example.test'}.items():
        monkeypatch.setenv(key, value)
    database.dispose_engine()
    database.Base.metadata.create_all(database.get_engine(), tables=[
        LlmUsage.__table__, LlmReservation.__table__, LlmBillingAuthorization.__table__])
    # Preserve runner's intentional process-wide clock/log/umask changes in tests.
    monkeypatch.setattr(budget, '_now', budget._now)
    monkeypatch.setattr(llm, 'current_datetime_line', llm.current_datetime_line)
    old_log = logging.root.manager.disable
    old_umask = os.umask(0o077)
    manifest = {'as_of': 'Current date/time: 2026-09-15T12:00:00Z', 'cases': [
        {'id': 'case-one', 'stage': 'memory.extract', 'request': {
            'messages': [{'role': 'user', 'content': 'Synthetic fixture'}], 'max_tokens': 20}}],
        'cells': [{'id': 'cell-one', 'case_id': 'case-one', 'model': MODEL}]}
    manifest_path = tmp_path / 'manifest.json'
    out = tmp_path / 'outputs'
    def run(handler, execute=True, per_model=1, max_active=4):
        manifest_path.write_text(json.dumps(manifest))
        real_http = httpx.Client
        def mocked(**kwargs):
            return real_http(transport=httpx.MockTransport(handler), **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(httpx, 'Client', mocked)
            patch.setattr(runner.sys, 'stdin', io.StringIO('synthetic-api-key'))
            patch.setattr(runner.sys, 'argv', ['runner', '--manifest', str(manifest_path),
                '--ledger', str(root), '--output', str(out), '--per-model', str(per_model), '--max-active', str(max_active)] + (['--execute'] if execute else []))
            runner.main()
        return [json.loads(x) for x in (out/'attempts.jsonl').read_text().splitlines()] if (out/'attempts.jsonl').exists() else []
    yield runner, root, out, manifest, run
    database.dispose_engine()
    logging.disable(old_log)
    os.umask(old_umask)


def returned(request):
    assert budget.budget_snapshot('synthetic')['reserved_usd'] > 0
    return httpx.Response(200, json={'id':'gen-synthetic','model':MODEL,
        'content':[{'type':'text','text':'SKIP'}], 'stop_reason':'end_turn',
        'usage':{'input_tokens':10,'output_tokens':2,'cost':0.00002}})


def test_dry_run_never_dispatches(rig):
    _, _, _, _, run = rig
    assert run(lambda request: pytest.fail('dry run dispatched'), False) == []


def test_intent_prevents_replay_and_secrets_never_journaled(rig):
    _, _, out, _, run = rig
    calls=[]
    def first(request):
        calls.append(request)
        return returned(request)
    rows=run(first)
    assert len(calls)==1 and rows[0]['event']=='intent'
    assert any(r['event']=='result' and r['status']=='returned' for r in rows)
    run(lambda request: pytest.fail('recorded intent replayed'))
    assert budget.budget_snapshot('synthetic')['spent_usd']==0.00002
    assert 'synthetic-api-key' not in (out/'attempts.jsonl').read_text()


def test_timeout_retains_hold_and_circuit_survives_resume(rig):
    _, _, _, manifest, run=rig
    manifest['cells']=[{'id':f'cell-{i}','case_id':'case-one','model':MODEL} for i in range(5)]
    calls=[]
    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout('synthetic uncertainty')
    rows=run(timeout)
    assert len(calls)==3
    assert sum(r['event']=='intent' for r in rows)==3
    held=budget.budget_snapshot('synthetic')['reserved_usd']
    assert held>0
    run(lambda request: pytest.fail('circuit reset on resume'))
    assert budget.budget_snapshot('synthetic')['reserved_usd']==held


def test_preexisting_usage_and_hold_prevent_dispatch(rig):
    _, _root, _, _, run=rig
    with database.get_engine().begin() as conn:
        conn.execute(LlmUsage.__table__.insert().values(id='old',owner_id='synthetic',
            ts=datetime(2026,9,15,1),est_cost_usd=.998))  # noqa: DTZ001 -- SQLite accounting timestamps intentionally use naive UTC
        conn.execute(LlmReservation.__table__.insert().values(id='old-hold',owner_id='synthetic',
            created_at=datetime(2026,9,14),model=MODEL,transport='openrouter',call_site='old',reserved_micro_usd=1000))  # noqa: DTZ001 -- SQLite accounting timestamps intentionally use naive UTC
    rows=run(lambda request: pytest.fail('old liabilities discarded'))
    assert rows[-1]['reason']=='budget'
    assert budget.budget_snapshot('synthetic')['spent_usd']==.998


def test_partial_journal_refuses_without_network(rig):
    _, _, out, _, run=rig
    out.mkdir(mode=0o700)
    (out/'attempts.jsonl').write_text('{"event":"intent"')
    with pytest.raises((ValueError, json.JSONDecodeError)):
        run(lambda request: pytest.fail('corrupt journal dispatched'))


def test_manifest_change_refuses_reuse(rig):
    _, _, _, manifest, run=rig
    run(returned)
    manifest['cases'][0]['request']['messages'][0]['content']='Changed input'
    with pytest.raises(ValueError,match='different manifest'):
        run(lambda request: pytest.fail('changed manifest dispatched'))


def test_marker_cannot_exclude_older_settled_usage(rig):
    runner, root, _, _, _ = rig
    with database.get_engine().begin() as conn:
        conn.execute(LlmUsage.__table__.insert().values(id='older',owner_id='synthetic',
            ts=datetime(2026,9,14,23),est_cost_usd=.5))  # noqa: DTZ001 -- SQLite accounting timestamps intentionally use naive UTC
    with pytest.raises(ValueError,match='omit previous'):
        runner.validate_scratch(root)


def test_symlinked_ledger_refused(rig):
    runner, root, _, _, _ = rig
    alias=root.parent/'alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError): runner.validate_scratch(alias)
    original=root/'ledger.db'
    moved=root/'real.db'
    original.rename(moved)
    original.symlink_to(moved)
    with pytest.raises(ValueError): runner.validate_scratch(root)


def test_truncated_responses_trip_completion_circuit(rig):
    _, _, _, manifest, run = rig
    manifest['cells']=[{'id':f'trunc-{i}','case_id':'case-one','model':MODEL} for i in range(5)]
    calls=[]
    def truncated(request):
        calls.append(request)
        response=returned(request)
        data=response.json();data['stop_reason']='max_tokens'
        return httpx.Response(200,json=data)
    rows=run(truncated)
    assert len(calls)==3
    assert sum(r['event']=='result' and r['status']=='returned' for r in rows)==3
    run(lambda request: pytest.fail('completion circuit reset on resume'))


@pytest.mark.parametrize("reviewed", [None, {
    "input_rate": "0.7", "output_rate": "2.2", "only": ["another-provider"]
}])
def test_unreviewed_routing_refuses_before_http(rig, reviewed):
    _, root, out, manifest, run = rig
    manifest["routing"] = {MODEL: {
        "input_rate": "0.7", "output_rate": "2.2", "only": ["digitalocean"]}}
    if reviewed is not None:
        path = root / "evaluation-ledger.json"
        marker = json.loads(path.read_text())
        marker["reviewed_routing"] = {MODEL: reviewed}
        path.write_text(json.dumps(marker))
    original_rates = pricing.RATES[MODEL]
    with pytest.raises(ValueError, match="no reviewed ledger authorization"):
        run(lambda request: pytest.fail("unreviewed routing dispatched"))
    assert pricing.RATES[MODEL] == original_rates
    assert not (out / "attempts.jsonl").exists()
    assert budget.budget_snapshot("synthetic")["reserved_usd"] == 0


def test_reviewed_routing_changes_wire_and_reservation_and_settles(rig):
    _, root, out, manifest, run = rig
    override = {"input_rate": "0.7", "output_rate": "2.2", "only": ["digitalocean"]}
    manifest["routing"] = {MODEL: override}
    path = root / "evaluation-ledger.json"
    marker = json.loads(path.read_text())
    marker["reviewed_routing"] = {MODEL: override}
    path.write_text(json.dumps(marker))
    old_rates = pricing.RATES[MODEL]
    seen = []
    def routed(request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["provider"]["only"] == ["digitalocean"]
        assert body["provider"]["max_price"] == {
            "prompt": "0.7", "completion": "2.2", "request": "0"}
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["require_parameters"] is True
        assert request.headers["X-OpenRouter-Metadata"] == "enabled"
        reserved_request = {k: v for k, v in body.items() if k not in {"provider", "thinking", "stream"}}
        reserved_request["service_tier"] = "standard_only"
        expected = pricing.request_bound(reserved_request)
        assert pricing.RATES[MODEL] == (Decimal("0.7"), Decimal("2.2"))
        pricing.RATES[MODEL] = old_rates
        try:
            old_bound = pricing.request_bound(reserved_request)
        finally:
            pricing.RATES[MODEL] = (Decimal("0.7"), Decimal("2.2"))
        assert expected > old_bound
        with database.get_engine().connect() as conn:
            hold = conn.execute(LlmReservation.__table__.select()).mappings().one()
            assert hold["reserved_micro_usd"] == expected
        return returned(request)
    rows = run(routed)
    assert len(seen) == 1
    result = next(r for r in rows if r["event"] == "result")
    assert result["status"] == "returned"
    assert result["http"]["provider_policy"] == seen[0]["provider"]
    snapshot = budget.budget_snapshot("synthetic")
    assert snapshot["spent_usd"] == 0.00002
    assert snapshot["reserved_usd"] == 0
    assert "synthetic-api-key" not in (out / "attempts.jsonl").read_text()


def test_concurrent_cases_freeze_independent_wire_clocks_and_bounds(rig):
    _, _, out, manifest, run = rig
    clocks = ["Current date/time: 2024-01-02T03:04:00Z",
              "Current date/time: 2025-06-07T08:09:00Z (" + "frozen " * 80 + ")"]
    manifest["cases"] = [
        {"id": f"case-{i}", "stage": "memory.extract", "datetime_line": clock,
         "request": {"messages": [{"role": "user", "content": f"Fixture {i}"}],
                     "system": "Frozen source policy", "max_tokens": 20}}
        for i, clock in enumerate(clocks)]
    manifest["cells"] = [{"id": f"cell-{i}", "case_id": f"case-{i}", "model": MODEL}
                         for i in range(2)]
    barrier = threading.Barrier(2)
    seen = {}
    def simultaneous(request):
        body = json.loads(request.content)
        i = int(body["messages"][0]["content"].split()[-1])
        system = json.dumps(body["system"])
        assert clocks[i] in system
        assert clocks[1-i] not in system
        assert manifest["as_of"] not in system
        reserved_request = {k: v for k, v in body.items()
                            if k not in {"provider", "thinking", "stream"}}
        reserved_request["service_tier"] = "standard_only"
        expected = pricing.request_bound(reserved_request)
        with database.get_engine().connect() as conn:
            hold = conn.execute(LlmReservation.__table__.select().where(
                LlmReservation.call_site == f"evaluation.controlled.cell-{i}"
            )).mappings().one()
        seen[f"cell-{i}"] = hold["reserved_micro_usd"]
        assert seen[f"cell-{i}"] == expected
        journal = [json.loads(line) for line in (out / "attempts.jsonl").read_text().splitlines()]
        intent = next(row for row in journal
                      if row["event"] == "intent" and row["cell_id"] == f"cell-{i}")
        assert intent["bound_micro_usd"] == hold["reserved_micro_usd"]
        # Both actual adapters must be active with distinct clock contexts.
        barrier.wait(timeout=10)
        return returned(request)
    rows = run(simultaneous, per_model=2)
    results = [r for r in rows if r["event"] == "result"]
    assert len(results) == 2 and all(r["status"] == "returned" for r in results)
    intents = {r["cell_id"]: r["bound_micro_usd"] for r in rows if r["event"] == "intent"}
    assert intents == seen
    assert seen["cell-1"] > seen["cell-0"]
    assert budget.budget_snapshot("synthetic")["reserved_usd"] == 0
    assert budget.budget_snapshot("synthetic")["spent_usd"] == 0.00004


@pytest.mark.parametrize("max_active", [1, 2])
def test_global_concurrency_cap_across_models(rig, max_active):
    _, _, _, manifest, run = rig
    models = [MODEL, "anthropic/claude-opus-5", "moonshotai/kimi-k3"]
    manifest["cells"] = [{"id": f"global-{i}", "case_id": "case-one", "model": model}
                         for i, model in enumerate(models)]
    state = {"active": 0, "peak": 0, "calls": 0}
    lock = threading.Lock()
    first_pair = threading.Barrier(2) if max_active == 2 else None
    def observed(request):
        with lock:
            state["active"] += 1
            state["calls"] += 1
            ordinal = state["calls"]
            state["peak"] = max(state["peak"], state["active"])
            assert state["active"] <= max_active
        try:
            if first_pair and ordinal <= 2:
                first_pair.wait(timeout=10)
            else:
                time.sleep(0.03)
            data = returned(request).json()
            data["model"] = json.loads(request.content)["model"]
            return httpx.Response(200, json=data)
        finally:
            with lock:
                state["active"] -= 1
    rows = run(observed, per_model=2, max_active=max_active)
    assert state == {"active": 0, "peak": max_active, "calls": 3}
    results = [r for r in rows if r["event"] == "result"]
    assert len(results) == 3 and all(r["status"] == "returned" for r in results)
    assert budget.budget_snapshot("synthetic")["reserved_usd"] == 0


def test_completed_wrong_contract_is_graded_without_availability_circuit(rig):
    _, _, _, manifest, run = rig
    manifest["cases"][0]["stage"] = "task.detect"
    manifest["cells"] = [{"id": f"contract-{i}", "case_id": "case-one", "model": MODEL}
                         for i in range(5)]
    rows = run(returned)
    results = [r for r in rows if r["event"] == "result"]
    assert len(results) == 5
    assert all(r["availability_ok"] and not r["completion_ok"] for r in results)
    assert not any(r["event"] == "not_dispatched" for r in rows)
    # Reconstructed streaks on resume obey the same distinction.
    run(lambda request: pytest.fail("completed contract failures replayed"))
