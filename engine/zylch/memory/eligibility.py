"""Read eligibility for company FACT rows: which ones ordinary reads may use.

Retaining a legacy row's readability does not make a **known customer-shaped
FACT** eligible as global knowledge. A row in the facts family is ineligible
when one of two things is true, and nothing else:

- its own header states an explicit structured mismatch — ``Scope: entity`` or
  ``Scope: account``, or an ``Entity type`` of PERSON, COMPANY or STYLE — so the
  row itself says it is not company-wide knowledge;
- a row of the operation journal names its blob id in ``restrictions``,
  whatever that row's state. A review writes one when the mnemonic role was
  shown the row, declined to treat it as company knowledge, and the harness
  recorded that against the exact identity and observed version
  (``mnemonic/commit.restrictions_from``); the row keeps it when it settles
  otherwise, so a review the owner dismissed (state ``skipped``) and a join
  receipt that carries a source store's restrictions into the destination
  (state ``committed``) keep the restricted row ineligible.

The predicate is applied *before* ranking and limits — in the fact store's
category enumeration and reads, and in hybrid search at index load, text
search and hydration — so a quarantined row cannot crowd a valid one out of
the top-K. It never classifies: a read path makes no paid call and writes no
marker; a restriction exists only because a review wrote it, or a join
carried one a review wrote, and it stays on its row whatever the row becomes:
no resolution clears it. A version change does not clear it either — the
restriction is keyed by blob id, and the recorded version is evidence of what
was seen, not the key.

Exact-id reads (``BlobStorage.get_blob``) are not filtered: candidate pinning
and ``update_memory``'s hint read by id, and no prompt-assembly path reads a
FACT by id — facts reach prompts only through the reads covered here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from sqlalchemy import func
from sqlalchemy.orm import Session

from zylch.storage.models import Blob, MemoryOperation

FACTS_FAMILY = "facts"
_ENTITY_SCOPES = ("entity", "account")
_ENTITY_TYPES = ("PERSON", "COMPANY", "STYLE")


def scope_mismatch(content: str) -> bool:
    """Does this facts-family row's own header say it is not company knowledge?"""
    # Deferred: the mnemonic package imports the workers, which import this
    # package, so a module-level import here would be a cycle. One parser,
    # not a second copy of it.
    from .mnemonic.candidates import parse_header

    header = parse_header(content or "")
    scope = (header.get("scope") or "").strip().lower()
    entity_type = (header.get("entity type") or "").strip().upper()
    return scope in _ENTITY_SCOPES or entity_type in _ENTITY_TYPES


def restriction_entries(session: Session, company_key: str) -> List[Dict[str, Any]]:
    """Every restriction entry any row of this company's journal records, in any state.

    Each entry names a ``blob_id`` (and the version the review observed).
    Filtered in SQL to the rows whose ``restrictions`` is not empty, which keeps
    the read off the rest of the journal. The join import carries the entries
    against the blobs it copies onto its receipt in the destination.
    """
    rows = (
        session.query(MemoryOperation.restrictions)
        .filter(
            MemoryOperation.company_key == company_key,
            MemoryOperation.restrictions.isnot(None),
            func.json_array_length(MemoryOperation.restrictions) > 0,
        )
        .all()
    )
    return [
        dict(entry)
        for (entries,) in rows
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("blob_id")
    ]


def restricted_ids(session: Session, company_key: str) -> Set[str]:
    """Blob ids any row of this company's journal has restricted, in any state.

    Filtered in SQL to the rows whose ``restrictions`` is not empty, which keeps
    the read off the rest of the journal.
    """
    return {str(entry["blob_id"]) for entry in restriction_entries(session, company_key)}


def ineligible_fact_ids(session: Session, company_key: str) -> Set[str]:
    """Every facts-family row this company's ordinary reads must leave out.

    One read over the facts family (small: tens to hundreds of rows) and one
    over the journal rows that carry restrictions, in the caller's own session
    — no second transaction, no paid call, no marker written anywhere.
    """
    rows = (
        session.query(Blob.id, Blob.content)
        .filter(Blob.company_key == company_key, Blob.namespace.like(f"{FACTS_FAMILY}:%"))
        .all()
    )
    mismatched = {str(row.id) for row in rows if scope_mismatch(row.content or "")}
    return mismatched | restricted_ids(session, company_key)


__all__ = ["ineligible_fact_ids", "restricted_ids", "restriction_entries", "scope_mismatch"]
