"""The join fence: what stops a company's memory from changing while it is joined.

A join copies one company's memory into another and then moves the joining
profile's key. Between the snapshot the import reads and the moment the key
moves, nothing may land in the source that the destination would then miss. The
fence is that guarantee: one row in the source company's own store
(``memory_join_fences``, :mod:`zylch.storage.join_fence_model`), and one check,
:func:`refuse_if_fenced`, that every journal writer runs inside its write
transaction, after the write lock.

Two refusals, both :class:`CompanyFenced`:

- **an active fence** — phase ``fenced`` or ``accepted`` — on the company being
  written refuses every account, the joining one included, with
  :data:`JOINING`. The refusal never names the destination: the fence keeps
  only the destination's digest, and a store other key holders open never
  learns the key.
- **the binding check** refuses a process whose profile has left the company
  it writes: the profile's ``.env`` on disk names a ``MEMORY_KEY`` other than
  that company, while this process still holds the old key in its environment
  (a second process of the joining profile, a Desktop engine beside a CLI join
  or the reverse). It answers :data:`REBOUND`. The file is read through
  ``settings_io`` and cached on its inode, ``st_mtime_ns`` and size, since a
  join replaces it twice within moments. A process with no active profile, or
  whose ``.env`` names no key, is not checked.

A ``completed`` or ``released`` fence refuses nothing. Nothing here is keyed to
an identity: a fresh profile, or the same profile joining back, names the
company again and is admitted.

``CompanyFenced`` is a :class:`~zylch.memory.mnemonic.session.JournalError`, so
``submit`` answers it as a ``retryable_failure`` and the row keeps its state and
allowance. It is not a failure of the item: ingestion re-raises it, and
preparation's ``bounded_item`` finishes the item as refused and ends the run
with the fence as its stop reason.

Phase moves are compare-and-set under the source store's write lock:
``fenced`` → ``accepted`` → ``completed``, ``fenced`` → ``released``, and
``accepted`` → ``released`` for the joining profile's own recovery. The partial
unique index admits at most one active fence per company.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zylch.storage.join_fence_model import MemoryJoinFence

from .session import JournalError, company_transaction

FENCED = "fenced"
ACCEPTED = "accepted"
COMPLETED = "completed"
RELEASED = "released"

ACTIVE: Tuple[str, ...] = (FENCED, ACCEPTED)

MOVES = frozenset(
    {
        (FENCED, ACCEPTED),
        (FENCED, RELEASED),
        (ACCEPTED, COMPLETED),
        (ACCEPTED, RELEASED),
        (FENCED, FENCED),
        (ACCEPTED, ACCEPTED),
    }
)
FIELDS = frozenset({"snapshot_digest", "detail"})

JOINING = "company memory is being joined"
REBOUND = "this profile has joined another company memory; restart the engine"


class CompanyFenced(JournalError):
    """This company's memory may not be written now: it is being joined, or this profile left it."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def destination_digest(key: str) -> str:
    """What a fence records of its destination: the sha256 of the key, never the key."""
    return hashlib.sha256((key or "").strip().encode("utf-8")).hexdigest()


# ─── Reads ────────────────────────────────────────────────────────────


def active(session: Session, company_key: str) -> Optional[Dict[str, Any]]:
    """The company's active fence as a dict, or ``None``. Read in the caller's session."""
    row = (
        session.query(MemoryJoinFence)
        .filter(
            MemoryJoinFence.company_key == company_key,
            MemoryJoinFence.phase.in_(ACTIVE),
        )
        .one_or_none()
    )
    return None if row is None else row.to_dict()


# ─── The check every journal writer runs ──────────────────────────────


def refuse_if_fenced(session: Session, company_key: str) -> None:
    """Refuse a write to ``company_key`` now, or return.

    Called inside the writer's own transaction, after the write lock, so a
    fence placed by another process is seen before the write and not after it.
    """
    if active(session, company_key) is not None:
        raise CompanyFenced(JOINING)
    named = profile_key()
    if named is not None and named != company_key:
        raise CompanyFenced(REBOUND)


_ENV_CACHE: Dict[str, Tuple[Tuple[int, int, int], Optional[str]]] = {}


def profile_key() -> Optional[str]:
    """The ``MEMORY_KEY`` the profile's ``.env`` names on disk now, or ``None``.

    ``None`` when no profile is active (``settings_io`` cannot resolve a
    ``.env``), when the file is absent, or when it names no key: such a process
    is not checked. The answer is cached per path on the file's inode,
    ``st_mtime_ns`` and size, read from the descriptor the content came from,
    so a replaced file is re-read even within the same clock tick.
    """
    from zylch.services.settings_io import _env_path

    try:
        path = _env_path()
    except RuntimeError:
        return None
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None
    stamp = (info.st_ino, info.st_mtime_ns, info.st_size)
    cached = _ENV_CACHE.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            info = os.fstat(handle.fileno())
            key = _named_key(handle)
    except FileNotFoundError:
        return None
    _ENV_CACHE[path] = ((info.st_ino, info.st_mtime_ns, info.st_size), key)
    return key


