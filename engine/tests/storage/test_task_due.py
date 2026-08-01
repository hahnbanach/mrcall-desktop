"""The due/follow-up primitive: "call me back in N days".

Before ``due_at`` a task was only open or closed. ``dedup_skip_until``
looks similar but answers a different question — it is SUPPRESS-UNTIL
(keep the dedup sweep off this row), never ACT-AT. Without an act-at
field there was no way to park a task: the choice was leave it in the
list as apparent neglect, or close work that is not done.

Contracts locked here:

- ``tasks.snooze`` writes ``due_at`` (relative ``days`` or absolute
  ``due_at``), refuses a closed task, and records actor/why;
- ``tasks.list`` defaults to the pre-``due_at`` behaviour and only hides
  parked tasks under ``due_filter="due_now"``;
- a parked task is not F4 work and cannot be aged out by hygiene;
- it all comes back the moment ``due_at`` is in the past.
"""

import asyncio
import time

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "task_due.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield
    db_mod.dispose_engine()


OWNER = "owner-task-due"


def _seed(store, event_id="<due@example.com>", channel="email", created_at=None):
    store.store_task_item(
        OWNER,
        {
            "event_type": "email",
            "event_id": event_id,
            "contact_email": "cliente@example.com",
            "contact_name": "Cliente",
            "title": "Richiamare",
            "action_required": True,
            "urgency": "medium",
            "reason": "seed",
            "sources": {"thread_id": "thread-due", "emails": []},
            "channel": channel,
        },
    )
    return store.get_task_by_event(OWNER, "email", event_id)


async def _rpc(method, params):
    import json

    from zylch.rpc.dispatch import dispatch_raw

    raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return await dispatch_raw(raw, lambda m, p: None)


def test_snooze_sets_due_at_and_records_the_decision(fresh_db):
    from zylch.storage.storage import Storage

    store = Storage()
    task = _seed(store)
    res = asyncio.run(_rpc("tasks.snooze", {"task_id": task["id"], "days": 3}))["result"]
    assert res["ok"] is True
    assert res["due_at"] > time.time() + 2 * 86400

    row = store.get_task_by_id(OWNER, task["id"])
    assert row["due_at"] == res["due_at"]
    assert row["completed_at"] is None  # a snooze is NOT a close
    history = row["sources"]["snoozes"]
    assert history[-1]["actor"] == "human"
    assert history[-1]["why"]


def test_snooze_refuses_a_closed_task(fresh_db):
    from zylch.storage.storage import Storage

    store = Storage()
    task = _seed(store)
    store.complete_task_item(OWNER, task["id"], actor="test", why="done")
    res = asyncio.run(_rpc("tasks.snooze", {"task_id": task["id"], "days": 3}))["result"]
    assert res["ok"] is False
    assert store.get_task_by_id(OWNER, task["id"])["due_at"] is None


def test_snooze_requires_exactly_one_of_days_or_due_at(fresh_db):
    from zylch.storage.storage import Storage

    store = Storage()
    task = _seed(store)
    for params in ({"task_id": task["id"]}, {"task_id": task["id"], "days": 1, "due_at": 1.0}):
        assert "error" in asyncio.run(_rpc("tasks.snooze", params))


def test_list_default_is_unchanged_and_due_now_hides_parked(fresh_db):
    from zylch.storage.storage import Storage

    store = Storage()
    parked = _seed(store, "<parked@example.com>")
    active = _seed(store, "<active@example.com>")
    store.snooze_task_item(OWNER, parked["id"], days=3, actor="test", why="park")

    default_ids = {t["id"] for t in asyncio.run(_rpc("tasks.list", {}))["result"]}
    all_ids = {t["id"] for t in asyncio.run(_rpc("tasks.list", {"due_filter": "all"}))["result"]}
    now_ids = {
        t["id"] for t in asyncio.run(_rpc("tasks.list", {"due_filter": "due_now"}))["result"]
    }

    assert default_ids == all_ids == {parked["id"], active["id"]}
    assert now_ids == {active["id"]}


def test_list_rejects_an_unknown_due_filter(fresh_db):
    from zylch.storage.storage import Storage

    Storage()
    assert "error" in asyncio.run(_rpc("tasks.list", {"due_filter": "soon"}))


def test_parked_task_is_not_f4_work(fresh_db):
    from zylch.storage.storage import Storage
    from zylch.workers.task_gating import f4_candidates, is_snoozed

    store = Storage()
    parked = _seed(store, "<parked@example.com>")
    active = _seed(store, "<active@example.com>")
    store.snooze_task_item(OWNER, parked["id"], days=3, actor="test", why="park")

    tasks = store.get_task_items(OWNER, action_required=True, limit=100)
    assert is_snoozed(next(t for t in tasks if t["id"] == parked["id"])) is True
    # force_all is the daily pass — even that must leave a parked task alone.
    ids = {t["id"] for t in f4_candidates(OWNER, store, tasks, force_all=True)}
    assert ids == {active["id"]}


def test_hygiene_never_expires_a_parked_phone_task(fresh_db):
    from datetime import datetime, timedelta, timezone

    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    store = Storage()
    parked = _seed(store, "<phone-parked@example.com>", channel="phone")
    stale = _seed(store, "<phone-stale@example.com>", channel="phone")
    store.snooze_task_item(OWNER, parked["id"], days=30, actor="test", why="call back next month")

    # Both call-backs are ancient; only one is parked.
    old = datetime.now(timezone.utc) - timedelta(days=90)
    with get_session() as session:
        session.query(TaskItem).filter(TaskItem.owner_id == OWNER).update({"created_at": old})

    closed = store.auto_close_stale_phone_tasks(OWNER, max_age_days=30)
    assert closed == 1
    assert store.get_task_by_id(OWNER, parked["id"])["completed_at"] is None
    assert store.get_task_by_id(OWNER, stale["id"])["completed_at"] is not None


def test_a_past_due_at_makes_the_task_actionable_again(fresh_db):
    from zylch.storage.storage import Storage
    from zylch.workers.task_gating import f4_candidates

    store = Storage()
    task = _seed(store)
    store.snooze_task_item(OWNER, task["id"], days=3, actor="test", why="park")
    store.snooze_task_item(
        OWNER, task["id"], due_at=time.time() - 60, actor="test", why="bring it back"
    )

    now_ids = {
        t["id"] for t in asyncio.run(_rpc("tasks.list", {"due_filter": "due_now"}))["result"]
    }
    assert task["id"] in now_ids
    tasks = store.get_task_items(OWNER, action_required=True, limit=100)
    assert task["id"] in {t["id"] for t in f4_candidates(OWNER, store, tasks, force_all=True)}
