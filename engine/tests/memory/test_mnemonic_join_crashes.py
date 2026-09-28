"""The join's crash states converge, and a profile that left a company writes nothing there (AC5).

Against two real company stores and a real profile: the destination holds a
fact the source also states, the joining profile holds an entity with a
retained version, a losing fact and its own rule. A crash is a real
``BaseException`` raised from an injected fault — inside the import, after the
destination commit, after the acceptance, after the key write, after the
rebind — and a restart is the real boot (``reboot()``), whose attach path runs
the join's recovery, or the recovery itself. Each converges on one import: no
duplicate row, nothing lost, nothing written into the source after acceptance,
the fence ``completed``. The refusals of unsettled work are
``test_mnemonic_join_cutover.py``.
"""

from __future__ import annotations

import fcntl
from types import SimpleNamespace

import pytest

from zylch.memory import join_import, join_recover
from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import current_company_key
from zylch.memory.join import join
from zylch.memory.mnemonic import fence, journal
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
from zylch.memory.mnemonic.fence import ACCEPTED, COMPLETED, FENCED, REBOUND, RELEASED, CompanyFenced
from zylch.memory.store import memory_db_path, open_memory_engine
from zylch.storage import database as dbm
from zylch.storage.database import get_session

from . import seeding
from .join_env import (
    blob_ids,
    count,
    env_bytes,
    env_value,
    file_bytes,
    isolate,
    phases,
    receipts,
    rows,
    store_digest,
)
from .mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    boot,
    clear_process_state,
    reboot,
    stub_embedder,
)

OWNER_C = "uid-owner-c"
LUCA = "#IDENTIFIERS\nEntity type: PERSON\nName: Luca Bianchi\nEmail: luca@alpha.example\n#ABOUT\nPurchasing at Alpha."
LUCA_LATER = LUCA + "\n#HISTORY\n- asked for a quote"
PRICE_B = "Category: pricing\nKey: list\nValue: EUR 100 per unit"
PRICE_A = "Category: pricing\nKey: list\nValue: EUR 120 per unit"
RULE_A = "Sign every reply with the warehouse number."


class Crash(BaseException):
    """The process going away: not an Exception, so nothing on the way out catches it."""


def once(real):
    """``real``, except that its first call crashes."""
    left = {"n": 1}

    def crashing(*args, **kwargs):
        if left["n"]:
            left["n"] -= 1
            raise Crash()
        return real(*args, **kwargs)

    return crashing


@pytest.fixture
def world(tmp_path, monkeypatch, embedder):
    """The destination with its own fact; the joining profile on the source, booted last."""
    isolate(monkeypatch)
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_B)
    seeding.store_blob(BlobStorage(get_session, embedder), OWNER_B, f"facts:{COMPANY_B}", PRICE_B, "seed")
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    storage = BlobStorage(get_session, embedder)
    luca = seeding.store_blob(storage, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    seeding.update_blob(storage, luca["id"], OWNER_A, LUCA_LATER, "seed", expected_updated_at=luca["updated_at"])
    price = seeding.store_blob(storage, OWNER_A, f"facts:{COMPANY_A}", PRICE_A, "seed")
    rule = seeding.store_blob(storage, OWNER_A, f"template:{OWNER_A}", RULE_A, "seed")
    yield SimpleNamespace(
        root=tmp_path, storage=storage, luca=luca["id"], price=price["id"], rule=rule["id"]
    )
    dbm.dispose_engine()
    clear_process_state()


def converged(world):
    """One import, nothing twice, nothing lost; the profile on the destination, the fence completed."""
    assert current_company_key() == COMPANY_B and env_value("MEMORY_KEY") == COMPANY_B
    assert env_value("MEMORY_JOIN_TO") == "" and env_value("MEMORY_JOIN_FROM") == ""
    assert dbm.current_memory_engine().url.database == memory_db_path(COMPANY_B)
    assert phases(COMPANY_A)[-1] == COMPLETED and FENCED not in phases(COMPANY_A)
    assert len(receipts()) == 1
    assert {world.luca, world.rule} <= blob_ids(COMPANY_B) and world.price not in blob_ids(COMPANY_B)
    assert count(COMPANY_B, "blobs") == 3
    assert count(COMPANY_B, "fact_history") == 1
    assert rows(COMPANY_B, "SELECT COUNT(*) FROM blob_versions WHERE blob_id = ?", [world.luca]) == [(1,)]


def chat_event(event_id: str, owner: str = OWNER_A) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme Srl pays at 60 days.",
    )


