"""Semantic indexes and references, written inside the caller's transaction.

An identifier row, a source link and a merge alias are not decorations on a
memory — they are part of what it means. A blob committed without its email
link is invisible to the task worker's exact lookup; a keeper committed
without the donor's alias leaves stale ids in other profiles' ledgers. When
those writes happened in their own sessions after the blob was already saved,
a crash between the two left memory that says one thing and an index that says
another.

So every function here takes the **session that is already committing the
blob** and writes into it. Each one is idempotent, none of them commits, and
none of them swallows an error: inside a transaction a swallowed failure is
exactly the half-written state this module exists to prevent.

``storage.Storage`` keeps its own standalone methods for the legacy writers
that have not been converted yet; they delegate here so there is one
implementation of each rule rather than two that can drift.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Sequence, Tuple

from sqlalchemy.orm import Session

from zylch.storage.models import (
    BlobAlias,
    CalendarBlob,
    EmailBlob,
    PersonIdentifier,
    WhatsAppBlob,
)

logger = logging.getLogger(__name__)

# Which association table a source kind writes into. A kind that is not here
# has no index of its own — a chat turn, for instance — and links nothing.
SOURCE_LINKS = {
    "email": (EmailBlob, "email_id"),
    "calendar": (CalendarBlob, "event_id"),
    "whatsapp": (WhatsAppBlob, "whatsapp_message_id"),
}


def link_source(
    session: Session,
    *,
    source_kind: str,
    source_id: str,
    blob_id: str,
    owner_id: str,
) -> bool:
    """Idempotent ``(source, blob)`` link for one channel. True when inserted.

    An unknown source kind links nothing and says so by returning False; it
    is not an error, because most events (a chat turn) have no channel index.

    The three models are named one by one rather than looked up and called
    dynamically. ``model(**fields)`` would be shorter and the milestone 0
    inventory scanner, which reads the AST, could not see a write edge through
    it — and an unlisted write edge is exactly what that inventory exists to
    make impossible.
    """
    kind = (source_kind or "").strip().lower()
    entry = SOURCE_LINKS.get(kind)
    if not entry or not (source_id and blob_id and owner_id):
        return False
    model, column = entry
    existing = (
        session.query(model)
        .filter(getattr(model, column) == source_id, model.blob_id == blob_id)
        .one_or_none()
    )
    if existing is not None:
        return False
    if kind == "email":
        row = EmailBlob(email_id=source_id, blob_id=blob_id, owner_id=owner_id)
    elif kind == "calendar":
        row = CalendarBlob(event_id=source_id, blob_id=blob_id, owner_id=owner_id)
    else:
        row = WhatsAppBlob(whatsapp_message_id=source_id, blob_id=blob_id, owner_id=owner_id)
    session.add(row)
    session.flush()
    return True


def links_of(session: Session, *, blob_id: str, company_key: str) -> List[Tuple[str, str, str]]:
    """Every source link of one blob, as ``(source_kind, source_id, owner_id)``.

    Read by a merge before it drops its donor, so each source the donor was
    extracted from can be linked to the keeper in the same transaction: the
    donor's own link rows go with it by cascade, and a source link is
    provenance the merge must not lose. Each link keeps the ``owner_id`` of
    whoever linked it.
    """
    found: List[Tuple[str, str, str]] = []
    for kind, (model, column) in SOURCE_LINKS.items():
        rows = (
            session.query(getattr(model, column), model.owner_id)
            .filter(model.blob_id == blob_id, model.company_key == company_key)
            .all()
        )
        found.extend((kind, str(source_id), str(owner)) for source_id, owner in rows)
    return found


def add_identifiers(
    session: Session,
    *,
    owner_id: str,
    blob_id: str,
    identifiers: Sequence[Tuple[str, str]],
    company_key: str,
) -> int:
    """Add ``(kind, value)`` identifier rows for a blob. Returns rows inserted.

    Unique per company, so an identifier another account already indexed on
    this blob is skipped rather than duplicated. The caller bumps the mutation
    sequence once for the whole commit; this never bumps it itself.
    """
    if not (owner_id and blob_id and identifiers):
        return 0
    existing = {
        (str(kind), str(value))
        for kind, value in session.query(PersonIdentifier.kind, PersonIdentifier.value)
        .filter(
            PersonIdentifier.company_key == company_key,
            PersonIdentifier.blob_id == blob_id,
        )
        .all()
    }
    inserted = 0
    for kind, value in identifiers:
        if not kind or not value:
            continue
        k, v = str(kind).strip().lower(), str(value).strip()
        if not k or not v or (k, v) in existing:
            continue
        session.add(PersonIdentifier(owner_id=owner_id, blob_id=blob_id, kind=k, value=v))
        existing.add((k, v))
        inserted += 1
    if inserted:
        session.flush()
    return inserted


def drop_identifiers(session: Session, *, blob_id: str, company_key: str) -> int:
    """Remove this blob's identifier rows. Returns the number removed.

    An UPDATE that changes an identifier must change the index with it. The
    old writer only ever appended, so a corrected email address left the wrong
    one in the index and the next cross-channel lookup still found it.
    """
    if not blob_id:
        return 0
    removed = (
        session.query(PersonIdentifier)
        .filter(
            PersonIdentifier.company_key == company_key,
            PersonIdentifier.blob_id == blob_id,
        )
        .delete(synchronize_session=False)
    )
    if removed:
        session.flush()
    return int(removed)


def record_alias(session: Session, *, merged_id: str, keeper_id: str) -> None:
    """``merged_id -> keeper_id``, so a stale id still resolves after a merge.

    Chains stay resolvable: merging the keeper again later re-points nothing,
    and a reader that follows aliases from either end finds the survivor.
    """
    if not (merged_id and keeper_id) or merged_id == keeper_id:
        return
    session.merge(BlobAlias(merged_id=merged_id, keeper_id=keeper_id))
    session.flush()


def identifiers_from(pairs: Iterable[Tuple[str, str]]) -> Tuple[Tuple[str, str], ...]:
    """Normalize ``(kind, value)`` pairs, dropping the empty ones."""
    return tuple(
        (str(kind).strip().lower(), str(value).strip())
        for kind, value in pairs
        if kind and value and str(kind).strip() and str(value).strip()
    )


__all__ = [
    "SOURCE_LINKS",
    "add_identifiers",
    "drop_identifiers",
    "identifiers_from",
    "link_source",
    "links_of",
    "record_alias",
]
