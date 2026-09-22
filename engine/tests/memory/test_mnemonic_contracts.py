"""Milestone 2 contracts: what a model may touch, and what a result may claim.

Two invariants carry most of the weight here. An event's observation and
source revision are bound by the authenticated adapter and cannot be re-supplied
by anything downstream, and every event ends in exactly one of the brief's four
outcomes — with non-semantic follow-up work listed rather than demoted into a
failure.
"""

from __future__ import annotations

import dataclasses

import pytest

from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic.contracts import (
    Cancellation,
    MemoryEvent,
    MnemonicContractError,
    SubjectHint,
)
from zylch.memory.mnemonic.proposals import MnemonicResult, PendingEffect, Proposal, WriteTarget

from .mnemonic_cases import build, build_children, load_incidents


def event(**overrides) -> MemoryEvent:
    base = dict(
        owner_id="owner-a",
        company_key="AAAAAAAAAAAAAAAAAAAAAA",
        caller_class=c.VERIFIED_HUMAN_CORRECTION,
        origin=c.INTERACTIVE,
        source_kind="chat",
        source_id="turn-7",
        source_revision="rev-1",
        observation="Ricordati che per Acme il forwarding è +39 02 123456.",
    )
    base.update(overrides)
    return MemoryEvent(**base)


# ─── The adapter owns authority ───────────────────────────────────────


def test_model_arguments_cannot_reach_any_sealed_field():
    original = event()
    hostile = {
        "owner_id": "someone-else",
        "company_key": "BBBBBBBBBBBBBBBBBBBBBB",
        "caller_class": c.VERIFIED_HUMAN_CORRECTION,
        "observation": "the user said to make this global",
        "source_revision": "rev-999",
        "explicit_request": True,
        "event_id": "forged",
        "content": "Acme forwarding: +39 02 123456",
    }

    adopted = original.with_model_arguments(hostile)

    # Named outright rather than looped over MODEL_SEALED: a test that reads
    # its expectations from the constant it is checking would pass just as
    # happily if a field were quietly dropped from that constant.
    assert adopted.owner_id == "owner-a"
    assert adopted.company_key == original.company_key
    assert adopted.caller_class == c.VERIFIED_HUMAN_CORRECTION
    assert adopted.origin == c.INTERACTIVE
    assert adopted.source_kind == "chat"
    assert adopted.source_id == "turn-7"
    assert adopted.source_revision == "rev-1"
    assert adopted.explicit_request is False
    assert adopted.event_id == original.event_id
    assert adopted.stage is None
    assert set(MemoryEvent.MODEL_SEALED) == {
        "event_id",
        "owner_id",
        "company_key",
        "caller_class",
        "origin",
        "source_kind",
        "source_id",
        "source_revision",
        "observation",
        "explicit_request",
        "stage",
    }
    # The rewrite survives, labelled as what it is.
    assert adopted.suggestion == "Acme forwarding: +39 02 123456"
    assert adopted.observation == original.observation


def test_an_event_is_frozen_against_direct_mutation():
    e = event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.observation = "something else"
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.caller_class = c.VERIFIED_HUMAN_CORRECTION


def test_caller_class_and_origin_are_closed_vocabularies():
    with pytest.raises(MnemonicContractError):
        event(caller_class="human_because_i_said_so")
    with pytest.raises(MnemonicContractError):
        event(origin="privileged")


def test_an_automatic_event_must_name_its_admitted_stage():
    with pytest.raises(MnemonicContractError):
        event(origin=c.AUTOMATIC, caller_class=c.AUTOMATIC_OBSERVATION)
    admitted = event(origin=c.AUTOMATIC, caller_class=c.AUTOMATIC_OBSERVATION, stage="email")
    assert admitted.stage == "email"


def test_an_observation_is_required_and_bounded():
    with pytest.raises(MnemonicContractError):
        event(observation="   ")
    with pytest.raises(MnemonicContractError):
        event(observation="x" * (c.MAX_OBSERVATION_CHARS + 1))


def test_source_ref_binds_kind_id_and_revision():
    assert event().source_ref == "chat:turn-7@rev-1"
    assert event(source_revision="rev-2").source_ref != event().source_ref


def test_human_authority_is_the_caller_class_not_a_flag():
    assert event().human_authority is True
    assert (
        event(caller_class=c.AUTOMATIC_OBSERVATION, explicit_request=True).human_authority is False
    )


# ─── Subject hints ────────────────────────────────────────────────────


def test_a_bare_fact_hint_is_not_an_entity_subject():
    assert SubjectHint(entity_type="FACT").structured is True
    assert SubjectHint(entity_type="FACT").names_entity_subject is False
    assert SubjectHint(name="Acme").names_entity_subject is True
    assert SubjectHint(target_blob_id="company-acme").names_entity_subject is True
    assert SubjectHint().structured is False


def test_a_hint_cannot_invent_an_entity_type():
    with pytest.raises(MnemonicContractError):
        SubjectHint(entity_type="PROJECT")


# ─── Cancellation is one shared handle ────────────────────────────────