# ─── Crash points ─────────────────────────────────────────────────────


def test_a_crash_inside_the_import_rolls_the_destination_back_and_the_rerun_imports_once(world, monkeypatch):
    real = join_import._put
    calls = {"n": 0}

    def crashing(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return real(*args, **kwargs)

    monkeypatch.setattr(join_import, "_put", crashing)
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert phases(COMPANY_A) == [FENCED] and env_value("MEMORY_JOIN_TO") == COMPANY_B
    assert count(COMPANY_B, "blobs") == 1 and receipts() == []
    monkeypatch.setattr(join_import, "_put", real)
    source = store_digest(COMPANY_A)

    assert join(COMPANY_B)["ok"] is True

    converged(world)
    assert phases(COMPANY_A) == [RELEASED, COMPLETED]
    assert store_digest(COMPANY_A) == source


def test_a_crash_after_the_destination_commit_is_accepted_at_boot_without_a_second_import(world, monkeypatch):
    monkeypatch.setattr(join_import, "_accept", once(join_import._accept))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert phases(COMPANY_A) == [FENCED] and len(receipts()) == 1
    assert current_company_key() == COMPANY_A and env_value("MEMORY_JOIN_TO") == COMPANY_B
    source, destination = store_digest(COMPANY_A), store_digest(COMPANY_B)
    real_copy = join_import._copy
    copies = []
    monkeypatch.setattr(join_import, "_copy", lambda *a, **k: copies.append(1) or real_copy(*a, **k))

    reboot()

    converged(world)
    assert copies == [] and phases(COMPANY_A) == [COMPLETED]
    assert store_digest(COMPANY_A) == source and store_digest(COMPANY_B) == destination
    assert COMPANY_B.encode() not in file_bytes(COMPANY_A)
    assert COMPANY_A.encode() not in file_bytes(COMPANY_B)


def test_a_crash_after_the_acceptance_before_the_key_finishes_at_boot(world, monkeypatch):
    from zylch.memory import company_key

    monkeypatch.setattr(company_key, "persist_company_key", once(company_key.persist_company_key))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert phases(COMPANY_A) == [ACCEPTED] and env_value("MEMORY_KEY") == COMPANY_A
    source = store_digest(COMPANY_A)

    reboot()

    converged(world)
    assert store_digest(COMPANY_A) == source


def test_a_crash_after_the_key_write_is_completed_at_boot(world, monkeypatch):
    monkeypatch.setattr(dbm, "rebind_memory", once(dbm.rebind_memory))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert env_value("MEMORY_KEY") == COMPANY_B and env_value("MEMORY_JOIN_FROM") == COMPANY_A
    assert env_value("MEMORY_JOIN_TO") == "" and phases(COMPANY_A) == [ACCEPTED]
    source = store_digest(COMPANY_A)

    reboot()

    converged(world)
    assert store_digest(COMPANY_A) == source


def test_a_crash_after_the_rebind_is_completed_by_the_next_recovery(world, monkeypatch):
    monkeypatch.setattr(join_recover, "_complete", once(join_recover._complete))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert dbm.current_memory_engine().url.database == memory_db_path(COMPANY_B)
    assert phases(COMPANY_A) == [ACCEPTED] and env_value("MEMORY_JOIN_FROM") == COMPANY_A

    assert join_recover.recover() == {"state": "after_key", "completed": True}

    converged(world)
    assert join_recover.recover() == {"state": "completed", "released": 0}


def test_a_fence_left_before_the_evaluation_is_released_by_recovery(world, monkeypatch):
    from zylch.memory import join as join_mod

    monkeypatch.setattr(join_mod, "blocking_work", once(join_mod.blocking_work))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert phases(COMPANY_A) == [FENCED] and env_value("MEMORY_JOIN_TO") == ""

    assert join_recover.recover() == {"state": "completed", "released": 1}
    assert phases(COMPANY_A) == [RELEASED] and current_company_key() == COMPANY_A


# ─── The import's keys, its compare-and-set, a changed source ─────────


def imported(fence_id: str) -> dict:
    destination = join_recover.open_store(COMPANY_B)
    try:
        return join_import.import_into(
            dbm.current_memory_engine(), destination, fence_id,
            source_key=COMPANY_A, destination_key=COMPANY_B,
        )
    finally:
        destination.dispose()


def completed_import() -> dict:
    fence_id = fence.place(COMPANY_A, [OWNER_A], COMPANY_B)
    counts = imported(fence_id)
    assert fence.move(fence_id, ACCEPTED, COMPLETED)
    return counts


def tables():
    return {t: count(COMPANY_B, t) for t in ("blobs", "blob_versions", "fact_history", "blob_sentences", "person_identifiers")}


def test_a_second_import_of_the_same_source_under_a_new_fence_writes_nothing_twice(world):
    completed_import()
    first = tables()
    assert first["fact_history"] == 1

    assert completed_import()["blobs"] == 0
    assert tables() == first
    current = world.storage.get_blob(world.luca, OWNER_A)
    seeding.update_blob(
        world.storage, world.luca, OWNER_A, LUCA_LATER + "\n- paid", "seed",
        expected_updated_at=current["updated_at"],
    )
    assert completed_import()["retained"] == 1
    changed = tables()
    completed_import()

    assert tables() == changed and changed["blob_versions"] == first["blob_versions"] + 2
    assert rows(COMPANY_B, "SELECT COUNT(*) FROM blob_versions WHERE reason = 'join'") == [(1,)]
    assert rows(COMPANY_B, "SELECT content FROM blobs WHERE id = ?", [world.luca]) == [(LUCA_LATER,)]
    assert len(receipts()) == 4


def test_an_import_under_a_fence_that_is_no_longer_fenced_writes_nothing(world):
    fence_id = fence.place(COMPANY_A, [OWNER_A], COMPANY_B)
    assert fence.release(fence_id)
    before = store_digest(COMPANY_B)

    with pytest.raises(join_import.ImportRefused, match="released, not fenced"):
        imported(fence_id)

    assert store_digest(COMPANY_B) == before and phases(COMPANY_A) == [RELEASED]


def test_a_source_changed_after_the_destination_commit_refuses_the_switch_and_releases(world, monkeypatch):
    monkeypatch.setattr(join_import, "_accept", once(join_import._accept))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert world.storage.delete_blob(world.rule, OWNER_A)

    answer = join_recover.recover()

    assert answer["action"] == "released" and "changed" in answer["reason"]
    assert phases(COMPANY_A) == [RELEASED] and current_company_key() == COMPANY_A
    assert env_value("MEMORY_KEY") == COMPANY_A and env_value("MEMORY_JOIN_TO") == ""
    assert join(COMPANY_B)["ok"] is True
    assert world.rule in blob_ids(COMPANY_B) and len(receipts()) == 2


def test_a_recovery_beside_a_running_join_touches_nothing(world, monkeypatch):
    monkeypatch.setattr(join_import, "_accept", once(join_import._accept))
    with pytest.raises(Crash):
        join(COMPANY_B)
    before = env_bytes()
    holder = open(join_recover.lock_path() + join_recover.LOCK_SUFFIX, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert join_recover.recover() == {"state": "busy"}
        assert phases(COMPANY_A) == [FENCED] and env_bytes() == before
    finally:
        holder.close()

    assert join_recover.recover() == {"state": "before_key", "action": "accepted"}
    converged(world)


# ─── After cutover ────────────────────────────────────────────────────


def test_a_second_process_still_bound_to_the_source_writes_nothing_there(world, monkeypatch):
    from tests.workers.ingestion_env import create_decision, email_processed, extraction, make_worker, run, seed_email

    assert join(COMPANY_B)["ok"] is True
    source = store_digest(COMPANY_A)
    monkeypatch.setenv("MEMORY_KEY", COMPANY_A)
    dbm.set_memory_engine(open_memory_engine(COMPANY_A, create=False), None)
    clear_process_state()

    answer = submit(chat_event("turn-stale"))
    assert answer.outcome == "retryable_failure" and answer.reason == REBOUND
    mail = seed_email(owner=OWNER_A)
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    with pytest.raises(CompanyFenced, match="restart the engine"):
        run(worker, "process_email", mail)

    assert worker.client._client.messages.create.call_count == 0
    assert not email_processed("mail-1")
    assert store_digest(COMPANY_A) == source


def test_another_account_a_fresh_profile_and_the_joiner_coming_back_write_the_source(world, monkeypatch):
    assert join(COMPANY_B)["ok"] is True
    joiner = world.root / f"profile-{OWNER_A}"

    boot(monkeypatch, world.root, OWNER_C, COMPANY_A)
    assert journal.open_operation(chat_event("turn-colleague", owner=OWNER_C)).state == journal.PENDING
    boot(monkeypatch, world.root, OWNER_A, COMPANY_A, profile="profile-fresh")
    assert journal.open_operation(chat_event("turn-fresh")).state == journal.PENDING

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(joiner))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(joiner / "zylch.db"))
    monkeypatch.setenv("MEMORY_KEY", COMPANY_B)
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "join")
    reboot()
    assert join(COMPANY_A)["ok"] is True

    assert journal.open_operation(chat_event("turn-back")).state == journal.PENDING
    assert phases(COMPANY_A) == [COMPLETED] and phases(COMPANY_B) == [COMPLETED]


