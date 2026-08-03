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
  ``get_task_items()`` but PRESENT with ``include_completed=True``;
- and, over the JSON-RPC boundary the operator actually speaks
  (``dispatch_raw``): a full contact record round-trips, ``actor``
  records who closed a task, and a reopen touches only its own row.
"""

import asyncio
import json

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

    assert (
        storage.complete_task_item(
            OWNER,
            task_id,
            note="risposto da personale",
            actor="human",
            why="closed by the user in the test",
        )
        is True
    )

    # Absent from the open list...
    open_ids_after = {t["id"] for t in storage.get_task_items(OWNER)}
    assert task_id not in open_ids_after, "completed task still in the open list"

    # ...but present with include_completed=True.
    all_ids = {t["id"] for t in storage.get_task_items(OWNER, include_completed=True)}
    assert task_id in all_ids, "completed task missing from include_completed list"


def test_external_operator_lifecycle_preserves_audit_and_reopens_explicitly(fresh_db, monkeypatch):
    """Pin the brain/body reconciliation contract across every lifecycle state."""
    from zylch.rpc import methods, task_queries

    monkeypatch.setattr(methods, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(task_queries, "_owner_id", lambda: OWNER)

    def notify(*args, **kwargs):
        return None

    created = asyncio.run(methods.tasks_create(_item(), notify))
    task_id = created["task_id"]
    open_row = asyncio.run(task_queries.tasks_get({"task_id": task_id}, notify))
    assert open_row["reason"] == _item()["reason"]
    assert open_row["completed_at"] is None

    # A snooze before the close: its audit history must survive the same
    # lifecycle the close history survives.
    asyncio.run(methods.tasks_snooze({"task_id": task_id, "days": 1}, notify))

    assert asyncio.run(
        methods.tasks_complete({"task_id": task_id, "note": "handled from the operator"}, notify)
    ) == {"ok": True}
    closed = asyncio.run(task_queries.tasks_get({"task_id": task_id}, notify))
    assert closed["close_note"] == "handled from the operator"
    assert closed["close_actor"] == "human"

    refused = asyncio.run(methods.tasks_create(_item(), notify))
    assert refused["ok"] is False
    assert refused["closed"] is True
    assert refused["task_id"] == task_id

    refreshed = _item()
    refreshed["title"] = "Reconciled external work"
    refreshed["reopen_if_closed"] = True
    reopened = asyncio.run(methods.tasks_create(refreshed, notify))
    assert reopened == {
        "ok": True,
        "task_id": task_id,
        "created": False,
        "reopened": True,
    }
    row = asyncio.run(task_queries.tasks_get({"task_id": task_id}, notify))
    assert row["completed_at"] is None
    assert row["close_note"] is None
    assert row["title"] == "Reconciled external work"
    assert row["sources"]["closes"][-1]["actor"] == "human"
    assert row["sources"]["closes"][-1]["why"] == "handled from the operator"
    assert len(row["sources"]["snoozes"]) == 1, "snooze audit history lost on upsert-reopen"

    first_close = dict(row["sources"]["closes"][-1])
    assert asyncio.run(
        methods.tasks_complete(
            {
                "task_id": task_id,
                "actor": "operator",
                "why": "reconciled and closed by the external operator",
            },
            notify,
        )
    ) == {"ok": True}
    reclosed = asyncio.run(task_queries.tasks_get({"task_id": task_id}, notify))
    assert len(reclosed["sources"]["closes"]) == 2
    assert reclosed["sources"]["closes"][0] == first_close
    assert reclosed["sources"]["closes"][1]["actor"] == "operator"
    assert (
        reclosed["sources"]["closes"][1]["why"]
        == "reconciled and closed by the external operator"
    )


# ─── Through the JSON-RPC boundary ────────────────────────────────────
#
# The tests above call the handlers as Python functions, which skips
# everything the dispatcher does: param validation, the unknown/missing
# gates, JSON encoding of the payload and of the reply. An external
# operator only ever reaches the ledger through that boundary, so the
# contract has to be pinned there too.


@pytest.fixture
def rpc(fresh_db, monkeypatch):
    """Call the ledger the way an external operator does: over JSON-RPC."""
    from zylch.rpc import methods as methods_mod
    from zylch.rpc import task_queries as task_queries_mod
    from zylch.rpc.dispatch import dispatch_raw

    monkeypatch.setattr(methods_mod, "_owner_id", lambda: OWNER)
    monkeypatch.setattr(task_queries_mod, "_owner_id", lambda: OWNER)

    def raw(method: str, params: dict):
        frame = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        response = asyncio.run(dispatch_raw(frame, lambda *a, **k: None))
        assert response is not None, method
        return response

    def call(method: str, params: dict):
        response = raw(method, params)
        assert "error" not in response, f"{method} -> {response['error']}"
        return response["result"]

    call.raw = raw
    return call


def test_tasks_create_roundtrips_through_dispatch_with_full_contact_record(rpc):
    """A representative payload survives JSON-RPC in both directions."""
    payload = {
        "event_type": "email",
        "event_id": "<rpc-roundtrip@example.com>",
        "contact_email": "cliente@example.com",
        "contact_name": "Mario Rossi",
        "contact_phone": "+393480000001",
        "title": "Richiamare per il preventivo",
        "urgency": "high",
        "reason": "inbound 8 giorni fa, nessuna risposta",
        "suggested_action": "rispondere con il listino aggiornato",
        "channel": "phone",
        "sources": {"emails": ["<rpc-roundtrip@example.com>"], "thread_id": "thread-77"},
    }

    created = rpc("tasks.create", payload)
    assert created["ok"] is True and created["created"] is True

    row = rpc("tasks.get", {"task_id": created["task_id"]})
    assert row["contact_email"] == payload["contact_email"]
    assert row["contact_name"] == payload["contact_name"]
    assert row["contact_phone"] == payload["contact_phone"]
    assert row["title"] == payload["title"]
    assert row["reason"] == payload["reason"]
    assert row["suggested_action"] == payload["suggested_action"]
    assert row["urgency"] == "high"
    assert row["sources"]["thread_id"] == "thread-77"
    assert row["completed_at"] is None
    assert row["close_actor"] is None

    # Idempotent across the boundary too: same event key, no duplicate.
    again = rpc("tasks.create", payload)
    assert again == {
        "ok": True,
        "task_id": created["task_id"],
        "created": False,
        "reopened": False,
    }


def test_tasks_complete_records_the_closing_actor_through_dispatch(rpc):
    """`actor` is what tells a machine close from a human one."""
    created = rpc(
        "tasks.create",
        {
            "event_id": "<actor-close@example.com>",
            "contact_email": "cliente@example.com",
            "title": "Richiesta pre-vendita",
            "reason": "inbound senza risposta",
        },
    )
    task_id = created["task_id"]

    assert rpc(
        "tasks.complete",
        {
            "task_id": task_id,
            "note": "answered from the shared mailbox",
            "actor": "operator",
            "why": "closed by the cs operator after replying",
        },
    ) == {"ok": True}

    closed = rpc("tasks.get", {"task_id": task_id})
    assert closed["close_actor"] == "operator"
    assert closed["close_note"] == "answered from the shared mailbox"
    assert closed["completed_at"] is not None
    close_event = closed["sources"]["closes"][-1]
    assert close_event["actor"] == "operator"
    assert close_event["why"] == "closed by the cs operator after replying"
    assert close_event["display_note"] == "answered from the shared mailbox"
    assert close_event["at"]


def test_tasks_complete_still_defaults_to_human_for_callers_that_send_no_actor(rpc):
    """The two new params are additive: an old caller is unaffected."""
    created = rpc(
        "tasks.create",
        {
            "event_id": "<default-actor@example.com>",
            "contact_email": "cliente@example.com",
            "title": "Richiesta pre-vendita",
        },
    )

    assert rpc("tasks.complete", {"task_id": created["task_id"]}) == {"ok": True}

    closed = rpc("tasks.get", {"task_id": created["task_id"]})
    assert closed["close_actor"] == "human"


def test_reopen_touches_only_its_own_task_and_preserves_the_reason(rpc):
    """Two tasks, one reopen: the other must not move, and `reason` survives."""
    first = rpc(
        "tasks.create",
        {
            "event_id": "<reopen-mine@example.com>",
            "contact_email": "uno@example.com",
            "title": "Preventivo A",
            "reason": "inbound del 3 marzo, nessuna risposta",
        },
    )
    second = rpc(
        "tasks.create",
        {
            "event_id": "<reopen-other@example.com>",
            "contact_email": "due@example.com",
            "title": "Preventivo B",
            "reason": "inbound del 7 marzo, nessuna risposta",
        },
    )
    assert first["task_id"] != second["task_id"]

    for task_id, actor in ((first["task_id"], "operator"), (second["task_id"], "f4.reanalyze")):
        assert rpc("tasks.complete", {"task_id": task_id, "actor": actor}) == {"ok": True}

    assert rpc("tasks.reopen", {"task_id": first["task_id"]}) == {"ok": True}

    reopened = rpc("tasks.get", {"task_id": first["task_id"]})
    assert reopened["completed_at"] is None
    assert reopened["close_actor"] is None
    assert reopened["reason"] == "inbound del 3 marzo, nessuna risposta"
    assert reopened["sources"]["closes"][-1]["actor"] == "operator"
    assert reopened["sources"]["closes"][-1]["why"]

    untouched = rpc("tasks.get", {"task_id": second["task_id"]})
    assert untouched["completed_at"] is not None
    assert untouched["close_actor"] == "f4.reanalyze"
    assert untouched["reason"] == "inbound del 7 marzo, nessuna risposta"


def test_idempotent_recreate_on_an_open_task_preserves_audit_history(rpc):
    """A create-on-miss retry (no reopen flag) must not erase the append-only
    sources.closes / sources.snoozes histories the row has accumulated."""
    payload = {
        "event_id": "<recreate-audit@example.com>",
        "contact_email": "cliente@example.com",
        "title": "Richiesta pre-vendita",
        "sources": {"emails": ["<recreate-audit@example.com>"]},
    }
    created = rpc("tasks.create", payload)
    task_id = created["task_id"]

    assert rpc(
        "tasks.complete",
        {"task_id": task_id, "actor": "operator", "why": "first close"},
    ) == {"ok": True}
    assert rpc("tasks.reopen", {"task_id": task_id}) == {"ok": True}
    rpc("tasks.snooze", {"task_id": task_id, "days": 1})

    again = rpc("tasks.create", payload)
    assert again == {
        "ok": True,
        "task_id": task_id,
        "created": False,
        "reopened": False,
    }

    row = rpc("tasks.get", {"task_id": task_id})
    assert len(row["sources"]["closes"]) == 1, "close audit history lost on re-create"
    assert row["sources"]["closes"][0]["actor"] == "operator"
    assert len(row["sources"]["snoozes"]) == 1, "snooze audit history lost on re-create"


@pytest.mark.parametrize("field,value", [("actor", {"bad": "shape"}), ("why", ["bad"])])
def test_tasks_complete_rejects_non_string_audit_fields(rpc, field, value):
    created = rpc(
        "tasks.create",
        {
            "event_id": f"<bad-{field}@example.com>",
            "contact_email": "cliente@example.com",
            "title": "Invalid audit payload",
        },
    )

    response = rpc.raw("tasks.complete", {"task_id": created["task_id"], field: value})
    assert response["error"]["code"] == -32603
    assert f"{field} must be a string" in response["error"]["message"]
