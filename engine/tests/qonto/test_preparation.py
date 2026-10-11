"""Source-only rules through actual preparation and Desktop RPC paths."""

import asyncio

import httpx
import pytest

from zylch.qonto import preparation, repository, sync
from zylch.qonto.models import QontoCheckpoint, QontoTransaction
from zylch.services import preparation as shared
from zylch.storage import database as dbm
from zylch.storage.models import TaskItem
from zylch.storage.storage import Storage
from .conftest import UID, signin
from .test_sync import STARTED, raw


@pytest.fixture(autouse=True)
def fixed_time(monkeypatch):
    monkeypatch.setattr(sync, "now", lambda: STARTED)


def setup(env, http_api, count=1):
    http_api.rows = [raw(str(n), status="declined") for n in range(count)]
    assert env.connect()["result"]["ok"]


def run(env, **params):
    result = env.rpc("qonto.prepare", **params)
    assert "result" in result, result
    return result["result"]


def records(model):
    with repository.profile_transaction() as session:
        return session.query(model).all()


def test_real_dispatch_free_rule_task_and_checkpoint_are_idempotent(env, http_api):
    setup(env, http_api, 3)
    before = env.rpc("preparation.status")["result"]["channels"]["qonto:task"]
    assert before == {"pending": 3, "completed": 0}
    result = run(env)
    assert result["success"] and result["attempted"] == result["completed"] == 3
    assert result["failed"] == 0 and not result["errors"]
    tasks = env.rpc("tasks.list")["result"]
    assert len(tasks) == 3
    assert all(
        task["owner_id"] == UID and task["event_type"] == task["channel"] == "qonto"
        for task in tasks
    )
    assert all(task["sources"]["qonto"]["source_id"].startswith("qonto:") for task in tasks)
    assert all("_qonto" not in task["sources"] for task in tasks)
    assert len(records(QontoCheckpoint)) == len(records(TaskItem)) == 3
    assert all(task.sources["_qonto"]["company_scope"] for task in records(TaskItem))
    assert run(env)["attempted"] == 0
    assert env.rpc("preparation.status")["result"]["channels"]["qonto:task"] == {
        "pending": 0,
        "completed": 3,
    }
    dbm.dispose_engine()
    dbm.init_db()
    assert run(env)["attempted"] == 0
    assert len(env.rpc("tasks.list")["result"]) == 3


def test_saved_pause_one_batch_resume_and_shared_busy(env, http_api):
    setup(env, http_api, 3)
    path = env.directory / ".env"
    path.write_text(path.read_text() + "PREPARATION_BATCH_SIZE=2\nLLM_DAILY_BUDGET_USD=0\n")
    env.rpc("preparation.pause")
    result = run(env)
    assert result["status"] == "paused" and not records(TaskItem)
    result = run(env, resume=True)
    assert result["attempted"] == result["completed"] == 2 and result["paused"]
    assert run(env)["status"] == "paused"
    result = run(env, resume=True)
    assert result["completed"] == 1 and result["paused"]
    with shared.preparation_run(UID, explicit=True):
        result = run(env, resume=True)
        assert result["status"] == "busy"


def test_revision_preserves_real_user_edits_and_latest_counts(env, http_api):
    setup(env, http_api)
    run(env)
    task = env.rpc("tasks.list")["result"][0]
    from zylch.qonto.task_access import access_scope, desktop_access

    access = asyncio.run(desktop_access("display@example.test"))
    with access_scope(access):
        assert Storage.get_instance().update_task_item(
            "display@example.test", task["id"], title="My review", reason="My notes"
        )
    assert env.rpc("tasks.pin", task_id=task["id"], pinned=True)["result"]["ok"]
    assert env.rpc("tasks.snooze", task_id=task["id"], days=2)["result"]["ok"]
    assert env.rpc("tasks.complete", task_id=task["id"], note="My closing note")["result"]["ok"]
    with repository.profile_transaction() as session:
        source = session.query(QontoTransaction).one()
        source.source_revision = "next-revision"
        source.status = "completed"
    assert run(env)["completed"] == 1
    updated = env.rpc("tasks.get", task_id=task["id"])["result"]
    assert updated["title"] == "My review" and updated["reason"] == "My notes"
    assert updated["pinned"] and updated["due_at"] and updated["completed_at"]
    assert updated["close_note"] == "My closing note"
    assert updated["sources"]["qonto"]["source_revision"] == "next-revision"
    assert not updated["action_required"]
    assert env.rpc("preparation.status")["result"]["channels"]["qonto:task"] == {
        "pending": 0,
        "completed": 1,
    }


