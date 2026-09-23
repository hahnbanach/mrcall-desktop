"""Retaining what a rewrite replaces, and what a consolidation removes.

The one rule this module exists for: **no write in the estate destroys text.**
Every rewrite of a blob puts the text it is about to replace here first, in the
same session, and every consolidation drop does the same before the row goes.
Recall keeps reading the current text — a version competes with nothing at
retrieval time — but a wrong write becomes a recoverable wrong belief instead
of a lost fact, and the number of versions a blob has accumulated is itself the
alarm the June 2026 sink never raised.

Two reasons, and they are told apart on purpose:

- ``append`` — an ordinary rewrite: ingestion merging a new message into a
  known contact, a chat or solve correction, a restore. These are the writes
  whose accumulation on one blob means something.
- ``consolidate`` — the sweep's own work: the keeper's text before a merge,
  the donor's final text before it is dropped. Stamped separately so
  consolidation's rewrites are never counted as a sink's growth.

Pruning is consolidation's alone, and it is not here yet: until milestone 7
applies the window and the floor, retention is unbounded on purpose. The two
pruning calls that DO exist are the owner's — ``delete_blob(retain=False)`` and
``delete_all_blobs`` — and they remove a blob's versions with the blob, because
an owner who deletes means it. ``blob_id`` carries no cascading foreign key
(see :class:`~zylch.storage.models.BlobVersion`), so those two calls are the
only thing standing between an owner's delete and prose that outlives it.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from zylch.storage.models import Blob, BlobVersion

logger = logging.getLogger(__name__)

APPEND = "append"
CONSOLIDATE = "consolidate"
REASONS = (APPEND, CONSOLIDATE)


def retain_version(
    session: Session,
    blob: Blob,
    *,
    reason: str,
    owner_id: str,
    operation_id: Optional[str] = None,
) -> BlobVersion:
    """Copy ``blob``'s current text into a version row, in this session.

    Called BEFORE the caller mutates or deletes ``blob``, and never commits:
    the version lands with the write it precedes or not at all. ``owner_id``
    is the writer's provenance — who caused this text to be superseded — and
    on a shared store that is often not the blob's owner.
    """
    if reason not in REASONS:
        raise ValueError(f"unknown version reason {reason!r}; expected one of {REASONS}")
    version = BlobVersion(
        blob_id=str(blob.id),
        owner_id=owner_id,
        namespace=blob.namespace,
        content=blob.content,
        reason=reason,
        operation_id=operation_id,
    )
    session.add(version)
    session.flush()
    logger.debug(
        f"[versions] retained blob={blob.id} reason={reason} "
        f"operation={operation_id or '-'} version={version.id}"
    )
    return version


def prune_versions(session: Session, blob_ids: Iterable[str]) -> int:
    """Remove every version of the given blobs. The owner's delete, not the sweep's.

    Filters on ``blob_id`` and nothing else — never on ``owner_id``, which is
    the writer's provenance and would leave another account's rewrites of a
    deleted blob behind, or worse, take this account's rewrites of a living one.
    """
    ids = [str(b) for b in blob_ids if b]
    if not ids:
        return 0
    count = (
        session.query(BlobVersion)
        .filter(BlobVersion.blob_id.in_(ids))
        .delete(synchronize_session=False)
    )
    logger.debug(f"[versions] pruned {count} version(s) of {len(ids)} blob(s)")
    return int(count)


def list_versions(session: Session, blob_id: str) -> List[BlobVersion]:
    """Every retained version of one blob, oldest first."""
    return (
        session.query(BlobVersion)
        .filter(BlobVersion.blob_id == str(blob_id))
        .order_by(BlobVersion.superseded_at.asc(), BlobVersion.id.asc())
        .all()
    )


def get_version(session: Session, blob_id: str, version_id: str) -> Optional[BlobVersion]:
    """One version, only if it belongs to the blob the caller names."""
    return (
        session.query(BlobVersion)
        .filter(BlobVersion.blob_id == str(blob_id), BlobVersion.id == str(version_id))
        .one_or_none()
    )


__all__ = [
    "APPEND",
    "CONSOLIDATE",
    "REASONS",
    "get_version",
    "list_versions",
    "prune_versions",
    "retain_version",
]
