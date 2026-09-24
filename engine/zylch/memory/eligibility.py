"""Read eligibility for company FACT rows: which ones ordinary reads may use.

Retaining a legacy row's readability does not make a **known customer-shaped
FACT** eligible as global knowledge. A row in the facts family is ineligible
when one of two things is true, and nothing else:

- its own header states an explicit structured mismatch — ``Scope: entity`` or
  ``Scope: account``, or an ``Entity type`` of PERSON, COMPANY or STYLE — so the
  row itself says it is not company-wide knowledge;
- a review recorded in the operation journal names its blob id in
  ``restrictions``: the mnemonic role was shown the row, declined to treat it
  as company knowledge, and the harness recorded that against the exact
  identity and observed version (``mnemonic/commit.restrictions_from``).

The predicate is applied *before* ranking and limits — in the fact store's
category enumeration and reads, and in hybrid search at index load, text
search and hydration — so a quarantined row cannot crowd a valid one out of
the top-K. It never classifies: a read path makes no paid call and writes no
marker; a restriction exists only because a review wrote it, and it stays
until an authorized resolution clears it (none does in this milestone). A
version change does not clear it — the restriction is keyed by blob id, and
the recorded version is evidence of what was seen, not the key.

Exact-id reads (``BlobStorage.get_blob``) are not filtered: candidate pinning
and ``update_memory``'s hint read by id, and no prompt-assembly path reads a
FACT by id — facts reach prompts only through the reads covered here.
"""

from __future__ import annotations

from typing import Set

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


def restricted_ids(session: Session, company_key: str) -> Set[str]:
    """Blob ids a review in this company's journal has restricted."""
    rows = (
        session.query(MemoryOperation.restrictions)
        .filter(
            MemoryOperation.company_key == company_key,
            MemoryOperation.state == "review",
        )
        .all()
    )
    found: Set[str] = set()
    for (entries,) in rows:
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("blob_id"):
                found.add(str(entry["blob_id"]))
    return found


def ineligible_fact_ids(session: Session, company_key: str) -> Set[str]:
    """Every facts-family row this company's ordinary reads must leave out.

    One read over the facts family (small: tens to hundreds of rows) and one
    over the review rows, in the caller's own session — no second transaction,
    no paid call, no marker written anywhere.
    """
    rows = (
        session.query(Blob.id, Blob.content)
        .filter(Blob.company_key == company_key, Blob.namespace.like(f"{FACTS_FAMILY}:%"))
        .all()
    )
    mismatched = {str(row.id) for row in rows if scope_mismatch(row.content or "")}
    return mismatched | restricted_ids(session, company_key)


__all__ = ["ineligible_fact_ids", "restricted_ids", "scope_mismatch"]
