"""The small symbolic validator, driven by the frozen milestone 0 incidents.

Each incident is replayed with its deterministic decision and must be accepted;
then the same incident is replayed with the mutation that actually caused the
production damage, and must be refused. The attack cases below — authority
spoofing, an UPDATE that is really a merge, a write target nobody was shown,
stale keeper/donor versions, a wrong header or namespace — are the shapes that
a purely semantic guard cannot be trusted to catch.
"""

from __future__ import annotations

import pytest

from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic.agent import adapt_response
from zylch.memory.mnemonic.contracts import (
    Candidate,
    MemoryEvent,
    SubjectHint,
)
from zylch.memory.mnemonic.proposals import Proposal, Reclassification, WriteTarget
from zylch.memory.mnemonic.validator import validate

from .mnemonic_cases import (
    COMPANY_KEY,
    OWNER,
    build,
    build_children,
    case,
    decision_text,
    load_incidents,
    version_of,
)


class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    """The Anthropic-shaped answer the client hands back, with nothing else."""

    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Text(text)]
        self.stop_reason = stop_reason


def proposal_for(case_id: str) -> Proposal:
    return adapt_response(_Response(decision_text(case_id)))


def replace(proposal: Proposal, **changes) -> Proposal:
    import dataclasses

    return dataclasses.replace(proposal, **changes)


# ─── Every frozen incident, decided safely ────────────────────────────


SINGLE_SUBJECT = [
    spec["id"]
    for spec in load_incidents()["cases"]
    if spec["id"] not in ("multi_entity_source", "malformed_output")
]


@pytest.mark.parametrize("case_id", SINGLE_SUBJECT)
def test_the_deterministic_decision_for_each_incident_validates(case_id):
    event, candidates = build(case_id)
    proposal = proposal_for(case_id)
    expected = case(case_id)["expected"]

    result = validate(event, proposal, candidates)

    assert result.ok, f"{case_id}: {result.errors}"
    if "allowed_actions" in expected:
        assert proposal.action in expected["allowed_actions"]
    if expected.get("entity_type") and proposal.mutates:
        assert proposal.entity_type == expected["entity_type"]
        assert proposal.scope == expected["scope"]
    if expected.get("required_target"):
        assert proposal.target.blob_id == expected["required_target"]
    for forbidden in expected.get("forbidden_targets", []):
        assert forbidden not in [t.blob_id for t in proposal.write_set]
    for forbidden in expected.get("forbidden_types", []):
        assert proposal.entity_type != forbidden


@pytest.mark.parametrize("case_id", SINGLE_SUBJECT)
def test_each_decision_preserves_what_the_incident_says_must_survive(case_id):
    """The corpus names the substance; the decision must still carry it."""
    proposal = proposal_for(case_id)
    body = f"{proposal.content}\n{proposal.reason}".lower()
    for fragment in case(case_id)["expected"].get("must_preserve", []):
        assert fragment.lower() in body, f"{case_id} dropped {fragment!r}"


def test_planned_work_is_not_written_as_completed_work():
    proposal = proposal_for("planned_not_completed")
    for claim in case("planned_not_completed")["expected"]["must_not_assert"]:
        assert claim.lower() not in proposal.content.lower()


def test_every_child_of_the_multi_entity_source_decides_independently():
    person, company = build_children()
    for event, key in ((person, "person"), (company, "company")):
        proposal = proposal_for(f"multi_entity_source__{key}")
        assert validate(event, proposal, ()).ok, key


# ─── A caller-resolved subject can never become global knowledge ──────


@pytest.mark.parametrize(
    "case_id", ["customer_forwarding_number_correction", "customer_price_correction"]
)
def test_a_customer_correction_cannot_be_committed_as_a_company_fact(case_id):
    event, candidates = build(case_id)
    as_fact = replace(
        proposal_for(case_id),
        entity_type=c.FACT,
        scope=c.COMPANY_SCOPE,
        write_set=(),
        content="#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: pricing\nKey: k\n#ABOUT\nx",
    )

    result = validate(event, as_fact, candidates)

    assert not result.ok
    assert any("company-wide knowledge" in e for e in result.errors)


