"""Private source never becomes company memory through generic chat or correction."""

import pytest

from zylch.memory.company_key import require_company_key
from zylch.memory.mnemonic import submit
from zylch.memory.mnemonic.contracts import (
    INTERACTIVE,
    OPERATOR_DELEGATED,
    VERIFIED_HUMAN_CORRECTION,
    MemoryEvent,
)
from zylch.qonto import repository
from zylch.qonto.models import QontoTransaction
from zylch.storage.database import current_memory_engine

from .chat_fixture import install_client, reservations, tool_data, turn
from .test_reads import bank as bank_fixture

bank = bank_fixture

PRIVATE = "BANK-NARRATIVE-PRIVATE-ALPHA-9341"


def assert_company_private():
    engine = current_memory_engine()
    with engine.connect() as conn:
        tables = (
            conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")
            .scalars()
            .all()
        )
        for table in tables:
            values = conn.exec_driver_sql('SELECT * FROM "' + table + '"').fetchall()
            assert PRIVATE not in str(values), table
    for suffix in ("", "-wal", "-journal"):
        from pathlib import Path

        file = Path(str(engine.url.database) + suffix)
        if file.exists():
            assert PRIVATE.encode() not in file.read_bytes()


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("create_memory", {"content": PRIVATE}),
        ("update_memory", {"blob_id": "existing-blob-id", "new_content": PRIVATE}),
        ("create_memory", {"content": PRIVATE, "entry_type": "behavioral_rule"}),
    ],
)
def test_finance_tools_then_generic_memory_publish_blocked_before_company_journal(
    bank, monkeypatch, tool, arguments
):
    env, _ = bank
    with repository.profile_transaction() as session:
        row = session.query(QontoTransaction).first()
        row.note = PRIVATE
        key = row.source_id
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_transaction", source_id=key)
    wire.tool(tool, **arguments)
    wire.answer("Private bank evidence was not published.")
    response = turn(env)
    assert "result" in response
    assert len(wire.calls) == 3
    assert tool_data(wire, call=2)["status"] == "error"
    assert reservations() == 3
    assert_company_private()


def test_retained_finance_followup_cannot_publish_and_preserves_provenance(bank, monkeypatch):
    env, _ = bank
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    wire.answer(PRIVATE)
    first = turn(env)["result"]
    wire.tool("create_memory", content=PRIVATE)
    wire.answer("No company publication.")
    replay = turn(
        env,
        message="Save the earlier answer.",
        history_handle=first["history_handle"],
        history_revision=first["history_revision"],
    )
    assert "result" in replay
    assert tool_data(wire, call=3)["status"] == "error"
    with repository.profile_transaction() as session:
        from zylch.qonto.models import QontoConversation

        row = session.query(QontoConversation).one()
        assert row.finance_marked
    assert_company_private()


@pytest.mark.parametrize("caller", [OPERATOR_DELEGATED, VERIFIED_HUMAN_CORRECTION])
def test_generic_direct_memory_correction_cannot_republish_known_finance_answer(
    bank, monkeypatch, caller
):
    env, _ = bank
    wire = install_client(env, monkeypatch)
    wire.tool("qonto_accounts")
    wire.answer(PRIVATE)
    assert "result" in turn(env)
    before = reservations()
    event = MemoryEvent(
        owner_id="fixtureFirebaseUid",
        company_key=require_company_key(),
        caller_class=caller,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="generic-correction",
        source_revision="1",
        observation=PRIVATE,
        suggestion=PRIVATE,
        explicit_request=True,
    )
    result = submit(event)
    assert result.outcome == "review_needed"
    assert "finance" in result.reason.lower()
    assert reservations() == before
    assert_company_private()


def test_profile_source_never_in_company_tables_or_extraction(bank):
    env, _ = bank
    with repository.profile_transaction() as session:
        row = session.query(QontoTransaction).first()
        row.note = PRIVATE
        key = row.source_id
    detail = env.rpc("qonto.transaction", source_id=key)["result"]
    assert detail["transaction"]["untrusted_source_text"]["note"] == PRIVATE
    assert_company_private()
