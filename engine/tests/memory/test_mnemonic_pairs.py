"""Consolidation pairs: the event, the evidence checked before paying, the door.

What makes a consolidation event a *pair* is small and each part is checked on
its own here: the hint states only what both members' headers assert in
common; the pre-check is the validator's own identity rule; a pair another
account already answered is found by `source_ref`; the MERGE guard admits only
the very pair, inside its admitted item; and outside an admitted item nothing
is submitted. The merge itself — the transaction — is `test_mnemonic_merge.py`.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic import pairs
from zylch.memory.mnemonic.candidates import parse_header
from zylch.memory.mnemonic.contracts import Candidate, MnemonicContractError
from zylch.memory.mnemonic.proposals import MnemonicResult, Proposal, WriteTarget
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    OWNER_B,
    boot,
    clear_process_state,
    client,
)


def person(name, *lines, entity_type="PERSON", history=""):
    header = ["#IDENTIFIERS"] + ([f"Entity type: {entity_type}"] if entity_type else [])
    body = [f"Name: {name}", *lines, "#ABOUT", "Known.", "#HISTORY", history or "- met once"]
    return "\n".join(header + body)


def blob(blob_id, content, version="2026-09-24T10:00:00"):
    return {"id": blob_id, "content": content, "updated_at": version}


def candidate(row):
    return Candidate(
        blob_id=row["id"],
        content=row["content"],
        updated_at=row["updated_at"],
        namespace=f"user:{COMPANY_A}",
        entity_type=parse_header(row["content"]).get("entity type"),
    )


def evidence(first, second):
    event = pairs.pair_event(OWNER_A, COMPANY_A, first, second)
    return pairs.has_evidence(event, candidate(first), candidate(second))


# ─── The hint: what both headers state in common ──────────────────────


def test_the_hint_is_what_both_headers_state_in_common_and_nothing_else():
    first = blob("a", person("Luca Bianchi", "Email: luca@alpha.example", "Company: Alpha"))
    second = blob(
        "b",
        person(
            "luca bianchi",
            "Email: luca@alpha.example",
            "Phone: +39 333 1200000",
            "Company: Alpha",
            entity_type="person",
            history="- wrote to anna@beta.example about the order",
        ),
    )
    hint = pairs.common_hint(first["content"], second["content"])
    assert hint.entity_type == c.PERSON  # compared without regard to case
    assert hint.name == "Luca Bianchi"
    assert hint.identifiers == (("email", "luca@alpha.example"),)  # not the phone, not prose
    assert hint.company is None  # a shared company is never identity


def test_the_hint_states_no_type_or_name_the_members_disagree_on():
    hint = pairs.common_hint(
        person("Luca Bianchi", "Email: luca@alpha.example"),
        person("Marta Riva", "Email: marta@alpha.example", entity_type="COMPANY"),
    )
    assert (hint.entity_type, hint.name, hint.identifiers) == (None, None, ())
    one_sided = pairs.common_hint(
        person("Acme", entity_type="COMPANY"), person("Acme", entity_type="")
    )
    assert one_sided.entity_type == c.COMPANY and one_sided.name == "Acme"


def test_a_pair_is_the_same_event_whichever_member_is_named_first():
    first = blob("a", person("Luca Bianchi", "Email: luca@alpha.example"))
    second = blob("b", person("Luca Bianchi", "Email: luca@alpha.example"), version="v2")
    forward = pairs.pair_event(OWNER_A, COMPANY_A, first, second)
    backward = pairs.pair_event(OWNER_A, COMPANY_A, second, first)
    assert forward.event_id == backward.event_id and forward.observation == backward.observation
    assert (forward.source_kind, forward.source_id) == (pairs.PAIR_SOURCE_KIND, "a|b")
    assert (forward.origin, forward.stage) == (c.AUTOMATIC, pairs.CONSOLIDATE_STAGE)
    changed = pairs.pair_event(OWNER_A, COMPANY_A, first, dict(second, updated_at="v3"))
    assert changed.event_id != forward.event_id  # a changed member is a new event
    other_account = pairs.pair_event(OWNER_B, COMPANY_A, first, second)
    assert other_account.event_id != forward.event_id
    assert other_account.source_ref == forward.source_ref  # the same pair, whoever asks


def test_one_blob_is_never_a_pair_and_a_write_set_never_names_it_twice():
    same = blob("a", person("Luca Bianchi", "Email: luca@alpha.example"))
    with pytest.raises(MnemonicContractError):
        pairs.pair_event(OWNER_A, COMPANY_A, same, same)
    with pytest.raises(MnemonicContractError):
        Proposal(
            action=c.MERGE,
            entity_type=c.PERSON,
            scope=c.ENTITY_SCOPE,
            content=same["content"],
            write_set=(WriteTarget("a", "v1", "keeper"), WriteTarget("a", "v1", "donor")),
        )


# ─── The evidence checked before paying ───────────────────────────────


@pytest.mark.parametrize(
    "first_lines, second_lines, expected",
    [
        (("Email: luca@alpha.example",), ("Email: luca@alpha.example",), True),
        (("Phone: +39 333 1200000",), ("Phone: +393331200000",), True),
        (("LID: 185800503328844@lid",), ("LID: 185800503328844",), True),
        (("Email: luca@alpha.example",), ("Email: luca@beta.example",), False),
        ((), (), False),  # the same name alone never makes two people one
    ],
)
def test_a_person_pair_needs_identity_evidence_in_both_headers(first_lines, second_lines, expected):
    first = blob("a", person("Luca Bianchi", *first_lines))
    second = blob("b", person("Luca Bianchi", *second_lines))
    assert evidence(first, second) is expected


def test_a_shared_phone_or_lid_needs_the_same_name():
    for line in ("Phone: +39 333 1200000", "LID: 185800503328844@lid"):
        first = blob("a", person("Luca Bianchi", line))
        second = blob("b", person("Marta Riva", line))
        assert evidence(first, second) is False, line


def test_prose_is_never_evidence():
    first = blob("a", person("Luca Bianchi", "Email: luca@alpha.example"))
    second = blob("b", person("Luca Bianchi", history="- reachable at luca@alpha.example"))
    assert evidence(first, second) is False


def test_a_company_pair_folds_on_a_shared_name_and_types_decide_the_rule():
    acme = blob("a", person("Acme Srl", entity_type="COMPANY"))
    acme_again = blob("b", person("acme srl", entity_type="company"))
    assert evidence(acme, acme_again) is True
    untyped = blob("c", person("Acme Srl", entity_type=""))
    assert evidence(acme, untyped) is True  # the weaker, COMPANY rule decides whether to ask
    mixed = blob("d", person("Acme Srl", "Email: info@acme.test"))
    assert evidence(acme, mixed) is False  # a PERSON and a COMPANY are never one
    project = blob("e", person("Acme Srl", entity_type="PROJECT"))
    assert evidence(project, blob("f", person("Acme Srl", entity_type="PROJECT"))) is False
    stranger = blob("g", person("Beta Srl", entity_type=""))
    assert evidence(untyped, stranger) is False


def test_intact_means_every_member_present_at_its_paired_version():
    first = blob("a", person("Luca"))
    second = blob("b", person("Luca"), version="v2")
    pinned = pairs.pair_context(None, OWNER_A, first, second).pinned
    assert pairs.intact(pinned, [candidate(first), candidate(second)])
    assert not pairs.intact(pinned, [candidate(first)])
    assert not pairs.intact(pinned, [candidate(first), candidate(dict(second, updated_at="v3"))])


# ─── The journal pre-check and the door, on a real store ──────────────


@pytest.fixture
def profile_a(tmp_path, monkeypatch):
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


def _pair():
    first = blob("blob-a", person("Luca Bianchi", "Email: luca@alpha.example"))
    second = blob("blob-b", person("Luca Bianchi", "Email: luca@alpha.example"), version="v2")
    return first, second


def _record(event, owner, state):
    with get_session() as session:
        session.add(
            MemoryOperation(
                event_id=f"{owner}-{state}",
                owner_id=owner,
                company_key=COMPANY_A,
                input_digest="d",
                source_ref=event.source_ref,
                origin=c.AUTOMATIC,
                caller_class=c.AUTOMATIC_OBSERVATION,
                state=state,
            )
        )


def test_a_pair_another_account_answered_is_settled_and_a_pending_one_is_not(profile_a):
    first, second = _pair()
    event = pairs.pair_event(OWNER_A, COMPANY_A, first, second)
    assert pairs.settled(event) is None
    _record(event, OWNER_B, "pending")
    assert pairs.settled(event) is None
    _record(event, OWNER_B, "skipped")
    assert pairs.settled(event) == "skipped"


def test_outside_a_preparation_run_a_pair_is_not_submitted(profile_a):
    first, second = _pair()
    pair_ = {
        "id": pairs.pair_key("blob-a", "blob-b"),
        "event": pairs.pair_event(OWNER_A, COMPANY_A, first, second),
    }
    llm = client()  # any provider call would raise: the transport has no answer
    item = pairs.PairItem(OWNER_A, lambda p: pairs.decide(p, client=llm))

    assert asyncio.run(item.run(pair_)) is None
    assert item.results == {}
    assert llm._client.messages.create.call_count == 0
    with get_session() as session:
        assert session.query(MemoryOperation).count() == 0


def test_the_merge_door_admits_only_the_pair_inside_its_admitted_item(profile_a):
    first, second = _pair()
    event = pairs.pair_event(OWNER_A, COMPANY_A, first, second)
    merge = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content=first["content"],
        write_set=(WriteTarget("blob-a", "v1", "keeper"), WriteTarget("blob-b", "v2", "donor")),
        declared_effects=("alias:blob-b->blob-a",),
    )
    other = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content=first["content"],
        write_set=(WriteTarget("blob-a", "v1", "keeper"), WriteTarget("blob-x", "v9", "donor")),
        declared_effects=("alias:blob-x->blob-a",),
    )
    assert (
        pairs.admits_merge(event, merge, (c.CREATE, c.UPDATE)) == pairs.MERGE_OUTSIDE_CONSOLIDATION
    )
    assert pairs.admits_merge(event, merge, (c.MERGE,)) == pairs.MERGE_UNADMITTED  # no item
    seen = {}

    def inside(pair_):
        seen["same"] = pairs.admits_merge(pair_["event"], merge, (c.MERGE,))
        seen["other"] = pairs.admits_merge(pair_["event"], other, (c.MERGE,))
        return MnemonicResult.skipped(pair_["event"].event_id, "probe")

    item = pairs.PairItem(OWNER_A, inside)
    with preparation_run(OWNER_A):
        asyncio.run(item.run({"id": event.source_id, "event": event}))
    assert seen == {"same": "", "other": pairs.MERGE_OTHER_PAIR}
