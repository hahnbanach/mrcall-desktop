"""A proposal that departs from the request is committed, and the departure is recorded.

The write-time approval gate is withdrawn (brief amendment, 2026-09-23). What
replaces it is not another gate: the rewrite retains the text it replaces
(`test_blob_versions.py`), and the operation receipt says how the role's
decision departed from what the tool call asked for. Both halves are asserted
against real rows — the journal row's `departure` column and the tool's
`data["departure"]` — so a departure that is written but not recorded, or
recorded but not returned, fails here.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zylch.memory.mnemonic.approval import (
    CHANGED_SUBJECT,
    UNNAMED_SUBJECT,
    RequestedWrite,
    departure_for,
)
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    CREATE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.memory.mnemonic.proposals import Proposal, WriteTarget
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, MemoryOperation

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
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
BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: info@beta.test\n#ABOUT\nPackaging supplier in Turin."
)
BETA_CORRECTED = BETA.replace("info@beta.test", "orders@beta.test")
SAID = "L'indirizzo ordini di Beta Spa ora è orders@beta.test, non info@beta.test"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation(SAID)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def seed(content, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(
        owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", content=content, event_description="seed"
    )
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def blobs():
    with get_session() as session:
        return {b.id: b.content for b in session.query(Blob).all()}


def journal_rows():
    with get_session() as session:
        return [r.to_dict() for r in session.query(MemoryOperation).all()]


def update_decision(blob_id, version, content=BETA_CORRECTED):
    return json.dumps(
        {
            "action": UPDATE,
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the ordering address replaces the old one",
        }
    )


def run_update(monkeypatch, *, named, target, version):
    """The real ``update_memory`` tool: the model named ``named``, the role writes ``target``."""
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    with_client(monkeypatch, client(update_decision(target, version)))
    return asyncio.run(
        UpdateMemoryTool(owner_id=OWNER_A).execute(
            blob_id=named, new_content=BETA_CORRECTED, entry_type="entity_fact"
        )
    )


# ─── What a departure is ──────────────────────────────────────────────


def test_a_faithful_proposal_records_no_departure():
    requested = RequestedWrite(action=UPDATE, blob_id="b1", subject_is_authoritative=True)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b1", expected_version="v1"),),
    )
    assert departure_for(requested, proposal) is None


def test_a_departure_names_the_flags_the_reasons_and_both_sides():
    requested = RequestedWrite(action=CREATE, entity_type="COMPANY")
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b9", expected_version="v1"),),
    )
    record = departure_for(requested, proposal)
    assert record["flags"] == ["changed_action", UNNAMED_SUBJECT]
    assert len(record["why"]) == 2
    assert record["requested"]["action"] == CREATE
    assert record["proposed"] == {
        "action": UPDATE,
        "entity_type": "COMPANY",
        "scope": "entity",
        "targets": ["b9"],
    }
    # JSON-shaped, because it is stored and returned as it is.
    json.dumps(record)


def test_with_no_baseline_nothing_is_recorded():
    """A false flag in the journal is worse than an absent one."""
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="b1", expected_version="v1"),),
    )
    assert departure_for(None, proposal) is None


# ─── Against real rows ────────────────────────────────────────────────


def test_a_changed_subject_is_committed_and_recorded_on_both_sides(profile, monkeypatch, embedder):
    """The model named ACME; the human spoke about Beta; the role wrote Beta.

    That write lands — nobody is asked — and the departure is in the journal
    row and in the tool's response, so a reader can see the role chose
    differently from the call.
    """
    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)

    result = run_update(monkeypatch, named=named, target=target, version=version)

    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]
    assert blobs()[named] == ACME
    departure = result.data["departure"]
    assert CHANGED_SUBJECT in departure["flags"]
    assert departure["requested"]["blob_id"] == named
    assert departure["proposed"]["targets"] == [target]
    (row,) = journal_rows()
    assert row["state"] == "committed"
    assert row["departure"] == departure


def test_a_faithful_update_leaves_the_column_and_the_field_empty(profile, monkeypatch, embedder):
    target, version = seed(BETA, embedder)

    result = run_update(monkeypatch, named=target, target=target, version=version)

    assert result.status.value == "success", result.error
    assert result.data["departure"] is None
    (row,) = journal_rows()
    assert row["departure"] is None


def test_a_headless_caller_writes(profile, monkeypatch, embedder):
    """There is no channel to lack: nothing at write time asks anyone."""
    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)
    result = run_update(monkeypatch, named=named, target=target, version=version)
    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]


def test_the_departing_write_retained_what_it_replaced(profile, monkeypatch, embedder):
    """The two halves together: recorded, and reversible."""
    from zylch.memory.blob_versions import list_versions

    named, _ = seed(ACME, embedder)
    target, version = seed(BETA, embedder)
    run_update(monkeypatch, named=named, target=target, version=version)
    with get_session() as session:
        kept = list_versions(session, target)
        assert [v.content for v in kept] == [BETA]
        assert kept[0].operation_id == journal_rows()[0]["event_id"]


def test_submit_without_a_baseline_commits_and_records_nothing(profile, monkeypatch, embedder):
    target, version = seed(BETA, embedder)
    event = MemoryEvent(
        event_id="evt-no-baseline",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation=SAID,
    )
    result = submit(event, client=client(update_decision(target, version)))
    assert result.outcome == "committed", result.reason
    assert result.departure is None
    (row,) = journal_rows()
    assert row["departure"] is None
