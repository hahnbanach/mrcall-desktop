"""No owner prompt, internal note, unrelated customer or replaced fact reaches tool input."""

import asyncio
import json
import threading

import pytest
from sqlalchemy import event

from tests.voice.m2_fixture import (
    FOLLOWUP,
    INTERNAL,
    KNOWN,
    NUMBER,
    OTHER,
    OTHER_FACT,
    PUBLIC,
    SHARED,
    configuration,
)
from tests.voice.test_agent_config import save
from zylch.services.voice import agent_config as config
from zylch.services.voice.caller_memory import CallerMemory
from zylch.storage import database as db
from zylch.storage.models import BlobSentence


def tool(phone=KNOWN, **kwargs):
    return CallerMemory(config.snapshot_for_call(NUMBER), phone, **kwargs)


@pytest.mark.parametrize("phone", [KNOWN, "0039 333 0000001", "+39 (333) 000-0001"])
def test_normalized_and_followup_only_approved_model_input(fixture_db, phone):
    save()
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db.current_memory_engine(), "before_cursor_execute", observe)
    try:
        initial = asyncio.run(tool(phone).execute()).to_dict()
        followup = asyncio.run(tool(phone).execute(query="delivery Thursday")).to_dict()
    finally:
        event.remove(db.current_memory_engine(), "before_cursor_execute", observe)
    assert {f["text"] for f in initial["data"]["facts"]} == {PUBLIC, FOLLOWUP}
    assert [f["text"] for f in followup["data"]["facts"]] == [FOLLOWUP]
    assert followup["data"]["facts"][0]["source"]["sentence_id"] == "a-followup"
    model_input = json.dumps([initial, followup])
    for forbidden in (
        INTERNAL,
        OTHER_FACT,
        "FOREIGN COMPANY SECRET",
        fixture_db,
        "PRIVATE FULL BLOB",
    ):
        assert forbidden not in model_input
    assert not any("blobs.content" in sql or "embedding" in sql for sql in statements)
    missing = asyncio.run(tool(phone).execute(query="nonexistent elephant"))
    assert not missing.data["facts"] and missing.data["missing"]


@pytest.mark.parametrize(
    "phone,state",
    [
        (None, "unknown"),
        ("withheld", "unknown"),
        ("1234@lid", "unknown"),
        ("+393339999999", "unknown"),
        (SHARED, "ambiguous"),
        (OTHER, "unselected"),
    ],
)
def test_no_customer_context_for_unknown_or_ambiguous(fixture_db, phone, state):
    save()
    out = asyncio.run(tool(phone).execute())
    assert out.data["recognition"] == state and out.data["facts"] == []


@pytest.mark.parametrize("change", ["delete", "text", "customer", "company", "replace"])
def test_stale_sentence_never_inherits_grant(fixture_db, change):
    save()
    memory = tool()
    with db.get_session() as session:
        row = session.get(BlobSentence, "a-public")
        if change == "delete":
            session.delete(row)
        elif change == "text":
            row.sentence_text = INTERNAL
        elif change == "customer":
            row.blob_id = "customer-b"
        elif change == "company":
            row.company_key = "other-company"
        else:
            session.delete(row)
            session.flush()
            session.add(
                BlobSentence(
                    id="a-public",
                    blob_id="customer-a",
                    owner_id="fixture-owner",
                    sentence_text=PUBLIC,
                    embedding=b"",
                    company_key=fixture_db,
                )
            )
    out = asyncio.run(memory.execute())
    assert [f["text"] for f in out.data["facts"]] == [FOLLOWUP]


def test_disabled_capability_and_model_cannot_select_another_caller(fixture_db):
    save(configuration() | {"tools": []})
    assert asyncio.run(tool().execute()).error == "Caller memory is disabled"
    save()
    assert asyncio.run(tool().execute(caller_number=OTHER)).error == "Invalid memory query"


def test_lookup_failure_safe_and_membership_change(fixture_db, monkeypatch, caplog):
    save()
    memory = tool()

    def broken(query):
        raise RuntimeError("secret memory SQL parameters")

    monkeypatch.setattr(memory, "_lookup", broken)
    out = asyncio.run(memory.execute())
    assert out.error == "Caller memory unavailable" and out.data["facts"] == []
    assert "secret memory" not in caplog.text
    monkeypatch.setenv("MEMORY_KEY", "changed")
    assert asyncio.run(tool().execute()).data["facts"] == []


def test_timeout_cancellation_and_event_loop_keeps_running(fixture_db, monkeypatch):
    save()
    memory = tool(timeout=0.03)
    started, release = threading.Event(), threading.Event()
    original = memory._lookup

    def slow(query):
        started.set()
        release.wait(timeout=2)
        return original(query)

    monkeypatch.setattr(memory, "_lookup", slow)

    async def scenario():
        pending = asyncio.create_task(memory.execute())
        while not started.is_set():
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.005)  # Audio reader would still run here.
        assert not pending.done()
        out = await pending
        assert out.error == "Caller memory timed out" and not out.data["facts"]
        release.set()

    asyncio.run(scenario())
    release.clear()

    async def cancelled():
        pending = asyncio.create_task(memory.execute())
        await asyncio.sleep(0.005)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release.set()

    asyncio.run(cancelled())


def test_final_binding_read_shares_the_lookup_deadline(fixture_db, monkeypatch):
    from zylch.services.voice import caller_memory

    save()
    memory = tool(timeout=0.03)
    release = threading.Event()
    monkeypatch.setattr(memory, "_lookup", lambda _: caller_memory.result("matched"))

    def slow_binding(_):
        release.wait(timeout=2)

    monkeypatch.setattr(caller_memory, "require_binding", slow_binding)

    async def scenario():
        try:
            out = await asyncio.wait_for(memory.execute(), 0.3)
            assert out.error == "Caller memory timed out" and not out.data["facts"]
        finally:
            release.set()

    asyncio.run(scenario())
