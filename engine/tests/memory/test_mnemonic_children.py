"""A source and its children in the journal, and the restrictions a review records.

Against real split databases, as every journal test is. The parent's manifest
and its pending children land in one transaction or not at all; a terminal
child replays from its own row; a review that declined a shown FACT candidate
records a read restriction against that exact row and version and bumps the
store's mutation sequence in the same transaction, so every process's index
learns a row it holds is no longer eligible.
"""

from __future__ import annotations

import json

import pytest

from zylch.memory.mnemonic import journal, manifest
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    FACT,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    MemoryEvent,
    SubjectHint,
)
from zylch.memory.mnemonic.proposals import MnemonicResult, Proposal
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation

from .mnemonic_env import COMPANY_A, OWNER_A, boot, clear_process_state, client, stub_embedder

pytestmark = pytest.mark.usefixtures("stub_embeddings")

MAIL = "From: mario@acme.test\n\nLuca Bianchi (luca@alpha.example) will call; Acme confirms."


@pytest.fixture
def stub_embeddings(monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)


@pytest.fixture
def profile_a(tmp_path, monkeypatch):
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def parent(event_id="src-1", revision="rev-1") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-1",
        source_revision=revision,
        observation=MAIL,
        stage="memory:email",
    )


def child(index: int, entity: str, parent_id="src-1") -> MemoryEvent:
    return MemoryEvent(
        event_id=f"{parent_id}:{index}",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-1",
        source_revision="rev-1",
        observation=MAIL,
        suggestion=entity,
        stage="memory:email",
    )


ENTITIES = [
    "#IDENTIFIERS\nEntity type: PERSON\nName: Luca Bianchi\nEmail: luca@alpha.example\n#ABOUT\nCalls.",
    "#IDENTIFIERS\nEntity type: COMPANY\nName: Acme\n#ABOUT\nConfirms.",
]


def restrictions():
    """Every restriction a review recorded, read the way the eligibility predicate reads it."""
    from zylch.memory.eligibility import restricted_ids

    with get_session() as session:
        return sorted(restricted_ids(session, COMPANY_A))


def states_of(parent_id: str):
    with get_session() as session:
        return {
            r.event_id: r.state
            for r in session.query(MemoryOperation).filter(MemoryOperation.parent_event_id == parent_id).all()
        }


def rows():
    with get_session() as session:
        return {r.event_id: r.to_dict() for r in session.query(MemoryOperation).all()}


def mutation_seq():
    from zylch.storage.models import MemoryMeta

    with get_session() as session:
        return session.query(MemoryMeta.mutation_seq).filter(MemoryMeta.id == 1).scalar()


def opened_parent():
    source = parent()
    journal.open_operation(source)
    lease = journal.claim(source.event_id)
    assert lease
    return source, lease


# ─── The manifest and the children are one transaction ────────────────


def test_the_manifest_and_the_pending_children_land_together(profile_a):
    source, lease = opened_parent()
    children = [child(0, ENTITIES[0]), child(1, ENTITIES[1])]

    manifest.record_manifest(source, lease, ENTITIES, children)

    stored = rows()
    assert [entry["event_id"] for entry in stored["src-1"]["payload"]["manifest"]] == [
        "src-1:0",
        "src-1:1",
    ]
    assert stored["src-1"]["payload"]["manifest"][1]["content"] == ENTITIES[1]
    for index in (0, 1):
        row = stored[f"src-1:{index}"]
        assert row["parent_event_id"] == "src-1"
        assert row["state"] == journal.PENDING
        assert row["allowance"] == journal.EVENT_DISPATCH_ALLOWANCE
        assert row["payload"]["suggestion"] == ENTITIES[index]
    assert manifest.read_manifest("src-1")[0]["content"] == ENTITIES[0]
    assert states_of("src-1") == {"src-1:0": "pending", "src-1:1": "pending"}


