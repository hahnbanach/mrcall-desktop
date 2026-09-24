"""Consolidation pairs: two memories the store paired, decided as one event.

Consolidation finds memories that may be the same subject — they share an
identity-index row or a stated name — and asks the mnemonic role about them one
pair at a time. A pair is an ordinary automatic event: the role proposes, the
validator checks, ``commit.py`` writes. What this module adds is what makes the
event a *pair*:

- **the event** (:func:`pair_event`): automatic, stage ``memory:consolidate``,
  source kind ``consolidation``, the two ids sorted as its source, a digest of
  both versions as its revision, and a hint stating only what both members'
  own ``#IDENTIFIERS`` headers assert in common (:func:`common_hint`) — never an
  index row, never prose, so the identity evidence is the same whichever member
  the role makes the keeper;
- **the comparison set** (:func:`pair_context`): the two blobs, pinned at the
  versions they were paired at, re-read on every round and nothing else shown;
  a member that changed or vanished ends the event (:func:`intact`);
- **the checks that need no model**: :func:`has_evidence` applies the
  validator's own identity rule before a pair is admitted, and :func:`settled`
  finds a pair this store already answered, by any account sharing it;
- **the only door a MERGE is committed through** (:func:`admits_merge`): a
  consolidation pair, the very pair its source names, inside the admitted
  consolidation item for that pair;
- **admission** (:class:`PairItem`): each pair is one bounded preparation item,
  so its paid decision faces the pause, busy, backoff and batch checks, and
  outside an admitted item nothing is submitted at all.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Tuple

from zylch.services.preparation import bounded_item, current_item

from . import journal
from .candidates import lid_token, parse_header
from .contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    COMPANY,
    MERGE,
    PERSON,
    RETRYABLE_FAILURE,
    Cancellation,
    Candidate,
    MemoryEvent,
    MnemonicContractError,
    SubjectHint,
)
from .evidence import corroborates
from .turn import turn_cancellation
from .wiring import CommitContext, parse_identifiers_block

logger = logging.getLogger(__name__)

PAIR_SOURCE_KIND = "consolidation"
CONSOLIDATE_STAGE = "memory:consolidate"

OBSERVATION = (
    "Consolidation pair in this company's memory: {first} and {second} were paired "
    "because they share an identifier or a stated name. Both are shown as "
    "candidates, at the versions they were paired at."
)
MERGE_OUTSIDE_CONSOLIDATION = (
    "a merge drops a memory, and only consolidation drops one; "
    "the proposal is recorded for review"
)
MERGE_OTHER_PAIR = (
    "the merge names a pair other than the one consolidation submitted; "
    "the proposal is recorded for review"
)
MERGE_UNADMITTED = (
    "a merge is committed only inside the admitted consolidation item for its pair; "
    "the proposal is recorded for review"
)
PAIR_CHANGED = (
    "a paired memory changed or vanished since it was paired; "
    "the next consolidation pairs it afresh"
)


# ─── The event ────────────────────────────────────────────────────────


def pair_key(first_id: str, second_id: str) -> str:
    """The pair's identity, whichever member is named first: both ids, sorted."""
    return "|".join(sorted((str(first_id), str(second_id))))


def pair_revision(first: Dict[str, Any], second: Dict[str, Any]) -> str:
    """A digest of both members at the versions they were paired at."""
    members = sorted((str(b["id"]), str(b.get("updated_at") or "")) for b in (first, second))
    text = "|".join(f"{blob_id}@{version}" for blob_id, version in members)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def pair_event_id(owner_id: str, company_key: str, key: str, revision: str) -> str:
    """Deterministic, so a replayed pair is recognised; the owner is part of it,
    because an operation row belongs to the account that submitted it."""
    parts = (owner_id, company_key, PAIR_SOURCE_KIND, key, revision)
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"pair-{digest[:40]}"


