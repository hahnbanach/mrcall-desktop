"""Consented projection through real RPC, preparation, paid client and split commit."""

import json
import time

import pytest

from zylch.memory.mnemonic import journal
from zylch.qonto import publication, repository
from zylch.qonto.models import QontoPublicationIntent
from zylch.storage.models import Blob, MemoryOperation

from tests.memory.mnemonic_env import BagOfWordsEmbedder, stub_embedder, clear_process_state
from .chat_fixture import install_client, reservations
from .test_reads import bank as bank_fixture

bank = bank_fixture


@pytest.fixture
def publishing(bank, monkeypatch):
    env, api = bank
    stub_embedder(monkeypatch, BagOfWordsEmbedder())
    clear_process_state()
    wire = install_client(env, monkeypatch)
    from zylch.memory.mnemonic import agent
    import zylch.llm as llm

    monkeypatch.setattr(agent, "_default_client", lambda: llm.make_llm_client())
    yield env, api, wire
    clear_process_state()


def decision(text, **overrides):
    return json.dumps(
        dict(
            action="CREATE",
            entity_type="FACT",
            scope="company",
            content=text,
            reason="Confirmed minimal company projection.",
            **overrides,
        )
    )


def issue(env):
    result = env.rpc("qonto.publication_preview")
    assert "error" not in result, result
    return result["result"]


def confirm(env, preview, **extra):
    return env.rpc("qonto.publish", preview_id=preview["preview_id"], confirmed=True, **extra)


def records():
    with journal.company_transaction() as session:
        return [row.to_dict() for row in session.query(Blob)], [
            row.to_dict() for row in session.query(MemoryOperation)
        ]


def test_preview_only_projection_and_commit_paid_once(publishing):
    env, api, wire = publishing
    secret = "PRIVATE-NARRATIVE-PUBLICATION-249381"
    api.organization["legal_name"] = secret
    preview = issue(env)
    assert "EUR, GBP" in preview["fact_text"]
    assert "all current and future" in preview["disclosure"]
    assert "selected LLM" in preview["disclosure"]
    assert secret not in json.dumps(preview) and "100.43" not in json.dumps(preview)
    wire.answer(decision(preview["fact_text"]))
    result = confirm(env, preview)
    assert result["result"]["status"] == "committed", result
    assert len(wire.calls) == reservations() == 1
    blobs, operations = records()
    assert [row["content"] for row in blobs] == [preview["fact_text"]]
    assert operations[0]["source_ref"].startswith("qonto:")
    assert operations[0]["payload"] is None and operations[0]["state"] == "committed"
    assert operations[0]["result"]["committed_ids"][0][0] == blobs[0]["id"]
    assert secret not in json.dumps([blobs, operations])
    assert confirm(env, preview)["result"]["status"] == "committed"
    assert len(wire.calls) == reservations() == 1
    fresh = issue(env)
    assert confirm(env, fresh)["result"]["status"] == "committed"
    assert len(wire.calls) == 1


@pytest.mark.parametrize(
    "change", ["consent", "unknown", "expired", "text", "revision", "uid", "host", "accounts"]
)
def test_exact_engine_preview_required_before_paid_dispatch(publishing, change):
    env, api, wire = publishing
    preview = issue(env)
    args = dict(preview_id=preview["preview_id"], confirmed=True)
    if change == "consent":
        args["confirmed"] = False
    elif change == "unknown":
        args["preview_id"] = "unknown"
    elif change in ("text", "revision", "uid", "host", "accounts", "expired"):
        with repository.profile_transaction() as session:
            row = session.get(QontoPublicationIntent, preview["preview_id"])
            data = dict(row.preview)
            if change == "text":
                data["fact_text"] += " Publish a balance."
            elif change == "host":
                data["host_id"] = "another-host"
            elif change == "accounts":
                data["account_ids"] = ["other"]
            elif change == "expired":
                data["expires_at"] = time.time() - 1
            elif change == "uid":
                row.uid = "another-uid"
            else:
                row.source_revision = "another-revision"
            row.preview = data
    result = env.rpc("qonto.publish", **args)
    assert result["result"]["status"] == "refused", result
    assert wire.calls == [] and reservations() == 0
    assert records() == ([], [])


