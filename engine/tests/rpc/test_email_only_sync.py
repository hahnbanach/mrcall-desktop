import asyncio
import json
import threading

import pytest

from zylch.rpc import setup
from zylch.rpc.dispatch import INVALID_PARAMS, dispatch_raw


@pytest.mark.parametrize("scope", ["all", "email"])
def test_sync_dispatch_rejects_unknown_parameters_before_work(monkeypatch, scope):
    async def forbidden(*args, **kwargs):
        pytest.fail("Unknown RPC parameter entered synchronization")

    monkeypatch.setattr(setup, "_sync_run", forbidden)
    response = asyncio.run(
        dispatch_raw(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 19,
                    "method": "sync.run",
                    "params": {"scope": scope, "days_back": 2, "day_back": 1},
                }
            ),
            lambda *args: None,
        )
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 19,
        "error": {
            "code": INVALID_PARAMS,
            "message": "Unknown parameter(s) for sync.run: day_back",
        },
    }


@pytest.mark.parametrize(
    "scope,days",
    [("other", 1), ([], 1), ("email", True), ("email", 0), ("email", 61), ("email", "1")],
)
def test_invalid_email_intake_refuses_before_work(monkeypatch, scope, days):
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid intake entered worker")

    monkeypatch.setattr(setup, "_sync_run", forbidden)
    result = asyncio.run(setup.sync_run({"scope": scope, "days_back": days}, lambda *args: None))
    assert result["success"] is False


def test_rpc_email_only_scope_excludes_whatsapp_and_ai(monkeypatch):
    from zylch.services import process_pipeline as pipeline
    from zylch.storage.storage import Storage

    monkeypatch.setenv("EMAIL_ADDRESS", "owner@example.test")
    monkeypatch.setenv("EMAIL_PASSWORD", "disposable-fixture-password")
    monkeypatch.setattr(Storage, "get_instance", lambda: object())
    calls = []

    async def email(owner, store, days, **kwargs):
        calls.append((owner, days))
        return {"new_messages": 3}

    def whatsapp(*args, **kwargs):
        pytest.fail("Email-only RPC entered WhatsApp")

    monkeypatch.setattr(pipeline, "_run_sync", email)
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", whatsapp)
    result = asyncio.run(setup.sync_run({"scope": "email", "days_back": 2}, lambda *args: None))
    assert result["success"] and result["scope"] == "email"
    assert result["result"] == {
        "sync_new": 3,
        "wa_messages": 0,
        "wa_contacts": 0,
        "wa_skipped_reason": "Email-only scope.",
    }
    assert calls == [("owner@example.test", 2)]


def test_disconnected_intake_retains_single_flight_until_worker_finishes(monkeypatch):
    entered, released = threading.Event(), threading.Event()

    async def worker(*args, **kwargs):
        assert kwargs["email_only"] is True
        entered.set()
        assert await asyncio.to_thread(released.wait, 5)
        return {"success": True}

    monkeypatch.setattr(setup, "_sync_run", worker)

    async def run():
        task = asyncio.create_task(setup.sync_run({"scope": "email"}, lambda *args: None))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            result = await setup.sync_run({"scope": "email"}, lambda *args: None)
            assert result["busy"] is True and not result["success"]
        finally:
            released.set()
            await asyncio.gather(*setup._email_intake_futures)
        assert not setup._email_intake_lock.locked()

    asyncio.run(run())
