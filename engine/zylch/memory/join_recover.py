"""The join's crash states, told apart and finished — at boot and at the start of every join.

A join moves a profile's key from one company memory to another in five steps
(:mod:`zylch.memory.join`). The profile's ``.env`` carries what a restart needs
to know which step it stopped at:

1. after the source fence is placed and the evaluation passes:
   ``MEMORY_JOIN_TO=<destination key>``;
2. the import and the acceptance (:mod:`zylch.memory.join_import`);
3. one write: ``MEMORY_KEY=<destination>``, ``MEMORY_KEY_SOURCE=join``,
   ``MEMORY_JOIN_FROM=<source key>``, ``MEMORY_JOIN_TO=`` (empty);
4. the process rebinds to the destination;
5. the source fence moves to ``completed``; then ``MEMORY_JOIN_FROM=`` (empty).

:func:`recover_locked` reads the ``.env`` on disk and this profile's fences:

- **before the key** — ``MEMORY_JOIN_TO`` is set and the bound (source) store
  holds this profile's active fence for that destination. An ``accepted`` fence
  runs steps 3–5. A ``fenced`` one whose import receipt is in the destination
  with a digest the source still matches is accepted (the import is not
  repeated) and then steps 3–5 run; otherwise the fence is released,
  ``MEMORY_JOIN_TO`` cleared, and the profile stays on the source.
- **after the key** — ``MEMORY_JOIN_FROM`` is set: the process is bound to the
  destination (a boot binds it; a live process is rebound here), this
  profile's ``accepted`` fence in the source is set ``completed`` and
  ``MEMORY_JOIN_FROM`` cleared. Idempotent.
- **completed** — neither is set; a ``fenced`` fence of this profile left in the
  bound store by a crash before step 1 is released.

"This profile's" fence is one whose recorded identities meet the identities the
profile states (``authorization._current_owners``). One lock serialises a join
and its recovery: the profile's join lock, beside the profile's own database
with the suffix :data:`LOCK_SUFFIX`. A join holds it for its whole run and calls
:func:`recover_locked` itself; :func:`recover`, at engine boot after the store
is attached, takes it without waiting and does nothing when another process
holds it, so a command booting beside a running join never touches that join's
fence or ``.env``. Only the lock holder writes the ``MEMORY_JOIN_*`` settings.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import Engine

logger = logging.getLogger(__name__)

JOIN_TO = "MEMORY_JOIN_TO"
JOIN_FROM = "MEMORY_JOIN_FROM"
LOCK_SUFFIX = ".join.lock"


def lock_path() -> str:
    """The profile's own database file, beside which its join lock lives."""
    from zylch.storage.database import _resolve_db_path

    return _resolve_db_path()


@contextmanager
def join_lock(*, wait: bool = True) -> Iterator[bool]:
    """Hold the profile's join lock; yields ``False`` without it when ``wait`` is off and it is held."""
    from zylch.storage.migrations import DEFAULT_LOCK_TIMEOUT_S, MigrationLockTimeout, db_file_lock

    held = db_file_lock(
        lock_path(), timeout_s=DEFAULT_LOCK_TIMEOUT_S if wait else 0.0, suffix=LOCK_SUFFIX
    )
    try:
        held.__enter__()
    except MigrationLockTimeout:
        if wait:
            raise
        yield False
        return
    try:
        yield True
    finally:
        held.__exit__(None, None, None)


def recover() -> Dict[str, Any]:
    """Boot's recovery: finish or undo an interrupted join of this profile, if the lock is free.

    Called by ``storage.database`` once the company store is attached. A
    process with no active profile has nothing to recover. Another process
    holding the join lock is running a join (or its recovery): nothing is
    touched. A recovery that fails is logged and answered as ``failed``, and
    the boot goes on bound to whichever store the ``.env`` names, where an
    active fence still refuses every write.
    """
    if _profile_env() is None:
        return {"state": "none"}
    try:
        with join_lock(wait=False) as held:
            if not held:
                logger.info("[join] recovery skipped: another process holds this profile's join lock")
                return {"state": "busy"}
            return recover_locked()
    except Exception as exc:  # noqa: BLE001 - a boot serves the bound store; the fence still refuses
        logger.error(f"[join] recovery failed: {exc}", exc_info=True)
        return {"state": "failed", "reason": str(exc)}


def recover_locked() -> Dict[str, Any]:
    """The recovery body, for a caller that already holds the profile's join lock."""
    env = _profile_env()
    if env is None:
        return {"state": "none"}
    joined_from = (env.get(JOIN_FROM) or "").strip()
    joining_to = (env.get(JOIN_TO) or "").strip()
    if joined_from:
        return _after_key(joined_from, (env.get("MEMORY_KEY") or "").strip())
    if joining_to:
        return _before_key(joining_to)
    return _stray()


def _profile_env() -> Optional[Dict[str, str]]:
    from zylch.services.settings_io import read_env

    try:
        return read_env()
    except RuntimeError:
        return None


def _owners() -> frozenset:
    from zylch.memory.mnemonic.authorization import _current_owners

    return _current_owners()


def _mine(fence: Dict[str, Any], owners: frozenset) -> bool:
    return bool(owners & {str(o) for o in fence.get("owner_ids") or []})