def test_unbound_prose_is_left_to_the_role_to_classify():
    """No hint, no mechanical veto: a genuine company policy stays possible."""
    event, candidates = build("global_opening_hours")
    assert event.subject_hint is None
    assert validate(event, proposal_for("global_opening_hours"), candidates).ok


# ─── Family, scope, header and namespace must agree ───────────────────


def test_a_person_cannot_claim_company_scope():
    event, candidates = build("unrelated_same_name_people")
    bad = replace(proposal_for("unrelated_same_name_people"), scope=c.COMPANY_SCOPE)
    errors = validate(event, bad, candidates).errors
    assert any("requires scope 'entity'" in e for e in errors)


def test_a_header_contradicting_its_envelope_is_refused():
    event, candidates = build("corroborated_same_person")
    bad = replace(
        proposal_for("corroborated_same_person"),
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
    )
    errors = validate(event, bad, candidates).errors
    assert any("header says 'COMPANY'" in e for e in errors)


def test_an_account_rule_cannot_be_written_into_a_company_namespace():
    event, _ = build("account_feedback")
    company_row = Candidate(
        blob_id="company-acme",
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme\n#ABOUT\nx",
        updated_at=version_of("company-acme"),
        namespace=f"user:{COMPANY_KEY}",
        entity_type="COMPANY",
        scope="entity",
        shared_identifiers=1,
    )
    rule_into_company = Proposal(
        action=c.UPDATE,
        entity_type=c.STYLE,
        scope=c.ACCOUNT_SCOPE,
        content="#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\nAvoid exclamation marks.",
        write_set=(WriteTarget("company-acme", version_of("company-acme"), "target"),),
    )

    errors = validate(event, rule_into_company, (company_row,)).errors

    assert any("rule cannot target a company memory namespace" in e for e in errors)


def test_a_fact_cannot_be_written_into_a_rule_namespace():
    event, _ = build("global_opening_hours")
    rule_row = Candidate(
        blob_id="prefs-1",
        content="#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\nx",
        updated_at=version_of("prefs-1"),
        namespace=f"prefs:{OWNER}",
        entity_type="STYLE",
        scope="account",
        shared_identifiers=1,
    )
    fact_into_rule = Proposal(
        action=c.UPDATE,
        entity_type=c.FACT,
        scope=c.COMPANY_SCOPE,
        content="#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: hours\nKey: k\n#ABOUT\nx",
        write_set=(WriteTarget("prefs-1", version_of("prefs-1"), "target"),),
    )

    errors = validate(event, fact_into_rule, (rule_row,)).errors

    assert any("rule namespace" in e for e in errors)


# ─── Reclassification is explicit, never a side effect ────────────────


def test_moving_a_memory_between_families_needs_a_stated_reclassification():
    event, _ = build("contradictory_legacy_fact_rule")
    legacy_fact = Candidate(
        blob_id="legacy-fact-edera",
        content="Category: pricing\nKey: edera-term\nEdera has a 6-month minimum.",
        updated_at=version_of("legacy-fact-edera"),
        namespace=f"facts:{COMPANY_KEY}",
        shared_identifiers=1,
    )
    silent_move = Proposal(
        action=c.UPDATE,
        entity_type=c.COMPANY,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Edera\n#ABOUT\n12-month minimum.",
        write_set=(WriteTarget("legacy-fact-edera", version_of("legacy-fact-edera"), "target"),),
    )

    errors = validate(event, silent_move, (legacy_fact,)).errors

    assert any("explicit reclassification" in e for e in errors)

    stated = replace(
        silent_move,
        reclassification=Reclassification("FACT", "company", "COMPANY", "entity"),
    )
    # The move is now stated — and still checked against the row it would move.
    assert "explicit reclassification" not in " ".join(
        validate(event, stated, (legacy_fact,)).errors
    )