def test_a_fault_while_opening_a_child_leaves_no_manifest_and_no_child(profile_a, monkeypatch):
    """Atomic: the second child's row fails, and neither the manifest nor the
    first child survives — the next run re-extracts instead of resuming a
    half-written source."""
    source, lease = opened_parent()
    children = [child(0, ENTITIES[0]), child(1, ENTITIES[1])]
    real = manifest._payload
    calls = {"n": 0}

    def failing(event, proposal):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return real(event, proposal)

    monkeypatch.setattr(manifest, "_payload", failing)
    with pytest.raises(journal.JournalError):
        manifest.record_manifest(source, lease, ENTITIES, children)

    stored = rows()
    assert set(stored) == {"src-1"}
    assert "manifest" not in (stored["src-1"]["payload"] or {})
    assert manifest.read_manifest("src-1") is None
    assert states_of("src-1") == {}


def test_a_manifest_needs_the_parents_lease(profile_a):
    source, _lease = opened_parent()
    with pytest.raises(journal.JournalError):
        manifest.record_manifest(source, "not-the-lease", ENTITIES, [child(0, ENTITIES[0]), child(1, ENTITIES[1])])
    assert states_of("src-1") == {}


def test_a_resume_leaves_existing_children_alone_and_refuses_a_re_pointed_one(profile_a):
    source, lease = opened_parent()
    children = [child(0, ENTITIES[0]), child(1, ENTITIES[1])]
    manifest.record_manifest(source, lease, ENTITIES, children)
    journal.record_result(
        "src-1:0",
        MnemonicResult.skipped("src-1:0", "nothing durable"),
        state=journal.SKIPPED,
    )

    manifest.record_manifest(source, lease, ENTITIES, children)  # the resume
    assert states_of("src-1") == {"src-1:0": "skipped", "src-1:1": "pending"}

    repointed = [child(0, ENTITIES[0]), child(1, ENTITIES[1])]
    repointed[0] = MemoryEvent(**{**repointed[0].__dict__, "observation": "something else"})
    with pytest.raises(journal.EventIdReused):
        manifest.record_manifest(source, lease, ENTITIES, repointed)


def test_a_terminal_child_replays_from_its_own_row(profile_a):
    source, lease = opened_parent()
    children = [child(0, ENTITIES[0]), child(1, ENTITIES[1])]
    manifest.record_manifest(source, lease, ENTITIES, children)
    journal.record_result(
        "src-1:1", MnemonicResult.skipped("src-1:1", "already known"), state=journal.SKIPPED
    )

    replay = journal.open_operation(children[1], parent_event_id="src-1").replay
    assert replay is not None and replay.outcome == "skipped"
    assert journal.open_operation(children[0], parent_event_id="src-1").replay is None


# ─── A review records restrictions, and the sequence moves with them ──


def test_a_review_records_a_restriction_and_bumps_the_sequence(profile_a):
    event = parent()
    journal.open_operation(event)
    before = mutation_seq()

    journal.record_result(
        "src-1",
        MnemonicResult.review_needed("src-1", "a customer's price"),
        state=journal.REVIEW,
        restrictions=[{"blob_id": "fact-1", "version": "v1"}],
    )

    assert rows()["src-1"]["restrictions"] == [{"blob_id": "fact-1", "version": "v1"}]
    assert mutation_seq() == before + 1
    assert restrictions() == ["fact-1"]


def test_a_review_without_restrictions_leaves_the_sequence_alone(profile_a):
    journal.open_operation(parent())
    before = mutation_seq()
    journal.record_result(
        "src-1", MnemonicResult.review_needed("src-1", "unclear"), state=journal.REVIEW
    )
    assert mutation_seq() == before
    assert restrictions() == []


