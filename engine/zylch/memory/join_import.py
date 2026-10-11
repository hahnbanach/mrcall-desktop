"""The join import: one company's memory copied into another, once, under a fence.

A reviewed mechanical primitive with a fixed precondition: the source company
holds this join's fence in phase ``fenced`` (:mod:`zylch.memory.mnemonic.fence`).
It makes no semantic decision. Every change of exposure or meaning it makes is
fixed by a rule, so a model has nothing to decide:

- **what travels** is what the joining account can see in the source
  (:func:`zylch.memory.scope.blob_visible` for either identity the fence
  records): every company-family row, and that account's own ``template:`` /
  ``prefs:`` rows — never another account's rules;
- **facts converge**: a source fact whose ``(category, key)`` the destination
  already holds loses, and its value goes to ``fact_history`` under its own
  owner;
- **nothing is overwritten**: a blob id the destination already holds with
  other text keeps the destination's row, and the source's text is retained on
  it as a ``join`` version; the row keeps its own sentences too, since the
  source's describe text the destination row does not hold;
- **restrictions travel**: every restriction the source journal records
  against a copied blob is written on the import's receipt, so a restricted
  FACT is ineligible in the destination before anything can read it;
- company-family namespaces are rewritten to the destination key; rule
  namespaces stay as they are; the source key is written nowhere in the
  destination and the destination key nowhere in the source.

Two transactions, one per store. The source transaction takes the source's
write lock, compares-and-sets the fence (this id, phase ``fenced``) and computes
the snapshot digest over what is copied: the id and ``updated_at`` of every
copied blob and the restriction set. The destination transaction takes the
destination's write lock and copies, row by row, each keyed so that a second
import of the same source writes nothing twice whichever fence carries it:
blobs, versions, sentences, links, identifiers and aliases by their own ids
(``INSERT OR IGNORE``), a history row by an id derived from the losing blob's id
and ``updated_at`` and the winner's id, a ``join`` version by an id derived from
the blob id and the source row's ``updated_at``. It writes one receipt row,
``join-<fence id>``, directly and not through the journal's checked writers —
the profile's ``.env`` still names the source — bumps the mutation sequence
once and runs ``project_join.merge_projects`` unchanged. The destination
commits first; then the source fence moves to ``accepted`` with the snapshot
digest and the source commits. An acceptance never exists without its import.

A receipt for this fence whose digest equals the snapshot's means the import
already ran (a crash before the acceptance): nothing is copied again and the
fence is accepted. A receipt whose digest differs means the source changed in
an unlocked gap: :class:`SourceChanged`, nothing is written, and the caller
releases the fence.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from zylch.memory.company_key import COMPANY_FAMILIES
from zylch.storage.models import (
    Blob,
    BlobAlias,
    BlobSentence,
    BlobVersion,
    CalendarBlob,
    EmailBlob,
    FactHistory,
    MemoryOperation,
    PersonIdentifier,
    WhatsAppBlob,
)

logger = logging.getLogger(__name__)

RECEIPT_PREFIX = "join-"
JOIN_REASON = "join"
_CHUNK = 500

DEPENDENTS: Tuple[Tuple[Any, str, str], ...] = (
    (BlobVersion, "blob_versions", "blob_id"),
    (BlobSentence, "blob_sentences", "blob_id"),
    (EmailBlob, "email_blobs", "blob_id"),
    (CalendarBlob, "calendar_blobs", "blob_id"),
    (WhatsAppBlob, "whatsapp_blobs", "blob_id"),
    (PersonIdentifier, "person_identifiers", "blob_id"),
    (BlobAlias, "blob_aliases", "keeper_id"),
)
COUNTED = {
    "blob_versions": "versions",
    "blob_sentences": "blob_sentences",
    "email_blobs": "links",
    "calendar_blobs": "links",
    "whatsapp_blobs": "links",
    "person_identifiers": "identifiers",
    "blob_aliases": "aliases",
}


class ImportRefused(RuntimeError):
    """The import may not run under this fence; nothing was written."""


class SourceChanged(ImportRefused):
    """The source changed since this fence's import: its digest no longer matches the receipt."""


def receipt_id(fence_id: str) -> str:
    """The destination journal's event id for the import a fence carries."""
    return f"{RECEIPT_PREFIX}{fence_id}"


def _now() -> str:
    return str(datetime.now(timezone.utc).replace(tzinfo=None))


