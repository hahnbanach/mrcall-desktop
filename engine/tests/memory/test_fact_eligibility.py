"""Read eligibility: a known customer-shaped FACT is absent from every ordinary read.

Against a real store. Two arms make a facts-family row ineligible — its own
header stating an entity scope or type, and a review in the journal naming it
— and both are applied before ranking and limits: category enumeration, the
exact reads, and hybrid search at index load, text search and hydration. The
journal arm is proven on the frozen corpus's ``contradictory_legacy_fact_rule``
run through the real ``submit`` with its scripted REVIEW.
"""

from __future__ import annotations

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.eligibility import ineligible_fact_ids, scope_mismatch
from zylch.memory.hybrid_search import HybridSearchEngine
from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    COMPANY,
    MemoryEvent,
    SubjectHint,
)
from zylch.services import facts_store
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob

from .mnemonic_cases import case, decision_text
from .mnemonic_env import COMPANY_A, OWNER_A, boot, clear_process_state, client, stub_embedder

pytestmark = pytest.mark.usefixtures("stub_embeddings")

FACTS = f"facts:{COMPANY_A}"
HOURS = "Category: hours\nKey: opening\nValue: 9-18 on weekdays"
PRICE = "Category: pricing\nKey: list\nValue: EUR 100 per unit"
ENTITY_SCOPED = "#IDENTIFIERS\nEntity type: FACT\nScope: entity\nCategory: pricing\nKey: acme-term\n#ABOUT\nValue: 60 days"
PERSON_TYPED = "#IDENTIFIERS\nEntity type: PERSON\nCategory: pricing\nKey: mario-rate\n#ABOUT\nValue: EUR 80"


@pytest.fixture
def stub_embeddings(monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)


@pytest.fixture
def profile_a(tmp_path, monkeypatch):
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def seed(embedder, content, *, namespace=FACTS, blob_id=None):
    """A row the way the legacy writer left it: embedded, in its namespace."""
    with get_session() as session:
        blob = Blob(
            owner_id=OWNER_A,
            company_key=COMPANY_A,
            namespace=namespace,
            content=content,
            embedding=embedder.encode(content).tobytes(),
            **({"id": blob_id} if blob_id else {}),
        )
        session.add(blob)
        session.flush()
        return str(blob.id)


def fact_ids(owner=OWNER_A):
    return {row["blob_id"] for row in facts_store._all_fact_blobs(owner)}


def searched(engine, query, **kwargs):
    return [r.blob_id for r in engine.search(OWNER_A, query, **kwargs)]


# ─── The header arm ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "content, mismatched",
    [
        (HOURS, False),
        ("#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: a\nKey: b\n#ABOUT\nc", False),
        (ENTITY_SCOPED, True),
        (PERSON_TYPED, True),
        ("#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\nx", True),
    ],
)
def test_a_header_stating_an_entity_scope_or_type_is_a_mismatch(content, mismatched):
    assert scope_mismatch(content) is mismatched


def test_a_customer_shaped_fact_is_absent_from_categories_counts_and_reads(profile_a, embedder):
    hours = seed(embedder, HOURS)
    price = seed(embedder, PRICE)
    scoped = seed(embedder, ENTITY_SCOPED)
    typed = seed(embedder, PERSON_TYPED)

    assert fact_ids() == {hours, price}
    assert {c["category"]: c["count"] for c in facts_store.list_categories(OWNER_A)} == {
        "hours": 1,
        "pricing": 1,
    }
    assert {r["blob_id"] for r in facts_store.get_facts_by_category(OWNER_A, "pricing")} == {price}
    assert facts_store.exact_fact(OWNER_A, "pricing", "list")["blob_id"] == price
    assert facts_store.exact_fact(OWNER_A, "pricing", "acme-term") is None
    assert facts_store.exact_fact(OWNER_A, "pricing", "mario-rate") is None
    with get_session() as session:
        assert ineligible_fact_ids(session, COMPANY_A) == {scoped, typed}