def test_a_reclassification_must_match_its_own_envelope():
    event, candidates = build("corroborated_same_person")
    mismatched = replace(
        proposal_for("corroborated_same_person"),
        reclassification=Reclassification("PERSON", "entity", "FACT", "company"),
    )
    errors = validate(event, mismatched, candidates).errors
    assert any("contradicts the proposal's own envelope" in e for e in errors)


def test_an_unsupported_legacy_type_is_reviewed_not_silently_retyped():
    event, _ = build("corroborated_same_person")
    project_row = Candidate(
        blob_id="legacy-project",
        content="#IDENTIFIERS\nEntity type: PROJECT\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        updated_at=version_of("legacy-project"),
        namespace=f"user:{COMPANY_KEY}",
        entity_type="PROJECT",
        scope="entity",
        shared_identifiers=2,
    )
    touch = Proposal(
        action=c.UPDATE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        write_set=(WriteTarget("legacy-project", version_of("legacy-project"), "target"),),
    )

    errors = validate(event, touch, (project_row,)).errors

    assert any("unsupported type 'PROJECT'" in e for e in errors)


# ─── Targets: visible, exact, current, and only the declared ones ─────


def test_a_write_target_nobody_was_shown_is_refused():
    event, candidates = build("corroborated_same_person")
    elsewhere = replace(
        proposal_for("corroborated_same_person"),
        write_set=(WriteTarget("person-somebody-else", "v1", "target"),),
    )
    errors = validate(event, elsewhere, candidates).errors
    assert any("not one of the memories this decision was shown" in e for e in errors)


def test_a_stale_target_version_is_refused_and_never_becomes_a_create():
    event, candidates = build("customer_forwarding_number_correction")
    stale = replace(
        proposal_for("customer_forwarding_number_correction"),
        write_set=(WriteTarget("company-acme", "2026-09-19T08:00:00-company-acme", "target"),),
    )

    result = validate(event, stale, candidates)

    assert not result.ok
    assert any("changed since it was read" in e for e in result.errors)


def test_a_stale_keeper_or_donor_fails_the_merge():
    event, candidates = build("corroborated_same_person")
    donor = Candidate(
        blob_id="person-luca-dup",
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n"
        "Email: luca@alpha.example\n#ABOUT\nDuplicate row.",
        updated_at=version_of("person-luca-dup"),
        namespace=f"user:{COMPANY_KEY}",
        entity_type="PERSON",
        scope="entity",
        shared_identifiers=2,
    )
    merge = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        write_set=(
            WriteTarget("person-luca-alpha", version_of("person-luca-alpha"), "keeper"),
            WriteTarget("person-luca-dup", "2026-09-01T00:00:00-person-luca-dup", "donor"),
        ),
        declared_effects=("alias:person-luca-dup->person-luca-alpha",),
    )

    errors = validate(event, merge, (*candidates, donor)).errors

    assert any("changed since it was read" in e for e in errors)


def test_an_update_may_not_drop_its_targets_stated_subject():
    event, candidates = build("corroborated_same_person")
    hijack = replace(
        proposal_for("corroborated_same_person"),
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Andrea Rossi\n#ABOUT\nx",
    )
    errors = validate(event, hijack, candidates).errors
    assert any("only modify the same subject" in e for e in errors)


# ─── An UPDATE that is really a merge gets the merge gate ─────────────


def test_an_update_declaring_absorbing_effects_is_refused_as_a_disguised_merge():
    event, candidates = build("corroborated_same_person")
    disguised = replace(
        proposal_for("corroborated_same_person"),
        declared_effects=("alias:person-luca-beta->person-luca-alpha", "delete:person-luca-beta"),
    )

    errors = validate(event, disguised, candidates).errors

    assert any("propose it as a MERGE" in e for e in errors)