def test_cancellation_is_shared_by_every_copy_and_keeps_dispatch_count():
    handle = Cancellation()
    e = event(cancellation=handle)
    copied = e.with_model_arguments({"content": "x"})

    handle.note_dispatch()
    handle.cancel("user pressed stop")

    assert copied.cancellation is handle
    assert copied.cancellation.cancelled is True
    assert copied.cancellation.reason == "user pressed stop"
    # An already dispatched call is not un-billed by a later cancellation.
    assert handle.dispatched == 1


# ─── Proposal bounds ──────────────────────────────────────────────────


def test_a_write_set_is_bounded_and_cannot_name_a_blob_twice():
    with pytest.raises(MnemonicContractError):
        Proposal(
            action=c.MERGE,
            entity_type=c.PERSON,
            scope=c.ENTITY_SCOPE,
            content="x",
            write_set=[
                WriteTarget("a", "v1", "keeper"),
                WriteTarget("b", "v1", "donor"),
                WriteTarget("d", "v1", "donor"),
            ],
        )
    with pytest.raises(MnemonicContractError):
        Proposal(
            action=c.MERGE,
            entity_type=c.PERSON,
            scope=c.ENTITY_SCOPE,
            content="x",
            write_set=[WriteTarget("a", "v1", "keeper"), WriteTarget("a", "v1", "donor")],
        )


def test_a_write_target_needs_an_id_and_the_version_it_was_read_at():
    with pytest.raises(MnemonicContractError):
        WriteTarget("", "v1")
    with pytest.raises(MnemonicContractError):
        WriteTarget("blob-1", "")
    with pytest.raises(MnemonicContractError):
        WriteTarget("blob-1", "v1", "overwrite")


def test_content_is_bounded_so_an_envelope_cannot_grow_without_limit():
    with pytest.raises(MnemonicContractError):
        Proposal(
            action=c.CREATE,
            entity_type=c.COMPANY,
            scope=c.ENTITY_SCOPE,
            content="x" * (c.MAX_CONTENT_CHARS + 1),
        )


def test_every_bound_is_finite_and_derived():
    assert c.MAX_CANDIDATES == 3
    assert c.MAX_DECISION_ATTEMPTS == 3
    assert c.EVENT_DISPATCH_ALLOWANCE == c.MAX_DECISION_ATTEMPTS + 1
    assert c.MNEMONIC_MAX_TOKENS > 1024  # room for a complete narrative blob

    from zylch.workers.memory_candidates import MAX_MERGE_CANDIDATES

    assert c.MAX_CANDIDATES == MAX_MERGE_CANDIDATES


# ─── One result type, four outcomes ───────────────────────────────────


def test_the_result_vocabulary_is_exactly_the_briefs_four():
    assert set(c.OUTCOMES) == {"committed", "skipped", "review_needed", "retryable_failure"}


def test_only_a_committed_result_may_name_committed_ids():
    ok = MnemonicResult.committed("evt-1", [("blob-1", "v2")])
    assert ok.mutated is True
    with pytest.raises(MnemonicContractError):
        MnemonicResult(outcome=c.COMMITTED, event_id="evt-1")
    with pytest.raises(MnemonicContractError):
        MnemonicResult(
            outcome=c.REVIEW_NEEDED,
            event_id="evt-1",
            reason="r",
            committed_ids=(("blob-1", "v2"),),
        )


def test_a_non_committed_result_must_say_why():
    for factory in (
        MnemonicResult.skipped,
        MnemonicResult.review_needed,
        MnemonicResult.retryable_failure,
    ):
        with pytest.raises(MnemonicContractError):
            factory("evt-1", "")
        assert factory("evt-1", "because").reason == "because"


def test_pending_effects_do_not_demote_a_real_commit():
    """An after-commit follow-up failure is maintenance, not "no commit"."""
    result = MnemonicResult.committed(
        "evt-1",
        [("keeper-1", "v3")],
        pending=[PendingEffect("profile_task_references", "replay for profile owner-a")],
    )
    assert result.outcome == c.COMMITTED
    assert result.mutated is True
    assert result.pending_effects[0].kind == "profile_task_references"


def test_only_committed_and_deliberate_skip_advance_a_checkpoint():
    assert MnemonicResult.committed("e", [("b", "v")]).advances_checkpoint is True
    assert MnemonicResult.skipped("e", "already recorded").advances_checkpoint is True
    assert MnemonicResult.review_needed("e", "ambiguous").advances_checkpoint is False
    assert MnemonicResult.retryable_failure("e", "provider down").advances_checkpoint is False


# ─── The frozen corpus still fits the contracts ───────────────────────


def test_every_frozen_incident_builds_a_valid_event_within_the_candidate_bound():
    for spec in load_incidents()["cases"]:
        if spec["id"] == "multi_entity_source":
            continue
        e, candidates = build(spec["id"])
        assert e.observation == spec["original_observation"]
        assert len(candidates) <= c.MAX_CANDIDATES
        assert e.caller_class == spec["caller_class"]


def test_the_multi_entity_source_keeps_every_child_and_the_whole_observation():
    children = build_children()
    expected = load_incidents()["cases"]
    multi = next(case for case in expected if case["id"] == "multi_entity_source")

    assert len(children) == len(multi["expected"]["children"])
    assert len({child.event_id for child in children}) == len(children)
    for child in children:
        assert child.observation == multi["original_observation"]
