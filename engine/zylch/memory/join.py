"""Joining a company memory — the only write path for ``MEMORY_KEY`` after M2.

Entering an existing key from a profile that already holds a memory merges
two memories, as a fenced, crash-safe cutover. The merge is deterministic and
lossless (:mod:`zylch.memory.join_import`):

- **facts** with the same (category, key) converge to one row — the store
  being joined wins, it is the company's — and the value that does not
  win is kept in ``fact_history`` with the losing row's ``owner_id``, so
  the rollback can still return it to the profile it came from;
- **entities** from both memories are all kept; consolidation, which
  under a shared store runs once per company, folds the duplicates whose
  headers state the same identity;
- **rules** travel with their owner (``template:<owner>`` is personal), and
  only the joining account's own rules travel: another account's rules in the
  source stay there;
- sentences, versions, links, identifiers and aliases follow their blob, and a
  restriction the source journal records against a blob follows it too.

:func:`join` runs under the profile's join lock
(:mod:`zylch.memory.join_recover`), whose recovery body it runs first. With
``drain`` it then runs one ordinary memory pass of this profile inside a
bounded preparation run, before anything else: it resumes pending children and
lands the checkpoints of settled sources, and a paused or busy preparation
refuses the join with its own reason, paying nothing. Then it fences the
source company (:mod:`zylch.memory.mnemonic.fence`) and evaluates this
profile's journal there under the fence (:func:`blocking_work`): an undecided,
failed or reviewed row, a settled source whose checkpoint has not landed, or a
pending task-reference follow-up refuses the cutover, releases the fence and
answers the blocking rows with the verb that settles each; the ``.env`` is not
touched. Otherwise the ``.env`` names the destination in ``MEMORY_JOIN_TO``,
the import copies and accepts, and one write of the ``.env`` switches the key
(``MEMORY_KEY_SOURCE=join``, ``MEMORY_JOIN_FROM`` set), after which the
session factory is rebound to the joined store in-process (a restart is not
available to a headless daemon), the vector index follows the joined store's
mutation sequence, the source fence completes and ``MEMORY_JOIN_FROM`` is
cleared. The old store is left on disk, intact: it is the only copy of the
pre-join state. A profile with no store of its own switches the key with no
fence and no import.

``settings.update`` refuses ``MEMORY_KEY`` — a key written there would boot
the engine on a new store with no merge and orphan the old one.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import Engine

from zylch.memory.company_key import well_formed
from zylch.memory.store import (
    MemoryUnavailable,
    open_memory_engine,
    prepare_store,
    store_exists,
    store_summary,
)

logger = logging.getLogger(__name__)


def preview(key: str) -> Dict[str, Any]:
    """What joining ``key`` would join — echoed to the user before they commit.

    Never creates anything; an unknown key is ``{"exists": False}``.
    """
    ok, reason = well_formed(key)
    if not ok:
        return {"well_formed": False, "reason": reason, "exists": False}
    key = key.strip()
    if not store_exists(key):
        return {
            "well_formed": True,
            "exists": False,
            "reason": "no company memory exists for this key",
        }
    engine = open_memory_engine(key, create=False)
    try:
        return {"well_formed": True, "exists": True, "reason": "", **store_summary(engine)}
    finally:
        engine.dispose()


BLOCKED = (
    "this profile's memory work in the current company memory is not settled; "
    "settle each blocking operation and join again"
)
DRAIN = "zylch memory-join --drain"


def _verb(row: Dict[str, Any]) -> str:
    """The command that settles one blocking row."""
    from zylch.memory.mnemonic.ingestion import SOURCE_KINDS
    from zylch.memory.mnemonic.pairs import PAIR_SOURCE_KIND
    from zylch.memory.mnemonic.reviews import RETRY

    event_id = row["event_id"]
    dismiss = f"zylch memory-reviews --dismiss {event_id}"
    if row["state"] == "review":
        if RETRY in row.get("actions", ()):
            return f"zylch memory-reviews --retry {event_id} (or --dismiss)"
        return dismiss
    kind = str(row.get("source_ref") or "").split(":", 1)[0]
    if kind in SOURCE_KINDS or kind == PAIR_SOURCE_KIND:
        return f"{DRAIN} (or {dismiss})"
    return dismiss


_CHECKPOINTS = {
    "email": "Email",
    "whatsapp": "WhatsAppMessage",
    "calendar": "CalendarEvent",
    "mrcall": "MrcallConversation",
}


def _unprocessed(kind: str) -> set:
    """The ids of this profile's ``kind`` sources whose memory checkpoint has not landed."""
    from zylch.storage import models
    from zylch.storage.database import get_session

    model = getattr(models, _CHECKPOINTS[kind])
    with get_session() as session:
        rows = session.query(model.id).filter(model.memory_processed_at.is_(None)).all()
    return {str(r[0]) for r in rows}