def common_hint(first_content: str, second_content: str) -> SubjectHint:
    """What both members' own headers assert in common, and nothing else.

    The stated type when the two agree on it or only one states it; the stated
    name when both state the same one; the typed identifiers both headers list,
    in the identity index's canonical form, a lid in its comparison form so a
    bare-digit lid and its ``@lid`` form are one lid. Types and names are
    compared without regard to case — legacy blobs say ``Entity type: person``. No
    index row, no prose and no company line: a ``#HISTORY`` that mentions
    another person's address can never become evidence, and the evidence does
    not depend on which member the role later makes the keeper.
    """
    first, second = parse_header(first_content), parse_header(second_content)
    stated = {
        value
        for value in (
            (first.get("entity type") or "").strip().upper(),
            (second.get("entity type") or "").strip().upper(),
        )
        if value
    }
    entity_type = next(iter(stated)) if len(stated) == 1 and stated <= {PERSON, COMPANY} else None
    first_name = (first.get("name") or "").strip()
    second_name = (second.get("name") or "").strip()
    name = first_name if first_name and first_name.lower() == second_name.lower() else None

    def comparable(content: str) -> set:
        return {
            (kind, lid_token(value) if kind == "lid" else value)
            for kind, value in parse_identifiers_block(content)
        }

    shared = {pair_ for pair_ in comparable(first_content) & comparable(second_content) if pair_[1]}
    return SubjectHint(entity_type=entity_type, name=name, identifiers=tuple(sorted(shared)))


def pair_event(
    owner_id: str,
    company_key: str,
    first: Dict[str, Any],
    second: Dict[str, Any],
    *,
    cancellation: Optional[Cancellation] = None,
) -> MemoryEvent:
    """The automatic event that asks the role whether two memories are one subject.

    ``first`` and ``second`` are the two blobs as ``get_blob`` returns them —
    id, content, version. Everything sealed is derived from them, so the same
    pair at the same versions is the same event, and a changed member makes a
    new one.
    """
    if str(first["id"]) == str(second["id"]):
        raise MnemonicContractError("a pair names two different memories")
    key = pair_key(first["id"], second["id"])
    revision = pair_revision(first, second)
    low, high = key.split("|")
    return MemoryEvent(
        event_id=pair_event_id(owner_id, company_key, key, revision),
        owner_id=owner_id,
        company_key=company_key,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind=PAIR_SOURCE_KIND,
        source_id=key,
        source_revision=revision,
        observation=OBSERVATION.format(first=low, second=high),
        subject_hint=common_hint(first["content"], second["content"]),
        stage=CONSOLIDATE_STAGE,
        cancellation=cancellation or turn_cancellation(),
    )


def pair_context(
    storage: Any, owner_id: str, first: Dict[str, Any], second: Dict[str, Any]
) -> CommitContext:
    """The comparison set: exactly these two, pinned at the versions they were paired at."""
    return CommitContext(
        storage=storage,
        get_blob=lambda blob_id: storage.get_blob(blob_id, owner_id),
        pinned=tuple((str(b["id"]), str(b.get("updated_at") or "")) for b in (first, second)),
    )


def pair(
    storage: Any,
    owner_id: str,
    company_key: str,
    first: Dict[str, Any],
    second: Dict[str, Any],
    *,
    cancellation: Optional[Cancellation] = None,
) -> Dict[str, Any]:
    """One pair as consolidation submits it: its admission key, its event, its context."""
    event = pair_event(owner_id, company_key, first, second, cancellation=cancellation)
    return {
        "id": event.source_id,
        "event": event,
        "context": pair_context(storage, owner_id, first, second),
    }


def intact(pinned: Sequence[Tuple[str, str]], candidates: Iterable[Candidate]) -> bool:
    """Is every pinned member still there, at the version it was paired at?"""
    live = {c.blob_id: c.updated_at for c in candidates}
    return all(blob_id in live and live[blob_id] == version for blob_id, version in pinned)


# ─── The checks that need no model ────────────────────────────────────


def has_evidence(event: MemoryEvent, first: Candidate, second: Candidate) -> bool:
    """Could the validator ever accept a MERGE of these two? Asked before paying.

    The validator's own rule on the same inputs: members that state different
    types, or a type other than PERSON or COMPANY, can only end in a
    reclassification review or a refused merge; a stated PERSON or COMPANY
    needs its family's evidence in the hint. When neither states a type the
    role will choose one, so the weaker, COMPANY rule decides whether to ask.
    """
    stated = {(c.entity_type or "").strip().upper() for c in (first, second)} - {""}
    if len(stated) > 1:
        return False
    kind = next(iter(stated), COMPANY)
    if kind not in (PERSON, COMPANY):
        return False
    return corroborates(event, first, kind) and corroborates(event, second, kind)


