"""The operation journal: idempotency, the durable allowance, and who may read it.

Three questions a stateless decision layer cannot answer, asked here against
real profile and company databases rather than a mock:

- **exactly once** — a replayed event returns what it decided before, and an
  event id arriving with different input is refused rather than re-pointed;
- **a budget that survives a restart** — the per-event dispatch allowance was
  an in-process table, so a crash loop used to buy each attempt a fresh one;
- **who may read a payload** — the journal lives in the shared company store,
  and an account rule's original instruction must not become readable by every
  other account holding the key.
"""

from __future__ import annotations

import pytest

from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.contracts import (
    EVENT_DISPATCH_ALLOWANCE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    MemoryEvent,
)
from zylch.memory.mnemonic.proposals import MnemonicResult, Proposal, WriteTarget
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation

from .mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    boot,
    clear_process_state,
    reboot,
)

pytestmark = pytest.mark.usefixtures("stub_embeddings")


@pytest.fixture
def stub_embeddings(monkeypatch, embedder):
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)


@pytest.fixture
def profile_a(tmp_path, monkeypatch):
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    clear_process_state()


def event(
    *,
    event_id="evt-1",
    owner=OWNER_A,
    company=COMPANY_A,
    observation="Ricordati che Acme paga a 60 giorni.",
    source_id="turn:abc",
    source_kind="chat",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=company,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind=source_kind,
        source_id=source_id,
        source_revision="rev-1",
        observation=observation,
    )


def proposal(
    entity_type="COMPANY", scope="entity", content="#IDENTIFIERS\nName: Acme\n"
) -> Proposal:
    return Proposal(action="CREATE", entity_type=entity_type, scope=scope, content=content)


# ─── Exactly once ─────────────────────────────────────────────────────


def test_a_replayed_event_returns_its_recorded_result_and_decides_nothing(profile_a):
    first = event()
    opened = journal.open_operation(first)
    assert opened.state == journal.PENDING
    assert opened.replay is None

    journal.record_result(
        first.event_id,
        MnemonicResult.committed(first.event_id, (("blob-1", "v1"),)),
        state=journal.COMMITTED,
    )

    again = journal.open_operation(event())
    assert again.replay is not None
    assert again.replay.outcome == "committed"
    assert again.replay.committed_ids == (("blob-1", "v1"),)


def test_an_event_id_reused_with_different_input_is_refused(profile_a):
    journal.open_operation(event())
    with pytest.raises(journal.EventIdReused):
        journal.open_operation(event(observation="a completely different sentence"))


def test_a_differently_worded_model_suggestion_is_not_different_input(profile_a):
    """The digest covers the sealed fields, not the model's rewrite.

    An outer agent re-asked the same turn may word ``content`` differently. The
    observation, the owner and the source are what the id promises.
    """
    journal.open_operation(event())
    resubmitted = event().with_model_arguments({"content": "Acme pays in 60 days"})
    assert journal.open_operation(resubmitted).replay is None


def test_an_event_id_belonging_to_another_account_is_refused(profile_a):
    journal.open_operation(event())
    with pytest.raises(journal.EventIdReused):
        journal.open_operation(event(owner=OWNER_B))


def test_a_failed_operation_is_retried_rather_than_replayed(profile_a):
    """``retryable_failure`` means retryable; only a settled answer replays."""
    journal.open_operation(event())
    journal.record_result(
        "evt-1",
        MnemonicResult.retryable_failure("evt-1", "provider down"),
        state=journal.FAILED,
    )
    assert journal.open_operation(event()).replay is None


def test_a_review_persists_and_is_not_paid_for_again(profile_a):
    journal.open_operation(event())
    journal.record_result(
        "evt-1",
        MnemonicResult.review_needed("evt-1", "ambiguous subject"),
        state=journal.REVIEW,
    )
    replay = journal.open_operation(event()).replay
    assert replay is not None and replay.outcome == "review_needed"
    assert replay.reason == "ambiguous subject"


# ─── The durable allowance ────────────────────────────────────────────


def test_the_dispatch_allowance_starts_full_and_decrements_durably(profile_a):
    journal.open_operation(event())
    assert journal.allowance_for("evt-1") == EVENT_DISPATCH_ALLOWANCE
    assert journal.spend_allowance("evt-1") == EVENT_DISPATCH_ALLOWANCE - 1
    assert journal.allowance_for("evt-1") == EVENT_DISPATCH_ALLOWANCE - 1


def test_a_restart_does_not_hand_a_stuck_event_a_fresh_budget(profile_a):
    journal.open_operation(event())
    for _ in range(EVENT_DISPATCH_ALLOWANCE):
        journal.spend_allowance("evt-1")
    assert journal.allowance_for("evt-1") == 0

    reboot()

    # The in-process cache is gone; the column is not.
    assert journal.allowance_for("evt-1") == 0
    from zylch.memory.mnemonic.authorization import issue_grant

    grant = issue_grant(event())
    assert grant.remaining == 0


def test_an_event_with_no_operation_row_has_no_durable_allowance(profile_a):
    assert journal.allowance_for("never-opened") is None
    assert journal.spend_allowance("never-opened") is None


def test_no_company_store_means_no_durable_allowance_rather_than_an_error(tmp_path, monkeypatch):
    """An engine with memory unavailable still answers; it just governs nothing.

    ``None`` here is what keeps the decision layer usable where no store is
    attached at all. It is deliberately different from a store that exists and
    cannot be read, which raises.
    """
    from zylch.storage import database as dbm

    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "zylch.db"))
    monkeypatch.delenv("MEMORY_KEY", raising=False)
    dbm.dispose_engine()
    try:
        assert journal.allowance_for("anything") is None
    finally:
        dbm.dispose_engine()


