"""What the mnemonic role answers with, and what the caller finally gets.

The input side — the event, its authority and the bounded retrieval set — is
:mod:`zylch.memory.mnemonic.contracts`; the shared vocabularies and bounds live
there too and are imported here rather than restated.

Two rules shape this half. A proposal is a **control envelope, not an
ontology**: it fixes the action, the family, the targets and the versions, and
leaves the memory's prose entirely to the role. And there is **one result with
four outcomes** — ``committed``, ``skipped``, ``review_needed``,
``retryable_failure`` — with non-semantic follow-up work listed as a
:class:`PendingEffect` rather than demoting a real commit to a failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .contracts import (
    COMMITTED,
    ENTITY_TYPES,
    MAX_CANDIDATES,
    MAX_CONTENT_CHARS,
    MAX_DECLARED_EFFECTS,
    MAX_REASON_CHARS,
    MAX_WRITE_SET,
    MUTATING_ACTIONS,
    OUTCOMES,
    REQUIRED_FAMILY,
    RETRYABLE_FAILURE,
    REVIEW,
    REVIEW_NEEDED,
    SCOPES,
    SKIPPED,
    ACTIONS,
    MnemonicContractError,
    _choice,
    _text,
)


@dataclass(frozen=True)
class WriteTarget:
    """One blob a proposal declares it will touch, with the version it read."""

    blob_id: str
    expected_version: str
    role: str = "target"  # target | keeper | donor

    def __post_init__(self) -> None:
        _choice(self.role, ("target", "keeper", "donor"), "write target role")
        object.__setattr__(self, "blob_id", _text(self.blob_id, limit=200, what="write target id"))
        object.__setattr__(
            self,
            "expected_version",
            _text(self.expected_version, limit=200, what="write target expected_version"),
        )


# A declared effect has a fixed shape — ``<verb>:<blob_id>`` or
# ``<verb>:<blob_id>-><blob_id>`` — so the validator can check WHICH blobs an
# effect touches without reading English. The earlier version matched words
# like "merge" and "delete" inside a free string, which is precisely the
# substring classification this harness exists to remove: "fold-in:x" carried
# a deletion past it, and a typo'd verb would have carried anything.
_EFFECT = re.compile(
    r"^(?P<verb>[a-z_]{2,20}):(?P<first>[A-Za-z0-9._:-]{1,200})"
    r"(?:->(?P<second>[A-Za-z0-9._:-]{1,200}))?$"
)

# Closed set. An unrecognized verb is refused, not guessed at.
EFFECT_VERBS: Tuple[str, ...] = ("alias", "reference", "index", "delete")


@dataclass(frozen=True)
class DeclaredEffect:
    """One structural side effect a proposal takes responsibility for."""

    verb: str
    blob_ids: Tuple[str, ...]
    text: str = ""

    @property
    def absorbing(self) -> bool:
        """Does this effect fold one memory into another, or remove one?"""
        return self.verb in ("alias", "delete")


def parse_effect(text: str) -> DeclaredEffect:
    """``"alias:donor->keeper"`` → verb and the blob ids it names.

    Shape only. What an ``alias`` means is the commit step's business; all this
    decides is which blobs the proposal has declared it will touch, so the
    validator can refuse one that reaches outside its write set.
    """
    match = _EFFECT.match((text or "").strip())
    if not match:
        raise MnemonicContractError(
            f"declared effect {text!r} is not <verb>:<blob_id>[-><blob_id>]"
        )
    verb = match.group("verb")
    if verb not in EFFECT_VERBS:
        raise MnemonicContractError(
            f"unknown declared effect verb {verb!r}; known: {', '.join(EFFECT_VERBS)}"
        )
    ids = [match.group("first")]
    if match.group("second"):
        ids.append(match.group("second"))
    return DeclaredEffect(verb=verb, blob_ids=tuple(ids), text=text.strip())


@dataclass(frozen=True)
class Reclassification:
    """Moving a memory between families, stated outright.

    Never inferred from an UPDATE's prose: a proposal that changes a blob's
    family without this attribute is refused, not interpreted.
    """

    from_entity_type: str
    from_scope: str
    to_entity_type: str
    to_scope: str

    def __post_init__(self) -> None:
        _choice(self.from_entity_type, ENTITY_TYPES, "reclassification from_entity_type")
        _choice(self.to_entity_type, ENTITY_TYPES, "reclassification to_entity_type")
        _choice(self.from_scope, SCOPES, "reclassification from_scope")
        _choice(self.to_scope, SCOPES, "reclassification to_scope")


@dataclass(frozen=True)
class Proposal:
    """The mnemonic role's complete structured answer.

    A control envelope, not an ontology: ``content`` is free narrative prose
    under the minimal header. ``confidence`` is diagnostic output and is never
    a threshold that substitutes for identity evidence.

    ``ineligible`` is a REVIEW's own field: the candidates the role declined to
    treat as company knowledge — a FACT row that is really about one customer.
    It is not a write set (nothing is written) and it never rides a mutating
    proposal; the harness records a read restriction against each named row
    that was actually among the candidates shown. Bounded here like the write
    set, so a model that names a thousand ids has produced no proposal at all.
    """

    action: str
    entity_type: Optional[str] = None
    scope: Optional[str] = None
    content: str = ""
    write_set: Tuple[WriteTarget, ...] = ()
    reason: str = ""
    reclassification: Optional[Reclassification] = None
    declared_effects: Tuple[str, ...] = ()
    no_op_target: Optional[WriteTarget] = None
    confidence: Optional[float] = None
    ineligible: Tuple[str, ...] = ()
    effects: Tuple[DeclaredEffect, ...] = field(default=(), init=False, compare=False)

    def __post_init__(self) -> None:
        _choice(self.action, ACTIONS, "action")
        if self.entity_type is not None:
            _choice(self.entity_type, ENTITY_TYPES, "entity_type")
        if self.scope is not None:
            _choice(self.scope, SCOPES, "scope")
        object.__setattr__(
            self,
            "content",
            _text(self.content, limit=MAX_CONTENT_CHARS, what="content", required=False),
        )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, limit=MAX_REASON_CHARS, what="reason", required=False),
        )
        object.__setattr__(self, "write_set", tuple(self.write_set))
        object.__setattr__(self, "declared_effects", tuple(self.declared_effects))
        object.__setattr__(
            self,
            "ineligible",
            tuple(_text(bid, limit=200, what="ineligible blob id") for bid in self.ineligible),
        )
        if len(self.write_set) > MAX_WRITE_SET:
            raise MnemonicContractError(
                f"write set holds {len(self.write_set)} targets; the bound is {MAX_WRITE_SET}"
            )
        if len(self.declared_effects) > MAX_DECLARED_EFFECTS:
            raise MnemonicContractError("proposal declares too many effects")
        ids = [target.blob_id for target in self.write_set]
        if len(set(ids)) != len(ids):
            raise MnemonicContractError("write set names the same blob twice")
        if len(self.ineligible) > MAX_CANDIDATES:
            raise MnemonicContractError(
                f"a review names {len(self.ineligible)} ineligible memories; "
                f"it was shown at most {MAX_CANDIDATES}"
            )
        if len(set(self.ineligible)) != len(self.ineligible):
            raise MnemonicContractError("a review names the same ineligible memory twice")
        if self.ineligible and self.action != REVIEW:
            raise MnemonicContractError("only a REVIEW may name ineligible memories")
        # Parsed at construction so a malformed effect is no proposal at all,
        # the same way a malformed write target is.
        object.__setattr__(self, "effects", tuple(parse_effect(e) for e in self.declared_effects))

    @property
    def mutates(self) -> bool:
        return self.action in MUTATING_ACTIONS

    @property
    def effect_blob_ids(self) -> frozenset:
        """Every blob any declared effect names."""
        return frozenset(bid for effect in self.effects for bid in effect.blob_ids)

    @property
    def absorbs_another_memory(self) -> bool:
        """Does this proposal fold in, or remove, a blob other than its target?

        Structural, not lexical: an effect is absorbing when its verb says so
        AND it names a blob the proposal does not hold as its single target.
        That is what turns an UPDATE into a merge under another name, and it is
        decided from ids, never from the wording of the effect.
        """
        held = {t.blob_id for t in self.write_set if t.role in ("target", "keeper")}
        return any(
            effect.absorbing and not set(effect.blob_ids).issubset(held) for effect in self.effects
        )

    @property
    def target(self) -> Optional[WriteTarget]:
        for entry in self.write_set:
            if entry.role in ("target", "keeper"):
                return entry
        return None

    @property
    def keeper(self) -> Optional[WriteTarget]:
        return next((t for t in self.write_set if t.role == "keeper"), None)

    @property
    def donor(self) -> Optional[WriteTarget]:
        return next((t for t in self.write_set if t.role == "donor"), None)

    @property
    def family(self) -> Optional[str]:
        return REQUIRED_FAMILY.get(self.entity_type) if self.entity_type else None


# ─── Result ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PendingEffect:
    """Non-semantic follow-up work owed after a real commit.

    Profile task-reference replay and index reconciliation are idempotent
    maintenance, not part of the meaning that was committed. Listing them here
    is what keeps an after-commit failure from being reported as
    ``retryable_failure``, which would say no commit occurred.
    """

    kind: str
    detail: str = ""


@dataclass(frozen=True)
class MnemonicResult:
    """The one authoritative answer to a submitted event."""

    outcome: str
    event_id: str
    reason: str = ""
    proposal: Optional[Proposal] = None
    committed_ids: Tuple[Tuple[str, str], ...] = ()
    pending_effects: Tuple[PendingEffect, ...] = ()
    attempts: int = 0
    # How a committed proposal departed from what the caller asked for, or
    # None. Diagnostics the journal row and the tool response both carry; it
    # gates nothing (see mnemonic/approval.py).
    departure: Optional[Dict[str, Any]] = None
    # The refusal a paid dispatch met before it reached a provider — the
    # ``BudgetError`` the decision round caught, or its ``PreparationStopped``
    # subclass for a pause — carried as the object itself so a caller that owes
    # its own caller that class (the ingestion loop, whose batch stops on it)
    # can re-raise it rather than a flattened copy. Never serialized: the
    # journal keeps the reason, the result keeps the exception.
    refusal: Optional[BaseException] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        _choice(self.outcome, OUTCOMES, "outcome")
        object.__setattr__(self, "committed_ids", tuple(self.committed_ids))
        object.__setattr__(self, "pending_effects", tuple(self.pending_effects))
        if self.outcome == COMMITTED and not self.committed_ids:
            raise MnemonicContractError("a committed result must name what it committed")
        if self.outcome != COMMITTED and self.committed_ids:
            raise MnemonicContractError(f"a {self.outcome} result cannot name committed ids")
        if self.outcome != COMMITTED and not self.reason:
            raise MnemonicContractError(f"a {self.outcome} result must carry a reason")
        if self.refusal is not None and self.outcome != RETRYABLE_FAILURE:
            raise MnemonicContractError("only a retryable failure carries a dispatch refusal")

    @classmethod
    def committed(
        cls, event_id, ids, *, proposal=None, pending=(), attempts=0, departure=None
    ) -> "MnemonicResult":
        return cls(
            outcome=COMMITTED,
            event_id=event_id,
            proposal=proposal,
            committed_ids=tuple(ids),
            pending_effects=tuple(pending),
            attempts=attempts,
            departure=departure,
        )

    @classmethod
    def skipped(cls, event_id, reason, *, proposal=None, attempts=0) -> "MnemonicResult":
        return cls(
            outcome=SKIPPED,
            event_id=event_id,
            reason=reason,
            proposal=proposal,
            attempts=attempts,
        )

    @classmethod
    def review_needed(cls, event_id, reason, *, proposal=None, attempts=0) -> "MnemonicResult":
        return cls(
            outcome=REVIEW_NEEDED,
            event_id=event_id,
            reason=reason,
            proposal=proposal,
            attempts=attempts,
        )

    @classmethod
    def retryable_failure(
        cls, event_id, reason, *, proposal=None, attempts=0, refusal=None
    ) -> "MnemonicResult":
        return cls(
            outcome=RETRYABLE_FAILURE,
            event_id=event_id,
            reason=reason,
            proposal=proposal,
            attempts=attempts,
            refusal=refusal,
        )

    @property
    def mutated(self) -> bool:
        return self.outcome == COMMITTED

    @property
    def advances_checkpoint(self) -> bool:
        """Automatic workers advance their processed checkpoint only here.

        ``review_needed`` stays visible and ``retryable_failure`` keeps the
        existing retry behavior; neither may be mistaken for done.
        """
        return self.outcome in (COMMITTED, SKIPPED)