def blocking_work(company_key: str) -> List[Dict[str, Any]]:
    """This profile's rows in ``company_key`` that a cutover must not leave behind.

    Owned by either identity of the profile; another account's rows never
    block. A row not terminal or in review (:func:`reviews.list_unsettled`), a
    ``committed`` or ``skipped`` ingestion parent whose source row exists in
    this profile with no memory checkpoint, and a ``committed`` row with a
    pending effect. Each answer names ``event_id``, ``state``, ``source_ref``
    and ``verb``, oldest first. Read in its own transaction: under the fence
    no row of any account can change between this and the import.
    """
    from sqlalchemy import func, or_

    from zylch.memory.mnemonic.authorization import _current_owners
    from zylch.memory.mnemonic.ingestion import PARENT_ID_PREFIX
    from zylch.memory.mnemonic.reviews import list_unsettled
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage.models import MemoryOperation

    found = [
        {"event_id": r["event_id"], "state": r["state"], "source_ref": r["source_ref"], "verb": _verb(r)}
        for r in list_unsettled(company_key)
    ]
    owners = sorted(_current_owners())
    with company_transaction() as session:
        settled = (
            session.query(
                MemoryOperation.event_id,
                MemoryOperation.state,
                MemoryOperation.source_ref,
                MemoryOperation.parent_event_id,
                MemoryOperation.pending_effects,
            )
            .filter(
                MemoryOperation.company_key == company_key,
                MemoryOperation.owner_id.in_(owners),
                MemoryOperation.state.in_(("committed", "skipped")),
                or_(
                    MemoryOperation.event_id.like(f"{PARENT_ID_PREFIX}%"),
                    func.json_array_length(MemoryOperation.pending_effects) > 0,
                ),
            )
            .order_by(MemoryOperation.created_at, MemoryOperation.event_id)
            .all()
        )
    unprocessed: Dict[str, set] = {}
    for event_id, state, source_ref, parent, effects in settled:
        ref = str(source_ref or "")
        kind, _, rest = ref.partition(":")
        if state == "committed" and effects:
            found.append({"event_id": event_id, "state": state, "source_ref": ref, "verb": DRAIN})
            continue
        if parent is not None or kind not in _CHECKPOINTS or not event_id.startswith(PARENT_ID_PREFIX):
            continue
        if kind not in unprocessed:
            unprocessed[kind] = _unprocessed(kind)
        if rest.rsplit("@", 1)[0] in unprocessed[kind]:
            found.append({"event_id": event_id, "state": state, "source_ref": ref, "verb": DRAIN})
    return found


def _drain(owner: str) -> Optional[str]:
    """One ordinary memory pass of this profile, admitted by preparation; the refusal, or ``None``."""
    import asyncio

    from zylch.services.preparation import PreparationStopped, company_fenced, preparation_run
    from zylch.services.process_pipeline import _run_memory
    from zylch.storage.storage import Storage

    try:
        with preparation_run(owner):
            asyncio.run(_run_memory(owner, Storage.get_instance()))
    except (PreparationStopped, company_fenced()) as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - a drain that failed refuses the join, visibly
        logger.error(f"[memory] join drain failed: {exc}", exc_info=True)
        return f"the memory pass before the join failed: {exc}"
    return None


def _open(key: str) -> Engine:
    from zylch.memory.join_recover import open_store

    return open_store(key)


def _abandon(fence_id: str) -> None:
    """Undo a join that did not cut over: its fence released, ``MEMORY_JOIN_TO`` cleared."""
    from zylch.memory.join_recover import JOIN_TO
    from zylch.memory.mnemonic import fence
    from zylch.services.settings_io import update_env

    try:
        fence.release(fence_id)
    finally:
        update_env({JOIN_TO: ""})


def join(key: str, *, drain: bool = False) -> Dict[str, Any]:
    """Join the company memory ``key`` names. Refuses an unknown or malformed key.

    Answers ``{ok, already, merged, …summary}``, or ``{ok: False, reason}``
    and, when this profile's unsettled work refused the cutover, ``blocking``:
    one entry per row, with its ``event_id``, ``state``, ``source_ref`` and the
    ``verb`` that settles it. ``drain`` runs one memory pass first (the CLI's
    ``--drain``; ``memory.join`` never pays for anything itself).
    """
    from zylch.memory.company_key import current_company_key
    from zylch.memory.join_recover import join_lock, recover_locked
    from zylch.storage import database as dbm

    ok, reason = well_formed(key)
    if not ok:
        return {"ok": False, "reason": reason}
    key = key.strip()
    if not store_exists(key):
        return {"ok": False, "reason": "no company memory exists for this key on this host"}
    current = current_company_key()
    if current == key:
        # Same key — but the store may not have existed when this profile
        # booted (a typed key, refused then; the colleague minted since).
        # A headless daemon has no restart to pick it up: attach now.
        if dbm.memory_unavailable_reason() is not None and store_exists(key):
            engine = open_memory_engine(key, create=False)
            prepare_store(engine, key, created_by=None)
            dbm.rebind_memory(engine)
            logger.info("[memory] attached the store for this profile's own key")
            return {
                "ok": True,
                "already": True,
                "attached": True,
                "merged": {},
                **store_summary(engine),
            }
        return {"ok": True, "already": True, "merged": {}}

    with join_lock():
        recover_locked()
        if current_company_key() == key:
            return {"ok": True, "already": True, "merged": {}}
        if drain:
            from zylch.cli.utils import get_owner_id

            refused = _drain(get_owner_id())
            if refused:
                return {"ok": False, "reason": refused}
        return _cut_over(key)


