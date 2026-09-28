"""Test-only seeding of memory rows: the one door a test uses to put a blob in place.

A test that needs memory to exist before it runs the harness seeds it here
rather than calling a storage writer itself, so every test seeds through one
module. ``store_blob`` and ``update_blob`` were ``BlobStorage``'s legacy
writers, and ``add_person_identifiers`` and the three ``add_*_blob_link``
were ``Storage``'s — they opened their own session, decided their own
transaction boundary and trusted whoever called them — until milestone 8 took
them out of production: no production code called them any more, and a
writer that trusts its caller is exactly the bypass the sealed boundary
refuses. They live here now, under ``tests/``, over the same internals the
committed writers use (``prepare``, ``_insert``, ``_rewrite``, and the
:mod:`zylch.memory.associations` rules); nothing under ``zylch/`` or
``scripts/`` imports this module (``test_mnemonic_write_boundary.py``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from zylch.memory.blob_commits import _iso
from zylch.memory.blob_versions import APPEND
from zylch.memory.company_key import require_company_key
from zylch.memory.scope import blob_visible
from zylch.storage.database import get_session
from zylch.storage.models import Blob

logger = logging.getLogger(__name__)


def store_blob(
    storage: Any,
    owner_id: str,
    namespace: str,
    content: str,
    event_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Store new blob with sentence embeddings.

    Returns the created blob record.
    """
    prepared = storage.prepare(content)
    with storage._get_session() as session:
        blob = storage._insert(
            session,
            owner_id=owner_id,
            namespace=namespace,
            prepared=prepared,
            event_description=event_description,
        )
        storage._notify_mutation(session)
        return blob.to_dict()


def update_blob(
    storage: Any,
    blob_id: str,
    owner_id: str,
    content: str,
    event_description: Optional[str] = None,
    expected_updated_at: Optional[str] = None,
    reason: str = APPEND,
) -> Dict[str, Any]:
    """Update blob content and regenerate sentence embeddings.

    Compare-and-swap: the caller read the blob, merged new facts into
    it (an LLM call taking seconds — never inside a transaction), and
    now writes back. With ``expected_updated_at`` set to the value it
    read, a blob that another writer changed in between is NOT
    overwritten: the return carries ``conflict: True`` plus the
    current row, and the caller re-merges onto that. The transaction
    takes the store's write lock as its first statement, so the
    check and the write happen under one lock.

    Returns ``{}`` when the blob is not visible to this owner.
    """
    # Generate new embeddings before entering transaction
    prepared = storage.prepare(content)

    key = require_company_key()
    with storage._get_session() as session:
        # Hold the store's write lock across read + compare + write.
        try:
            from zylch.memory.store import take_write_lock

            take_write_lock(session)
        except Exception as e:  # a store without the meta row (tests, legacy)
            logger.debug(f"[seeding] write-lock upgrade skipped: {e}")
        blob = (
            session.query(Blob)
            .filter(Blob.id == blob_id, blob_visible(owner_id, key))
            .one_or_none()
        )

        if blob is None:
            logger.warning(
                f"update_blob: blob {blob_id} is not visible to owner {owner_id} "
                f"(missing, or another account's rule)"
            )
            return {}

        if expected_updated_at is not None and _iso(blob.updated_at) != _iso(
            expected_updated_at
        ):
            logger.info(
                f"update_blob: blob {blob_id} changed since it was read "
                f"(expected {expected_updated_at}, now {_iso(blob.updated_at)}) — conflict"
            )
            current = blob.to_dict()
            current["conflict"] = True
            return current

        storage._rewrite(
            session,
            blob,
            owner_id=owner_id,
            prepared=prepared,
            event_description=event_description,
            reason=reason,
        )
        storage._notify_mutation(session)
        return blob.to_dict()


def _link_source(source_kind: str, source_id: str, blob_id: str, owner_id: str) -> bool:
    """One standalone-session link, for the writers not yet converted.

    The rule itself lives in :mod:`zylch.memory.associations`, which the
    semantic commit calls inside its own transaction. These legacy callers
    keep their own session and their own swallow-and-log behavior; what
    they must not keep is a second copy of the rule.
    """
    from zylch.memory.associations import link_source

    try:
        with get_session() as session:
            return link_source(
                session,
                source_kind=source_kind,
                source_id=source_id,
                blob_id=blob_id,
                owner_id=owner_id,
            )
    except Exception as e:
        logger.error(f"add_{source_kind}_blob_link({source_id}, {blob_id}) failed: {e}")
        return False


def add_email_blob_link(owner_id: str, email_id: str, blob_id: str) -> bool:
    """Idempotent (email_id, blob_id) link. Returns True when inserted."""
    return _link_source("email", email_id, blob_id, owner_id)


def add_calendar_blob_link(owner_id: str, event_id: str, blob_id: str) -> bool:
    """Idempotent (event_id, blob_id) link. Returns True when inserted."""
    return _link_source("calendar", event_id, blob_id, owner_id)


def add_whatsapp_blob_link(owner_id: str, whatsapp_message_id: str, blob_id: str) -> bool:
    """Idempotent (whatsapp_message_id, blob_id) link. Returns True when inserted."""
    return _link_source("whatsapp", whatsapp_message_id, blob_id, owner_id)


def add_person_identifiers(owner_id: str, blob_id: str, identifiers: List[tuple]) -> int:
    """Bulk add identifier rows for a blob.

    Args:
        owner_id: Profile owner.
        blob_id: Blob the identifiers belong to.
        identifiers: List of (kind, value) tuples. kind ∈ {'email','phone','lid'}.
            Values should be already normalised by the caller (lowercased
            emails, digit-only phones with optional leading '+', etc.).
            Empty / None values are skipped.

    Returns:
        Number of NEW rows inserted (existing rows are silently no-op'd
        via the unique constraint).
    """
    if not (owner_id and blob_id and identifiers):
        return 0
    from zylch.memory.associations import add_identifiers

    try:
        with get_session() as session:
            inserted = add_identifiers(
                session,
                owner_id=owner_id,
                blob_id=blob_id,
                identifiers=identifiers,
                company_key=require_company_key(),
            )
            if inserted:
                # identifiers are what the reconsolidation sweep clusters
                # on: a new one can make two blobs a merge candidate, so
                # it counts as a change the next sweep must see
                try:
                    from zylch.memory.store import bump_mutation_seq

                    bump_mutation_seq(session)
                except Exception as e:  # a store without the meta row (legacy tests)
                    logger.debug(f"add_person_identifiers: mutation_seq bump skipped: {e}")
            return inserted
    except Exception as e:
        logger.warning(f"add_person_identifiers(blob={blob_id}) failed: {e}")
        return 0


__all__ = [
    "add_calendar_blob_link",
    "add_email_blob_link",
    "add_person_identifiers",
    "add_whatsapp_blob_link",
    "store_blob",
    "update_blob",
]
