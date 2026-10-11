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

from zylch.memory.company_key import require_company_key
from zylch.memory.store import memory_db_path
from zylch.storage import database as dbm

logger = logging.getLogger(__name__)

# Defaults every profile without the identity shares (cli.utils.get_owner_id,
# config.Settings.owner_id): they name no account.
STAND_INS = ("local-user", "owner_default")


def delete_owned_rules(owner_id: str, *, last_holder: bool = False) -> int:
    """Delete ``owner_id``'s personal rows from the bound company store.

    Delegates to :meth:`BlobStorage.delete_all_blobs`, the one per-account
    reset, with the predicate chosen by ``last_holder`` (the helper's
    group-membership fact), never by row presence: not the last holder →
    only this account's rule rows (``blob_owned_rules``), company-family
    contributions stay with provenance; last holder → everything, and the
    file goes too. Returns the count."""
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session

    require_company_key()
    if dbm.current_memory_engine() is None:
        raise RuntimeError(f"memory unavailable: {dbm.memory_unavailable_reason()}")
    count = BlobStorage(get_session, None).delete_all_blobs(owner_id, sole_holder=last_holder)
    logger.info(f"[offboard] rows removed={count}")
    return count


def delete_account_rules(owners, *, last_holder: bool = False) -> int:
    """Delete the rule rows of every identity the profile names its account by.

    A profile names its account twice (``mnemonic.authorization._current_owners``):
    ``EMAIL_ADDRESS``, which chat and the RPC handlers put on the rules they
    write, and ``OWNER_ID``, the Firebase uid a path without a session falls
    back to (``ToolConfig.from_settings``). Offboarding by one of them leaves
    the other's rules behind with no profile left to remove them.

    ``owners`` is a collection of identities, never one string (iterating a
    string would offboard its characters). Blank values and the shared
    stand-ins, which name no account, are refused."""
    if isinstance(owners, str):
        raise TypeError("owners must be a collection of identities, not one string")
    cleaned = sorted({str(owner).strip() for owner in owners})
    if not cleaned or any(owner in ("", *STAND_INS) for owner in cleaned):
        raise ValueError("refusing to offboard a blank or stand-in identity")
    return sum(delete_owned_rules(owner, last_holder=last_holder) for owner in cleaned)


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
