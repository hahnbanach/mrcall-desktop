"""Ordinary email intake, including ownership after RPC cancellation."""
import asyncio
import threading
from datetime import datetime, timezone

import pytest

from zylch.rpc import setup
from zylch.services import process_pipeline as pipeline
from zylch.storage.storage import Storage
from tests.email.test_multi_mailbox_sync import env, OWNER, SECOND, _servers, _inbox, _rows
from tests.email.fake_imap import build_raw_message, make_client


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", "fake-test-password")
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: object())


@pytest.mark.asyncio
@pytest.mark.parametrize("params,wa", [({}, True), ({"scope": "all"}, True),
                                       ({"scope": "email", "days_back": 14}, False)])
async def test_channels(configured, monkeypatch, params, wa):
    calls = []
    async def email(*a, **kw):
        calls.append("email")
        return {"success": True, "new_messages": 1, "errors": []}
    monkeypatch.setattr(pipeline, "_run_sync", email)
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", lambda *a: calls.append("wa") or {"messages": 2})
    result = await setup.sync_run(params, lambda *a: None)
    assert result["success"] is True
    assert calls == (["email", "wa"] if wa else ["email"])
    if not wa:
        assert result["scope"] == "email"
        assert result["result"]["wa_messages"] == result["result"]["wa_contacts"] == 0
        assert result["result"]["wa_skipped_reason"] == "Email-only scope."


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"scope": x} for x in [None, False, 1, "bad"]] +
                         [{"scope": "email", "days_back": x} for x in [None, False, 0, -1, 61, "14", 1.5]])
async def test_invalid_before_effects(configured, monkeypatch, params):
    async def forbidden(*a, **kw):
        pytest.fail("invalid parameters started intake")
    monkeypatch.setattr(pipeline, "run_sync_only", forbidden)
    result = await setup.sync_run(params, lambda *a: None)
    assert result["success"] is False
    if params["scope"] == "email":
        assert result["scope"] == "email"


@pytest.mark.asyncio
async def test_cancel_does_not_release_worker_ownership(configured, monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    async def slow(*a, **kw):
        started.set()
        try:
            assert release.wait(5)
            return {"success": True, "new_messages": 0, "errors": []}
        finally:
            finished.set()
    monkeypatch.setattr(pipeline, "_run_sync", slow)
    task = asyncio.create_task(setup.sync_run({"scope": "email"}, lambda *a: None))
    assert await asyncio.to_thread(started.wait, 2)
    try:
        busy = await setup.sync_run({"scope": "email"}, lambda *a: None)
        assert busy["scope"] == "email" and busy["busy"] is True and busy["success"] is False
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        busy = await setup.sync_run({"scope": "email"}, lambda *a: None)
        assert busy["busy"] is True and setup._email_intake_lock.locked()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        for _ in range(100):
            if not setup._email_intake_lock.locked():
                break
            await asyncio.sleep(.01)
    assert not setup._email_intake_lock.locked()
    result = await setup.sync_run({"scope": "email"}, lambda *a: None)
    assert result["scope"] == "email" and result["success"] is True


@pytest.mark.asyncio
async def test_email_failures_echo_scope(configured, monkeypatch):
    monkeypatch.delenv("EMAIL_PASSWORD")
    result = await setup.sync_run({"scope": "email"}, lambda *a: None)
    assert result["scope"] == "email" and result["success"] is False
    monkeypatch.setenv("EMAIL_PASSWORD", "fake")
    async def fail(*a, **kw):
        raise RuntimeError("failed mailbox access")
    monkeypatch.setattr(pipeline, "_run_sync", fail)
    result = await setup.sync_run({"scope": "email"}, lambda *a: None)
    assert result["scope"] == "email" and result["success"] is False and result["errors"]
    assert not setup._email_intake_lock.locked()


@pytest.mark.asyncio
async def test_exact_fresh_body_and_failed_uid_retry(env, monkeypatch):
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: env["store"])
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", lambda *a: pytest.fail("email intake invoked WhatsApp"))
    when = datetime.now(timezone.utc)
    mid = "<fresh-intake@client.test>"
    body = "Fresh complete body: calculate 234 + 52."
    folder = _inbox({10: build_raw_message(mid, date=when, body=body)})
    folder.fetch_errors.add(10)
    _servers(monkeypatch, {OWNER: lambda mb: make_client({"INBOX": folder}, email_addr=OWNER),
                          SECOND: lambda mb: make_client({"INBOX": _inbox({})}, email_addr=SECOND)})
    first = await setup.sync_run({"scope": "email", "days_back": 14}, lambda *a: None)
    assert first["scope"] == "email"
    assert _rows(env["db"], "SELECT body_plain FROM emails WHERE message_id_header=?", (mid,)) == []
    cursor = _rows(env["db"], "SELECT last_uid FROM email_sync_cursor_v2 WHERE owner_id=? AND mailbox_id=?", (OWNER, env["primary"].id))
    assert not cursor or cursor[0][0] < 10
    folder.fetch_errors.clear()
    second = await setup.sync_run({"scope": "email", "days_back": 14}, lambda *a: None)
    assert second["success"] is True and second["scope"] == "email"
    rows = _rows(env["db"], "SELECT thread_id,body_plain FROM emails WHERE message_id_header=?", (mid,))
    assert len(rows) == 1 and rows[0][0] == mid and body in rows[0][1]
    cursor = _rows(env["db"], "SELECT last_uid FROM email_sync_cursor_v2 WHERE owner_id=? AND mailbox_id=?", (OWNER, env["primary"].id))
    assert cursor[0][0] == 10


@pytest.mark.asyncio
async def test_submission_failure_releases_and_echoes(configured, monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("executor unavailable")
    monkeypatch.setattr(asyncio.get_running_loop(), "run_in_executor", fail)
    result = await setup.sync_run({"scope": "email"}, lambda *a: None)
    assert result["scope"] == "email" and result["success"] is False
    assert not setup._email_intake_lock.locked()


@pytest.mark.asyncio
async def test_worker_exception_releases_and_echoes(configured, monkeypatch):
    async def fail(*a, **kw):
        raise RuntimeError("unexpected worker exception")
    monkeypatch.setattr(setup, "_sync_run", fail)
    result = await setup.sync_run({"scope": "email"}, lambda *a: None)
    assert result["scope"] == "email" and result["success"] is False
    assert not setup._email_intake_lock.locked()