def _cut_over(key: str) -> Dict[str, Any]:
    """Fence, evaluate, import, switch — under the join lock."""
    from zylch.memory import join_import
    from zylch.memory.company_key import current_company_key, persist_company_key
    from zylch.memory.join_recover import JOIN_TO, finish
    from zylch.memory.mnemonic import fence
    from zylch.memory.mnemonic.authorization import _current_owners
    from zylch.services.settings_io import update_env
    from zylch.storage import database as dbm

    current = current_company_key()
    source = dbm.current_memory_engine()
    if source is None or not current or not store_exists(current):
        dst = _open(key)
        persist_company_key(key, source="join")
        dbm.rebind_memory(dst)
        logger.info("[memory] joined company memory (no store of this profile to merge)")
        return {"ok": True, "already": False, "merged": {}, **store_summary(dst)}
    owners = _current_owners()
    if not owners:
        return {"ok": False, "reason": "this profile names no account (EMAIL_ADDRESS or OWNER_ID)"}
    try:
        fence_id = fence.place(current, owners, key)
    except fence.CompanyFenced as exc:
        return {"ok": False, "reason": str(exc)}
    try:
        blocking = blocking_work(current)
    except Exception:
        fence.release(fence_id)
        raise
    if blocking:
        fence.release(fence_id)
        logger.info(f"[memory] join refused: {len(blocking)} unsettled operation(s)")
        return {"ok": False, "reason": BLOCKED, "blocking": blocking}
    try:
        update_env({JOIN_TO: key})
        dst = _open(key)
        merged = join_import.import_into(
            source, dst, fence_id, source_key=current, destination_key=key
        )
    except join_import.ImportRefused as exc:
        _abandon(fence_id)
        return {"ok": False, "reason": str(exc)}
    except Exception:
        _abandon(fence_id)
        raise
    finish(fence_id, current, key, dst)
    logger.info(f"[memory] joined company memory (merged={merged})")
    return {"ok": True, "already": False, "merged": merged, **store_summary(dst)}


def release_fence() -> Dict[str, Any]:
    """Release the ``fenced`` fence on the bound company, whoever placed it.

    Safe for any profile bound to the company: acceptance is a compare-and-set
    on the fence the import read, so a released fence is never accepted. An
    ``accepted`` fence is refused here; only its own profile's recovery
    releases or completes it.
    """
    from zylch.memory.company_key import current_company_key
    from zylch.memory.mnemonic import fence
    from zylch.memory.mnemonic.session import company_transaction

    key = current_company_key()
    if not key:
        return {"ok": False, "reason": "this profile is bound to no company memory"}
    with company_transaction() as session:
        held = fence.active(session, key)
    if held is None:
        return {"ok": False, "reason": "no join fence holds this company memory"}
    if held["phase"] != fence.FENCED:
        return {
            "ok": False,
            "reason": "an accepted join fence is finished by its own profile's recovery, never released here",
        }
    if not fence.release(held["id"]):
        return {"ok": False, "reason": "the join fence moved meanwhile; look again"}
    return {"ok": True, "released": True}


def status() -> Dict[str, Any]:
    """Is memory available for this profile, and if not, why. No paths.

    ``joining`` says whether an active join fence holds the bound company, and
    ``joining_reason`` says why its writes are refused while it does. Neither
    names the destination: not its key, not its digest.
    """
    from zylch.memory.company_key import current_company_key
    from zylch.storage import database as dbm

    key = current_company_key()
    reason = dbm.memory_unavailable_reason()
    out: Dict[str, Any] = {
        "has_key": key is not None,
        "available": reason is None,
        "reason": reason or "",
    }
    if reason is None:
        engine = dbm.current_memory_engine()
        if engine is not None:
            try:
                out.update(store_summary(engine))
                out.update(_joining(key))
            except MemoryUnavailable as e:
                out.update({"available": False, "reason": e.reason})
    return out


def _joining(key: Optional[str]) -> Dict[str, Any]:
    """Whether an active join fence holds the bound company, and the refusal it answers."""
    from zylch.memory.mnemonic.fence import JOINING, active
    from zylch.memory.mnemonic.session import company_transaction

    with company_transaction() as session:
        fenced = bool(key) and active(session, key) is not None
    return {"joining": True, "joining_reason": JOINING} if fenced else {"joining": False}
