"""Retrieval tokens, identity tokens and the hint-driven query (milestone 6).

Two token sets leave ``candidates.py``, and this file holds them apart on
purpose: retrieval tokens select and rank, identity tokens are evidence. An
ingestion child's observation is the whole message it came from, so the split
is what keeps a sender's address from corroborating every entity the message
mentions. The chat and solve adapters state no hint identifiers, and for them
the observation is mined exactly as before.
"""

from __future__ import annotations

import pytest

from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic.candidates import (
    _normalize,
    event_identifiers,
    gather,
    identity_tokens,
    identity_tokens_of,
    parse_identifiers,
    retrieval_query,
)
from zylch.memory.mnemonic.contracts import MemoryEvent, SubjectHint
from zylch.memory.mnemonic.wiring import typed_identifiers

MAIL = (
    "From: mario@acme.test\nTo: support@company.test\nCC: cc@acme.test\n"
    "Subject: order\n\nLuca Bianchi (luca@alpha.example, +39 333 1200000) will call you."
)


def event(hint=None, observation=MAIL, **overrides) -> MemoryEvent:
    base = dict(
        owner_id="owner-a",
        company_key="AAAAAAAAAAAAAAAAAAAAAA",
        caller_class=c.AUTOMATIC_OBSERVATION,
        origin=c.AUTOMATIC,
        source_kind="email",
        source_id="mail-1",
        source_revision="rev-1",
        observation=observation,
        subject_hint=hint,
        stage="memory:email",
    )
    base.update(overrides)
    return MemoryEvent(**base)


# ─── One comparison form ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+39 333 1200000 (cell)", "+393331200000"),
        ("00393331200000", "+393331200000"),
        ("+39 333 1200000 / home", "+393331200000"),
        ("185800503328844@lid", "185800503328844@lid"),
        ("Info@Acme.test", "info@acmetest"),
        ("3M Company", "3mcompany"),
        ("Luca Bianchi", "lucabianchi"),
    ],
)
def test_normalize_clips_a_phone_like_the_index_and_never_a_value_with_an_at(raw, expected):
    assert _normalize(raw) == expected


def test_a_lids_digits_are_never_read_as_a_phone():
    tokens = parse_identifiers("#IDENTIFIERS\nPhone: 185800503328844@lid\n#ABOUT\nx")
    assert "185800503328844@lid" in tokens
    assert "185800503328844" not in tokens


# ─── Retrieval tokens versus identity tokens ──────────────────────────


def test_with_no_hint_an_interactive_observation_is_mined_as_before():
    mined = event(None, caller_class=c.OPERATOR_DELEGATED, origin=c.INTERACTIVE, source_kind="chat", stage=None)
    assert event_identifiers(mined) == parse_identifiers(MAIL)
    assert identity_tokens(mined) == identity_tokens_of(MAIL)
    assert "mario@acmetest" in identity_tokens(mined)
    assert "lucabianchi" not in identity_tokens(mined)


def test_a_hint_that_states_identifiers_keeps_the_sender_out():
    child = event(
        SubjectHint(
            entity_type=c.PERSON,
            name="Luca Bianchi",
            identifiers=[("email", "luca@alpha.example"), ("phone", "+393331200000")],
        )
    )
    assert identity_tokens(child) == {"luca@alphaexample", "+393331200000"}
    assert event_identifiers(child) == {"lucabianchi", "luca@alphaexample", "+393331200000"}
    assert "mario@acmetest" not in event_identifiers(child)


def test_an_automatic_event_never_mines_its_observation():
    """A name-only extracted entity states no address, and the message it came
    from carries the sender's: that address must not become its identity."""
    hinted = event(SubjectHint(entity_type=c.PERSON, name="Luca Bianchi", company="Acme"))
    assert identity_tokens(hinted) == set()
    assert event_identifiers(hinted) == {"lucabianchi", "acme"}
    unhinted = event(None)
    assert identity_tokens(unhinted) == set()
    assert event_identifiers(unhinted) == set()


def test_an_interactive_event_with_a_name_only_hint_still_mines_what_was_said():
    """The corpus's shared-switchboard shape, as an interactive turn: the hint
    names Sara and Delta, the reception number is in the text, and the count
    the role sees keeps it."""
    hinted = event(
        SubjectHint(entity_type=c.PERSON, name="Sara Conti", company="Delta"),
        observation="She gives the shared reception number +39 02 555500.",
        caller_class=c.OPERATOR_DELEGATED,
        origin=c.INTERACTIVE,
        source_kind="chat",
        stage=None,
    )
    assert identity_tokens(hinted) == {"+3902555500"}
    assert event_identifiers(hinted) == {"saraconti", "delta", "+3902555500"}