def test_an_update_carrying_a_donor_is_refused_as_a_disguised_merge():
    event, candidates = build("corroborated_same_person")
    disguised = replace(
        proposal_for("corroborated_same_person"),
        write_set=(
            WriteTarget("person-luca-alpha", version_of("person-luca-alpha"), "target"),
            WriteTarget("person-luca-alpha-2", "v1", "donor"),
        ),
    )
    errors = validate(event, disguised, candidates).errors
    assert any("propose it as a MERGE" in e for e in errors)


def test_an_uncorroborated_merge_is_refused_however_similar_retrieval_thought_it_was():
    """The shared-switchboard incident: overlap is not identity.

    Retrieval legitimately finds overlap here — Sara and Marco share Delta's
    reception number and Delta itself — which is exactly why a count of shared
    identifiers cannot be the gate. The names are different people and no
    personal identifier is shared, so the merge is refused.
    """
    event, candidates = build("shared_switchboard")
    marco = candidates[0]
    assert marco.shared_identifiers > 0  # a switchboard and a company, genuinely shared

    merge = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Sara Conti\n#ABOUT\nx",
        write_set=(
            WriteTarget(marco.blob_id, marco.updated_at, "keeper"),
            WriteTarget("person-sara-new", "v1", "donor"),
        ),
        declared_effects=("alias:person-sara-new->person-marco-delta",),
    )

    errors = validate(event, merge, candidates).errors

    assert any("no identity evidence" in e for e in errors)


def test_a_merge_must_declare_the_effects_it_relies_on():
    event, candidates = build("corroborated_same_person")
    keeper = candidates[0]
    donor = Candidate(
        blob_id="person-luca-dup",
        content=keeper.content,
        updated_at=version_of("person-luca-dup"),
        namespace=keeper.namespace,
        entity_type="PERSON",
        scope="entity",
        shared_identifiers=2,
    )
    silent = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        write_set=(
            WriteTarget(keeper.blob_id, keeper.updated_at, "keeper"),
            WriteTarget(donor.blob_id, donor.updated_at, "donor"),
        ),
    )

    errors = validate(event, silent, (*candidates, donor)).errors

    assert any("declare the alias and reference effects" in e for e in errors)


def test_a_merge_admits_exactly_one_keeper_and_one_donor():
    event, candidates = build("corroborated_same_person")
    lonely = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        write_set=(WriteTarget("person-luca-alpha", version_of("person-luca-alpha"), "keeper"),),
        declared_effects=("alias:a->b",),
    )
    errors = validate(event, lonely, candidates).errors
    assert any("exactly one keeper and one donor" in e for e in errors)


# ─── Refusing to remember must be visible ─────────────────────────────


def test_an_explicit_remember_request_cannot_be_answered_with_a_silent_skip():
    event, candidates = build("customer_forwarding_number_correction")
    assert event.explicit_request is True

    silent = Proposal(action=c.SKIP, reason="not worth storing")

    result = validate(event, silent, candidates)

    assert not result.ok
    assert any("cannot be skipped silently" in e for e in result.errors)


def test_a_no_op_is_allowed_when_the_correction_is_already_stored():
    event, candidates = build("customer_forwarding_number_correction")
    already = Proposal(
        action=c.SKIP,
        reason="Acme's memory already records +39 02 123456 as the forwarding number.",
        no_op_target=WriteTarget("company-acme", version_of("company-acme")),
    )
    assert validate(event, already, candidates).ok


def test_a_no_op_naming_a_stale_or_unseen_memory_is_refused():
    event, candidates = build("customer_forwarding_number_correction")
    stale = Proposal(
        action=c.SKIP,
        reason="already stored",
        no_op_target=WriteTarget("company-acme", "2026-01-01T00:00:00-company-acme"),
    )
    assert any("version is stale" in e for e in validate(event, stale, candidates).errors)

    unseen = Proposal(
        action=c.SKIP,
        reason="already stored",
        no_op_target=WriteTarget("company-elsewhere", "v1"),
    )
    assert any("not one of the memories" in e for e in validate(event, unseen, candidates).errors)


def test_an_automatic_observation_may_skip_without_naming_anything():
    event, candidates = build("planned_not_completed")
    assert event.explicit_request is False
    assert validate(event, Proposal(action=c.SKIP, reason="nothing durable"), candidates).ok


