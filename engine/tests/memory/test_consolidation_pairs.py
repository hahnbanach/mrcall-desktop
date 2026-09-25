"""Pairing through the real operation: what folds, what costs nothing, what is left out.

Each case runs `consolidate` itself, inside a preparation run, on a real split
profile and company store, with only the provider transport scripted and a
healthy canary verdict stored, so the transport sees pair decisions and nothing
else. The transport's call count is how "costs nothing" is asserted: a pair
the operation refuses before paying never reaches it, and a call nobody
scripted fails the pair loudly.
"""

from __future__ import annotations

import pytest

from zylch.memory import consolidation
from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    MemoryEvent,
)
from zylch.memory.mnemonic.pairs import CONSOLIDATE_STAGE, pair_key
from zylch.memory.mnemonic.proposals import MnemonicResult
from zylch.memory.mnemonic.turn import turn_cancellation
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation

from tests.memory.consolidation_env import (
    LUCA,
    LUCA_EMAIL,
    attempts,
    healthy,
    identifiers_of,
    live,
    merge_answer,
    person,
    profile,
    scripted,
    seed,
    seed_versions,
    skip_answer,
    sweep,
    version_count,
)
from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, OWNER_B, BagOfWordsEmbedder, boot

LONG = "Purchasing at Alpha; handles every order and every return."
SHORT = "Joins the Thursday sync."


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def store(tmp_path, monkeypatch, embedder):
    yield from profile(tmp_path, monkeypatch, embedder)


# ─── A pair folds through its own admitted item ───────────────────────


def test_a_pair_merges_through_its_own_admitted_item(store, monkeypatch):
    keeper, donor = seed(store, person(about=LONG)), seed(store, person(about=SHORT))
    healthy(monkeypatch)
    transport = scripted(monkeypatch, merge_answer(store, keeper, donor))

    summary = sweep()

    assert summary["blobs_merged"] == summary["pairs_decided"] == 1
    assert transport.call_count == 1 and live(store, keeper, donor) == {keeper}
    assert attempts() == [(CONSOLIDATE_STAGE, pair_key(keeper, donor), 0, 0)]
    with get_session() as session:
        (row,) = session.query(MemoryOperation).all()
    assert row.state == "committed" and row.source_ref.startswith("consolidation:")


def test_a_cluster_folds_into_whichever_blob_the_last_merge_kept(store, monkeypatch):
    """Three copies, one run: the survivor is re-read before every pair.

    The role keeps the second member the first time, so the next pair must be
    formed with it — at the version that merge left — and not with the
    longest member it started from.
    """
    first = seed(store, person(about=LONG))
    second = seed(store, person(about=SHORT))
    third = seed(store, person(about="Called once."))
    healthy(monkeypatch)
    transport = scripted(
        monkeypatch,
        merge_answer(store, second, first),  # the role keeps the shorter one
        merge_answer(store, third, second),
    )

    summary = sweep()

    assert summary["blobs_merged"] == 2 and summary["pairs_changed"] == 0
    assert transport.call_count == 2
    assert live(store, first, second, third) == {third}


def test_a_skip_keeps_both_memories_and_their_identifiers(store, monkeypatch):
    first = seed(store, person(about="Sales, Milan office."), ("email", LUCA_EMAIL))
    second = seed(store, person(about="A namesake in Rome."), ("email", LUCA_EMAIL))
    healthy(monkeypatch)
    scripted(monkeypatch, skip_answer())

    summary = sweep()

    assert summary["blobs_kept_distinct"] == 1 and summary["blobs_merged"] == 0
    assert live(store, first, second) == {first, second}
    assert identifiers_of(first) == identifiers_of(second) == {("email", LUCA_EMAIL)}


def test_an_answered_pair_is_not_admitted_again_by_any_account(store, tmp_path, monkeypatch):
    first = seed(store, person(about="Sales, Milan office."))
    second = seed(store, person(about="A namesake in Rome."))
    healthy(monkeypatch)
    transport = scripted(monkeypatch, skip_answer())
    assert sweep()["blobs_kept_distinct"] == 1

    again = sweep()
    assert again["pairs_settled_before"] == 1 and again["pairs_decided"] == 0

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)  # another account, the same store
    healthy(monkeypatch, OWNER_B)
    theirs = sweep(OWNER_B)
    assert theirs["pairs_settled_before"] == 1 and theirs["pairs_decided"] == 0
    assert transport.call_count == 1 and live(store, first, second) == {first, second}


# ─── What costs nothing ───────────────────────────────────────────────


def test_a_pair_without_identity_evidence_costs_no_call(store, monkeypatch):
    """Two people called Luca Bianchi, their addresses different: a name alone."""
    first = seed(store, person(ids="Email: luca@alpha.example\n", about=LONG))
    second = seed(store, person(ids="Email: luca@beta.example\n", about=SHORT))
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["groups_examined"] == 1 and summary["pairs_without_evidence"] == 1
    assert transport.call_count == 0 and live(store, first, second) == {first, second}


