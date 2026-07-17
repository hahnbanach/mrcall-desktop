"""Durability of the external `tasks.create` / `tasks.complete` path.

The cs operator's triage sweep reconciles against the engine task ledger:
create-on-miss (an inbound the engine's own detection never turned into a task)
and close-on-handled (mark a contact done — e.g. answered from a personal
mailbox the Sent-anchored sweep can't see). Both ride the SAME `task_items`
table + lifecycle as the detection pipeline. This test locks that contract at
the storage layer and through the `tasks_create` RPC handler:

- ``store_task_item`` + ``get_task_by_event`` round-trips the task id;
- the ``tasks_create`` handler returns ``{ok, task_id, created}`` and is
  idempotent (second create of the same event -> ``created=False``);
- after ``complete_task_item`` the task is ABSENT from the open
  ``get_task_items()`` but PRESENT with ``include_completed=True``.
"""

import asyncio

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks_create_close.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


OWNER = "owner-uid-1"


def _item(event_id: str = "<msg-abc@example.com>") -> dict:
    return {
        "event_type": "email",
        "event_id": event_id,
        "contact_email": "cliente@example.com",
        "contact_name": "Mario Rossi",
        "title": "Richiesta pre-vendita senza risposta",
        "action_required": True,
        "urgency": "high",
        "reason": "inbound 8 giorni fa, nessuna risposta",
        "sources": {"emails": [event_id], "thread_id": "thread-42"},
    }


def test_store_and_get_task_by_event_roundtrips_id(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    assert storage.store_task_item(OWNER, _item()) is True

    row = storage.get_task_by_event(
        owner_id=OWNER, event_type="email", event_id="<msg-abc@example.com>"
    )
    assert row is not None, "get_task_by_event found nothing after store"
    assert row["id"], "task row has no id"
    assert row["contact_email"] == "cliente@example.com"
    assert row["sources"].get("thread_id") == "thread-42"


def test_tasks_create_handler_returns_ok_task_id_created(fresh_db, monkeypatch):
    from zylch.rpc import methods

    monkeypatch.setattr(methods, "_owner_id", lambda: OWNER)

    params = _item()
    res = asyncio.run(methods.tasks_create(params, lambda *a, **k: None))
    assert res["ok"] is True, res
    assert res["task_id"], res
    assert res["created"] is True, res

    # Idempotent: re-creating the SAME event is an upsert, not a duplicate.
    res2 = asyncio.run(methods.tasks_create(params, lambda *a, **k: None))
    assert res2["ok"] is True, res2
    assert res2["task_id"] == res["task_id"], (res, res2)
    assert res2["created"] is False, res2


def test_complete_removes_from_open_but_kept_when_included(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    storage.store_task_item(OWNER, _item())
    row = storage.get_task_by_event(
        owner_id=OWNER, event_type="email", event_id="<msg-abc@example.com>"
    )
    task_id = row["id"]

    # Open list contains it.
    open_ids = {t["id"] for t in storage.get_task_items(OWNER)}
    assert task_id in open_ids, "task not in the open list before close"

    assert storage.complete_task_item(OWNER, task_id, note="risposto da personale") is True

    # Absent from the open list...
    open_ids_after = {t["id"] for t in storage.get_task_items(OWNER)}
    assert task_id not in open_ids_after, "completed task still in the open list"

    # ...but present with include_completed=True.
    all_ids = {t["id"] for t in storage.get_task_items(OWNER, include_completed=True)}
    assert task_id in all_ids, "completed task missing from include_completed list"
