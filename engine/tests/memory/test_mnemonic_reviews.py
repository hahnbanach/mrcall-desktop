"""The owner's resolution of parked memory work: list, dismiss, retry (AC6).

Against real split databases with the real worker, the real ``LLMClient`` and
the real reservation ledger; only the provider transport is scripted
(``tests/workers/ingestion_env.py``). A reviewed source is produced the way a
worker run produces one: two extracted entities, the first committed, the
second parked by the role in review, so the parent is settled in review with
its manifest kept. The next run after a resolution is a real worker run after
a restart, and its paid calls are counted at the transport. The refusal reviews
the owner-identity known issue records are ``test_mnemonic_reviews_known_issue.py``;
the CLI is ``test_mnemonic_reviews_cli.py``.
"""

from __future__ import annotations

import json

import pytest

from zylch.memory.eligibility import restricted_ids
from zylch.memory.mnemonic import fence, journal, pairs, reviews
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    EVENT_DISPATCH_ALLOWANCE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    MemoryEvent,
)
from zylch.memory.mnemonic.proposals import MnemonicResult, Proposal
from zylch.memory.mnemonic.reviews import DISMISS, DISMISSED, RETRY, ReviewRefused
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation

from tests.memory.mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    BagOfWordsEmbedder,
)
from tests.workers.ingestion_env import (
    ACME,
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
UNCLEAR = json.dumps({"action": "REVIEW", "reason": "which Acme is this"})
RESTRICTION = {"blob_id": "fact-1", "version": "v1"}


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


def reviewed_source():
    """One mail whose first child committed and whose second the role parked in review."""
    mail = seed_email()
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), UNCLEAR])
    assert run(worker, "process_email", mail) is False
    parent = parent_of("mail-1")
    first, second = sorted(children_of(parent["event_id"]))
    assert parent["state"] == journal.REVIEW and parent["payload"]["manifest"]
    assert operations()[first]["state"] == journal.COMMITTED
    assert operations()[second]["state"] == journal.REVIEW
    assert not email_processed("mail-1")
    return mail, parent["event_id"], first, second


def chat_event(event_id="turn-evt", owner=OWNER_A, source_kind="chat", **extra) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind=source_kind,
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme Srl pays at 60 days.",
        **extra,
    )


def pair_event(owner=OWNER_A) -> MemoryEvent:
    first = {"id": "blob-keeper", "content": "Name: Luca", "updated_at": "v1"}
    second = {"id": "blob-donor", "content": "Name: Luca", "updated_at": "v2"}
    return pairs.pair_event(owner, COMPANY_A, first, second)


def parked(event: MemoryEvent, state=journal.REVIEW, **kwargs) -> str:
    """One row settled as a refusal or a review records it."""
    journal.open_operation(event)
    result = (
        MnemonicResult.retryable_failure(event.event_id, "provider down")
        if state == journal.FAILED
        else MnemonicResult.review_needed(event.event_id, "the role declined")
    )
    journal.record_result(event.event_id, result, state=state, **kwargs)
    return event.event_id


def restricted():
    with get_session() as session:
        return sorted(restricted_ids(session, COMPANY_A))


def listed():
    return {row["event_id"]: row for row in reviews.list_unsettled(COMPANY_A)}


# ─── Listing ──────────────────────────────────────────────────────────


def test_the_listing_holds_this_profiles_rows_under_either_identity_and_nobody_elses(profile):
    _, parent, first, second = reviewed_source()
    by_email = parked(chat_event("turn-email", owner=EMAIL_A))
    foreign = parked(chat_event("turn-other", owner=OWNER_B))
    pending_other = chat_event("turn-other-2", owner=OWNER_B).event_id
    journal.open_operation(chat_event("turn-other-2", owner=OWNER_B))

    rows = listed()

    assert set(rows) == {parent, second, by_email}
    assert foreign not in rows and pending_other not in rows and first not in rows
    assert rows[second]["actions"] == [DISMISS, RETRY]
    assert rows[second]["parent_event_id"] == parent
    assert rows[second]["reason"] == "which Acme is this"
    assert rows[parent]["actions"] == [DISMISS]  # its children are decided on their own
    assert rows[by_email]["actions"] == [DISMISS]  # nothing resubmits a chat turn
    assert rows[by_email]["source_ref"].startswith("chat:")