# ─── What the import's digest and its guards answer ───────────────────


def test_a_source_text_changed_after_the_destination_commit_refuses_the_switch(world, monkeypatch):
    monkeypatch.setattr(join_import, "_accept", once(join_import._accept))
    with pytest.raises(Crash):
        join(COMPANY_B)
    current = world.storage.get_blob(world.luca, OWNER_A)
    seeding.update_blob(
        world.storage, world.luca, OWNER_A, LUCA_LATER + "\n- paid", "seed",
        expected_updated_at=current["updated_at"],
    )

    answer = join_recover.recover()

    assert answer["action"] == "released" and "changed" in answer["reason"]
    assert phases(COMPANY_A) == [RELEASED] and current_company_key() == COMPANY_A


def test_a_restriction_recorded_after_the_destination_commit_refuses_the_switch(world, monkeypatch):
    from zylch.memory.mnemonic.proposals import MnemonicResult

    monkeypatch.setattr(join_import, "_accept", once(join_import._accept))
    with pytest.raises(Crash):
        join(COMPANY_B)
    with monkeypatch.context() as slipped:
        slipped.setattr(journal, "refuse_if_fenced", lambda *args, **kwargs: None)
        event = chat_event("turn-restricts")
        journal.open_operation(event)
        journal.record_result(
            event.event_id, MnemonicResult.review_needed(event.event_id, "customer-specific"),
            state=journal.REVIEW, restrictions=[{"blob_id": world.price, "version": "v"}],
        )

    answer = join_recover.recover()

    assert answer["action"] == "released" and "changed" in answer["reason"]
    assert phases(COMPANY_A) == [RELEASED] and env_value("MEMORY_JOIN_TO") == ""