def settled(event: MemoryEvent) -> Optional[str]:
    """The terminal state this store already recorded for this pair, or ``None``.

    Matched by ``source_ref`` — the pair and its versions, no owner — so a pair
    another account sharing the store already answered costs nobody a second
    decision; the answer stands until one of the two blobs changes, which is a
    new ``source_ref``. Only an answer the role gave counts, which is a row
    that carries a proposal: a review a refusal produced — a read-only origin,
    an account that is not the event's, a revoked grant — carries none, and
    the pair is decided again once the refusal no longer holds.
    """
    from zylch.storage.models import MemoryOperation

    try:
        with journal.company_transaction() as session:
            row = (
                session.query(MemoryOperation.state)
                .filter(
                    MemoryOperation.company_key == event.company_key,
                    MemoryOperation.source_ref == event.source_ref,
                    MemoryOperation.state.in_(journal.TERMINAL),
                    MemoryOperation.proposal_digest.isnot(None),
                )
                .first()
            )
    except journal.JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - a journal that cannot answer is a refusal
        raise journal.JournalError(f"operation journal unavailable: {exc}") from exc
    return None if row is None else str(row[0])


def admits_merge(event: MemoryEvent, proposal: Any, allow_actions: Sequence[str]) -> str:
    """Why this MERGE may not be committed here, or ``""`` when it may.

    A merge drops a memory, and consolidation is the only operation that drops
    one. So the commit writes a MERGE only for a consolidation pair that asked
    for it, only for the very pair the event's source names, and only inside
    the admitted consolidation item for that pair.
    """
    if MERGE not in allow_actions or event.source_kind != PAIR_SOURCE_KIND:
        return MERGE_OUTSIDE_CONSOLIDATION
    keeper, donor = proposal.keeper, proposal.donor
    if keeper is None or donor is None:
        return MERGE_OTHER_PAIR
    if pair_key(keeper.blob_id, donor.blob_id) != event.source_id:
        return MERGE_OTHER_PAIR
    item = current_item()
    if not item or not item[3] or item[1] != CONSOLIDATE_STAGE or str(item[2]) != event.source_id:
        return MERGE_UNADMITTED
    return ""


# ─── Admission ────────────────────────────────────────────────────────


def decide(pair_: Dict[str, Any], *, client: Any) -> Any:
    """Submit one pair to the harness; MERGE is the one mutation it admits."""
    from .commit import submit  # deferred: commit imports this module

    return submit(pair_["event"], client=client, context=pair_["context"], allow_actions=(MERGE,))


class PairItem:
    """Each pair is one bounded preparation item, stage ``memory:consolidate``.

    ``run`` answers ``None`` when preparation did not admit the pair — a
    backed-off or suspended item, an exhausted batch, or no run at all — and
    then nothing is submitted, so no operation row exists to be replayed later
    as an answer. An admitted pair's result is kept in ``results``; a refusal
    its dispatch met is raised as itself, so the preparation item records it and
    the caller can stop.
    """

    def __init__(self, owner_id: str, decide_pair: Callable[[Dict[str, Any]], Any]) -> None:
        self.owner_id = owner_id
        self._decide = decide_pair
        self.results: Dict[str, Any] = {}

    @bounded_item(CONSOLIDATE_STAGE)
    async def run(self, pair_: Dict[str, Any]) -> Optional[bool]:
        item = current_item()
        if not item or not item[3]:
            logger.info(f"[consolidate] pair {pair_['id']} not admitted: no preparation run")
            return None
        result = await asyncio.to_thread(self._decide, pair_)
        self.results[pair_["id"]] = result
        if result.refusal is not None:
            raise result.refusal
        return result.outcome != RETRYABLE_FAILURE


__all__ = [
    "CONSOLIDATE_STAGE",
    "MERGE_OTHER_PAIR",
    "MERGE_OUTSIDE_CONSOLIDATION",
    "MERGE_UNADMITTED",
    "OBSERVATION",
    "PAIR_CHANGED",
    "PAIR_SOURCE_KIND",
    "PairItem",
    "admits_merge",
    "common_hint",
    "decide",
    "has_evidence",
    "intact",
    "pair",
    "pair_context",
    "pair_event",
    "pair_event_id",
    "pair_key",
    "pair_revision",
    "settled",
]