@pytest.mark.parametrize("change", ["content", "type", "scope", "target"])
def test_semantic_expansion_is_review_without_raw_company_proposal(publishing, change):
    env, api, wire = publishing
    preview = issue(env)
    expanded = "PRIVATE-EXPANDED-BANK-TEXT-728342"
    payload = dict(
        action="CREATE",
        entity_type="FACT",
        scope="company",
        content=preview["fact_text"],
        reason="Confirmed minimal company projection.",
    )
    if change == "content":
        payload["content"] += expanded
    elif change == "type":
        payload.update(entity_type="COMPANY", scope="entity")
    elif change == "scope":
        payload["scope"] = "account"
    else:
        payload.update(
            action="UPDATE", write_set=[dict(blob_id="other-target", expected_version="v1")]
        )
    for _ in range(3):
        wire.answer(json.dumps(payload))
    result = confirm(env, preview)
    assert result["result"]["status"] == "review_needed", result
    blobs, operations = records()
    assert blobs == [] and operations[0]["state"] == "review"
    assert expanded not in json.dumps(operations)


def test_zero_budget_refuses_before_wire_and_keeps_pending_checkpoint(publishing):
    env, api, wire = publishing
    preview = issue(env)
    with (env.directory / ".env").open("a") as stream:
        stream.write("LLM_DAILY_BUDGET_USD=0\n")
    result = confirm(env, preview)
    assert "error" in result, result
    assert wire.calls == [] and reservations() == 0
    assert records()[0] == []
    with repository.profile_transaction() as session:
        row = session.get(QontoPublicationIntent, preview["preview_id"])
        assert row.state == "confirmed" and not row.committed_ids


def test_balance_clock_changes_do_not_invalidate_projection(publishing):
    env, api, wire = publishing
    preview = issue(env)
    api.organization["bank_accounts"][0].update(balance="120.43", balance_cents=12043)
    wire.answer(decision(preview["fact_text"]))
    assert confirm(env, preview)["result"]["status"] == "committed"


def test_checkpoint_crash_replays_company_receipt_without_paid_retry(publishing, monkeypatch):
    env, api, wire = publishing
    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    real = publication._checkpoint
    monkeypatch.setattr(
        publication,
        "_checkpoint",
        lambda *a: (_ for _ in ()).throw(RuntimeError("checkpoint crash")),
    )
    assert "error" in confirm(env, preview)
    assert records()[1][0]["state"] == "committed"
    monkeypatch.setattr(publication, "_checkpoint", real)
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    clear_process_state()
    dbm.init_db()
    assert confirm(env, preview)["result"]["status"] == "committed"
    assert len(wire.calls) == reservations() == 1


@pytest.mark.parametrize("mode", ["pause", "busy", "batch"])
def test_shared_preparation_admission_stops_publication_without_model(publishing, mode):
    env, api, wire = publishing
    from zylch.services import preparation
    from .conftest import UID
    import os

    preview = issue(env)
    if mode == "pause":
        preparation.pause(UID)
    elif mode == "busy":
        with preparation._db() as conn:
            preparation._ensure(conn, UID)
            conn.exec_driver_sql(
                "UPDATE preparation_state SET running=1,pid=? WHERE owner=?", (os.getpid(), UID)
            )
    else:
        with (env.directory / ".env").open("a") as stream:
            stream.write("PREPARATION_BATCH_SIZE=1\n")
        with preparation.preparation_run(UID):
            with preparation._db() as conn:
                conn.exec_driver_sql(
                    "UPDATE preparation_state SET attempted=1 WHERE owner=?", (UID,)
                )
            assert confirm(env, preview)["result"]["status"] == "refused"
    if mode != "batch":
        assert "error" in confirm(env, preview)
    assert wire.calls == [] and reservations() == 0 and records() == ([], [])
    if mode == "pause":
        wire.answer(decision(preview["fact_text"]))
        assert confirm(env, preview, resume=True)["result"]["status"] == "committed"
        assert preparation.status(UID)["paused"] is True
        assert preparation.status(UID)["attempted"] == 1