def _named_key(lines: Iterable[str]) -> Optional[str]:
    """The last ``MEMORY_KEY`` assignment in ``lines``, unquoted; ``None`` when empty or absent."""
    from zylch.memory.company_key import SETTING
    from zylch.services.settings_io import _parse_kv

    found: Optional[str] = None
    for line in lines:
        kv = _parse_kv(line)
        if kv is None or kv[0] != SETTING:
            continue
        value = kv[1]
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        found = value.strip() or None
    return found


def refusal(company_key: str) -> Optional[str]:
    """Why a write to ``company_key`` would be refused now, or ``None``.

    :func:`refuse_if_fenced` in a read transaction of its own, for a caller
    that must know before it starts any work rather than at its first write.
    Raises :class:`JournalError` when the store cannot answer.
    """
    try:
        with company_transaction() as session:
            refuse_if_fenced(session, company_key)
    except CompanyFenced as exc:
        return str(exc)
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - a store that cannot answer is no admission
        raise JournalError(f"join fence unavailable: {exc}") from exc
    return None


# ─── Placing and moving a fence ───────────────────────────────────────


def place(company_key: str, owner_ids: Iterable[str], destination_key: str) -> str:
    """Fence ``company_key`` for one join attempt; returns the fence's fresh id.

    ``owner_ids`` are both identities of the joining profile. Only the
    destination's digest is written. A company that already holds an active
    fence refuses a second one — the partial unique index says so under the
    write lock — with :class:`CompanyFenced`.
    """
    fence_id = secrets.token_hex(24)
    try:
        with company_transaction(write=True) as session:
            from zylch.services.task_assignment_join import refusal_connection

            blocked = refusal_connection(session.connection(bind_arguments={"mapper": MemoryJoinFence}))
            if blocked:
                raise CompanyFenced(blocked)
            session.add(
                MemoryJoinFence(
                    id=fence_id,
                    company_key=company_key,
                    owner_ids=sorted({str(o) for o in owner_ids if o}),
                    destination_digest=destination_digest(destination_key),
                    phase=FENCED,
                    detail={},
                )
            )
            session.flush()
    except IntegrityError as exc:
        raise CompanyFenced(JOINING) from exc
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - a store that cannot answer places no fence
        raise JournalError(f"join fence unavailable: {exc}") from exc
    return fence_id


def cas(session: Session, fence_id: str, expected_phase: str, new_phase: str, **fields: Any) -> bool:
    """Compare-and-set one fence inside the caller's transaction; True when it moved.

    The caller holds the store's write lock. :func:`move` is this in a
    transaction of its own; the join import calls it inside the source
    transaction that read its snapshot, so the acceptance and the snapshot it
    accepts are one write. Same rules and errors as :func:`move`, except that
    an ``IntegrityError`` reaches the caller as it is.
    """
    if (expected_phase, new_phase) not in MOVES:
        raise ValueError(f"a fence cannot move from {expected_phase} to {new_phase}")
    unknown = set(fields) - FIELDS
    if unknown:
        raise ValueError(f"a fence has no field {', '.join(sorted(unknown))}")
    moved = (
        session.query(MemoryJoinFence)
        .filter(MemoryJoinFence.id == fence_id, MemoryJoinFence.phase == expected_phase)
        .update(
            {"phase": new_phase, "updated_at": _now(), **fields},
            synchronize_session=False,
        )
    )
    return moved == 1


def move(
    fence_id: str, expected_phase: str, new_phase: str, *, engine: Any = None, **fields: Any
) -> bool:
    """Compare-and-set one fence from ``expected_phase`` to ``new_phase``; True when it moved.

    :data:`MOVES` lists every move a fence may take; a move within an active
    phase records fields in place. ``fields`` may set ``snapshot_digest`` and ``detail`` in the same write.
    A move outside :data:`MOVES` or a field outside :data:`FIELDS` is a
    programming error and raises ``ValueError``; a fence that is no longer in
    ``expected_phase`` (another process moved it) answers ``False``. Moving
    into an active phase is refused by the partial unique index when the
    company already holds another active fence. ``engine`` names the store
    the fence lives in when it is not the attached one: the source a join has
    already left.
    """
    try:
        with company_transaction(write=True, engine=engine) as session:
            return cas(session, fence_id, expected_phase, new_phase, **fields)
    except IntegrityError as exc:
        raise CompanyFenced(JOINING) from exc
    except (JournalError, ValueError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"join fence unavailable: {exc}") from exc


def release(fence_id: str, *, expected_phase: str = FENCED, engine: Any = None) -> bool:
    """Release a fence from ``expected_phase``; True when it was released by this call."""
    return move(fence_id, expected_phase, RELEASED, engine=engine)


__all__ = [
    "ACCEPTED",
    "ACTIVE",
    "COMPLETED",
    "FENCED",
    "JOINING",
    "REBOUND",
    "RELEASED",
    "CompanyFenced",
    "active",
    "cas",
    "destination_digest",
    "move",
    "place",
    "profile_key",
    "refuse_if_fenced",
    "refusal",
    "release",
]
