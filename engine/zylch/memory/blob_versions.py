"""Retaining what a rewrite replaces, what a consolidation removes, and for how long.

The one rule this module exists for: **no write in the estate destroys text.**
Every rewrite of a blob puts the text it is about to replace here first, in the
same session, and every consolidation drop does the same before the row goes.
Recall keeps reading the current text — a version competes with nothing at
retrieval time — but a wrong write becomes a recoverable wrong belief instead
of a lost fact, and the number of versions a blob has accumulated is itself the
alarm the June 2026 sink never raised.

Three reasons, and they are told apart on purpose:

- ``append`` — an ordinary rewrite: ingestion merging a new message into a
  known contact, a chat or solve correction. These are the writes whose
  accumulation on one blob means something.
- ``consolidate`` — the consolidation operation's own work: the keeper's text
  before a merge, the donor's final text before it is dropped. Stamped
  separately so consolidation's rewrites are never counted as a sink's growth.
- ``restore`` — the owner bringing a blob back to one of its versions. It is
  the owner's judgment of which text is the entity, so a blob's count starts
  again after its latest restore.

Retention is bounded by one policy, which the consolidation operation applies
and nothing else does (:func:`expire_versions`): a version older than the
window is pruned unless it is among its blob's ``floor`` newest, and a **sink**
— a live blob whose count of ``append`` versions after its latest restore
exceeds the threshold — keeps every version and is reported on every run until
its owner restores a version or deletes it. The two other removals are the
owner's — ``delete_blob(retain=False)`` and ``delete_all_blobs`` — and they
remove a blob's versions with the blob (:func:`prune_versions`), because an
owner who deletes means it. ``blob_id`` carries no cascading foreign key (see
:class:`~zylch.storage.models.BlobVersion`), so those two calls are the only
thing standing between an owner's delete and prose that outlives it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from zylch.storage.models import Blob, BlobVersion

logger = logging.getLogger(__name__)

APPEND = "append"
CONSOLIDATE = "consolidate"
RESTORE = "restore"
REASONS = (APPEND, CONSOLIDATE, RESTORE)

# The most sinks one report lists by id. ``version_sinks_total`` always says how
# many there are, so a store with more is told so rather than shown a short list.
SINK_REPORT_LIMIT = 100
# Ids per statement: SQLite bounds the variables one statement may bind.
_CHUNK = 500


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


def restore_version(storage, blob_id: str, version_id: str, *, owner_id: str) -> Dict[str, Any]:
    """Rewrite ``blob_id`` from one of its retained versions, retaining the current text first.

    Mechanical: the version's text comes back exactly, and no model is asked.
    It goes through ``BlobStorage._rewrite`` with reason ``restore``, so the
    text it replaces is kept like any other and a restore is itself
    reversible — a blob's history only ever grows — and, being the owner's
    judgment of which text is the entity, it ends a sink: the blob's count
    starts again after it (:func:`version_counts`). Scoped like every other
    write: the blob must be visible to ``owner_id`` and the version must belong
    to that blob.

    Answers rather than raises: ``{"ok": False, "reason": …}`` for a version
    or a blob it cannot see, ``{"ok": True, "blob": …, "version_id": …}``
    after the rewrite. ``storage`` is the :class:`~.blob_storage.BlobStorage`
    whose session and ``_rewrite`` the restore rides.
    """
    from .company_key import require_company_key
    from .scope import blob_visible
    from .store import take_write_lock

    key = require_company_key()
    with storage._get_session() as session:
        version = get_version(session, blob_id, version_id)
        content = None if version is None else version.content
    if content is None:
        return {"ok": False, "reason": "no such version for this blob"}
    # Embeddings before the transaction, as every rewrite computes them.
    prepared = storage.prepare(content)
    with storage._get_session() as session:
        try:
            take_write_lock(session)
        except Exception as e:  # a store without the meta row (tests, legacy)
            logger.debug(f"[versions] write-lock upgrade skipped: {e}")
        blob = (
            session.query(Blob)
            .filter(Blob.id == str(blob_id), blob_visible(owner_id, key))
            .one_or_none()
        )
        if blob is None:
            return {"ok": False, "reason": "blob not visible to this owner"}
        if get_version(session, blob_id, version_id) is None:
            return {"ok": False, "reason": "no such version for this blob"}
        storage._rewrite(
            session,
            blob,
            owner_id=owner_id,
            prepared=prepared,
            event_description=f"restore of version {version_id}",
            reason=RESTORE,
        )
        storage._notify_mutation(session)
        row = blob.to_dict()
    logger.info(f"[versions] restored blob={blob_id} from version={version_id} by owner={owner_id}")
    return {"ok": True, "blob": row, "version_id": str(version_id)}


# ─── The retention policy consolidation applies ───────────────────────


@dataclass(frozen=True)
class RetentionPolicy:
    """Window, floor and sink threshold as configured, and what is refused.

    The settings come from the sweeping engine's profile and act on a store
    every account shares, so a value below 1 is refused rather than applied: a
    window or a floor below 1 prunes nothing, and a threshold below 1 also
    decides no pair, because without a threshold the sink set is undefined and
    a sink could be paired.
    """

    window_days: int
    floor: int
    sink_threshold: int
    refused: Tuple[str, ...] = ()

    @property
    def prunes(self) -> bool:
        return not self.refused

    @property
    def pairs(self) -> bool:
        return self.sink_threshold >= 1


def retention_policy(config: Any = None) -> RetentionPolicy:
    """The configured policy (``MEMORY_VERSION_*``), checked before anything is pruned."""
    from .config import MemoryConfig

    cfg = config or MemoryConfig()
    values = (
        ("version_retention_days", int(cfg.version_retention_days)),
        ("version_floor", int(cfg.version_floor)),
        ("version_sink_threshold", int(cfg.version_sink_threshold)),
    )
    refused = tuple(f"{name}={value} is below 1" for name, value in values if value < 1)
    return RetentionPolicy(values[0][1], values[1][1], values[2][1], refused)


def version_counts(session: Session, company_key: str) -> Dict[str, int]:
    """Each blob's count: its ``append`` versions superseded after its latest restore.

    Every blob id that has a version in this company appears, live or dropped,
    with 0 when nothing counts. ``consolidate`` and ``restore`` versions never
    count: the first is consolidation's own work, the second the owner's
    judgment, after which the count starts again.
    """
    rows = (
        session.query(BlobVersion.blob_id, BlobVersion.reason, BlobVersion.superseded_at)
        .filter(BlobVersion.company_key == company_key)
        .all()
    )
    boundary: Dict[str, datetime] = {}
    for blob_id, reason, at in rows:
        if reason == RESTORE and at is not None:
            if blob_id not in boundary or at > boundary[blob_id]:
                boundary[blob_id] = at
    counts: Dict[str, int] = {}
    for blob_id, reason, at in rows:
        counts.setdefault(str(blob_id), 0)
        if reason != APPEND:
            continue
        after = boundary.get(blob_id)
        if after is not None and (at is None or at <= after):
            continue
        counts[str(blob_id)] += 1
    return counts


def _existing(session: Session, company_key: str, blob_ids: Iterable[str], *where) -> Set[str]:
    """The ids among ``blob_ids`` whose blob row exists, under any extra filter."""
    ids = sorted(str(b) for b in blob_ids)
    found: Set[str] = set()
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        rows = (
            session.query(Blob.id)
            .filter(Blob.company_key == company_key, Blob.id.in_(chunk), *where)
            .all()
        )
        found.update(str(row[0]) for row in rows)
    return found


def sink_report(
    session: Session, company_key: str, owner_id: str, threshold: int
) -> Tuple[Dict[str, Any], Set[str]]:
    """What every consolidation run reports before it prunes, and the sink set.

    A sink is a **live** blob — its row still exists — whose count exceeds the
    threshold. A dropped donor is never one: no version accrues to it after
    the drop and no owner verb can reach it, so its versions follow the window
    and the floor alone. The set is every sink in the store, whoever's it is,
    because none of them may be pruned or paired; the listed ids are the ones
    ``owner_id`` can see, because it is the owner who must act.
    """
    from .scope import blob_visible

    counts = version_counts(session, company_key)
    live = _existing(session, company_key, counts)
    found = {bid: n for bid, n in counts.items() if bid in live and n > threshold}
    visible = _existing(session, company_key, found, blob_visible(owner_id, company_key))
    listed = sorted(
        ((bid, n) for bid, n in found.items() if bid in visible), key=lambda p: (-p[1], p[0])
    )
    report = {
        "blobs_versions_max": max((n for bid, n in counts.items() if bid in live), default=0),
        "version_sinks_total": len(found),
        "version_sinks": [{"blob_id": bid, "versions": n} for bid, n in listed[:SINK_REPORT_LIMIT]],
    }
    return report, set(found)


def expire_versions(
    session: Session,
    company_key: str,
    *,
    window_days: int,
    floor: int,
    sinks: Iterable[str],
) -> int:
    """Prune by the policy: older than the window, beyond the floor, never a sink's.

    For every blob in this company that is not a sink, its versions are ranked
    newest first by ``superseded_at``; the first ``floor`` are kept whatever
    their age, and each one after them is removed when it is older than
    ``window_days``. A sink keeps everything. The consolidation operation is
    the only caller (a static test pins it), inside its own company
    transaction under the write lock. Returns the number of versions removed.
    """
    if window_days < 1 or floor < 1:
        raise ValueError("a retention window or floor below 1 prunes nothing; refuse it first")
    keep_all = {str(b) for b in sinks}
    # Naive UTC, the form `superseded_at` is stored in.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
    rows = (
        session.query(BlobVersion.id, BlobVersion.blob_id, BlobVersion.superseded_at)
        .filter(BlobVersion.company_key == company_key)
        .order_by(
            BlobVersion.blob_id.asc(),
            BlobVersion.superseded_at.desc(),
            BlobVersion.id.desc(),
        )
        .all()
    )
    ranks: Dict[str, int] = {}
    doomed: List[str] = []
    for version_id, blob_id, at in rows:
        rank = ranks.get(blob_id, 0)
        ranks[blob_id] = rank + 1
        if str(blob_id) in keep_all or rank < floor:
            continue
        if at is not None and at < cutoff:
            doomed.append(str(version_id))
    for start in range(0, len(doomed), _CHUNK):
        chunk = doomed[start : start + _CHUNK]
        session.query(BlobVersion).filter(BlobVersion.id.in_(chunk)).delete(
            synchronize_session=False
        )
    if doomed:
        session.flush()
    logger.info(
        f"[versions] retention pruned {len(doomed)} version(s); "
        f"window={window_days}d floor={floor} sinks={len(keep_all)}"
    )
    return len(doomed)


__all__ = [
    "APPEND",
    "CONSOLIDATE",
    "REASONS",
    "RESTORE",
    "SINK_REPORT_LIMIT",
    "RetentionPolicy",
    "expire_versions",
    "get_version",
    "list_versions",
    "prune_versions",
    "restore_version",
    "retain_version",
    "retention_policy",
    "sink_report",
    "version_counts",
]