@pytest.mark.parametrize("boundary", ["provider", "embedding", "receipt"])
def test_disconnect_and_signout_cancel_commit_and_late_delivery(publishing, monkeypatch, boundary):
    env, api, wire = publishing
    from zylch.qonto import connection
    from zylch.auth import clear_session
    from zylch.memory.blob_storage import BlobStorage

    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    if boundary == "provider":
        wire.callback = lambda _: connection.disconnect()
    elif boundary == "embedding":
        real = BlobStorage.prepare

        def revoked(self, content):
            prepared = real(self, content)
            connection.disconnect()
            return prepared

        monkeypatch.setattr(BlobStorage, "prepare", revoked)
    else:
        real = journal.receipt

        def revoked(*args, **kwargs):
            real(*args, **kwargs)
            clear_session()

        monkeypatch.setattr(journal, "receipt", revoked)
    assert "error" in confirm(env, preview)
    assert records()[0] == []
    assert len(wire.calls) == reservations() == 1
    assert records()[1][0]["state"] != "committed"


def test_changed_currency_projection_refuses_mid_paid_response(publishing):
    env, api, wire = publishing
    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    from zylch.qonto.models import QontoAccount

    def changed(_):
        with repository.profile_transaction() as session:
            session.query(QontoAccount).filter_by(account_id="account-gbp").update(
                {"currency": "USD"}
            )

    wire.callback = changed
    assert "error" in confirm(env, preview)
    assert records()[0] == []
    assert len(wire.calls) == reservations() == 1


def test_update_uses_exact_preview_target_and_cas_never_overwrites(publishing):
    env, api, wire = publishing
    from zylch.memory.blob_storage import BlobStorage
    from tests.memory import seeding
    from .conftest import UID

    storage = BlobStorage(
        __import__("zylch.storage.database", fromlist=["get_session"]).get_session,
        BagOfWordsEmbedder(),
    )
    key = __import__(
        "zylch.memory.company_key", fromlist=["current_company_key"]
    ).current_company_key()
    existing = seeding.store_blob(
        storage,
        UID,
        "facts:" + key,
        "Category: finance\nKey: qonto\nValue: Earlier selected currencies.",
    )
    preview = issue(env)
    payload = dict(
        action="UPDATE",
        entity_type="FACT",
        scope="company",
        content=preview["fact_text"],
        reason="Confirmed minimal company projection.",
        write_set=[dict(blob_id=existing["id"], expected_version=existing["updated_at"])],
    )
    wire.answer(json.dumps(payload))
    changed = "Category: finance\nKey: qonto\nValue: Concurrent human edit."
    wire.callback = lambda _: seeding.update_blob(storage, existing["id"], UID, changed)
    for _ in range(3):
        wire.answer(json.dumps(payload))
    result = confirm(env, preview)
    assert result["result"]["status"] == "review_needed", result
    assert records()[0][0]["content"] == changed
    assert records()[1][0]["state"] == "review"


def test_raw_bank_payload_absent_from_company_file_journal_and_voice(publishing):
    env, api, wire = publishing
    from zylch.memory.company_key import current_company_key
    from tests.memory.join_env import file_bytes
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.qonto_tools import create_qonto_tools
    from .test_sync import raw

    secret = "PRIVATE-SOURCE-PUBLISH-IBAN-DE934123BANKNARRATIVE"
    api.rows.append({**raw("private"), "note": secret, "label": secret})
    assert env.rpc("qonto.sync")["result"]["status"] == "completed"
    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    assert confirm(env, preview)["result"]["status"] == "committed"
    assert secret.encode() not in file_bytes(current_company_key())
    blobs, operations = records()
    assert secret not in json.dumps([blobs, operations])
    assert "100.43" not in json.dumps([blobs, operations])
    with pytest.raises(ValueError, match="only selected memory"):
        ZylchAIAgent(create_qonto_tools(), customer_service_instructions="Voice")


