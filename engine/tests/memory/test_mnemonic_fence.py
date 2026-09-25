"""The join fence: every journal writer refuses a company that is being joined or was left.

Against real split databases — a profile ``zylch.db`` and a company store booted
through the real ``init_db`` — because the fence is a row in the company store
and the check runs inside each writer's own transaction, after its write lock.
Each writer is refused under an active fence (``fenced``, ``accepted``) and
admitted under a finished one (``completed``, ``released``); the binding check
reads the per-test profile ``.env``. What preparation does with the refusal is
``test_mnemonic_fence_items.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import current_company_key
from zylch.memory.mnemonic import fence, journal, manifest, references
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
from zylch.memory.mnemonic.fence import (
    ACCEPTED,
    COMPLETED,
    FENCED,
    JOINING,
    REBOUND,
    RELEASED,
    CompanyFenced,
)
from zylch.memory.mnemonic.proposals import MnemonicResult, PendingEffect
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.join_fence_model import MemoryJoinFence
from zylch.storage.models import Blob, MemoryMeta, MemoryOperation

from . import seeding
from .consolidation_env import healthy, live, person, scripted, seed, skip_answer, sweep
from .mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    boot,
    clear_process_state,
    client,
    stub_embedder,
    with_client,
)

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nIndustrial supplier in Milan."
)
EDERA_FACT = "Category: pricing\nKey: edera-term\nEdera has a 6-month minimum."
OTHER_KEY = "CCCCCCCCCCCCCCCCCCCCCC"


@pytest.fixture
def profile_a(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def ev(event_id="evt-1", *, company=COMPANY_A, owner=OWNER_A, observation="Acme Srl pays at 60 days.") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=company,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:fence",
        source_revision="rev-1",
        observation=observation,
    )


def fence_at(phase: str, owners=(OWNER_B,), company=COMPANY_A) -> str:
    """A fence on ``company`` moved to ``phase`` through its own compare-and-set moves."""
    fence_id = fence.place(company, owners, COMPANY_B)
    path = {
        FENCED: [],
        ACCEPTED: [(FENCED, ACCEPTED)],
        COMPLETED: [(FENCED, ACCEPTED), (ACCEPTED, COMPLETED)],
        RELEASED: [(FENCED, RELEASED)],
    }[phase]
    for expected, new in path:
        assert fence.move(fence_id, expected, new) is True
    return fence_id


def journal_state():
    """Every operation row and the mutation sequence: what "nothing written" compares."""
    with get_session() as session:
        rows = {r.event_id: r.to_dict() for r in session.query(MemoryOperation).all()}
        seq = session.query(MemoryMeta.mutation_seq).filter(MemoryMeta.id == 1).scalar()
        blobs = sorted(str(b.id) for b in session.query(Blob).all())
    return rows, seq, blobs


# ─── Every writer ─────────────────────────────────────────────────────


def _opened(_=None):
    journal.open_operation(ev())


def _claimed(_=None):
    journal.open_operation(ev())
    return journal.claim("evt-1")


WRITERS = {
    "open_operation": (lambda: None, lambda _: journal.open_operation(ev())),
    "reopen_non_terminal": (_opened, lambda _: journal.open_operation(ev())),
    "claim": (_opened, lambda _: journal.claim("evt-1")),
    "spend_allowance": (_opened, lambda _: journal.spend_allowance("evt-1")),
    "record_attempt": (_claimed, lambda _: journal.record_attempt("evt-1", ev(), None)),
    "receipt": (
        _opened,
        lambda _: journal.record_result(
            "evt-1", MnemonicResult.skipped("evt-1", "nothing durable"), state=journal.SKIPPED
        ),
    ),
    "record_manifest": (
        _claimed,
        lambda lease: manifest.record_manifest(ev(), lease, [ACME], [ev("evt-1:0")]),
    ),
    "record_remaining": (
        _opened,
        lambda _: references._record_remaining("evt-1", [PendingEffect("task_references", "a->b")]),
    ),
}


@pytest.mark.parametrize("phase", [FENCED, ACCEPTED])
@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_every_writer_is_refused_under_an_active_fence_and_writes_nothing(profile_a, writer, phase):
    prepare, act = WRITERS[writer]
    prepared = prepare()
    fence_at(phase)
    before = journal_state()

    with pytest.raises(CompanyFenced) as refused:
        act(prepared)

    assert str(refused.value) == JOINING
    assert COMPANY_B not in str(refused.value) and fence.destination_digest(COMPANY_B) not in str(refused.value)
    assert journal_state() == before


@pytest.mark.parametrize("phase", [COMPLETED, RELEASED])
@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_no_writer_is_refused_under_a_finished_fence(profile_a, writer, phase):
    prepare, act = WRITERS[writer]
    prepared = prepare()
    fence_at(phase)

    act(prepared)


def test_a_terminal_row_still_replays_under_a_fence(profile_a):
    journal.open_operation(ev())
    journal.record_result("evt-1", MnemonicResult.skipped("evt-1", "nothing durable"), state=journal.SKIPPED)
    fence_at(FENCED)
    before = journal_state()

    opened = journal.open_operation(ev())

    assert opened.replay is not None and opened.replay.outcome == "skipped"
    assert journal_state() == before


# ─── Decisions already in flight ──────────────────────────────────────


def fence_after_the_attempt(monkeypatch, snapshot):
    """Place another account's fence right after the round's attempt is recorded.

    The event was opened and claimed before it; what the fence must refuse is
    the receipt — the commit's own, or a review's — not the decision.
    """
    real = journal.record_attempt

    def recorded(*args, **kwargs):
        real(*args, **kwargs)
        fence_at(FENCED, owners=(OWNER_B,))
        snapshot.append(journal_state())

    monkeypatch.setattr(journal, "record_attempt", recorded)


def test_an_in_flight_commit_is_refused_at_its_receipt_and_writes_nothing(profile_a, monkeypatch):
    llm = client(json.dumps({"action": "CREATE", "entity_type": "COMPANY", "scope": "entity", "content": ACME, "reason": "new"}))
    snapshot = []
    fence_after_the_attempt(monkeypatch, snapshot)

    result = submit(ev(), client=llm)

    assert result.outcome == "retryable_failure" and result.reason == JOINING
    assert isinstance(result.refusal, CompanyFenced)
    assert journal_state() == snapshot[0]
    assert snapshot[0][2] == [] and snapshot[0][0]["evt-1"]["state"] == journal.PENDING


def test_a_review_with_restrictions_is_refused_at_its_receipt_and_restricts_nothing(profile_a, monkeypatch, embedder):
    fact = seeding.store_blob(BlobStorage(get_session, embedder), OWNER_A, f"facts:{COMPANY_A}", EDERA_FACT)
    review = {"action": "REVIEW", "reason": "contradicts the legacy fact", "ineligible": [str(fact["id"])]}
    llm = client(json.dumps(review))
    snapshot = []
    fence_after_the_attempt(monkeypatch, snapshot)

    result = submit(ev(observation="For customer Edera, use the negotiated 12-month minimum term."), client=llm)

    assert str(fact["id"]) in llm._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert result.outcome == "retryable_failure" and result.reason == JOINING
    assert journal_state() == snapshot[0]
    assert snapshot[0][0]["evt-1"]["restrictions"] == [] and snapshot[0][0]["evt-1"]["state"] == journal.PENDING


def test_a_fence_met_at_the_dispatch_releases_the_hold_and_charges_nothing(profile_a, monkeypatch):
    from zylch.llm.budget import budget_snapshot

    real = journal.claim

    def claimed_then_fenced(event_id):
        lease = real(event_id)
        fence_at(FENCED, owners=(OWNER_B,))
        return lease

    monkeypatch.setattr(journal, "claim", claimed_then_fenced)
    spent = budget_snapshot(OWNER_A)["spent_usd"]
    llm = client(json.dumps({"action": "CREATE", "entity_type": "COMPANY", "scope": "entity", "content": ACME, "reason": "new"}))

    result = submit(ev(), client=llm)

    assert result.outcome == "retryable_failure" and result.reason == JOINING
    assert isinstance(result.refusal, CompanyFenced)
    assert llm._client.messages.create.call_count == 0
    assert budget_snapshot(OWNER_A)["reserved_usd"] == 0
    assert budget_snapshot(OWNER_A)["spent_usd"] == spent


def test_a_chat_create_memory_answers_retryable_failure_under_a_fence(profile_a, monkeypatch):
    from zylch.assistant.turn_context import set_turn_observation
    from zylch.tools.create_memory_tool import CreateMemoryTool

    llm = with_client(monkeypatch, client())
    fence_at(ACCEPTED, owners=(OWNER_A,))
    set_turn_observation("Acme Srl pays at 60 days.")
    before = journal_state()

    direct = submit(ev("evt-direct"), client=llm)
    tool = asyncio.run(CreateMemoryTool(owner_id=OWNER_A).execute(content="Acme pays at 60 days", entry_type="entity_fact"))

    assert direct.outcome == "retryable_failure" and direct.reason == JOINING
    assert tool.data["action"] == "retryable_failure" and tool.error == JOINING
    assert llm._client.messages.create.call_count == 0
    assert journal_state() == before


# ─── The fence row ────────────────────────────────────────────────────


def test_a_company_holds_one_active_fence_and_a_finished_one_does_not_count(profile_a):
    first = fence.place(COMPANY_A, [OWNER_A, "a@company.test", ""], COMPANY_B)
    with pytest.raises(CompanyFenced, match=JOINING):
        fence.place(COMPANY_A, [OWNER_B], OTHER_KEY)
    assert fence.release(first) is True
    second = fence.place(COMPANY_A, [OWNER_B], OTHER_KEY)
    assert fence.move(second, FENCED, ACCEPTED) and fence.move(second, ACCEPTED, COMPLETED)
    fence.place(COMPANY_A, [OWNER_A], COMPANY_B)

    with get_session() as session:
        rows = {r.id: r.to_dict() for r in session.query(MemoryJoinFence).all()}
    assert len(rows) == 3 and sorted(r["phase"] for r in rows.values()) == [COMPLETED, FENCED, RELEASED]
    assert rows[first]["owner_ids"] == ["a@company.test", OWNER_A]
    assert rows[first]["destination_digest"] == fence.destination_digest(COMPANY_B)
    assert all(COMPANY_B not in json.dumps(r, default=str) for r in rows.values())


def test_a_move_is_a_compare_and_set_and_refuses_an_unknown_move(profile_a):
    fence_id = fence.place(COMPANY_A, [OWNER_A], COMPANY_B)

    assert fence.move(fence_id, ACCEPTED, COMPLETED) is False
    assert fence.move(fence_id, FENCED, FENCED, snapshot_digest="d1", detail={"blobs": 2}) is True
    assert fence.move(fence_id, FENCED, ACCEPTED) is True
    assert fence.release(fence_id) is False
    with pytest.raises(ValueError):
        fence.move(fence_id, COMPLETED, FENCED)
    with pytest.raises(ValueError):
        fence.move(fence_id, ACCEPTED, ACCEPTED, destination_digest="x")
    with get_session() as session:
        row = session.get(MemoryJoinFence, fence_id).to_dict()
    assert (row["phase"], row["snapshot_digest"], row["detail"]) == (ACCEPTED, "d1", {"blobs": 2})


# ─── The binding check: the profile's .env on disk ────────────────────


def profile_env() -> Path:
    """The per-test profile's ``.env``: the only file these tests write."""
    path = Path(os.environ["ZYLCH_PROFILE_DIR"]) / ".env"
    assert "zylch-test-profile" in str(path) and path.is_file()
    return path