# ─── Dismiss ──────────────────────────────────────────────────────────


def test_dismissing_the_last_reviewed_child_lands_the_checkpoint_unpaid(profile):
    mail, parent, first, second = reviewed_source()

    answer = reviews.resolve(second, DISMISS)

    assert answer == {
        "event_id": second,
        "action": DISMISS,
        "state": journal.SKIPPED,
        "parent": {"event_id": parent, "state": journal.COMMITTED},
    }
    rows = operations()
    assert rows[second]["result"]["reason"] == DISMISSED and rows[second]["payload"] is None
    assert rows[parent]["payload"] is None  # the manifest is pruned on settle
    assert [tuple(p) for p in rows[parent]["result"]["committed_ids"]] == [
        tuple(p) for p in rows[first]["result"]["committed_ids"]
    ]
    before = blobs()

    resume(profile)
    worker = make_worker([], [])
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 0  # no extraction
    assert worker.decision_client._client.messages.create.call_count == 0  # no decision
    assert email_processed("mail-1") and blobs() == before


def test_dismissing_one_of_two_reviewed_children_leaves_the_parent_in_review(profile):
    mail = seed_email()
    worker = make_worker([extraction(LUCA, ACME)], [UNCLEAR, UNCLEAR])
    run(worker, "process_email", mail)
    parent = parent_of("mail-1")["event_id"]
    first, second = sorted(children_of(parent))

    assert reviews.resolve(first, DISMISS)["parent"] == {"event_id": parent, "state": journal.REVIEW}
    assert operations()[parent]["payload"]["manifest"]

    assert reviews.resolve(second, DISMISS)["parent"] == {"event_id": parent, "state": journal.SKIPPED}
    assert operations()[parent]["payload"] is None


def test_dismissing_a_failed_chat_row_and_a_leased_pending_row_outlasts_their_attempts(profile):
    failed = parked(chat_event("turn-failed"), state=journal.FAILED)
    leased = chat_event("turn-leased")
    journal.open_operation(leased)
    lease = journal.claim(leased.event_id)
    assert lease

    assert reviews.resolve(failed, DISMISS)["state"] == journal.SKIPPED
    assert reviews.resolve(leased.event_id, DISMISS)["state"] == journal.SKIPPED
    dismissed = operations()
    assert dismissed[leased.event_id]["lease"] is None

    with pytest.raises(journal.JournalError, match="already skipped"):
        journal.record_attempt(leased.event_id, leased, None)
    with pytest.raises(journal.JournalError, match="already skipped"):
        journal.record_result(
            leased.event_id, MnemonicResult.review_needed(leased.event_id, "late"), state=journal.REVIEW
        )
    with pytest.raises(journal.JournalError), journal.company_transaction(write=True) as session:
        journal.owns(session, leased.event_id, lease)
    assert operations() == dismissed
    assert journal.open_operation(leased).replay.reason == DISMISSED


def test_a_dismissed_pair_settles_nothing_for_another_account(profile):
    mine = pair_event()
    parked(mine, proposal=Proposal(action="REVIEW", reason="not sure"))
    theirs = pair_event(owner=OWNER_B)
    assert operations()[mine.event_id]["proposal_digest"]
    assert pairs.settled(theirs) == journal.REVIEW  # the role's answer settles it for all

    reviews.resolve(mine.event_id, DISMISS)

    assert operations()[mine.event_id]["proposal_digest"] is None
    assert pairs.settled(theirs) is None


# ─── Retry ────────────────────────────────────────────────────────────


def test_retrying_a_reviewed_child_decides_that_child_alone(profile):
    mail, parent, first, second = reviewed_source()
    assert operations()[second]["allowance"] < EVENT_DISPATCH_ALLOWANCE

    answer = reviews.resolve(second, RETRY)

    assert answer["state"] == journal.FAILED
    assert answer["parent"] == {"event_id": parent, "state": journal.FAILED}
    rows = operations()
    assert rows[second]["allowance"] == EVENT_DISPATCH_ALLOWANCE and rows[second]["lease"] is None
    assert rows[parent]["payload"]["manifest"]

    resume(profile)
    worker = make_worker([], [create_decision(ACME, "COMPANY")])
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 0  # the manifest resumed
    assert worker.decision_client._client.messages.create.call_count == 1  # that child alone
    rows = operations()
    assert rows[first]["state"] == rows[second]["state"] == journal.COMMITTED
    assert rows[parent]["state"] == journal.COMMITTED and rows[parent]["payload"] is None
    assert email_processed("mail-1") and len(blobs()) == 2