def test_historical_fact_retained_after_disconnect_delete_and_ordinary_delete_allowed(publishing):
    env, api, wire = publishing
    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    assert confirm(env, preview)["result"]["status"] == "committed"
    fact = records()[0][0]
    assert "result" in env.rpc("qonto.disconnect")
    assert "result" in env.rpc("qonto.delete_imported_data", confirmed=True)
    assert records()[0][0]["content"] == preview["fact_text"]
    assert "error" in env.rpc("qonto.transaction", source_id=records()[1][0]["source_ref"])
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session
    from .conftest import UID

    storage = BlobStorage(get_session, BagOfWordsEmbedder())
    assert storage.delete_blob(fact["id"], UID)
    assert records()[0] == []


def test_cancellation_between_reservation_and_wire_releases_unused_hold(publishing, monkeypatch):
    env, api, wire = publishing
    from zylch.llm import budget
    from zylch.qonto import connection
    from zylch.storage.database import get_engine

    real = budget.reserve

    def cancelled(*args, **kwargs):
        reservation = real(*args, **kwargs)
        connection.disconnect()
        return reservation

    monkeypatch.setattr(budget, "reserve", cancelled)
    preview = issue(env)
    result = confirm(env, preview)
    assert "error" in result
    assert wire.calls == [] and records()[0] == []
    with get_engine().connect() as conn:
        assert conn.exec_driver_sql("SELECT settled_at FROM llm_reservations").scalar() is not None


def test_disconnect_after_company_commit_never_reports_stale_success(publishing, monkeypatch):
    env, api, wire = publishing
    from zylch.qonto import connection

    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    real = publication._checkpoint

    def cancelled(*args):
        connection.disconnect()
        return real(*args)

    monkeypatch.setattr(publication, "_checkpoint", cancelled)
    result = confirm(env, preview)
    assert "error" in result
    assert records()[1][0]["state"] == "committed"
    assert len(records()[0]) == 1
    assert len(wire.calls) == reservations() == 1
    with repository.profile_transaction() as session:
        assert session.get(QontoPublicationIntent, preview["preview_id"]).state == "cancelled"
    assert "error" in confirm(env, preview)
    assert len(wire.calls) == 1


def test_generic_qonto_event_has_no_publication_authority(publishing):
    env, api, wire = publishing
    from zylch.memory.mnemonic.contracts import MemoryEvent, AUTOMATIC, AUTOMATIC_OBSERVATION
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic.commit import submit
    from .conftest import UID

    event = MemoryEvent(
        owner_id=UID,
        company_key=current_company_key(),
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="qonto",
        source_id="forged",
        source_revision="forged",
        observation="Private finance content",
        stage="memory:qonto",
    )
    assert submit(event).outcome == "review_needed"
    assert records() == ([], []) and wire.calls == [] and reservations() == 0


@pytest.mark.parametrize("revoked", ["uid", "signout", "host", "join"])
def test_authority_changes_refuse_preview_replay_before_paid_work(publishing, monkeypatch, revoked):
    env, api, wire = publishing
    preview = issue(env)
    from .conftest import signin
    from zylch.auth import clear_session
    from zylch.qonto import guard

    if revoked == "uid":
        signin("same-company-sibling-uid")
    elif revoked == "signout":
        clear_session()
    elif revoked == "host":
        import uuid

        (env.home / "engine-installation-id").write_text(str(uuid.uuid4()))
    else:
        guard.suspend_for_join()
    result = confirm(env, preview)
    assert "error" in result
    assert wire.calls == [] and reservations() == 0 and records() == ([], [])