def replace_env(path: Path, text: str, *, keep_mtime_ns: bool = False) -> None:
    """Replace the file as ``settings_io`` does: a new inode, renamed over the old."""
    before = os.stat(path)
    tmp = path.with_name(".env.fence-test")
    tmp.write_text(text)
    if keep_mtime_ns:
        os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(tmp, path)


def test_the_binding_check_refuses_a_profile_whose_env_names_another_company(company_db):
    key = current_company_key()
    path = profile_env()
    assert f"MEMORY_KEY={key}" in path.read_text()
    journal.open_operation(ev("evt-here", company=key))

    replace_env(path, path.read_text().replace(key, OTHER_KEY))

    with pytest.raises(CompanyFenced) as refused:
        journal.open_operation(ev("evt-left", company=key))
    assert str(refused.value) == REBOUND
    with get_session() as session:
        assert session.get(MemoryOperation, "evt-left") is None


def test_the_binding_check_admits_an_env_that_names_no_key(company_db):
    key = current_company_key()
    path = profile_env()
    replace_env(path, "".join(line for line in path.read_text().splitlines(True) if not line.startswith("MEMORY_KEY=")))

    journal.open_operation(ev("evt-unnamed", company=key))


def test_the_binding_check_admits_a_process_with_no_active_profile(company_db, monkeypatch):
    key = current_company_key()
    path = profile_env()
    replace_env(path, path.read_text().replace(key, OTHER_KEY))
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")

    journal.open_operation(ev("evt-no-profile", company=key))


