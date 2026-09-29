"""Leaving a company memory (plan M2.8).

A profile that is deleted from a host takes only what is personal: its
rule rows (``template:<owner>``, ``prefs:<owner>``, the
:func:`zylch.memory.scope.blob_owned_rules` predicate). Company-family rows
it wrote stay, ``owner_id`` on them being provenance, not a wall
(AGENTS.md). The store file itself goes only with the company's last key
holder, a fact the host helper establishes from group membership, never
from this module.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import sessionmaker

from zylch.memory.blob_versions import prune_versions
from zylch.memory.company_key import require_company_key
from zylch.memory.scope import blob_owned_rules
from zylch.memory.store import memory_db_path
from zylch.storage import database as dbm
from zylch.storage.models import Blob

logger = logging.getLogger(__name__)


def delete_owned_rules(owner_id: str) -> int:
    """Delete ``owner_id``'s rule rows (and their versions) from the bound
    company store. Company-family rows are untouched. Returns the count."""
    key = require_company_key()
    engine = dbm.current_memory_engine()
    if engine is None:
        raise RuntimeError(f"memory unavailable: {dbm.memory_unavailable_reason()}")
    predicate = blob_owned_rules(owner_id, key)
    with sessionmaker(bind=engine)() as session:
        ids = [row.id for row in session.query(Blob.id).filter(predicate).all()]
        count = session.query(Blob).filter(predicate).delete(synchronize_session=False)
        pruned = prune_versions(session, ids)
        session.commit()
    logger.info(f"[offboard] owner rules removed={count} versions pruned={pruned}")
    return count


def delete_store(company_key: str) -> str | None:
    """Delete the company store file and its sidecars. The caller has
    established that no other profile holds this key. Returns the path
    removed, or None when there was no file."""
    path = memory_db_path(company_key)
    engine = dbm.current_memory_engine()
    if engine is not None:
        engine.dispose()
    dbm.set_memory_engine(None, "store deleted at offboarding")
    if not os.path.isfile(path):
        return None
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass
    logger.info("[offboard] company store deleted (last key holder)")
    return path