# ─── The fenced claim ─────────────────────────────────────────────────


def test_a_second_claim_fences_out_the_first(profile_a):
    journal.open_operation(event())
    first = journal.claim("evt-1")
    second = journal.claim("evt-1")
    assert first != second

    with journal.company_transaction() as session:
        journal.owns(session, "evt-1", second)  # the winner proceeds
        with pytest.raises(journal.JournalError, match="took over"):
            journal.owns(session, "evt-1", first)


def test_claiming_a_settled_operation_returns_nothing_to_work_on(profile_a):
    journal.open_operation(event())
    journal.record_result(
        "evt-1", MnemonicResult.skipped("evt-1", "already known"), state=journal.SKIPPED
    )
    assert journal.claim("evt-1") is None


# ─── Reading, scoped like the memory it describes ─────────────────────


def test_an_account_rule_operation_is_private_to_its_owner(profile_a):
    """A STYLE payload carries one account's instruction, on a shared store."""
    journal.open_operation(event())
    journal.record_attempt("evt-1", event(), proposal(entity_type="STYLE", scope="account"))

    with get_session() as session:
        row = session.get(MemoryOperation, "evt-1")
        assert row.target_family == "template"
        assert journal.visible(row, OWNER_A, COMPANY_A) is True
        assert journal.visible(row, OWNER_B, COMPANY_A) is False


def test_a_company_entity_operation_is_shared_with_every_key_holder(profile_a):
    journal.open_operation(event())
    journal.record_attempt("evt-1", event(), proposal())

    with get_session() as session:
        row = session.get(MemoryOperation, "evt-1")
        assert row.target_family == "user"
        assert journal.visible(row, OWNER_B, COMPANY_A) is True


def test_an_undecided_operation_stays_private_until_its_family_is_known(profile_a):
    """Before the role answers, nobody knows whether the payload is company-wide."""
    journal.open_operation(event())
    with get_session() as session:
        row = session.get(MemoryOperation, "evt-1")
        assert row.target_family is None
        assert journal.visible(row, OWNER_B, COMPANY_A) is False


def test_another_company_never_sees_the_operation(profile_a):
    journal.open_operation(event())
    with get_session() as session:
        row = session.get(MemoryOperation, "evt-1")
        assert journal.visible(row, OWNER_A, COMPANY_B) is False


def test_two_owners_sharing_a_key_share_one_journal(tmp_path, monkeypatch, embedder):
    """The store is the company: an operation opened by A is B's history too."""
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    journal.open_operation(event())
    journal.record_attempt("evt-1", event(), proposal())

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)
    seen = journal.read("evt-1", owner_id=OWNER_B, company_key=COMPANY_A)
    assert seen is not None and seen["owner_id"] == OWNER_A

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_B)
    assert journal.read("evt-1", owner_id=OWNER_B, company_key=COMPANY_B) is None


# ─── Payload bounds and pruning ───────────────────────────────────────


def test_a_terminal_operation_keeps_its_receipt_and_drops_its_bodies(profile_a):
    journal.open_operation(event())
    journal.record_attempt("evt-1", event(), proposal())
    with get_session() as session:
        assert session.get(MemoryOperation, "evt-1").payload["observation"]

    journal.record_result(
        "evt-1",
        MnemonicResult.committed("evt-1", (("blob-1", "v1"),)),
        state=journal.COMMITTED,
        proposal=proposal(),
    )

    with get_session() as session:
        row = session.get(MemoryOperation, "evt-1")
        assert row.payload is None
        assert row.lease is None
        # What is left is exactly enough to recognize a replay.
        assert row.input_digest and row.proposal_digest
        assert row.result["committed_ids"] == [["blob-1", "v1"]]


def test_oversized_input_is_refused_before_it_can_become_an_operation(profile_a):
    """The payload is bounded because everything it can hold is.

    Refusal, never truncation: a trimmed observation is a different
    observation, and the operation would then be idempotent against something
    nobody submitted. Both caps are outside the journal, which is why the
    journal carries no size check of its own.
    """
    from zylch.memory.mnemonic.contracts import (
        MAX_CONTENT_CHARS,
        MAX_OBSERVATION_CHARS,
        MnemonicContractError,
    )

    with pytest.raises(MnemonicContractError, match="observation exceeds"):
        event(observation="x" * (MAX_OBSERVATION_CHARS + 1))
    with pytest.raises(MnemonicContractError, match="content exceeds"):
        proposal(content="x" * (MAX_CONTENT_CHARS + 1))


def test_a_referenced_source_is_not_copied_into_the_payload(profile_a):
    """An email has a row of its own; duplicating its body here would give the
    same text two retention policies."""
    journal.open_operation(event(source_kind="email", source_id="msg-1"))
    with get_session() as session:
        payload = session.get(MemoryOperation, "evt-1").payload
        assert "observation" not in payload


def test_the_proposal_digest_changes_with_the_write_set(profile_a):
    """A permit and an approval bind to this digest, so it must move with the
    targets, not only with the prose."""
    base = proposal()
    targeted = Proposal(
        action="UPDATE",
        entity_type="COMPANY",
        scope="entity",
        content=base.content,
        write_set=(WriteTarget(blob_id="b1", expected_version="v1"),),
    )
    other_version = Proposal(
        action="UPDATE",
        entity_type="COMPANY",
        scope="entity",
        content=base.content,
        write_set=(WriteTarget(blob_id="b1", expected_version="v2"),),
    )
    assert journal.proposal_digest(targeted) != journal.proposal_digest(base)
    assert journal.proposal_digest(targeted) != journal.proposal_digest(other_version)