def test_the_binding_cache_re_reads_a_replaced_env_within_the_same_mtime(company_db):
    key = current_company_key()
    path = profile_env()
    journal.open_operation(ev("evt-cached", company=key))
    text = path.read_text()
    first = os.stat(path)

    replace_env(path, text.replace(key, OTHER_KEY), keep_mtime_ns=True)
    second = os.stat(path)
    assert (second.st_mtime_ns, second.st_size) == (first.st_mtime_ns, first.st_size)
    assert second.st_ino != first.st_ino

    with pytest.raises(CompanyFenced, match="restart the engine"):
        journal.open_operation(ev("evt-replaced", company=key))
    replace_env(path, text, keep_mtime_ns=True)
    journal.open_operation(ev("evt-back", company=key))


# ─── What reads the fence ─────────────────────────────────────────────


def test_consolidation_rests_while_the_company_is_fenced(profile_a):
    from zylch.memory.consolidation import consolidate, failed, summary_lines

    fence_id = fence_at(FENCED, owners=(OWNER_B,))
    before = journal_state()

    summary = asyncio.run(consolidate(OWNER_A, force=True))

    assert summary["skipped"] is True and summary["reason"] == JOINING
    assert failed(summary) is None
    assert summary_lines(summary) == [f"skipped: {JOINING}"]
    assert journal_state() == before
    fence.release(fence_id)
    assert asyncio.run(consolidate(OWNER_A, force=True))["skipped"] is False