def _fences(company_key: str, engine: Optional[Engine] = None, *, phases=None):
    """This company's fences in ``phases`` that belong to this profile, oldest first."""
    from zylch.memory.mnemonic.fence import ACTIVE
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage.join_fence_model import MemoryJoinFence

    owners = _owners()
    with company_transaction(engine=engine) as session:
        rows = (
            session.query(MemoryJoinFence)
            .filter(
                MemoryJoinFence.company_key == company_key,
                MemoryJoinFence.phase.in_(phases or ACTIVE),
            )
            .order_by(MemoryJoinFence.created_at, MemoryJoinFence.id)
            .all()
        )
        return [row.to_dict() for row in rows if _mine(row.to_dict(), owners)]


def open_store(key: str) -> Engine:
    """An engine on an existing company store, brought to the current schema."""
    from zylch.memory.store import open_memory_engine, prepare_store

    engine = open_memory_engine(key, create=False)
    prepare_store(engine, key, created_by=None)
    return engine


def _clear(name: str) -> None:
    from zylch.services.settings_io import update_env

    update_env({name: ""})


# ─── Steps 3–5 ────────────────────────────────────────────────────────


def finish(
    fence_id: str, source_key: str, destination_key: str, destination: Optional[Engine] = None
) -> Engine:
    """Steps 3–5 for an ``accepted`` fence: the key, the rebind, the completion. Returns the bound engine."""
    from zylch.memory.company_key import persist_company_key
    from zylch.storage import database as dbm

    engine = destination if destination is not None else open_store(destination_key)
    persist_company_key(
        destination_key, source="join", also={JOIN_FROM: source_key, JOIN_TO: ""}
    )
    dbm.rebind_memory(engine)
    _complete(fence_id, source_key)
    _clear(JOIN_FROM)
    logger.info(f"[join] cutover finished under fence {fence_id[:8]}…")
    return engine


def _complete(fence_id: str, source_key: str) -> bool:
    """The source fence ``accepted`` → ``completed``, in the source store the process has left."""
    from zylch.memory.mnemonic import fence
    from zylch.memory.store import open_memory_engine

    engine = open_memory_engine(source_key, create=False)
    try:
        return fence.move(fence_id, fence.ACCEPTED, fence.COMPLETED, engine=engine)
    finally:
        engine.dispose()


# ─── The three states ─────────────────────────────────────────────────


def _before_key(destination_key: str) -> Dict[str, Any]:
    from zylch.memory import join_import
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic import fence
    from zylch.memory.store import store_exists
    from zylch.storage import database as dbm

    source_key = current_company_key()
    source = dbm.current_memory_engine()
    wanted = fence.destination_digest(destination_key)
    held = (
        [f for f in _fences(source_key) if f["destination_digest"] == wanted]
        if source is not None and source_key
        else []
    )
    if not held:
        _clear(JOIN_TO)
        return {"state": "before_key", "action": "cleared"}
    current = held[0]
    if current["phase"] == fence.ACCEPTED:
        finish(current["id"], source_key, destination_key)
        return {"state": "before_key", "action": "finished"}
    destination = open_store(destination_key) if store_exists(destination_key) else None
    if destination is not None and join_import.receipt_digest(destination, current["id"]):
        try:
            join_import.import_into(
                source, destination, current["id"],
                source_key=source_key, destination_key=destination_key,
            )
        except join_import.ImportRefused as exc:
            destination.dispose()
            fence.release(current["id"])
            _clear(JOIN_TO)
            logger.warning(f"[join] the interrupted join was not accepted: {exc}")
            return {"state": "before_key", "action": "released", "reason": str(exc)}
        finish(current["id"], source_key, destination_key, destination)
        return {"state": "before_key", "action": "accepted"}
    if destination is not None:
        destination.dispose()
    fence.release(current["id"])
    _clear(JOIN_TO)
    return {"state": "before_key", "action": "released", "reason": "the import never finished"}


def _after_key(source_key: str, key: str) -> Dict[str, Any]:
    from zylch.memory.mnemonic import fence
    from zylch.memory.store import memory_db_path, open_memory_engine, store_exists
    from zylch.storage import database as dbm

    bound = dbm.current_memory_engine()
    if key and (bound is None or bound.url.database != memory_db_path(key)):
        dbm.rebind_memory(open_store(key))
    completed = False
    if store_exists(source_key):
        engine = open_memory_engine(source_key, create=False)
        try:
            wanted = fence.destination_digest(key)
            for held in _fences(source_key, engine, phases=(fence.ACCEPTED,)):
                if held["destination_digest"] == wanted:
                    completed = _complete(held["id"], source_key) or completed
        finally:
            engine.dispose()
    _clear(JOIN_FROM)
    return {"state": "after_key", "completed": completed}


def _stray() -> Dict[str, Any]:
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic import fence
    from zylch.storage import database as dbm

    key = current_company_key()
    if not key or dbm.current_memory_engine() is None:
        return {"state": "completed", "released": 0}
    released = 0
    for held in _fences(key, phases=(fence.FENCED,)):
        released += int(fence.release(held["id"]))
    if released:
        logger.info(f"[join] released {released} stray join fence(s) of this profile")
    return {"state": "completed", "released": released}


__all__ = [
    "JOIN_FROM",
    "JOIN_TO",
    "LOCK_SUFFIX",
    "finish",
    "join_lock",
    "open_store",
    "recover",
    "recover_locked",
]
