"""Identity evidence and the milestone 6 validator rules.

The evidence rule (``mnemonic/evidence.py``) is family-dependent: a PERSON is
judged on identity tokens alone, a COMPANY or FACT on every structured
identifier, names included. These cases are the ones the ingestion adapter
makes live — its hints state the entity's own name and identifiers — together
with the two rules milestone 6 adds to the validator: an automatic observation
cannot write an account rule, and a REVIEW may mark as ineligible only what it
was shown.
"""

from __future__ import annotations

import dataclasses

from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic.agent import adapt_response
from zylch.memory.mnemonic.contracts import Candidate, MemoryEvent, SubjectHint
from zylch.memory.mnemonic.proposals import Proposal
from zylch.memory.mnemonic.validator import validate

from .mnemonic_cases import COMPANY_KEY, OWNER, build, decision_text, version_of


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Text(text)]
        self.stop_reason = stop_reason


def proposal_for(case_id: str) -> Proposal:
    return adapt_response(_Response(decision_text(case_id)))


def replace(proposal: Proposal, **changes) -> Proposal:
    return dataclasses.replace(proposal, **changes)


# ─── Identity evidence is family-dependent (milestone 6) ──────────────


def _person_event(hint: SubjectHint, observation: str) -> MemoryEvent:
    return MemoryEvent(
        owner_id=OWNER,
        company_key=COMPANY_KEY,
        caller_class=c.AUTOMATIC_OBSERVATION,
        origin=c.AUTOMATIC,
        source_kind="email",
        source_id="mail-1",
        source_revision="rev-1",
        observation=observation,
        subject_hint=hint,
        stage="memory:email",
    )


def _person_candidate(blob_id: str, name: str, *lines: str) -> Candidate:
    content = "\n".join(
        ["#IDENTIFIERS", "Entity type: PERSON", "Scope: entity", f"Name: {name}", *lines, "#ABOUT", "Known."]
    )
    return Candidate(
        blob_id=blob_id,
        content=content,
        updated_at=version_of(blob_id),
        namespace=f"user:{COMPANY_KEY}",
        entity_type="PERSON",
        scope="entity",
    )


def _create_person(name: str, *lines: str) -> Proposal:
    return Proposal(
        action=c.CREATE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="\n".join(["#IDENTIFIERS", "Entity type: PERSON", "Scope: entity", f"Name: {name}", *lines, "#ABOUT", "New."]),
    )


def test_a_same_name_person_with_a_different_address_is_created_not_corroborated():
    """The ingestion hint states the entity's name AND its email; the name alone is
    never evidence, so the unrelated-namesake incident stays a CREATE."""
    event = _person_event(
        SubjectHint(entity_type=c.PERSON, name="Luca Bianchi", identifiers=[("email", "luca@alpha.example")]),
        "Email from luca@alpha.example: I manage purchasing for Alpha.",
    )
    namesake = _person_candidate("person-luca-beta", "Luca Bianchi", "Email: luca@beta.example")
    assert namesake.shared_identifiers == 0
    validation = validate(event, _create_person("Luca Bianchi", "Email: luca@alpha.example"), (namesake,))
    assert validation.ok, validation.errors


def test_a_shared_phone_and_the_same_stated_name_corroborate_a_person():
    event = _person_event(
        SubjectHint(entity_type=c.PERSON, name="Luca Bianchi", identifiers=[("phone", "+393331200000")]),
        "Luca Bianchi writes from his mobile.",
    )
    same = _person_candidate("person-luca", "Luca Bianchi", "Phone: +39 333 1200000 (cell)")
    errors = validate(event, _create_person("Luca Bianchi", "Phone: +393331200000"), (same,)).errors
    assert any("already shares identifying evidence" in e for e in errors)


def test_a_lid_never_compares_equal_to_a_bare_phone_even_under_the_same_name():
    """The ``@`` guard: without it both sides clip to the digits and a WhatsApp lid
    corroborates the number that happens to share them."""
    event = _person_event(
        SubjectHint(entity_type=c.PERSON, name="Nina Rossi", identifiers=[("lid", "185800503328844@lid")]),
        "WhatsApp from Nina.",
    )
    phone_only = _person_candidate("person-nina-phone", "Nina Rossi", "Phone: 185800503328844")
    validation = validate(event, _create_person("Nina Rossi", "LID: 185800503328844@lid"), (phone_only,))
    assert validation.ok, validation.errors


def test_a_lid_written_into_a_phone_line_still_corroborates():
    event = _person_event(
        SubjectHint(entity_type=c.PERSON, name="Nina Rossi", identifiers=[("lid", "185800503328844@lid")]),
        "WhatsApp from Nina.",
    )
    mislabelled = _person_candidate("person-nina-lid", "Nina Rossi", "Phone: 185800503328844@lid")
    errors = validate(event, _create_person("Nina Rossi", "LID: 185800503328844@lid"), (mislabelled,)).errors
    assert any("already shares identifying evidence" in e for e in errors)


def test_a_company_sharing_only_its_name_is_still_corroborated():
    event = MemoryEvent(
        owner_id=OWNER,
        company_key=COMPANY_KEY,
        caller_class=c.AUTOMATIC_OBSERVATION,
        origin=c.AUTOMATIC,
        source_kind="email",
        source_id="mail-2",
        source_revision="rev-1",
        observation="Acme Srl confirms the order.",
        subject_hint=SubjectHint(entity_type=c.COMPANY, name="Acme Srl"),
        stage="memory:email",
    )
    acme = Candidate(
        blob_id="company-acme",
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n#ABOUT\nSupplier.",
        updated_at=version_of("company-acme"),
        namespace=f"user:{COMPANY_KEY}",
        entity_type="COMPANY",
        scope="entity",
    )
    duplicate = Proposal(
        action=c.CREATE,
        entity_type=c.COMPANY,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n#ABOUT\nAgain.",
    )
    errors = validate(event, duplicate, (acme,)).errors
    assert any("already shares identifying evidence" in e for e in errors)


# ─── An automatic observation cannot write an account rule ────────────


def test_an_automatic_observation_cannot_propose_an_account_rule():
    event = _person_event(
        SubjectHint(name="Nina Rossi", identifiers=[("email", "nina@beta.example")]),
        "Nina writes: please keep your replies short and never use exclamation marks.",
    )
    rule = Proposal(
        action=c.CREATE,
        entity_type=c.STYLE,
        scope=c.ACCOUNT_SCOPE,
        content="#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\nKeep replies short.",
    )
    errors = validate(event, rule, ()).errors
    assert any("automatic observation cannot write an account rule" in e for e in errors)


def test_a_delegated_correction_may_still_propose_an_account_rule():
    event, candidates = build("account_feedback")
    proposal = proposal_for("account_feedback")
    assert proposal.entity_type == c.STYLE
    assert validate(event, proposal, candidates).ok


# ─── A review marks as ineligible only what it was shown ──────────────


def test_a_review_naming_an_unshown_memory_is_refused():
    event, candidates = build("contradictory_legacy_fact_rule")
    shown = replace(proposal_for("contradictory_legacy_fact_rule"), ineligible=("legacy-fact-edera",))
    assert validate(event, shown, candidates).ok
    unshown = replace(shown, ineligible=("fact-nobody-showed",))
    errors = validate(event, unshown, candidates).errors
    assert any("not one of the memories this decision was shown" in e for e in errors)