def test_a_destination_that_is_being_joined_itself_refuses_the_import(world):
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage.join_fence_model import MemoryJoinFence

    destination = join_recover.open_store(COMPANY_B)
    with company_transaction(write=True, engine=destination) as session:
        session.add(MemoryJoinFence(
            id="fence-of-b", company_key=COMPANY_B, owner_ids=[OWNER_B],
            destination_digest=fence.destination_digest(COMPANY_A), phase=FENCED, detail={},
        ))
    destination.dispose()
    before = store_digest(COMPANY_B)

    out = join(COMPANY_B)

    assert out["ok"] is False and "being joined" in out["reason"], out
    assert store_digest(COMPANY_B) == before and receipts() == []
    assert phases(COMPANY_A) == [RELEASED] and env_value("MEMORY_JOIN_TO") == ""
    assert current_company_key() == COMPANY_A


def test_an_acceptance_that_finds_the_fence_moved_refuses_the_switch(world, monkeypatch):
    real = fence.cas

    def moved(session, fence_id, expected, new, **fields):
        return False if new == ACCEPTED else real(session, fence_id, expected, new, **fields)

    monkeypatch.setattr(fence, "cas", moved)

    out = join(COMPANY_B)

    assert out["ok"] is False and "moved during the import" in out["reason"], out
    assert phases(COMPANY_A) == [RELEASED] and env_value("MEMORY_JOIN_TO") == ""
    assert current_company_key() == COMPANY_A and env_value("MEMORY_KEY") == COMPANY_A


def test_a_live_process_stopped_after_the_key_write_is_rebound_by_its_next_recovery(world, monkeypatch):
    monkeypatch.setattr(dbm, "rebind_memory", once(dbm.rebind_memory))
    with pytest.raises(Crash):
        join(COMPANY_B)
    assert dbm.current_memory_engine().url.database == memory_db_path(COMPANY_A)

    assert join_recover.recover() == {"state": "after_key", "completed": True}

    converged(world)
