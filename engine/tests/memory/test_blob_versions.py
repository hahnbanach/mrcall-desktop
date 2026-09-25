"""No write in the estate destroys text — proved per writer path, on real stores.

Every case here runs against a real company store booted through `init_db`,
with foreign keys on, because the property under test is transactional: the
version row lands with the write it precedes or not at all, and an owner's
delete removes it explicitly because nothing cascades. A mocked session could
not fail any of these assertions.
"""

from __future__ import annotations

import json

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.blob_versions import APPEND, CONSOLIDATE, list_versions
from zylch.memory.mnemonic.approval import RequestedWrite
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, BlobVersion

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    OWNER_B,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
)

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nIndustrial supplier in Milan."
)
ACME_2 = ACME.replace("info@acme.test", "orders@acme.test")
ACME_3 = ACME_2.replace("Milan", "Turin")


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile_a(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def storage(embedder) -> BlobStorage:
    return BlobStorage(get_session, embedder)


def seed(embedder, content=ACME, owner=OWNER_A, namespace=None):
    blob = storage(embedder).store_blob(
        owner_id=owner,
        namespace=namespace or f"user:{COMPANY_A}",
        content=content,
        event_description="seed",
    )
    return blob["id"]


def versions(blob_id):
    with get_session() as session:
        return [v.to_dict() for v in list_versions(session, blob_id)]


def content_of(blob_id):
    with get_session() as session:
        row = session.get(Blob, blob_id)
        return None if row is None else row.content


def all_version_rows():
    with get_session() as session:
        return session.query(BlobVersion).count()


# ─── Rewrites retain ──────────────────────────────────────────────────


def test_a_legacy_rewrite_keeps_the_text_it_replaced(profile_a, embedder):
    """`update_blob` is the mail worker's call, and the June 2026 sink's path."""
    blob_id = seed(embedder)
    assert versions(blob_id) == []

    storage(embedder).update_blob(blob_id=blob_id, owner_id=OWNER_A, content=ACME_2)

    kept = versions(blob_id)
    assert [v["content"] for v in kept] == [ACME]
    assert kept[0]["reason"] == APPEND
    assert kept[0]["owner_id"] == OWNER_A
    assert kept[0]["namespace"] == f"user:{COMPANY_A}"
    assert kept[0]["operation_id"] is None
    assert content_of(blob_id) == ACME_2


def test_every_rewrite_adds_a_version_oldest_first(profile_a, embedder):
    blob_id = seed(embedder)
    storage(embedder).update_blob(blob_id=blob_id, owner_id=OWNER_A, content=ACME_2)
    storage(embedder).update_blob(blob_id=blob_id, owner_id=OWNER_A, content=ACME_3)
    assert [v["content"] for v in versions(blob_id)] == [ACME, ACME_2]
    assert content_of(blob_id) == ACME_3


def test_the_reason_is_the_callers_word_not_the_writers_guess(profile_a, embedder):
    """`_rewrite` cannot know its caller; the sweep says `consolidate` itself."""
    blob_id = seed(embedder)
    storage(embedder).update_blob(
        blob_id=blob_id, owner_id=OWNER_A, content=ACME_2, reason=CONSOLIDATE
    )
    assert versions(blob_id)[0]["reason"] == CONSOLIDATE
    with pytest.raises(ValueError):
        storage(embedder).update_blob(
            blob_id=blob_id, owner_id=OWNER_A, content=ACME_3, reason="whatever"
        )
    assert content_of(blob_id) == ACME_2  # the refused write wrote nothing


def test_the_semantic_update_retains_under_the_operations_id(profile_a, embedder):
    """Through `submit`: the version names the journal event that superseded it."""
    blob_id = seed(embedder)
    with get_session() as session:
        version_read = session.get(Blob, blob_id).updated_at
    from zylch.memory.blob_storage import _iso

    decision = json.dumps(
        {
            "action": UPDATE,
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": ACME_2,
            "write_set": [
                {"blob_id": blob_id, "expected_version": _iso(version_read), "role": "target"}
            ],
            "reason": "the ordering address replaces the old one",
        }
    )
    event = MemoryEvent(
        event_id="evt-retain-1",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme ordina da orders@acme.test adesso.",
    )
    result = submit(
        event,
        client=client(decision),
        requested=RequestedWrite(action=UPDATE, blob_id=blob_id, subject_is_authoritative=True),
    )

    assert result.outcome == "committed", result.reason
    kept = versions(blob_id)
    assert [v["content"] for v in kept] == [ACME]
    assert kept[0]["reason"] == APPEND
    assert kept[0]["operation_id"] == "evt-retain-1"


def test_a_rewrite_that_fails_retains_nothing(profile_a, embedder, monkeypatch):
    """The version lands with the write or not at all — never a version of a
    write that did not happen."""
    blob_id = seed(embedder)

    def explode(*_a, **_k):
        raise RuntimeError("sentence index unavailable")

    monkeypatch.setattr(BlobStorage, "_add_sentences", explode)
    with pytest.raises(RuntimeError):
        storage(embedder).update_blob(blob_id=blob_id, owner_id=OWNER_A, content=ACME_2)

    assert versions(blob_id) == []
    assert content_of(blob_id) == ACME


# ─── Removals: the sweep retains, the owner prunes ─────────────────────


def test_the_sweeps_delete_keeps_the_donors_final_text(profile_a, embedder):
    blob_id = seed(embedder)
    with get_session() as session:  # a retaining drop runs inside its caller's transaction
        assert storage(embedder).delete_blob(blob_id, OWNER_A, retain=True, session=session)
    kept = versions(blob_id)
    assert [v["content"] for v in kept] == [ACME]
    assert kept[0]["reason"] == CONSOLIDATE
    assert content_of(blob_id) is None  # the row is gone, the text is not


def test_the_owners_delete_takes_the_versions_with_the_blob(profile_a, embedder):
    """An owner who deletes means it, and nothing cascades — so this is explicit."""
    blob_id = seed(embedder)
    storage(embedder).update_blob(blob_id=blob_id, owner_id=OWNER_A, content=ACME_2)
    assert len(versions(blob_id)) == 1

    assert storage(embedder).delete_blob(blob_id, OWNER_A) is True

    assert content_of(blob_id) is None
    assert versions(blob_id) == []
    assert all_version_rows() == 0


def test_deleting_an_invisible_blob_touches_nothing(profile_a, embedder):
    assert storage(embedder).delete_blob("no-such-blob", OWNER_A) is False


def test_a_reset_on_a_shared_store_prunes_only_the_blobs_it_deletes(
    tmp_path, monkeypatch, embedder
):
    """Two owners, one store. Owner B's reset removes B's own rule rows — and
    exactly their versions — while owner A's blobs keep theirs.

    This is the one case that catches a prune filtered on `owner_id`: a
    version's owner is the writer, and on a shared store the writer of A's
    blob's latest version is B.
    """
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    a_blob = seed(embedder, owner=OWNER_A)
    storage(embedder).update_blob(blob_id=a_blob, owner_id=OWNER_A, content=ACME_2)

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)  # same file, second account
    # B rewrites A's company blob: the version's provenance is B, the blob is A's.
    storage(embedder).update_blob(blob_id=a_blob, owner_id=OWNER_B, content=ACME_3)
    b_rule = seed(
        embedder,
        content="Always answer B's customers in Italian.",
        owner=OWNER_B,
        namespace=f"template:{OWNER_B}",
    )
    storage(embedder).update_blob(
        blob_id=b_rule, owner_id=OWNER_B, content="Always answer B's customers in Italian, briefly."
    )
    assert [v["owner_id"] for v in versions(a_blob)] == [OWNER_A, OWNER_B]
    assert len(versions(b_rule)) == 1

    removed = storage(embedder).delete_all_blobs(OWNER_B)

    assert removed == 1  # B's rule; A's company blob stays on a shared store
    assert content_of(b_rule) is None and versions(b_rule) == []
    assert content_of(a_blob) == ACME_3
    assert [v["content"] for v in versions(a_blob)] == [ACME, ACME_2]
    dbm.dispose_engine()
    clear_process_state()