def test_a_scalar_email_hint_reads_like_a_typed_pair():
    assert identity_tokens(event(SubjectHint(email="Luca@Alpha.example"))) == {"luca@alphaexample"}


# ─── The query the search is asked ────────────────────────────────────


def test_a_hint_drives_the_cosine_query_and_no_hint_leaves_the_observation():
    assert retrieval_query(event(None)) == MAIL
    assert retrieval_query(event(SubjectHint(target_blob_id="blob-1"))) == MAIL
    child = event(
        SubjectHint(
            entity_type=c.PERSON,
            name="Luca Bianchi",
            company="Alpha",
            identifiers=[("email", "luca@alpha.example"), ("lid", "1234567890123@lid")],
        )
    )
    assert retrieval_query(child) == (
        "Name: Luca Bianchi\nCompany: Alpha\nEmail: luca@alpha.example\nLID: 1234567890123@lid"
    )


def test_gather_searches_with_the_hint_query_and_pins_the_named_row():
    queries = []

    def searched(query, limit):
        queries.append((query, limit))
        return ()

    child = event(SubjectHint(entity_type=c.PERSON, name="Luca Bianchi"))
    assert gather(child, get_blob=lambda _bid: None, search=searched) == ()
    assert queries == [("Name: Luca Bianchi", c.MAX_CANDIDATES)]

    pinned = event(SubjectHint(target_blob_id="blob-1"))
    rows = gather(
        pinned,
        get_blob=lambda bid: {"content": "#IDENTIFIERS\nName: X\n#ABOUT\ny", "updated_at": "v1", "namespace": "user:k"},
        search=searched,
    )
    assert [r.blob_id for r in rows] == ["blob-1"]
    assert queries[-1] == (MAIL, c.MAX_CANDIDATES)


# ─── The identity index is asked with typed pairs ─────────────────────


def test_typed_identifiers_come_from_the_hint_when_it_states_them():
    child = event(
        SubjectHint(
            entity_type=c.PERSON,
            identifiers=[("email", "luca@alpha.example"), ("lid", "1234567890123@lid")],
            phone="+39 333 1200000",
        )
    )
    assert typed_identifiers(child) == [
        ("email", "luca@alpha.example"),
        ("lid", "1234567890123@lid"),
        ("phone", "+39 333 1200000"),
    ]


def test_typed_identifiers_fall_back_to_the_observation_for_chat_and_solve():
    turn = event(
        None,
        caller_class=c.OPERATOR_DELEGATED,
        origin=c.INTERACTIVE,
        source_kind="chat",
        stage=None,
        observation="Acme ordina da info@acme.test e risponde al +39 02 1234567.",
    )
    # The index's own form: the address as written, lowercased, dots kept.
    assert set(typed_identifiers(turn)) == {("email", "info@acme.test"), ("phone", "+39021234567")}


def test_a_name_never_reaches_the_identity_index_and_neither_does_the_envelope():
    """A name-only child adds no pair, and its message's From/To/CC/Date lines
    are never read as its identity — with the module's own mail as the source."""
    child = event(SubjectHint(entity_type=c.COMPANY, name="Acme Srl"))
    assert typed_identifiers(child) == []
    assert "acmesrl" in event_identifiers(child)
    assert "mario@acmetest" not in event_identifiers(child)


# ─── The merge-gate brake shows the role nothing ──────────────────────


def test_a_context_without_retrieval_answers_nothing_but_exact_reads(company_db, embedder):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.mnemonic.wiring import default_context
    from zylch.storage.database import get_session

    storage = BlobStorage(get_session, embedder)
    from zylch.memory.company_key import current_company_key

    blob = storage.store_blob(
        "owner-a", f"user:{current_company_key()}", "#IDENTIFIERS\nName: Acme\n#ABOUT\nx", "seed"
    )
    braked = default_context("owner-a", retrieval=False)
    assert list(braked.search("Acme", 3)) == []
    assert list(braked.identifier_blob_ids([("email", "info@acme.test")])) == []
    assert braked.get_blob(blob["id"])["id"] == blob["id"]
