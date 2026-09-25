"""The refusal reviews of the owner-identity known issue, settled by the owner.

A milestone 5–7 build accepted only ``OWNER_ID`` as the account a process acts
as, so an event owned by the profile's email — every trigger's owner — was
refused before the role answered and recorded as a terminal review. The same
account re-submitting the same source or pair then replays that review for
good (``docs/known-issues/2026-09-24-mnemonic-owner-identity-mismatch.md``,
"Refusals already recorded"). Each case here records such a review through the
real harness with ``_current_owners`` answering as those builds did, shows the
next run replays it unpaid, resolves it, and shows the run after decides it
with the identity the fix accepts: a parent refused before extraction and a
consolidation pair are retried, a chat event is dismissed. Only the provider
transport is scripted.
"""

from __future__ import annotations

import contextlib

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import authorization, journal, reviews
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import INTERACTIVE, VERIFIED_HUMAN_CORRECTION, MemoryEvent
from zylch.memory.mnemonic.reviews import DISMISS, DISMISSED, RETRY, ReviewRefused
from zylch.storage.database import get_session

from tests.memory import seeding
from tests.memory.consolidation_env import healthy, merge_answer, person, scripted, sweep
from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder, client
from tests.workers.ingestion_env import (
    LUCA,
    blobs,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    make_worker,
    operations,
    parent_of,
    resume,
    run,
    seed_email,
)

EMAIL_A = f"{OWNER_A}@company.test"
CROSS_ACCOUNT = "does not match the event owner"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


@contextlib.contextmanager
def as_milestone_7(monkeypatch):
    """Inside the block the process names its account by ``OWNER_ID`` alone, as those builds did."""
    with monkeypatch.context() as patched:
        patched.setattr(authorization, "_current_owners", lambda: frozenset({OWNER_A}))
        yield


def test_a_source_refused_before_extraction_is_retried_and_decided_as_the_email(
    profile, monkeypatch
):
    mail = seed_email(owner=EMAIL_A)
    refused = make_worker([], [], owner=EMAIL_A)
    with as_milestone_7(monkeypatch):
        run(refused, "process_email", mail)
    parent = parent_of("mail-1")
    assert parent["state"] == journal.REVIEW and CROSS_ACCOUNT in parent["result"]["reason"]
    assert children_of(parent["event_id"]) == {} and parent["payload"] is None
    assert refused.client._client.messages.create.call_count == 0

    resume(profile)
    stuck = make_worker([], [], owner=EMAIL_A)
    run(stuck, "process_email", mail)  # the fixed build replays the recorded review
    assert stuck.client._client.messages.create.call_count == 0
    assert not email_processed("mail-1")

    assert reviews.list_unsettled(COMPANY_A)[0]["actions"] == [DISMISS, RETRY]
    reviews.resolve(parent["event_id"], RETRY)

    resume(profile)
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")], owner=EMAIL_A)
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 1  # extracted again, paid
    assert worker.decision_client._client.messages.create.call_count == 1
    parent = parent_of("mail-1")
    assert parent["state"] == journal.COMMITTED and parent["owner_id"] == EMAIL_A
    assert email_processed("mail-1") and len(blobs()) == 1


def test_a_pair_refused_before_the_role_answered_is_retried_and_merged(
    profile, monkeypatch, embedder
):
    store = BlobStorage(get_session, embedder)
    keeper, donor = (
        seeding.store_blob(store, OWNER_A, f"user:{COMPANY_A}", person(about=about), "seed")["id"]
        for about in ("Purchasing at Alpha; handles every order.", "Joins the Thursday sync.")
    )
    healthy(monkeypatch, owner=EMAIL_A)
    transport = scripted(monkeypatch, merge_answer(store, keeper, donor))

    with as_milestone_7(monkeypatch):
        sweep(EMAIL_A)
    (pair_row,) = [r for r in operations().values() if r["source_ref"].startswith("consolidation:")]
    assert pair_row["state"] == journal.REVIEW and CROSS_ACCOUNT in pair_row["result"]["reason"]
    assert pair_row["proposal_digest"] is None and transport.call_count == 0

    sweep(EMAIL_A)  # the fixed build replays it: the pair stays undecided
    assert transport.call_count == 0 and operations()[pair_row["event_id"]]["state"] == journal.REVIEW

    reviews.resolve(pair_row["event_id"], RETRY)
    sweep(EMAIL_A)

    decided = operations()[pair_row["event_id"]]
    assert decided["state"] == journal.COMMITTED and decided["owner_id"] == EMAIL_A
    assert transport.call_count == 1
    assert store.get_blob(keeper, OWNER_A) is not None and store.get_blob(donor, OWNER_A) is None


def test_a_refused_chat_event_is_dismissed_not_retried(profile, monkeypatch):
    event = MemoryEvent(
        owner_id=EMAIL_A,
        company_key=COMPANY_A,
        caller_class=VERIFIED_HUMAN_CORRECTION,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn-1",
        source_revision="rev-1",
        observation="Remember that Luca Bianchi handles purchasing at Alpha.",
    )
    llm = client()
    with as_milestone_7(monkeypatch):
        result = submit(event, client=llm)
    assert result.outcome == "review_needed" and CROSS_ACCOUNT in result.reason
    assert llm._client.messages.create.call_count == 0

    with pytest.raises(ReviewRefused, match="nothing resubmits a chat event"):
        reviews.resolve(event.event_id, RETRY)
    reviews.resolve(event.event_id, DISMISS)

    row = operations()[event.event_id]
    assert row["state"] == journal.SKIPPED and row["result"]["reason"] == DISMISSED
    assert reviews.list_unsettled(COMPANY_A) == []
