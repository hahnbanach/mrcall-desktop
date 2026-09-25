"""The MERGE's storage boundary: the permit names the donor, or nothing is dropped.

`semantic_merge` is where the harness refuses a write the permit does not
authorize, whoever the caller is. The donor is the row a merge deletes, so the
permit must name it — its id and the version it was decided against — and the
donor must live in the namespace the permit authorizes. A drop that removes
nothing is a conflict, never a silent success. Each case calls the boundary
directly, inside the company transaction the commit would own, with a permit
minted the way the commit mints one.
"""

from __future__ import annotations

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.commit_permit import MERGE, ConflictError, PermitError, issue_commit_permit
from zylch.memory.mnemonic import journal
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    stub_embedder,
)
from tests.memory.test_mnemonic_merge import LUCA_CAL, LUCA_MAIL, LUCA_THIRD, MERGED, read, seed


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def store(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield BlobStorage(get_session, embedder)
    dbm.dispose_engine()
    clear_process_state()


def permit_for(keeper, donor):
    """A MERGE permit for exactly these two memories at these two versions."""
    return issue_commit_permit(
        action=MERGE,
        company_key=COMPANY_A,
        owner_id=OWNER_A,
        event_id="pair-boundary",
        proposal_digest="d",
        content=MERGED,
        namespace=keeper["namespace"],
        write_set=((keeper["id"], keeper["updated_at"]), (donor["id"], donor["updated_at"])),
    )


def merge_at_the_boundary(store, permit, keeper, donor):
    """``semantic_merge`` on rows re-read in the transaction, as the commit calls it."""
    prepared = store.prepare(MERGED)
    with journal.company_transaction(write=True) as session:
        return store.semantic_merge(
            session,
            permit,
            keeper=session.get(Blob, keeper["id"]),
            donor=session.get(Blob, donor["id"]),
            owner_id=OWNER_A,
            prepared=prepared,
            keeper_version=keeper["updated_at"],
            donor_version=donor["updated_at"],
        )


def test_the_permit_for_exactly_this_pair_drops_the_donor(store):
    keeper, donor = read(store, seed(store, LUCA_MAIL)), read(store, seed(store, LUCA_CAL))

    merge_at_the_boundary(store, permit_for(keeper, donor), keeper, donor)

    assert read(store, keeper["id"])["content"] == MERGED and read(store, donor["id"]) is None


def test_a_donor_the_permit_does_not_name_is_never_dropped(store):
    keeper, named, other = (read(store, seed(store, c)) for c in (LUCA_MAIL, LUCA_CAL, LUCA_THIRD))

    with pytest.raises(PermitError, match="donor/version pair is not in the permit"):
        merge_at_the_boundary(store, permit_for(keeper, named), keeper, other)

    assert read(store, other["id"]) is not None and read(store, named["id"]) is not None
    assert read(store, keeper["id"])["content"] == LUCA_MAIL


def test_a_donor_outside_the_permits_namespace_is_never_dropped(store):
    """Visible to the account and in the company, in another entity namespace."""
    keeper = read(store, seed(store, LUCA_MAIL))
    donor_id = store.store_blob(OWNER_A, "user:another-namespace", LUCA_CAL, "seed")["id"]
    donor = read(store, donor_id)

    with pytest.raises(PermitError, match="namespace the permit does not authorize"):
        merge_at_the_boundary(store, permit_for(keeper, donor), keeper, donor)

    assert read(store, donor_id) is not None
    assert read(store, keeper["id"])["content"] == LUCA_MAIL


def test_a_drop_that_removes_nothing_is_a_conflict_and_writes_nothing(store, monkeypatch):
    keeper, donor = read(store, seed(store, LUCA_MAIL)), read(store, seed(store, LUCA_CAL))
    monkeypatch.setattr(BlobStorage, "delete_blob", lambda self, *args, **kwargs: False)

    with pytest.raises(ConflictError, match="could not be dropped"):
        merge_at_the_boundary(store, permit_for(keeper, donor), keeper, donor)

    assert read(store, keeper["id"])["content"] == LUCA_MAIL
    assert read(store, donor["id"]) is not None