def test_a_fence_placed_between_pairs_stops_the_sweep_and_is_no_failure(profile_a, monkeypatch, embedder):
    from zylch.memory import consolidation

    store = BlobStorage(get_session, embedder)
    first = seed(store, person(about="Purchasing at Alpha; handles every order and every return."))
    second = seed(store, person(about="Joins the Thursday sync."))
    third = seed(store, person(about="Called once."))
    healthy(monkeypatch)
    transport = scripted(monkeypatch, skip_answer())
    real = consolidation._tally

    def tallied_then_fenced(summary, result):
        kept = real(summary, result)
        fence_at(FENCED, owners=(OWNER_B,))
        return kept

    monkeypatch.setattr(consolidation, "_tally", tallied_then_fenced)

    summary = sweep()

    assert summary["stopped"] == JOINING and summary["skipped"] is False
    assert summary["pairs_decided"] == summary["blobs_kept_distinct"] == 1
    assert consolidation.failed(summary) is None
    assert transport.call_count == 1
    assert live(store, first, second, third) == {first, second, third}


def test_consolidation_rests_for_a_profile_that_left_the_company(company_db):
    from zylch.memory.consolidation import consolidate, failed

    path = profile_env()
    replace_env(path, path.read_text().replace(current_company_key(), OTHER_KEY))

    summary = asyncio.run(consolidate(OWNER_A, force=True))

    assert summary["skipped"] is True and summary["reason"] == REBOUND and failed(summary) is None


def test_memory_status_reports_the_fence_and_never_the_destination(profile_a):
    from zylch.memory.join import status

    assert status()["joining"] is False
    fence_id = fence_at(ACCEPTED, owners=(OWNER_B,))

    out = status()

    assert out["joining"] is True and out["joining_reason"] == JOINING and out["available"] is True
    rendered = json.dumps(out, default=str)
    assert COMPANY_B not in rendered and fence.destination_digest(COMPANY_B) not in rendered
    assert fence.move(fence_id, ACCEPTED, COMPLETED)
    assert status()["joining"] is False
