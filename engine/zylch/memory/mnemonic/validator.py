"""The deliberately small symbolic validator.

It enforces only rules that are stable, cheap and valuable — the ones a regex
can hold honestly. It does not decide whether Acme prefers short emails,
whether a conversation implies a changed relationship, or how two nuanced
histories reconcile. Those are the mnemonic role's judgments, measured by
semantic evaluations, not by string matching.

The line it does hold: when the *caller* supplied a structured entity subject,
forbidding a company FACT is mechanical and worth enforcing. When the subject
lives only in unbound prose, classification stays the role's job. Repeating the
semantic decision here as a heuristic would recreate exactly the substring
classifier the harness exists to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from zylch.memory.company_key import RULE_FAMILIES

from .candidates import parse_header
from .evidence import corroborates, duplicate_candidates
from .contracts import (
    ACCOUNT_SCOPE,
    AUTOMATIC_OBSERVATION,
    COMPANY,
    COMPANY_SCOPE,
    CREATE,
    FACT,
    MAX_CONTENT_CHARS,
    MERGE,
    PERSON,
    REQUIRED_FAMILY,
    REQUIRED_SCOPE,
    REVIEW,
    SKIP,
    STYLE,
    UPDATE,
    Candidate,
    MemoryEvent,
)
from .proposals import Proposal

# Types a legacy blob may carry that this harness will not silently keep
# writing to. Touching one is a review, not an update.
_UNSUPPORTED_LEGACY_TYPES = ("PROJECT", "TASK", "NOTE", "EVENT")

ACCEPT = "accept"
REJECT = "reject"


@dataclass(frozen=True)
class Validation:
    """Accept, or reject with every reason at once.

    Every failure is collected rather than short-circuiting: a rejected
    proposal that is re-decided should learn about all of its problems in one
    round, because each round costs money.
    """

    result: str
    errors: Tuple[str, ...] = ()
    needs_review: bool = True

    @property
    def ok(self) -> bool:
        return self.result == ACCEPT


@dataclass
class _Check:
    event: MemoryEvent
    proposal: Proposal
    by_id: Dict[str, Candidate]
    errors: List[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.errors.append(message)


def validate(
    event: MemoryEvent,
    proposal: Proposal,
    candidates: Sequence[Candidate],
) -> Validation:
    """Judge one proposal against the event and the bounded candidate set."""
    check = _Check(event=event, proposal=proposal, by_id={c.blob_id: c for c in candidates})

    _check_refusals(check)
    _check_ineligible(check)
    if proposal.mutates:
        _check_family_and_scope(check)
        _check_caller_subject(check)
        _check_automatic_rule(check)
        _check_content(check)
        _check_write_set(check)
        _check_declared_effects(check)
        _check_reclassification(check)
        _check_targets(check)

    if check.errors:
        return Validation(result=REJECT, errors=tuple(check.errors), needs_review=True)
    return Validation(result=ACCEPT, needs_review=False)


# ─── Refusal must be visible ──────────────────────────────────────────


def _check_refusals(check: _Check) -> None:
    """An explicit "remember this" may not be answered with a silent SKIP.

    A semantic no-op is a legitimate answer — the correction is already stored —
    and the proposal proves it by naming the memory that already holds it, with
    the exact id and version it was shown. Without that, SKIP is a hidden
    refusal of a human instruction and becomes REVIEW.
    """
    proposal, event = check.proposal, check.event
    if proposal.action != SKIP:
        return
    if not (event.explicit_request or event.human_authority):
        return
    target = proposal.no_op_target
    if target is None:
        check.fail(
            "an explicit remember/correct request cannot be skipped silently; "
            "name the memory that already holds it, or return REVIEW with a reason"
        )
        return
    existing = check.by_id.get(target.blob_id)
    if existing is None:
        check.fail("the no-op target is not one of the memories this decision was shown")
    elif existing.updated_at != target.expected_version:
        check.fail("the no-op target's version is stale; re-read it before claiming a no-op")
    if not proposal.reason:
        check.fail("a semantic no-op must say why the information is already recorded")


def _check_ineligible(check: _Check) -> None:
    """A review may mark as ineligible only memories it was actually shown.

    ``ineligible`` is the one field a REVIEW carries that has an effect — the
    harness records a read restriction against each row it names — so it is
    checked like a write set: an id the role was not shown is refused, not
    recorded. The contract already bounds the list and keeps it off mutating
    proposals; this is the check that needs the candidate set.
    """
    proposal = check.proposal
    if proposal.action != REVIEW or not proposal.ineligible:
        return
    for blob_id in proposal.ineligible:
        if blob_id not in check.by_id:
            check.fail(
                f"{blob_id} is not one of the memories this decision was shown; a review may "
                "mark as ineligible only what it was shown"
            )


# ─── Family, scope, header and namespace must agree ───────────────────


def _check_family_and_scope(check: _Check) -> None:
    proposal = check.proposal
    if not proposal.entity_type:
        check.fail("a mutating proposal must state its entity type")
        return
    if not proposal.scope:
        check.fail("a mutating proposal must state its scope")
        return
    required = REQUIRED_SCOPE[proposal.entity_type]
    if proposal.scope != required:
        check.fail(f"{proposal.entity_type} requires scope {required!r}, got {proposal.scope!r}")

    header = parse_header(proposal.content)
    declared = (header.get("entity type") or "").strip().upper()
    if declared and declared != proposal.entity_type:
        check.fail(
            f"the memory header says {declared!r} but the envelope says {proposal.entity_type!r}"
        )
    header_scope = (header.get("scope") or "").strip().lower()
    if header_scope and header_scope != proposal.scope:
        check.fail(
            f"the memory header scope {header_scope!r} contradicts the envelope {proposal.scope!r}"
        )

    for target in proposal.write_set:
        candidate = check.by_id.get(target.blob_id)
        if candidate is None:
            continue  # _check_targets already refuses a target nobody was shown
        _check_target_family(check, target, candidate)
        _check_target_type(check, target, candidate)


def _check_target_family(check: _Check, target, candidate: Candidate) -> None:
    """The family a target actually lives in must be one this proposal may write.

    A rule may live in either rule family — `template:<owner>` and
    `prefs:<owner>` are both account-scoped — so STYLE is checked against both.
    An empty namespace is refused rather than skipped: it means the caller did
    not say where the row lives, and defaulting that to "fine" would let a FACT
    overwrite an account rule the moment an adapter builds a candidate by hand.
    """
    proposal = check.proposal
    if not candidate.namespace:
        check.fail(
            f"target {target.blob_id} arrived without a namespace, so the family it lives in "
            "cannot be checked; refusing rather than assuming"
        )
        return
    family = candidate.namespace.split(":", 1)[0].strip().lower()
    allowed = (
        RULE_FAMILIES if proposal.entity_type == STYLE else (REQUIRED_FAMILY[proposal.entity_type],)
    )
    if family in allowed:
        return
    if proposal.entity_type == STYLE:
        check.fail("an account rule cannot target a company memory namespace")
    elif family in RULE_FAMILIES:
        check.fail("an entity or fact cannot be written into a rule namespace")
    elif proposal.reclassification is None:
        check.fail(
            f"target {target.blob_id} lives in the {family!r} family but the proposal is "
            f"{proposal.entity_type}; moving a memory between families is an explicit "
            "reclassification, never an UPDATE side effect"
        )


def _check_target_type(check: _Check, target, candidate: Candidate) -> None:
    """Retyping a memory is a reclassification even inside one family.

    PERSON and COMPANY share the `user` family, so the family rule alone lets
    an UPDATE quietly turn a person into a company. A blob that states its own
    type may only change it when the proposal says so outright.
    """
    stated = (candidate.entity_type or "").strip().upper()
    if not stated or stated == check.proposal.entity_type:
        return  # a legacy row without a header states nothing, and stays readable
    if check.proposal.reclassification is None:
        check.fail(
            f"target {target.blob_id} states it is {stated} but the proposal writes it as "
            f"{check.proposal.entity_type}; retyping a memory is an explicit reclassification"
        )


def _check_caller_subject(check: _Check) -> None:
    """A caller-resolved entity subject cannot become global knowledge.

    This is the one classification rule the validator owns outright, because
    the *caller* already did the resolving: the adapter handed in a structured
    person or company. Turning that into a company FACT is how a customer's
    price became everyone's price.
    """
    hint = check.event.subject_hint
    if hint is None or not hint.names_entity_subject:
        return
    if check.proposal.entity_type == FACT or check.proposal.scope == COMPANY_SCOPE:
        check.fail(
            "this observation carries a structured entity subject, so it cannot be committed "
            "as company-wide knowledge; put it in that entity's memory"
        )


def _check_automatic_rule(check: _Check) -> None:
    """An automatic observation cannot write an account rule.

    A STYLE rule is one account's own instruction about how its replies are
    written, and ``REQUIRED_FAMILY[STYLE]`` files it in the rule namespace
    every prompt injects verbatim. A channel message — a mail, a WhatsApp
    message, a call — is an observation about somebody else, and behavioural
    detail in it belongs to that person's or company's memory. Without this
    line an extraction typed STYLE would become an operating rule of the
    account that merely received the message: the runaway class the rule store
    exists to keep out. The role's prompt says the same; this is the structural
    backstop, and a proposal that insists lands the event in review.
    """
    if check.event.caller_class != AUTOMATIC_OBSERVATION:
        return
    if check.proposal.entity_type == STYLE:
        check.fail(
            "an automatic observation cannot write an account rule; behavioural detail in a "
            "channel message belongs to that person's or company's memory, or is skipped"
        )


def _check_content(check: _Check) -> None:
    proposal = check.proposal
    if not proposal.content:
        check.fail(f"{proposal.action} requires the complete resulting memory text")
        return
    if len(proposal.content) > MAX_CONTENT_CHARS:
        check.fail("the proposed memory exceeds the size bound")
    if proposal.scope == ACCOUNT_SCOPE and proposal.entity_type != STYLE:
        check.fail("only an account STYLE rule may take account scope")


# ─── Write set, targets and versions ──────────────────────────────────


def _check_write_set(check: _Check) -> None:
    proposal = check.proposal
    if proposal.action == CREATE:
        if proposal.write_set:
            check.fail("a CREATE declares no existing write target")
        _check_duplicate_create(check)
        return

    if proposal.action == UPDATE:
        # Checked before the arity rule so a disguised merge is told what it
        # actually is, rather than being refused for having two targets.
        if proposal.donor is not None or proposal.absorbs_another_memory:
            check.fail(
                "this UPDATE folds another memory in; propose it as a MERGE so the identity "
                "evidence is actually checked"
            )
            return
        if len(proposal.write_set) != 1 or proposal.target is None:
            check.fail("an UPDATE declares exactly one existing target with its exact version")
        return

    if proposal.action == MERGE:
        keeper, donor = proposal.keeper, proposal.donor
        if keeper is None or donor is None or len(proposal.write_set) != 2:
            check.fail("a MERGE declares exactly one keeper and one donor, with exact versions")
            return
        if not proposal.declared_effects:
            check.fail("a MERGE must declare the alias and reference effects it relies on")
        for role, target in (("keeper", keeper), ("donor", donor)):
            candidate = check.by_id.get(target.blob_id)
            if candidate is not None and not corroborates(check.event, candidate, proposal.entity_type):
                check.fail(
                    f"the {role} carries no identity evidence tying it to this observation; "
                    "similarity, a shared company or a shared switchboard cannot authorize a merge"
                )


def _check_duplicate_create(check: _Check) -> None:
    """A CREATE may not duplicate an entity it was just shown corroborated.

    The evidence rule itself — what counts as identity for a person and for a
    company — lives in :mod:`zylch.memory.mnemonic.evidence`; this is the
    check that applies it to a CREATE, the mirror of the merge gate.
    """
    for candidate in duplicate_candidates(check.event, check.proposal, check.by_id.values()):
        check.fail(
            f"{candidate.blob_id} already shares identifying evidence with this "
            "observation; update it or return REVIEW rather than creating a second "
            "memory for the same subject"
        )


def _check_declared_effects(check: _Check) -> None:
    """A declared effect may name only blobs the proposal already holds.

    Without this the effects list is a second, unchecked write set: a MERGE
    could declare ``delete:some-innocent-blob`` and the commit step would read
    that as authorized. The check is on ids, so it needs no opinion about what
    the effect means.
    """
    proposal = check.proposal
    declared = {target.blob_id for target in proposal.write_set}
    for effect in proposal.effects:
        outside = set(effect.blob_ids) - declared
        if outside:
            check.fail(
                f"declared effect {effect.text!r} names "
                f"{', '.join(sorted(outside))}, which is not in the write set; "
                "a proposal may touch only what it declares"
            )
    if proposal.effects and not proposal.write_set:
        check.fail("a proposal declaring effects must declare the write set they act on")


def _check_targets(check: _Check) -> None:
    """Every declared target must be visible, exact and currently versioned."""
    proposal = check.proposal
    for target in proposal.write_set:
        candidate = check.by_id.get(target.blob_id)
        if candidate is None:
            check.fail(
                f"{target.blob_id} is not one of the memories this decision was shown; "
                "a proposal may touch only its declared, visible write set"
            )
            continue
        if not target.expected_version:
            check.fail(f"{target.blob_id} was declared without the version it was read at")
        elif candidate.updated_at != target.expected_version:
            check.fail(
                f"{target.blob_id} changed since it was read "
                f"(read {target.expected_version!r}, now {candidate.updated_at!r})"
            )
        _check_legacy_type(check, candidate)
        _check_subject_preserved(check, candidate)


def _check_legacy_type(check: _Check, candidate: Candidate) -> None:
    declared = (candidate.entity_type or "").strip().upper()
    if declared and declared in _UNSUPPORTED_LEGACY_TYPES:
        check.fail(
            f"{candidate.blob_id} carries the unsupported type {declared!r}; touching it needs "
            "review, not a silent retype"
        )


def _check_subject_preserved(check: _Check, candidate: Candidate) -> None:
    """An UPDATE keeps the subject it started from.

    Mechanical and narrow: a structured subject the *inputs* already state must
    still be present in the proposed text. It says nothing about whether the
    prose is right — only that the memory still belongs to the same subject,
    which is what stops an UPDATE from quietly becoming a different entity.

    Anchored first on the target's own header, and — when the target is a
    legacy row that states nothing — on the caller's structured hint. Without
    that fallback the check was a no-op on exactly the headerless rows it
    exists to protect: an old blob could be replaced wholesale by a different
    subject and nothing would notice. If neither anchor exists, there is
    nothing to check the update against and it is refused rather than waved
    through; a rule has no entity subject and is exempt.
    """
    proposal = check.proposal
    if proposal.action != UPDATE or proposal.entity_type == STYLE:
        return
    body = proposal.content.lower()
    header = parse_header(candidate.content)
    anchors = [(key, (header.get(key) or "").strip()) for key in ("name", "key")]
    anchors = [(key, value) for key, value in anchors if value]
    if anchors:
        for key, stated in anchors:
            if stated.lower() not in body:
                check.fail(
                    f"the update drops {candidate.blob_id}'s stated {key} {stated!r}; an UPDATE "
                    "may only modify the same subject"
                )
        return

    hint = check.event.subject_hint
    hinted = [value for value in ((hint.name, hint.company) if hint else ()) if value]
    if not hinted:
        check.fail(
            f"{candidate.blob_id} states no subject and the request named none, so this update "
            "cannot be shown to stay on the same subject; it needs review"
        )
        return
    if not any(value.lower() in body for value in hinted):
        check.fail(
            f"the update to {candidate.blob_id} does not carry the subject the request named "
            f"({', '.join(hinted)}); an UPDATE may only modify the same subject"
        )


def _check_reclassification(check: _Check) -> None:
    """A stated reclassification must match the envelope it claims to produce."""
    move = check.proposal.reclassification
    if move is None:
        return
    proposal = check.proposal
    if move.to_entity_type != proposal.entity_type or move.to_scope != proposal.scope:
        check.fail("the reclassification's destination contradicts the proposal's own envelope")
    if move.from_entity_type == move.to_entity_type and move.from_scope == move.to_scope:
        check.fail("a reclassification that changes nothing is not a reclassification")
    if proposal.action not in (UPDATE, MERGE):
        check.fail("only an UPDATE or MERGE of an existing memory can reclassify it")
    target = proposal.target
    candidate = check.by_id.get(target.blob_id) if target else None
    if candidate is not None and candidate.entity_type:
        if candidate.entity_type.strip().upper() != move.from_entity_type:
            check.fail("the reclassification's origin does not match the memory it would move")


def review_reason(validation: Validation) -> str:
    """One readable line for a refusal, kept short enough to show a human."""
    return "; ".join(validation.errors) or "the proposal could not be validated"