def test_failed_profile_write_retries_without_claiming_checkpoint(env, http_api, monkeypatch):
    setup(env, http_api)
    original = preparation.Processor.process.__wrapped__

    async def fail(self, data):
        raise RuntimeError("private source must not be returned")

    monkeypatch.setattr(
        preparation.Processor, "process", shared.bounded_item(preparation.STAGE)(fail)
    )
    result = run(env)
    assert result["failed"] == 1 and result["completed"] == 0
    assert result["errors"][0]["detail"] == "Finance task processing failed."
    assert records(QontoCheckpoint)[0].state == "failed" and not records(TaskItem)
    monkeypatch.setattr(
        preparation.Processor, "process", shared.bounded_item(preparation.STAGE)(original)
    )
    assert run(env)["attempted"] == 0
    with shared._db() as conn:
        conn.exec_driver_sql("UPDATE preparation_attempts SET retry_at=0")
    assert run(env)["completed"] == 1


@pytest.mark.parametrize("failure", [401, 503])
def test_prepare_live_authority_refuses_revocation_and_network(env, http_api, failure):
    setup(env, http_api)
    http_api.callback = lambda request: httpx.Response(
        failure, json={"private": "bank information"}
    )
    result = env.rpc("qonto.prepare")
    assert "error" in result and "bank information" not in str(result)
    assert not records(TaskItem) and not records(QontoCheckpoint)


def test_generation_changed_between_admission_and_commit(env, http_api, monkeypatch):
    setup(env, http_api)
    original = preparation.Processor.process.__wrapped__

    async def revoke(self, data):
        assert (await env.arpc("qonto.disconnect"))["result"]["ok"]
        return await original(self, data)

    monkeypatch.setattr(
        preparation.Processor, "process", shared.bounded_item(preparation.STAGE)(revoke)
    )
    result = run(env)
    assert result["status"] == "refused" and result["completed"] == 0
    assert result["errors"][0]["error"] == "generation_changed"
    assert not records(TaskItem) and not records(QontoCheckpoint)


def test_pending_status_omits_invalid_identity_and_connection(env, http_api):
    setup(env, http_api)
    signin("other-uid")
    assert "qonto:task" not in env.rpc("preparation.status")["result"]["channels"]
    signin()
    env.rpc("qonto.disconnect")
    assert "qonto:task" not in env.rpc("preparation.status")["result"]["channels"]


@pytest.mark.parametrize("action", ["preparation.pause", "qonto.disconnect", "cancel"])
def test_real_concurrent_control_stops_remaining_free_items(env, http_api, monkeypatch, action):
    setup(env, http_api, 20)
    original = preparation.Processor.process

    async def scenario():
        committed = asyncio.Event()

        async def first(self, data):
            result = await original(self, data)
            committed.set()
            return result

        monkeypatch.setattr(preparation.Processor, "process", first)
        running = asyncio.create_task(env.arpc("qonto.prepare"))
        await committed.wait()
        if action == "cancel":
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        else:
            assert "result" in await env.arpc(action)
            result = await running
            assert result["result"]["status"] in {"paused", "refused"}
        assert len(records(TaskItem)) == len(records(QontoCheckpoint)) == 1
        assert not shared.status(UID)["running"]

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_actual_profile_flush_failure_rolls_back_task_and_processed_checkpoint(env, http_api):
    from sqlalchemy import event

    setup(env, http_api)

    def reject_insert(*_):
        raise RuntimeError("private SQL payload")

    event.listen(TaskItem, "before_insert", reject_insert)
    try:
        result = run(env)
    finally:
        event.remove(TaskItem, "before_insert", reject_insert)
    assert result["failed"] == 1 and result["completed"] == 0
    assert not records(TaskItem)
    checkpoint = records(QontoCheckpoint)[0]
    assert checkpoint.state == "failed" and checkpoint.processed_at is None
    assert "private SQL payload" not in str(result)
    with shared._db() as conn:
        conn.exec_driver_sql("UPDATE preparation_attempts SET retry_at=0")
    assert run(env)["completed"] == 1
    assert len(records(TaskItem)) == len(records(QontoCheckpoint)) == 1
