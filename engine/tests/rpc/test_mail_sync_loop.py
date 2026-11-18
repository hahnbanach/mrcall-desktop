"""The daemon's own mail loop, and how an RPC caller meets one of its runs.

A hosted engine that is only read used to answer from an archive as old as the
last sync a client had asked for. The loop in ``rpc/server_ws.py`` runs the
email-only intake on its own. These tests cover what the loop runs, when it
runs nothing and says why, and the one place the loop and the RPC
``sync.run {scope: "email"}`` meet: the intake lock in ``rpc/setup.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import threading
import time
from datetime import datetime, timezone

import pytest
from rich.console import Console

from tests.email.fake_imap import build_raw_message, make_client
from tests.email.test_multi_mailbox_sync import (  # noqa: F401  (env is a fixture)
    OWNER,
    SECOND,
    _inbox,
    _rows,
    _servers,
    env,
)
from zylch.rpc import dispatch, server_ws, setup
from zylch.services import process_pipeline as pipeline
from zylch.storage.storage import Storage

_PRIVATE_LOGS = importlib.util.find_spec("zylch.observability_producers") is not None


def _ok(new: int = 0) -> dict:
    return {"success": True, "new_messages": new, "errors": []}


def _silent(*args, **kwargs) -> None:
    return None


async def _until(predicate, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _console(monkeypatch) -> io.StringIO:
    """Replace the pipeline's stderr console with one that writes into a buffer.

    The real console binds ``sys.stderr`` when the module is imported, so a
    capture fixture installed later does not see what it writes.
    """
    shown = io.StringIO()
    monkeypatch.setattr(pipeline, "console", Console(file=shown, width=200))
    return shown


class Gate:
    """A mailbox sync that holds its worker thread until the test releases it."""

    def __init__(self, new: int = 0):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list = []
        self.new = new

    async def __call__(self, owner_id, store, days_back, progress=None, **kwargs):
        self.calls.append(days_back)
        self.started.set()
        assert self.release.wait(5)
        return _ok(self.new)


@pytest.fixture(autouse=True)
def intake_state():
    """The intake lock is process-wide: every test starts and ends with it free."""
    assert not setup._email_intake_lock.locked()
    setup._email_intake_loop_run = None
    yield
    for _ in range(600):
        if not setup._email_intake_lock.locked():
            break
        time.sleep(0.01)
    assert not setup._email_intake_lock.locked()
    setup._email_intake_loop_run = None


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", "fake-test-password")
    monkeypatch.delenv("MAIL_SYNC_INTERVAL_MINUTES", raising=False)
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: object())


@pytest.fixture
def fast(monkeypatch):
    """Run the real loop with no start delay and a hundredth of a second between runs."""
    monkeypatch.setattr(server_ws, "_MAIL_SYNC_FIRST_DELAY_SECONDS", 0)
    monkeypatch.setattr(server_ws, "_MAIL_SYNC_DISABLED_POLL_SECONDS", 0.01)
    monkeypatch.setattr(server_ws, "_mail_sync_interval_seconds", lambda: 0.01)


# ─── the setting ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,seconds",
    [
        (None, 600),
        ("", 600),
        ("not-a-number", 600),
        ("10", 600),
        ("1", 120),
        ("2", 120),
        ("360", 21600),
        ("9999", 21600),
        ("0", 0),
        ("-5", 0),
    ],
)
def test_interval_setting(monkeypatch, raw, seconds):
    if raw is None:
        monkeypatch.delenv("MAIL_SYNC_INTERVAL_MINUTES", raising=False)
    else:
        monkeypatch.setenv("MAIL_SYNC_INTERVAL_MINUTES", raw)
    assert server_ws._mail_sync_interval_seconds() == seconds


# ─── what the loop runs ───────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_runs_the_email_only_intake_and_nothing_else(
    configured, fast, monkeypatch, caplog
):
    from zylch.rpc import methods

    reached: list = []

    async def email(owner_id, store, days_back, progress=None, **kwargs):
        reached.append(("email", days_back))
        return _ok(3)

    async def update(params, notify):
        reached.append(("update",))
        return {"success": True}

    async def paid_pipeline(*args, **kwargs):
        # Every entry into memory extraction and task detection passes here.
        reached.append(("pipeline",))
        return ""

    asked: list = []
    real_intake = setup._email_intake

    async def spy(params, notify, *, from_loop):
        asked.append((dict(params), from_loop))
        return await real_intake(params, notify, from_loop=from_loop)

    monkeypatch.setattr(pipeline, "_run_sync", email)
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", lambda *a: reached.append(("wa",)) or {})
    monkeypatch.setattr(methods, "update_run", update)
    monkeypatch.setattr(pipeline, "handle_process", paid_pipeline)
    monkeypatch.setattr(setup, "_email_intake", spy)
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        await _until(lambda: len(reached) >= 2)
    finally:
        await _stop(task)

    assert asked[0] == ({"scope": "email", "days_back": 14}, True)
    assert set(reached) == {("email", 14)}
    assert "[mail-sync] run completed new=3" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,line",
    [
        ("disabled", "[mail-sync] skipped: disabled"),
        ("credentials", "[mail-sync] skipped: no mail credentials"),
        ("pipeline", "[mail-sync] skipped: pipeline run in flight"),
    ],
)
async def test_tick_runs_nothing_and_says_why(configured, monkeypatch, caplog, case, line):
    started: list = []

    async def intake():
        started.append(1)
        return {"success": True, "busy": False, "result": {"sync_new": 0}, "errors": []}

    monkeypatch.setattr(setup, "email_intake_from_daemon", intake)
    caplog.set_level(logging.INFO)
    if case == "disabled":
        monkeypatch.setenv("MAIL_SYNC_INTERVAL_MINUTES", "0")
    if case == "credentials":
        monkeypatch.delenv("EMAIL_PASSWORD")
    if case == "pipeline":
        assert pipeline._pipeline_lock.acquire(blocking=False)
    try:
        await server_ws._mail_sync_tick()
    finally:
        if case == "pipeline":
            pipeline._pipeline_lock.release()

    assert started == []
    assert [r.getMessage() for r in caplog.records if "[mail-sync]" in r.getMessage()] == [line]


@pytest.mark.asyncio
async def test_disabled_loop_picks_up_a_later_setting(configured, monkeypatch, caplog):
    started: list = []

    async def intake():
        started.append(1)
        return {"success": True, "busy": False, "result": {"sync_new": 0}, "errors": []}

    monkeypatch.setattr(setup, "email_intake_from_daemon", intake)
    monkeypatch.setattr(server_ws, "_MAIL_SYNC_FIRST_DELAY_SECONDS", 0)
    monkeypatch.setattr(server_ws, "_MAIL_SYNC_DISABLED_POLL_SECONDS", 0.01)
    monkeypatch.setenv("MAIL_SYNC_INTERVAL_MINUTES", "0")
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        await _until(lambda: caplog.text.count("[mail-sync] skipped: disabled") >= 2)
        assert started == []
        monkeypatch.setenv("MAIL_SYNC_INTERVAL_MINUTES", "10")
        await _until(lambda: started == [1])
    finally:
        await _stop(task)


@pytest.mark.asyncio
async def test_crashing_run_is_logged_and_the_next_interval_runs(
    configured, fast, monkeypatch, caplog
):
    attempts: list = []

    async def intake():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("intake exploded")
        return {"success": True, "busy": False, "result": {"sync_new": 0}, "errors": []}

    monkeypatch.setattr(setup, "email_intake_from_daemon", intake)
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        await _until(lambda: len(attempts) >= 2)
    finally:
        await _stop(task)

    assert "[mail-sync] run crashed" in caplog.text
    assert "[mail-sync] run completed new=0" in caplog.text


@pytest.mark.asyncio
async def test_stopping_the_daemon_during_a_run_ends_the_loop_at_once(
    configured, fast, monkeypatch, caplog
):
    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        task.cancel()
        # The worker is still blocked: the loop must not wait for it.
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done == {task} and task.cancelled()
        assert setup._email_intake_lock.locked()
    finally:
        gate.release.set()
        await _stop(task)

    assert "[mail-sync] cancelled — exiting loop" in caplog.text
    assert gate.calls == [14]


# ─── where the loop and the RPC meet ──────────────────────────


@pytest.mark.asyncio
async def test_rpc_during_a_loop_run_receives_that_run(configured, monkeypatch):
    gate = Gate(new=7)
    monkeypatch.setattr(pipeline, "_run_sync", gate)

    loop_run = asyncio.create_task(setup.email_intake_from_daemon())
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        joiner = asyncio.create_task(setup.sync_run({"scope": "email", "days_back": 14}, _silent))
        await asyncio.sleep(0.05)
        assert not joiner.done()
    finally:
        gate.release.set()
    joined, own = await asyncio.gather(joiner, loop_run)

    assert joined is own
    assert joined["scope"] == "email" and joined["busy"] is False and joined["success"] is True
    assert joined["result"]["sync_new"] == 7
    assert gate.calls == [14]


@pytest.mark.asyncio
async def test_cancelled_joiner_leaves_the_run_and_the_loop_alone(
    configured, fast, monkeypatch, caplog
):
    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        joiner = asyncio.create_task(setup.sync_run({"scope": "email"}, _silent))
        await asyncio.sleep(0.05)
        joiner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await joiner
        # The run still owns the lock and the loop is still awaiting it.
        assert setup._email_intake_lock.locked()
        assert not task.done()
        gate.release.set()
        # The run ended, released the lock, and the next interval ran.
        await _until(lambda: len(gate.calls) >= 2)
        assert not task.done()
    finally:
        gate.release.set()
        await _stop(task)

    assert "run cancelled outside the loop" not in caplog.text
    assert caplog.text.count("[mail-sync] run completed") >= 1


@pytest.mark.asyncio
async def test_joined_run_that_raises_fails_both_callers_and_the_loop_continues(
    configured, fast, monkeypatch, caplog
):
    started, release = threading.Event(), threading.Event()
    runs: list = []

    async def exploding(params, notify, *, email_only=False):
        runs.append(dict(params))
        if len(runs) == 1:
            started.set()
            assert release.wait(5)
            raise RuntimeError("unexpected worker exception")
        return {"success": True, "summary": "", "result": {"sync_new": 0}, "errors": []}

    monkeypatch.setattr(setup, "_sync_run", exploding)
    caplog.set_level(logging.INFO)

    task = asyncio.create_task(server_ws._mail_sync_loop())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        joiner = asyncio.create_task(setup.sync_run({"scope": "email"}, _silent))
        await asyncio.sleep(0.05)
        assert not joiner.done()
        release.set()
        joined = await asyncio.wait_for(joiner, 2)
        await _until(lambda: len(runs) >= 2)
    finally:
        release.set()
        await _stop(task)

    assert joined["scope"] == "email" and joined["success"] is False and joined["busy"] is False
    assert joined["errors"]
    assert "[mail-sync] run finished with errors: Email synchronization failed." in caplog.text


@pytest.mark.asyncio
async def test_rpc_is_busy_during_an_rpc_run_also_right_after_a_loop_run(configured, monkeypatch):
    async def quick(owner_id, store, days_back, progress=None, **kwargs):
        return _ok()

    monkeypatch.setattr(pipeline, "_run_sync", quick)
    first = await setup.email_intake_from_daemon()
    assert first["success"] is True
    # The finished loop run is still named: nothing clears it when it ends.
    assert setup._email_intake_loop_run is not None

    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)
    rpc = asyncio.create_task(setup.sync_run({"scope": "email"}, _silent))
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        # The RPC that took the lock reset it, so the next RPC cannot join the old run.
        assert setup._email_intake_loop_run is None
        second = await setup.sync_run({"scope": "email"}, _silent)
    finally:
        gate.release.set()

    assert second["scope"] == "email" and second["busy"] is True and second["success"] is False
    assert (await rpc)["success"] is True
    assert gate.calls == [60]


@pytest.mark.asyncio
async def test_loop_tick_during_an_rpc_run_starts_nothing(configured, monkeypatch, caplog):
    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)
    caplog.set_level(logging.INFO)

    rpc = asyncio.create_task(setup.sync_run({"scope": "email", "days_back": 14}, _silent))
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        await server_ws._mail_sync_tick()
    finally:
        gate.release.set()

    assert (await rpc)["success"] is True
    assert gate.calls == [14]
    assert "[mail-sync] skipped: intake already in flight" in caplog.text


@pytest.mark.asyncio
async def test_second_loop_caller_is_busy_and_does_not_join(configured, monkeypatch):
    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)

    first = asyncio.create_task(setup.email_intake_from_daemon())
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        second = await asyncio.wait_for(setup.email_intake_from_daemon(), 1)
        assert not first.done()
    finally:
        gate.release.set()

    assert second["busy"] is True and second["success"] is False
    assert (await first)["success"] is True
    assert gate.calls == [14]


@pytest.mark.asyncio
async def test_event_loop_answers_while_a_run_is_blocked(configured, monkeypatch):
    """A sync awaited on the event loop cost a client its socket; this is the guard."""
    gate = Gate()
    monkeypatch.setattr(pipeline, "_run_sync", gate)

    loop_run = asyncio.create_task(setup.email_intake_from_daemon())
    try:
        assert await asyncio.to_thread(gate.started.wait, 2)
        direct = await asyncio.wait_for(setup.sync_run({"scope": "nope"}, _silent), 1)
        raw = json.dumps(
            {"jsonrpc": "2.0", "id": 7, "method": "sync.run", "params": {"scope": "nope"}}
        )
        dispatched = await asyncio.wait_for(dispatch.dispatch_raw(raw, _silent), 1)
        assert not loop_run.done()
    finally:
        gate.release.set()

    assert direct["success"] is False
    assert dispatched["id"] == 7 and dispatched["result"]["success"] is False
    assert (await loop_run)["success"] is True


@pytest.mark.asyncio
async def test_dispatcher_accepts_scope_and_refuses_unknown_names(configured, monkeypatch):
    async def quick(owner_id, store, days_back, progress=None, **kwargs):
        return _ok(1)

    monkeypatch.setattr(pipeline, "_run_sync", quick)

    def request(params: dict) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "sync.run", "params": params})

    accepted = await dispatch.dispatch_raw(request({"scope": "email", "days_back": 14}), _silent)
    assert accepted["result"]["scope"] == "email" and accepted["result"]["success"] is True

    refused = await dispatch.dispatch_raw(request({"scope": "email", "mailbox": "x"}), _silent)
    assert refused["error"]["code"] == dispatch.INVALID_PARAMS
    assert "mailbox" in refused["error"]["message"]


# ─── private logs, on source lines that have them ─────────────


@pytest.mark.asyncio
async def test_loop_run_logs_metadata_only_where_private_logging_exists(
    configured, monkeypatch, caplog
):
    """A hosted engine redacts the log records of ``sync.run``; a loop run must too."""
    pytest.importorskip("zylch.observability_producers")
    host = "imap.company.test"

    async def chatty(owner_id, store, days_back, progress=None, **kwargs):
        logging.getLogger("zylch.tests.mailbox").warning("mailbox %s refused by %s", OWNER, host)
        return _ok()

    monkeypatch.setattr(pipeline, "_run_sync", chatty)
    caplog.set_level(logging.INFO)

    result = await setup.email_intake_from_daemon()

    assert result["success"] is True
    assert any(r.name == "zylch.tests.mailbox" for r in caplog.records)
    assert OWNER not in caplog.text and host not in caplog.text


# ─── against a fake provider ──────────────────────────────────


@pytest.mark.asyncio
async def test_loop_run_stores_fresh_inbox_and_sent_mail(env, monkeypatch, caplog):  # noqa: F811
    """The observed failure: a reply sent by hand sits in Sent and not in the archive."""
    monkeypatch.delenv("MAIL_SYNC_INTERVAL_MINUTES", raising=False)
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: env["store"])
    reached: list = []
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", lambda *a: reached.append("wa") or {})
    shown = _console(monkeypatch)
    caplog.set_level(logging.INFO)

    when = datetime.now(timezone.utc)
    inbound = "<customer-question@client.test>"
    reply = "<owner-hand-reply@company.test>"
    inbox = _inbox({10: build_raw_message(inbound, date=when, body="Where is my order?")})
    sent = _inbox(
        {
            4: build_raw_message(
                reply,
                from_addr=OWNER,
                to_addr="customer@client.test",
                date=when,
                body="Answered by hand from the owner's own mail client.",
            )
        },
        uidvalidity=202,
    )
    _servers(
        monkeypatch,
        {
            OWNER: lambda mb: make_client(
                {"INBOX": inbox, "[Gmail]/Sent Mail": sent}, email_addr=OWNER
            ),
            SECOND: lambda mb: make_client({"INBOX": _inbox({})}, email_addr=SECOND),
        },
    )

    await server_ws._mail_sync_tick()

    stored = {
        row[0]
        for row in _rows(
            env["db"], "SELECT message_id_header FROM emails WHERE owner_id=?", (OWNER,)
        )
    }
    assert {inbound, reply} <= stored
    assert reached == []
    assert "[mail-sync] run completed new=2" in caplog.text
    # A daemon's stderr is its journal: no sync prints a mailbox line there.
    assert shown.getvalue() == ""


@pytest.mark.asyncio
async def test_failing_loop_run_keeps_the_provider_error_off_the_console(
    env,  # noqa: F811
    monkeypatch,
    caplog,
):
    from zylch.email.imap_client import IMAPError

    monkeypatch.delenv("MAIL_SYNC_INTERVAL_MINUTES", raising=False)
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: env["store"])
    shown = _console(monkeypatch)
    caplog.set_level(logging.INFO)

    def refuse(mailbox):
        raise IMAPError(f"LOGIN refused for {mailbox.address} at imap.company.test")

    _servers(monkeypatch, {OWNER: refuse, SECOND: refuse})

    await server_ws._mail_sync_tick()

    assert "[mail-sync] run finished with errors" in caplog.text
    assert shown.getvalue() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"scope": "email", "days_back": 14}], ids=["all", "email"])
async def test_mailbox_progress_is_a_log_record_and_never_a_console_line(
    env,  # noqa: F811
    monkeypatch,
    caplog,
    params,
):
    """The line names its mailbox, so it is a record the private log scope can mask."""
    monkeypatch.setattr(setup, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(Storage, "get_instance", lambda: env["store"])
    monkeypatch.setattr(pipeline, "_run_whatsapp_sync", lambda *a: {"skipped": True})
    shown = _console(monkeypatch)
    caplog.set_level(logging.INFO)

    inbox = _inbox(
        {10: build_raw_message("<progress-line@client.test>", date=datetime.now(timezone.utc))}
    )
    _servers(
        monkeypatch,
        {
            OWNER: lambda mb: make_client({"INBOX": inbox}, email_addr=OWNER),
            SECOND: lambda mb: make_client({"INBOX": _inbox({})}, email_addr=SECOND),
        },
    )

    result = await setup.sync_run(dict(params), _silent)

    assert result["success"] is True
    assert shown.getvalue() == ""
    progress = [
        record.getMessage()
        for record in caplog.records
        if record.name == pipeline.logger.name and record.levelno == logging.INFO
    ]
    assert progress
    # Which mailbox's line passes the percentage filter is not fixed. The line is
    # readable on a family without the private log scope and metadata only on one
    # that has it.
    assert any("company.test: Stored" in line for line in progress) is not _PRIVATE_LOGS
    if _PRIVATE_LOGS:
        assert OWNER not in caplog.text and SECOND not in caplog.text