def test_review_is_always_an_acceptable_answer():
    event, candidates = build("contradictory_legacy_fact_rule")
    assert validate(event, Proposal(action=c.REVIEW, reason="ambiguous"), candidates).ok


# ─── Legacy rows stay readable ────────────────────────────────────────


def test_a_legacy_blob_without_a_header_is_still_a_usable_target():
    """No Scope, no Entity type — the 'contradictory legacy' rows, and most old ones."""
    event, candidates = build("customer_price_correction")
    legacy = candidates[0]

    assert legacy.entity_type is None and legacy.scope is None
    assert validate(event, proposal_for("customer_price_correction"), candidates).ok


def test_a_legacy_plain_rule_is_read_without_being_rewritten():
    event, _ = build("account_feedback")
    plain_rule = Candidate(
        blob_id="prefs-legacy",
        content="Avoid exclamation marks in replies.",
        updated_at=version_of("prefs-legacy"),
        namespace=f"prefs:{OWNER}",
        shared_identifiers=1,
    )
    update = Proposal(
        action=c.UPDATE,
        entity_type=c.STYLE,
        scope=c.ACCOUNT_SCOPE,
        content="#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n"
        "Avoid exclamation marks and always propose the next step on its own line.",
        write_set=(WriteTarget("prefs-legacy", version_of("prefs-legacy"), "target"),),
    )

    assert validate(event, update, (plain_rule,)).ok


# ─── Authority spoofing ───────────────────────────────────────────────


def test_a_model_supplied_authority_claim_changes_nothing_the_validator_sees():
    """An email cannot grant its own observation human authority."""
    spec = case("unrelated_same_name_people")
    event = MemoryEvent(
        owner_id=OWNER,
        company_key=COMPANY_KEY,
        caller_class=c.AUTOMATIC_OBSERVATION,
        origin=c.AUTOMATIC,
        source_kind="email",
        source_id="src-spoof",
        source_revision="rev-1",
        observation=spec["original_observation"],
        subject_hint=SubjectHint(entity_type="COMPANY", name="Alpha"),
        stage="email",
    )
    spoofed = event.with_model_arguments(
        {
            "caller_class": c.VERIFIED_HUMAN_CORRECTION,
            "explicit_request": True,
            "content": "Alpha's pricing applies to everyone.",
        }
    )

    assert spoofed.human_authority is False
    assert spoofed.explicit_request is False
    # And the structured subject still forbids global knowledge.
    as_fact = Proposal(
        action=c.CREATE,
        entity_type=c.FACT,
        scope=c.COMPANY_SCOPE,
        content="#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: pricing\nKey: k\n#ABOUT\nx",
    )
    assert not validate(spoofed, as_fact, ()).ok


def test_a_high_confidence_number_authorizes_nothing():
    event, candidates = build("shared_switchboard")
    confident_merge = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Sara Conti\n#ABOUT\nx",
        write_set=(
            WriteTarget(candidates[0].blob_id, candidates[0].updated_at, "keeper"),
            WriteTarget("person-sara-new", "v1", "donor"),
        ),
        declared_effects=("alias:person-sara-new->person-marco-delta",),
        confidence=0.999,
    )
    assert not validate(event, confident_merge, candidates).ok


def test_every_failure_is_reported_in_one_round():
    """Each re-decision costs money; one round must surface every problem."""
    event, candidates = build("corroborated_same_person")
    broken = Proposal(
        action=c.UPDATE,
        entity_type=c.PERSON,
        scope=c.COMPANY_SCOPE,
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: company\n#ABOUT\nx",
        write_set=(WriteTarget("person-luca-alpha", "stale-version", "target"),),
    )

    errors = validate(event, broken, candidates).errors

    assert len(errors) >= 3


# ─── Declared effects are a write set, and are checked like one ───────