def test_a_chat_event_is_never_retried(profile):
    event_id = parked(chat_event())
    before = operations()

    with pytest.raises(ReviewRefused, match="nothing resubmits a chat event"):
        reviews.resolve(event_id, RETRY)
    assert operations() == before


def test_a_child_whose_parent_kept_no_manifest_is_dismissed_not_retried(profile):
    """A parent a milestone 5–7 build reviewed has no manifest; its child cannot be retried."""
    _, parent, _, second = reviewed_source()
    with get_session() as session:
        session.get(MemoryOperation, parent).payload = None
    before = operations()

    with pytest.raises(ReviewRefused, match="no extraction manifest"):
        reviews.resolve(second, RETRY)
    assert operations() == before
    assert listed()[second]["actions"] == [DISMISS]
    assert reviews.resolve(second, DISMISS)["parent"]["state"] == journal.COMMITTED


def test_a_retried_pair_is_decided_again_on_its_next_submission(profile):
    event = pair_event()
    parked(event)

    reviews.resolve(event.event_id, RETRY)

    opened = journal.open_operation(event)
    assert opened.replay is None and opened.state == journal.FAILED
    assert opened.allowance == EVENT_DISPATCH_ALLOWANCE


# ─── Restrictions stay ────────────────────────────────────────────────


@pytest.mark.parametrize("action", [DISMISS, RETRY])
def test_a_restriction_survives_either_action(profile, action):
    event = pair_event() if action == RETRY else chat_event()
    parked(event, restrictions=[RESTRICTION])
    assert restricted() == ["fact-1"]

    reviews.resolve(event.event_id, action)

    assert operations()[event.event_id]["restrictions"] == [RESTRICTION]
    assert restricted() == ["fact-1"]


# ─── Refusals ─────────────────────────────────────────────────────────


def test_another_accounts_row_and_another_companys_row_are_refused(profile):
    foreign = parked(chat_event("turn-other", owner=OWNER_B))
    with get_session() as session:
        session.add(
            MemoryOperation(
                event_id="elsewhere",
                owner_id=OWNER_A,
                company_key=COMPANY_B,
                input_digest="d",
                source_ref="chat:turn:9@r",
                origin=INTERACTIVE,
                caller_class=OPERATOR_DELEGATED,
                state=journal.REVIEW,
                restrictions=[],
            )
        )
    before = operations()

    for event_id in (foreign, "elsewhere", "nobody"):
        for action in (DISMISS, RETRY):
            with pytest.raises(ReviewRefused, match="no operation"):
                reviews.resolve(event_id, action)
    assert operations() == before


def test_a_settled_row_is_refused(profile):
    _, _, first, _ = reviewed_source()
    before = operations()

    for action in (DISMISS, RETRY):
        with pytest.raises(ReviewRefused, match="already committed"):
            reviews.resolve(first, action)
    assert operations() == before


def test_a_fenced_company_refuses_both_actions(profile):
    _, _, _, second = reviewed_source()
    fence.place(COMPANY_A, (OWNER_B,), COMPANY_B)
    before = operations()

    for action in (DISMISS, RETRY):
        with pytest.raises(ReviewRefused, match=fence.JOINING):
            reviews.resolve(second, action)
    assert operations() == before
    assert second in listed()  # the listing is a read


def test_an_automatic_row_nothing_resubmits_is_not_retried(profile):
    """A helper writer's event inside an admitted item: automatic, but no ingestion parent."""
    event = MemoryEvent(
        event_id="helper-1",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-9",
        source_revision="r",
        observation="Acme pays at 60 days.",
        stage="tasks:email",
    )
    parked(event)

    with pytest.raises(ReviewRefused, match="nothing resubmits this event"):
        reviews.resolve(event.event_id, RETRY)
    assert reviews.resolve(event.event_id, DISMISS)["state"] == journal.SKIPPED


def test_only_a_review_is_retried(profile):
    event = pair_event()
    parked(event, state=journal.FAILED)

    with pytest.raises(ReviewRefused, match="only a review is retried"):
        reviews.resolve(event.event_id, RETRY)
    assert listed()[event.event_id]["actions"] == [DISMISS]