def seed_fact(embedder, content):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(OWNER_A, f"facts:{COMPANY_A}", content, "seed")
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def fact_event(target: str) -> MemoryEvent:
    return MemoryEvent(
        event_id="evt-fact",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="r1",
        observation="For customer Edera use the negotiated 12-month minimum term.",
        subject_hint=SubjectHint(entity_type=FACT, target_blob_id=target),
    )


def review(ineligible):
    return json.dumps(
        {"action": "REVIEW", "reason": "this is Edera's term, not everyone's", "ineligible": ineligible}
    )


def test_through_submit_a_review_restricts_the_shown_fact_it_declined(profile_a, embedder):
    target, version = seed_fact(embedder, "Category: pricing\nKey: edera-term\nEdera has a 6-month minimum.")
    before = mutation_seq()

    result = submit(fact_event(target), client=client(review([target])))

    assert result.outcome == "review_needed"
    assert rows()["evt-fact"]["restrictions"] == [{"blob_id": target, "version": version}]
    assert mutation_seq() == before + 1


def test_a_review_naming_a_row_it_was_not_shown_records_nothing(profile_a, embedder):
    target, _ = seed_fact(embedder, "Category: pricing\nKey: edera-term\nEdera has a 6-month minimum.")
    # Three rounds of the same refused answer: the validator re-asks, then the
    # bounded attempts end in review with nothing recorded against anyone.
    llm = client(*[review(["fact-nobody-showed"])] * 3)

    result = submit(fact_event(target), client=llm)

    assert result.outcome == "review_needed"
    assert rows()["evt-fact"]["restrictions"] == []
    assert restrictions() == []


def test_a_review_naming_an_entity_row_records_nothing_either(profile_a, embedder):
    """Only the facts family can be quarantined: a person is not a customer-shaped FACT."""
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    person = storage.store_blob(
        OWNER_A, f"user:{COMPANY_A}", "#IDENTIFIERS\nEntity type: PERSON\nName: Edera Rossi\n#ABOUT\nx", "seed"
    )["id"]
    event = MemoryEvent(**{**fact_event(person).__dict__, "subject_hint": SubjectHint(target_blob_id=person)})

    result = submit(event, client=client(review([person])))

    assert result.outcome == "review_needed"
    assert rows()["evt-fact"]["restrictions"] == []


def test_a_restriction_survives_the_terminal_pruning(profile_a):
    journal.open_operation(parent())
    journal.record_result(
        "src-1",
        MnemonicResult.review_needed("src-1", "r"),
        state=journal.REVIEW,
        restrictions=[{"blob_id": "fact-1", "version": "v1"}],
    )
    row = rows()["src-1"]
    assert row["payload"] is None
    assert row["restrictions"] == [{"blob_id": "fact-1", "version": "v1"}]


def test_proposal_restrictions_are_shown_facts_only():
    from zylch.memory.mnemonic.commit import restrictions_from
    from zylch.memory.mnemonic.contracts import Candidate
    from zylch.memory.mnemonic.proposals import Reclassification, WriteTarget

    fact = Candidate(blob_id="fact-1", content="Category: a\nKey: b\nc", updated_at="v1", namespace=f"facts:{COMPANY_A}")
    person = Candidate(blob_id="person-1", content="x", updated_at="v2", namespace=f"user:{COMPANY_A}")
    named = Proposal(action="REVIEW", reason="r", ineligible=["fact-1", "person-1", "fact-unseen"])
    assert restrictions_from(named, (fact, person)) == [{"blob_id": "fact-1", "version": "v1"}]

    moved = Proposal(
        action="UPDATE",
        entity_type="COMPANY",
        scope="entity",
        content="#IDENTIFIERS\nEntity type: COMPANY\nName: Edera\n#ABOUT\nx",
        write_set=[WriteTarget("fact-1", "v1")],
        reclassification=Reclassification("FACT", "company", "COMPANY", "entity"),
    )
    assert restrictions_from(moved, (fact,)) == [{"blob_id": "fact-1", "version": "v1"}]
    assert restrictions_from(moved, ()) == []