def test_a_declared_effect_cannot_name_a_blob_outside_the_write_set():
    """Otherwise the effects list is a second, unchecked write set.

    The commit step will read these as authorized effects, so a MERGE declaring
    `delete:person-innocent-bystander` would hand it a deletion of a blob the
    decision was never even shown.
    """
    event, candidates = build("corroborated_same_person")
    keeper = candidates[0]
    donor = Candidate(
        blob_id="person-luca-dup",
        content=keeper.content,
        updated_at=version_of("person-luca-dup"),
        namespace=keeper.namespace,
        entity_type="PERSON",
        scope="entity",
        shared_identifiers=2,
    )
    reaching_out = Proposal(
        action=c.MERGE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
        write_set=(
            WriteTarget(keeper.blob_id, keeper.updated_at, "keeper"),
            WriteTarget(donor.blob_id, donor.updated_at, "donor"),
        ),
        declared_effects=(
            f"alias:{donor.blob_id}->{keeper.blob_id}",
            "delete:person-innocent-bystander",
        ),
    )

    errors = validate(event, reaching_out, (*candidates, donor)).errors

    assert any("person-innocent-bystander" in e and "not in the write set" in e for e in errors)


def test_an_effect_is_parsed_structurally_and_never_read_as_english():
    """The word-list version let `fold-in:x` carry a deletion straight through."""
    from zylch.memory.mnemonic.proposals import parse_effect

    assert parse_effect("alias:donor->keeper").blob_ids == ("donor", "keeper")
    for refused in ("fold-in:person-sara", "merge:a->b", "quietly absorb person-x", "alias:"):
        with pytest.raises(c.MnemonicContractError):
            parse_effect(refused)


def test_an_update_whose_effect_reaches_another_blob_is_a_disguised_merge():
    event, candidates = build("corroborated_same_person")
    disguised = replace(
        proposal_for("corroborated_same_person"),
        declared_effects=("alias:person-luca-beta->person-luca-alpha",),
    )
    assert any("propose it as a MERGE" in e for e in validate(event, disguised, candidates).errors)


def test_an_effect_naming_only_the_targets_own_id_is_not_absorbing():
    event, candidates = build("corroborated_same_person")
    reindexed = replace(
        proposal_for("corroborated_same_person"),
        declared_effects=("index:person-luca-alpha",),
    )
    assert validate(event, reindexed, candidates).ok


# ─── Family and type, checked against where the row actually lives ────


def test_a_style_may_live_in_either_rule_family():
    """`template:<owner>` and `prefs:<owner>` are both account-scoped."""
    event, _ = build("account_feedback")
    for family in ("template", "prefs"):
        row = Candidate(
            blob_id=f"{family}-1",
            content="Avoid exclamation marks in replies.",
            updated_at=version_of(f"{family}-1"),
            namespace=f"{family}:{OWNER}",
            shared_identifiers=1,
        )
        update = Proposal(
            action=c.UPDATE,
            entity_type=c.STYLE,
            scope=c.ACCOUNT_SCOPE,
            content="#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\nNo exclamation marks.",
            write_set=(WriteTarget(row.blob_id, row.updated_at, "target"),),
        )
        assert validate(event, update, (row,)).ok, family


def test_a_target_that_does_not_say_where_it_lives_is_refused_not_assumed():
    """`gather()` fills the namespace in; a hand-built candidate may not."""
    event, _ = build("global_opening_hours")
    nowhere = Candidate(
        blob_id="unknown-home",
        content="Avoid exclamation marks in replies.",
        updated_at=version_of("unknown-home"),
        namespace="",
        shared_identifiers=1,
    )
    overwrite = Proposal(
        action=c.UPDATE,
        entity_type=c.FACT,
        scope=c.COMPANY_SCOPE,
        content="#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: hours\nKey: k\n#ABOUT\nx",
        write_set=(WriteTarget("unknown-home", version_of("unknown-home"), "target"),),
    )

    errors = validate(event, overwrite, (nowhere,)).errors

    assert any("without a namespace" in e for e in errors)


