"""Reading the operation journal, scoped like the memory it describes.

An operation row carries the raw observation that produced a memory, so who may
read it is decided here, once, for every reader: :func:`visible` is the wall and
:func:`read` answers one row through it. :mod:`~zylch.memory.mnemonic.journal`
re-exports both, so a caller keeps reading them from the journal.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from zylch.memory.company_key import COMPANY_FAMILIES
from zylch.storage.models import MemoryOperation

from .session import JournalError, company_transaction


def visible(row: MemoryOperation, owner_id: str, company_key: str) -> bool:
    """May this account read this operation?

    The same wall ``memory/scope.blob_visible`` puts around a blob, hung the
    other way round. A blob defaults to visible and rule namespaces are carved
    out of it; an operation defaults to **private to its submitter** and only a
    decided company-family target opens it to the rest of the company.

    The asymmetry is the payload. A blob's content is already the committed
    memory; an operation carries the raw observation that produced it, and
    until the role has said which family it belongs to, nothing knows whether
    that text is company knowledge or one account's private correction.
    """
    if row.company_key != company_key:
        return False
    if row.owner_id == owner_id:
        return True
    return (row.target_family or "") in COMPANY_FAMILIES


def read(event_id: str, *, owner_id: str, company_key: str) -> Optional[Dict[str, Any]]:
    """One operation as a dict, or ``None`` when absent or not visible."""
    try:
        with company_transaction() as session:
            row = session.get(MemoryOperation, event_id)
            if row is None or not visible(row, owner_id, company_key):
                return None
            return row.to_dict()
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


__all__ = ["read", "visible"]