def test_hybrid_search_leaves_a_quarantined_fact_out_before_ranking(profile_a, embedder):
    """The crowd-out case: more quarantined rows than the vector arm's top-K,
    every one ranking above the single valid row, and the valid row is still
    the answer. Every row carries a header, so the text arm sees only the
    header and the query reaches the rows through the vector arm alone —
    which is the arm a filter applied after ranking would leave blind."""
    valid = seed(
        embedder,
        "#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: pricing\nKey: list\n"
        "#ABOUT\nValue: acme orders EUR per unit",
    )
    crowd = [
        seed(
            embedder,
            f"#IDENTIFIERS\nEntity type: FACT\nScope: entity\nCategory: pricing\nKey: acme-{i}\n"
            "#ABOUT\nValue: acme orders acme orders acme orders EUR per unit",
        )
        for i in range(4)
    ]
    engine = HybridSearchEngine(get_session, embedder)

    found = searched(engine, "acme orders EUR per unit", limit=1)

    assert found == [valid]
    assert not set(found) & set(crowd)


# ─── The journal arm, on the corpus's own case ────────────────────────


def seed_corpus_case(embedder):
    spec = case("contradictory_legacy_fact_rule")
    for candidate in spec["candidates"]:
        namespace = FACTS if candidate["entity_type"] == "FACT" else f"template:{OWNER_A}"
        seed(embedder, candidate["content"], namespace=namespace, blob_id=candidate["id"])
    hint = spec["subject_hint"]
    return MemoryEvent(
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-edera",
        source_revision="rev-1",
        observation=spec["original_observation"],
        subject_hint=SubjectHint(entity_type=COMPANY, name=hint["name"]),
        stage="memory:email",
        event_id="evt-edera",
    )


def admitted(event):
    """The corpus case is an automatic observation; run it as one admitted item."""
    from zylch.services.preparation import bounded_item, preparation_run

    class Worker:
        owner_id = OWNER_A

        @bounded_item("memory:email")
        async def process(self, source, llm):
            return submit(event, client=llm)

    import asyncio

    def run(llm):
        with preparation_run(OWNER_A):
            return asyncio.run(Worker().process({"id": "mail-edera"}, llm))

    return run


def test_the_corpus_review_restricts_the_legacy_fact_it_declined(profile_a, embedder):
    event = seed_corpus_case(embedder)
    engine = HybridSearchEngine(get_session, embedder)
    assert "legacy-fact-edera" in fact_ids()
    assert "legacy-fact-edera" in searched(engine, "Edera minimum term")
    shown_version = BlobStorage(get_session, embedder).get_blob("legacy-fact-edera", OWNER_A)["updated_at"]

    result = admitted(event)(client(decision_text("contradictory_legacy_fact_rule")))

    assert result.outcome == "review_needed", result.reason
    assert journal.restrictions_for() == [{"blob_id": "legacy-fact-edera", "version": shown_version}]
    assert "legacy-fact-edera" not in fact_ids()
    assert facts_store.exact_fact(OWNER_A, "pricing", "edera-term") is None
    # The same engine instance, its index loaded before the review: the bump
    # is what every process reads, so the cached index is not used again.
    assert "legacy-fact-edera" not in searched(engine, "Edera minimum term")
    assert "legacy-fact-edera" not in searched(HybridSearchEngine(get_session, embedder), "Edera minimum term")


def test_a_rewrite_of_a_restricted_fact_does_not_restore_its_eligibility(profile_a, embedder):
    event = seed_corpus_case(embedder)
    admitted(event)(client(decision_text("contradictory_legacy_fact_rule")))
    assert "legacy-fact-edera" not in fact_ids()

    storage = BlobStorage(get_session, embedder)
    rewritten = storage.update_blob(
        "legacy-fact-edera", OWNER_A, "Category: pricing\nKey: edera-term\nEdera has a 12-month minimum."
    )
    assert rewritten and rewritten["content"].endswith("12-month minimum.")
    recorded = journal.restrictions_for()[0]["version"]
    assert storage.get_blob("legacy-fact-edera", OWNER_A)["updated_at"] != recorded

    assert "legacy-fact-edera" not in fact_ids()
    assert "legacy-fact-edera" not in searched(HybridSearchEngine(get_session, embedder), "Edera minimum")


def test_the_corpus_rule_row_is_not_quarantined_by_that_review(profile_a, embedder):
    """The review names the FACT; the entity-shaped rule row is another
    account's problem and another milestone's, and stays where it is."""
    event = seed_corpus_case(embedder)
    admitted(event)(client(decision_text("contradictory_legacy_fact_rule")))
    with get_session() as session:
        assert ineligible_fact_ids(session, COMPANY_A) == {"legacy-fact-edera"}