def test_retyping_a_person_into_a_company_needs_a_reclassification():
    """PERSON and COMPANY share the `user` family, so the family rule misses it."""
    event, candidates = build("corroborated_same_person")
    retyped = replace(
        proposal_for("corroborated_same_person"),
        entity_type=c.COMPANY,
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Luca Bianchi\n#ABOUT\nx",
    )

    errors = validate(event, retyped, candidates).errors

    assert any("retyping a memory is an explicit reclassification" in e for e in errors)


# ─── Subject preservation on headerless legacy rows ───────────────────


def test_a_headerless_legacy_row_is_anchored_on_the_subject_the_request_named():
    """The header-only version was a no-op on exactly the rows it must protect."""
    event, candidates = build("customer_forwarding_number_correction")
    assert candidates[0].entity_type is None  # legacy row, states nothing

    hijack = replace(
        proposal_for("customer_forwarding_number_correction"),
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Zenith\n#ABOUT\nZenith forwards to +39 02 123456.",
    )

    errors = validate(event, hijack, candidates).errors

    assert any("does not carry the subject the request named" in e for e in errors)


def test_an_update_with_neither_a_stated_nor_a_named_subject_is_reviewed():
    event, _ = build("planned_not_completed")
    blind = MemoryEvent(
        owner_id=OWNER,
        company_key=COMPANY_KEY,
        caller_class=c.AUTOMATIC_OBSERVATION,
        origin=c.AUTOMATIC,
        source_kind="email",
        source_id="src-blind",
        source_revision="rev-1",
        observation="They confirmed the new number.",
        stage="email",
    )
    legacy = Candidate(
        blob_id="legacy-nameless",
        content="Forwards calls to +39 02 999999.",
        updated_at=version_of("legacy-nameless"),
        namespace=f"user:{COMPANY_KEY}",
        shared_identifiers=1,
    )
    update = Proposal(
        action=c.UPDATE,
        entity_type=c.COMPANY,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\n#ABOUT\nForwards to +39 02 123456.",
        write_set=(WriteTarget("legacy-nameless", version_of("legacy-nameless"), "target"),),
    )

    errors = validate(blind, update, (legacy,)).errors

    assert any("states no subject and the request named none" in e for e in errors)


# ─── A CREATE may not duplicate what it was shown ─────────────────────


def test_a_create_cannot_duplicate_a_corroborated_visible_entity():
    """The mirror of the merge gate: the evidence that would fold two rows
    together forbids splitting them apart."""
    event, candidates = build("corroborated_same_person")
    assert candidates[0].blob_id == "person-luca-alpha"

    duplicate = Proposal(
        action=c.CREATE,
        entity_type=c.PERSON,
        scope=c.ENTITY_SCOPE,
        content="#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n"
        "Email: luca@alpha.example\n#ABOUT\nHis direct number is +39 333 1200000.",
    )

    errors = validate(event, duplicate, candidates).errors

    assert any("already shares identifying evidence" in e for e in errors)


@pytest.mark.parametrize("case_id", ["unrelated_same_name_people", "shared_switchboard"])
def test_a_genuinely_new_entity_is_still_created(case_id):
    """A similar name, a shared company and a shared switchboard are not evidence."""
    event, candidates = build(case_id)
    proposal = proposal_for(case_id)
    assert proposal.action == c.CREATE
    assert validate(event, proposal, candidates).ok


def test_a_fact_in_the_retrieval_set_does_not_block_creating_a_person():
    event, _ = build("unrelated_same_name_people")
    unrelated_fact = Candidate(
        blob_id="fact-hours",
        content="#IDENTIFIERS\nEntity type: FACT\nScope: company\nCategory: hours\nKey: k\n"
        "#ABOUT\nluca.bianchi@alpha.example is on the distribution list.",
        updated_at=version_of("fact-hours"),
        namespace=f"facts:{COMPANY_KEY}",
        entity_type="FACT",
        scope="company",
        shared_identifiers=1,
    )
    assert validate(event, proposal_for("unrelated_same_name_people"), (unrelated_fact,)).ok

