"""Diagnostic originator failure paths; no paid calls."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "auto_caller", Path(__file__).parents[2] / "scripts/voice_m4_auto_call.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
UUID = "03871ec5c06c66c8c9a9267331d6fd48"


def test_lost_creation_response_retains_intent_and_blocks_restart(tmp_path):
    path = tmp_path / "caller.db"
    requests = []

    def wire(request):
        requests.append(request)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT state,reserved_microusd FROM attempts").fetchone() == (
                "initiating",
                1_000_000,
            )
        body = json.loads(request.content)
        assert body["to"][0]["number"] == body["from"]["number"] == driver.NUMBER
        assert all(a["action"] in {"wait", "talk"} for a in body["ncco"])
        raise httpx.ReadTimeout("lost", request=request)

    client = httpx.Client(
        base_url="https://example.invalid/v1", transport=httpx.MockTransport(wire)
    )
    caller = driver.DiagnosticCaller(path, client)
    with pytest.raises(httpx.ReadTimeout):
        caller.run("clock")
    caller.db.close()
    restarted = driver.DiagnosticCaller(path, client)
    with pytest.raises(RuntimeError, match="Unresolved"):
        restarted.run("privacy")
    assert len(requests) == 1


@pytest.mark.parametrize("fail_status", [False, True])
def test_known_uuid_finalizes_after_error_and_retains_receipt(tmp_path, fail_status):
    calls = []

    def wire(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"uuid": UUID})
        if request.method == "PUT":
            assert json.loads(request.content) == {"action": "hangup"}
            return httpx.Response(200, json={})
        if fail_status and "PUT" not in calls:
            raise httpx.ReadTimeout("status unavailable", request=request)
        return httpx.Response(
            200, json={"uuid": UUID, "status": "completed", "price": "0.0123", "duration": "42"}
        )

    client = httpx.Client(
        base_url="https://example.invalid/v1", transport=httpx.MockTransport(wire)
    )
    caller = driver.DiagnosticCaller(tmp_path / "caller.db", client, sleep=lambda _: None)
    if fail_status:
        with pytest.raises(httpx.ReadTimeout):
            caller.run("correction")
        assert "PUT" in calls
    else:
        caller.run("clock")
        assert "PUT" not in calls
    row = caller.db.execute("SELECT * FROM attempts").fetchone()
    assert row["state"] == "closed" and row["provider_uuid"] == UUID
    assert row["reserved_microusd"] == 1_000_000
    assert json.loads(row["receipt"])["price"] == "0.0123"
    assert len([m for m in calls if m == "POST"]) == 1


def test_failed_hangup_remains_unresolved(tmp_path):
    def wire(request):
        if request.method == "POST":
            return httpx.Response(201, json={"uuid": UUID})
        raise httpx.ReadTimeout("unavailable", request=request)

    client = httpx.Client(
        base_url="https://example.invalid/v1", transport=httpx.MockTransport(wire)
    )
    caller = driver.DiagnosticCaller(tmp_path / "caller.db", client)
    with pytest.raises(httpx.ReadTimeout):
        caller.run("clock")
    row = caller.db.execute("SELECT * FROM attempts").fetchone()
    assert row["state"] == "active" and row["provider_uuid"] == UUID
    with pytest.raises(RuntimeError, match="Unresolved"):
        caller.run("clock")