def _derived(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


def history_id(losing_blob_id: str, losing_updated_at: Any, winning_blob_id: str) -> str:
    """The ``fact_history`` id of one losing fact: the same loss is recorded once."""
    return _derived("join-history", losing_blob_id, losing_updated_at, winning_blob_id)


def version_id(blob_id: str, source_updated_at: Any) -> str:
    """The ``join`` version id of one source text: the same text is retained once."""
    return _derived("join-version", blob_id, source_updated_at)


def columns(model: Any) -> List[str]:
    """The model's real column names, in declaration order."""
    return [column.name for column in model.__table__.columns]


def rewrite_namespace(namespace: str, destination_key: str) -> str:
    """A company-family namespace moves to the destination key; any other stays."""
    family = namespace.split(":", 1)[0] if ":" in (namespace or "") else ""
    return f"{family}:{destination_key}" if family in COMPANY_FAMILIES else namespace


def parse_fact(content: str) -> Tuple[str, str]:
    from zylch.services.facts_store import parse_category, parse_key

    return parse_category(content or "").lower(), parse_key(content or "").lower()


def fact_value(content: str) -> str:
    """The value of a ``Category:/Key:/<value>`` fact blob — what history keeps."""
    body = [
        ln
        for ln in (content or "").splitlines()
        if not ln.strip().lower().startswith(("category:", "key:"))
    ]
    value = "\n".join(body).strip()
    if value.lower().startswith("value:"):
        value = value.split(":", 1)[1].strip()
    return value or content


def joining_owner(owner_ids: Iterable[str]) -> str:
    """The identity the receipt is written under: the one events carry, when stated."""
    from zylch.cli.utils import get_owner_id

    owners = sorted(str(o) for o in owner_ids if o)
    email = get_owner_id()
    return email if email in owners else owners[0]


def _chunks(values: Sequence[str]) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def _put(session: Session, table: str, model: Any, row: Dict[str, Any]) -> int:
    """``INSERT OR IGNORE`` one row of ``model`` by its own key; 1 when written, 0 when present.

    ``row`` names every column of the model: a missing one is a ``KeyError``,
    never a silent default.
    """
    names = columns(model)
    statement = (
        f"INSERT OR IGNORE INTO {table} ({', '.join(names)}) "
        f"VALUES ({', '.join('?' for _ in names)})"
    )
    values = tuple(row[name] for name in names)
    return int(session.connection().exec_driver_sql(statement, values).rowcount or 0)


def _rows(session: Session, table: str, names: Sequence[str], key: str, ids: Sequence[str]):
    """The rows of ``table`` whose ``key`` is one of ``ids``, as dicts of raw column values."""
    out: List[Dict[str, Any]] = []
    for chunk in _chunks(list(ids)):
        marks = ", ".join("?" for _ in chunk)
        found = session.connection().exec_driver_sql(
            f"SELECT {', '.join(names)} FROM {table} WHERE {key} IN ({marks}) ORDER BY {names[0]}",
            tuple(chunk),
        )
        out.extend(dict(zip(names, row)) for row in found.fetchall())
    return out


# ─── Step 1: the source snapshot ──────────────────────────────────────


def _snapshot(source: Session, fence: Dict[str, Any], source_key: str):
    """What the joining account can see in the source: blob rows, restrictions, digest."""
    from zylch.memory.eligibility import restriction_entries
    from zylch.memory.scope import blob_visible

    owners = [str(o) for o in fence.get("owner_ids") or [] if o]
    if not owners:
        raise ImportRefused("the join fence names no account")
    visible = or_(*[blob_visible(owner, source_key) for owner in owners])
    from zylch.qonto.provenance import excluded_blob_ids

    excluded = excluded_blob_ids(source, source_key)
    visible_ids = set(str(i) for i in source.execute(select(Blob.id).where(visible)).scalars())
    excluded_count = len(visible_ids & excluded)
    ids = sorted(visible_ids - excluded)
    blobs = _rows(source, "blobs", columns(Blob), "id", ids)
    wanted = set(ids)
    restrictions = sorted(
        {
            json.dumps(entry, sort_keys=True)
            for entry in restriction_entries(source, source_key)
            if str(entry["blob_id"]) in wanted
        }
    )
    digest = hashlib.sha256()
    for row in blobs:
        digest.update(f"{row['id']}|{row['updated_at']}\n".encode("utf-8"))
    digest.update(f"--qonto-excluded--{excluded_count}\n".encode())
    digest.update(b"--restrictions--\n")
    for entry in restrictions:
        digest.update(entry.encode("utf-8") + b"\n")
    from zylch.services.task_assignment_enrollment import read as read_enrollment
    from zylch.storage.models import ProjectSpace

    space = source.execute(select(ProjectSpace.space_id)).scalar_one()
    digest.update(json.dumps(read_enrollment(source.connection(), space), sort_keys=True).encode())
    return blobs, [json.loads(e) for e in restrictions], digest.hexdigest(), excluded_count


def _claim(source: Session, fence_id: str, source_key: str, destination_key: str):
    """Compare-and-set the fence (this id, phase ``fenced``) and answer it, or refuse."""
    from zylch.memory.mnemonic import fence as fences
    from zylch.storage.join_fence_model import MemoryJoinFence

    row = source.get(MemoryJoinFence, fence_id)
    if row is None or row.company_key != source_key:
        raise ImportRefused("no join fence of this attempt holds the source company memory")
    if row.destination_digest != fences.destination_digest(destination_key):
        raise ImportRefused("the join fence was placed for another destination")
    if not fences.cas(source, fence_id, fences.FENCED, fences.FENCED):
        raise ImportRefused(f"the join fence is {row.phase}, not fenced; join again")
    return row.to_dict()


# ─── Step 3: the destination copy ─────────────────────────────────────


def _copy(
    destination: Session,
    source: Session,
    blobs: List[Dict[str, Any]],
    *,
    destination_key: str,
    event_id: str,
    owner: str,
) -> Dict[str, int]:
    counts = {"blobs": 0, "facts_converged": 0, "retained": 0}
    counts.update({name: 0 for name in sorted(set(COUNTED.values()))})
    facts_ns = f"facts:{destination_key}"
    winners = {
        parse_fact(content): str(bid)
        for bid, content in destination.connection().exec_driver_sql(
            "SELECT id, content FROM blobs WHERE namespace = ? ORDER BY id", (facts_ns,)
        )
    }
    present = {
        row["id"]: row["content"]
        for row in _rows(destination, "blobs", ["id", "content"], "id", [b["id"] for b in blobs])
    }
    copied: List[str] = []
    conflicted: Set[str] = set()
    for row in blobs:
        bid = str(row["id"])
        namespace = rewrite_namespace(row["namespace"], destination_key)
        if namespace == facts_ns:
            fact_key = parse_fact(row["content"])
            winner = winners.get(fact_key)
            if winner and winner != bid:
                counts["facts_converged"] += 1
                _put(destination, "fact_history", FactHistory, {
                    "id": history_id(bid, row["updated_at"], winner),
                    "company_key": destination_key,
                    "category": fact_key[0],
                    "fact_key": fact_key[1],
                    "losing_value": fact_value(row["content"]),
                    "losing_owner_id": row["owner_id"],
                    "losing_blob_id": bid,
                    "winning_blob_id": winner,
                    "reason": JOIN_REASON,
                    "merged_at": _now(),
                })
                continue
            winners[fact_key] = bid
        copied.append(bid)
        if bid in present:
            if present[bid] != row["content"]:
                conflicted.add(bid)
                counts["retained"] += _put(destination, "blob_versions", BlobVersion, {
                    "id": version_id(bid, row["updated_at"]),
                    "blob_id": bid,
                    "company_key": destination_key,
                    "owner_id": owner,
                    "namespace": namespace,
                    "content": row["content"],
                    "reason": JOIN_REASON,
                    "operation_id": event_id,
                    "superseded_at": _now(),
                })
            continue
        fields = {**row, "namespace": namespace, "company_key": destination_key}
        counts["blobs"] += _put(destination, "blobs", Blob, fields)
    for model, table, key in DEPENDENTS:
        wanted = [b for b in copied if not (table == "blob_sentences" and b in conflicted)]
        for dep in _rows(source, table, columns(model), key, wanted):
            dep["company_key"] = destination_key
            if "namespace" in dep:
                dep["namespace"] = rewrite_namespace(dep["namespace"], destination_key)
            counts[COUNTED[table]] += _put(destination, table, model, dep)
    return counts


def _write_receipt(
    destination: Session,
    event_id: str,
    *,
    owner: str,
    destination_key: str,
    digest: str,
    counts: Dict[str, int],
    restrictions: List[Dict[str, Any]],
    enrollment: Dict[str, Any],
) -> None:
    """The import's own receipt row: written directly, not through the checked journal writers."""
    from zylch.memory.mnemonic.contracts import COMMITTED, INTERACTIVE, OPERATOR_DELEGATED
    from zylch.memory.mnemonic.journal import PROTOCOL_VERSION

    destination.add(
        MemoryOperation(
            event_id=event_id,
            company_key=destination_key,
            owner_id=owner,
            protocol_version=PROTOCOL_VERSION,
            input_digest=digest,
            source_ref=f"join:{event_id[len(RECEIPT_PREFIX):]}@{digest[:32]}",
            origin=INTERACTIVE,
            caller_class=OPERATOR_DELEGATED,
            state=COMMITTED,
            allowance=0,
            attempts=0,
            result={
                "outcome": COMMITTED,
                "reason": "company memory join import",
                "committed_ids": [],
                "counts": dict(counts),
                "assignment_enrollment": enrollment,
            },
            pending_effects=[],
            restrictions=restrictions,
        )
    )
    destination.flush()


def _accept(source: Session, fence_id: str, digest: str, counts: Dict[str, int]) -> None:
    """Step 4: the fence moves to ``accepted`` with the digest, in the source transaction."""
    from zylch.memory.mnemonic import fence as fences

    if not fences.cas(
        source, fence_id, fences.FENCED, fences.ACCEPTED,
        snapshot_digest=digest, detail={"counts": dict(counts)},
    ):
        raise ImportRefused("the join fence moved during the import; join again")


def import_into(
    source_engine: Engine,
    destination_engine: Engine,
    fence_id: str,
    *,
    source_key: str,
    destination_key: str,
) -> Dict[str, int]:
    """Copy the source into the destination under ``fence_id`` and accept the fence.

    Answers the import's counts — this run's, or the recorded run's when the
    receipt already held this snapshot. Raises :class:`ImportRefused` (the
    fence is not this attempt's or not ``fenced``, or the destination is being
    joined itself), :class:`SourceChanged`, or whatever the copy raised
    (``ProjectError`` for diverging project histories); nothing is committed
    then, in either store.
    """
    from zylch.memory.mnemonic import fence as fences
    from zylch.memory.store import bump_mutation_seq, take_write_lock
    from zylch.services import project_join

    event_id = receipt_id(fence_id)
    source = Session(bind=source_engine, expire_on_commit=False)
    destination = Session(bind=destination_engine, expire_on_commit=False)
    try:
        take_write_lock(source)
        fence = _claim(source, fence_id, source_key, destination_key)
        blobs, restrictions, digest, excluded_count = _snapshot(source, fence, source_key)
        take_write_lock(destination)
        if fences.active(destination, destination_key) is not None:
            raise ImportRefused(f"the destination {fences.JOINING}")
        recorded = destination.get(MemoryOperation, event_id)
        if recorded is not None:
            if recorded.input_digest != digest:
                raise SourceChanged(
                    "the source company memory changed after its import; "
                    "the join fence is released, join again"
                )
            counts = dict(dict(recorded.result or {}).get("counts") or {})
        else:
            owner = joining_owner(fence["owner_ids"])
            counts = _copy(
                destination, source, blobs,
                destination_key=destination_key, event_id=event_id, owner=owner,
            )
            counts["qonto_excluded"] = excluded_count
            counts["restrictions"] = len(restrictions)
            counts.update(project_join.merge_projects(source.connection(), destination.connection()))
            from zylch.services.task_assignment_enrollment import merge as merge_enrollment

            enrollment = merge_enrollment(source.connection(), destination.connection())
            _write_receipt(
                destination, event_id, owner=owner, destination_key=destination_key,
                digest=digest, counts=counts, restrictions=restrictions, enrollment=enrollment,
            )
            bump_mutation_seq(destination)
        destination.commit()
        _accept(source, fence_id, digest, counts)
        source.commit()
    except BaseException:
        destination.rollback()
        source.rollback()
        raise
    finally:
        destination.close()
        source.close()
    logger.info(f"[join] import accepted under fence {fence_id[:8]}… counts={counts}")
    return counts


def receipt_digest(destination_engine: Engine, fence_id: str) -> Optional[str]:
    """The snapshot digest this fence's receipt recorded in the destination, or ``None``."""
    with Session(bind=destination_engine) as session:
        row = session.get(MemoryOperation, receipt_id(fence_id))
        return None if row is None else str(row.input_digest)


__all__ = [
    "ImportRefused",
    "SourceChanged",
    "history_id",
    "import_into",
    "receipt_digest",
    "receipt_id",
    "rewrite_namespace",
    "version_id",
]