# ─── Consolidation, for real: both halves of a merge are retained ──────


def test_a_real_consolidation_retains_the_donor_and_the_keeper(profile_a, embedder, monkeypatch):
    """Through `consolidate` itself, not the primitives.

    Two blobs share an identifier, so consolidation pairs them; the role,
    scripted at the provider transport, folds the donor into the keeper and
    the harness commits the MERGE. What must hold afterwards: the donor row is
    gone but its final text is a `consolidate` version, the keeper's pre-merge
    text is a `consolidate` version too (so consolidation's own rewrite is
    never read as a sink's growth), and the alias points at the keeper. Only
    the transport is faked; the lock, the clustering, the preparation item,
    the validator, the rewrite, the drop and the alias are the real ones.
    """
    from zylch.storage.models import BlobAlias
    from zylch.storage.storage import Storage

    from tests.memory.consolidation_env import healthy, merge_answer, scripted, sweep

    keeper = seed(embedder, content=ACME)
    donor = seed(embedder, content=ACME.replace("Industrial supplier", "Also a distributor"))
    rows = Storage()
    for blob_id in (keeper, donor):
        rows.add_person_identifiers(
            owner_id=OWNER_A, blob_id=blob_id, identifiers=[("email", "info@acme.test")]
        )

    healthy(monkeypatch)
    scripted(monkeypatch, merge_answer(storage(embedder), keeper, donor, entity_type="COMPANY"))

    summary = sweep(OWNER_A)

    assert summary["blobs_merged"] == 1, summary
    survivors = {bid for bid in (keeper, donor) if content_of(bid) is not None}
    assert len(survivors) == 1
    kept_id = survivors.pop()
    gone_id = donor if kept_id == keeper else keeper
    # The keeper carries the merged text; its pre-merge text is retained as
    # the sweep's own version.
    assert f"folded in {gone_id[:8]}" in content_of(kept_id)
    keeper_versions = versions(kept_id)
    assert [v["reason"] for v in keeper_versions] == [CONSOLIDATE]
    assert "folded in" not in keeper_versions[0]["content"]
    # The donor's final text survives its row.
    donor_versions = versions(gone_id)
    assert [v["reason"] for v in donor_versions] == [CONSOLIDATE]
    assert donor_versions[0]["content"].startswith("#IDENTIFIERS")
    with get_session() as session:
        alias = session.get(BlobAlias, gone_id)
        assert alias is not None and alias.keeper_id == kept_id