@pytest.mark.parametrize(
    "calendar_ids, calendar_about, folds",
    [
        (f"Email: {LUCA_EMAIL}\n", SHORT, True),  # the header states the address
        ("", f"Invited as {LUCA_EMAIL} to the Thursday sync.", False),  # only the prose
        ("", SHORT, False),  # only a name
    ],
    ids=["address-in-header", "address-in-prose", "name-only"],
)
def test_a_calendar_person_folds_only_when_its_header_states_the_address(
    store, monkeypatch, calendar_ids, calendar_about, folds
):
    mail = seed(store, person(about=LONG))
    calendar = seed(store, person(ids=calendar_ids, about=calendar_about))
    healthy(monkeypatch)
    transport = scripted(monkeypatch, *([merge_answer(store, mail, calendar)] if folds else []))

    summary = sweep()

    assert summary["blobs_merged"] == int(folds)
    assert summary["pairs_without_evidence"] == int(not folds)
    assert transport.call_count == int(folds)
    assert live(store, mail, calendar) == ({mail} if folds else {mail, calendar})


@pytest.mark.parametrize("second_name, folds", [(LUCA, True), ("Luca B.", False)])
def test_a_shared_lid_folds_only_with_the_same_stated_name(store, monkeypatch, second_name, folds):
    lid = ("lid", "39123456@lid")
    first = seed(store, person(ids="LID: 39123456@lid\n", about=LONG), lid)
    second = seed(store, person(name=second_name, ids="LID: 39123456@lid\n", about=SHORT), lid)
    healthy(monkeypatch)
    transport = scripted(monkeypatch, *([merge_answer(store, first, second)] if folds else []))

    summary = sweep()

    assert summary["groups_examined"] == 1
    assert summary["blobs_merged"] == int(folds) and transport.call_count == int(folds)
    assert summary["pairs_without_evidence"] == int(not folds)


def test_a_legacy_pair_typed_in_lower_case_is_judged_as_person(store, monkeypatch):
    first = seed(store, person(entity_type="person", about=LONG))
    second = seed(store, person(entity_type="person", about=SHORT))
    healthy(monkeypatch)
    scripted(monkeypatch, merge_answer(store, first, second))

    summary = sweep()

    assert summary["blobs_merged"] == 1 and live(store, first, second) == {first}


# ─── What is left out ─────────────────────────────────────────────────


def test_a_sink_is_neither_paired_nor_pruned_and_is_named(store, monkeypatch):
    sink = seed(store, person(about=LONG))
    twin = seed(store, person(about=SHORT))
    seed_versions(sink, 26)  # over the default threshold of 25
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["version_sinks_total"] == 1
    assert summary["version_sinks"] == [{"blob_id": sink, "versions": 26}]
    assert summary["groups_examined"] == 0 and transport.call_count == 0
    assert live(store, sink, twin) == {sink, twin} and version_count(sink) == 26


def test_the_sink_report_reaches_the_cli_and_the_console_lines():
    summary = consolidation.empty_summary(
        blobs_versions_max=31,
        version_sinks_total=3,
        version_sinks=[{"blob_id": "b-1", "versions": 31}, {"blob_id": "b-2", "versions": 27}],
    )
    lines = consolidation.summary_lines(summary)

    assert "versions: 0 pruned; the most any memory holds is 31" in lines
    assert "  b-1: 31 versions" in lines and "  b-2: 27 versions" in lines
    assert any(line.startswith("  and 1 more") for line in lines)


def test_a_row_a_review_restricted_is_never_clustered(store, monkeypatch):
    first = seed(store, person(about=LONG))
    restricted = seed(store, person(about=SHORT))
    event = MemoryEvent(
        event_id="review-of-a-message",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-7",
        source_revision="r1",
        observation="A message about Luca's order.",
        stage="memory:email",
        cancellation=turn_cancellation(),
    )
    journal.open_operation(event)
    journal.record_result(
        event.event_id,
        MnemonicResult.review_needed(event.event_id, "held for review"),
        state=journal.REVIEW,
        restrictions=[{"blob_id": restricted, "version": "v1"}],
    )
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["blobs_examined"] == 1 and summary["groups_examined"] == 0
    assert transport.call_count == 0 and live(store, first, restricted) == {first, restricted}


def test_an_invalid_threshold_decides_no_pair(store, monkeypatch):
    monkeypatch.setenv("MEMORY_VERSION_SINK_THRESHOLD", "0")
    first, second = seed(store, person(about=LONG)), seed(store, person(about=SHORT))
    healthy(monkeypatch)
    transport = scripted(monkeypatch)

    summary = sweep()

    assert summary["retention_refused"] == ["version_sink_threshold=0 is below 1"]
    assert summary["pairs_decided"] == 0 and summary["groups_examined"] == 0
    assert transport.call_count == 0 and live(store, first, second) == {first, second}
