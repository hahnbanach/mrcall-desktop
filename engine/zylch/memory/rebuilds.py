"""Mechanical rebuilds of company-memory indexes from the rows they index.

Two rebuilds, each a reviewed mechanical primitive with a fixed precondition.
Neither makes a semantic decision and neither writes a blob:

- :func:`reindex_identifiers` — the identity index (``person_identifiers``)
  from the exact ``#IDENTIFIERS`` entries of the PERSON and COMPANY rows the
  profile can see, parsed by the one parser a commit uses
  (:func:`zylch.memory.mnemonic.wiring.parse_identifiers_block`) and written
  through :func:`zylch.memory.associations.add_identifiers`. Nothing else is
  indexed: a row with no ``Entity type`` of PERSON or COMPANY, or no
  identifier, is left alone. Dry run by default.
- :func:`rebuild_source_links` — the ``email_blobs`` / ``calendar_blobs``
  links from the legacy ``blob.events`` descriptions, once per boot. A
  calendar description names an event by its summary; it is linked only when
  exactly one of this profile's events carries that summary, and an ambiguous
  summary is counted and left unlinked.

Every rebuild runs in one transaction and takes a digest of the rows it must
not change — ``id``, ``owner_id``, ``namespace``, ``company_key`` and
``content`` of the company's blobs — before and after (:func:`guarded`). A
difference raises :class:`RebuildTampered` inside the transaction, which rolls
back everything the rebuild wrote.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

from sqlalchemy.orm import Session

from zylch.storage.models import Blob

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("PERSON", "COMPANY")

_EMAIL_EVENT = re.compile(r"^Extracted from email\s+([^\s()]+)(?:\s*\(.*\))?\s*$", re.IGNORECASE)
_CALENDAR_EVENT = re.compile(r"^Extracted from calendar event\s+'(.+?)'\s*\(.*\)\s*$", re.IGNORECASE)


class RebuildTampered(RuntimeError):
    """A rebuild changed a row it must not change; its transaction is rolled back."""


def scope_digest(session: Session, company_key: str) -> str:
    """sha256 over ``id``, ``owner_id``, ``namespace``, ``company_key``, ``content`` of the company's blobs."""
    digest = hashlib.sha256()
    rows = (
        session.query(Blob.id, Blob.owner_id, Blob.namespace, Blob.company_key, Blob.content)
        .filter(Blob.company_key == company_key)
        .order_by(Blob.id)
    )
    for row in rows:
        digest.update(repr(tuple(row)).encode("utf-8") + b"\n")
    return digest.hexdigest()


@contextmanager
def guarded(session: Session, company_key: str) -> Iterator[None]:
    """Run a rebuild's writes between two digests of the rows it must not change.

    Raises :class:`RebuildTampered` when they differ; the caller's transaction
    then rolls back.
    """
    before = scope_digest(session, company_key)
    yield
    session.flush()
    if scope_digest(session, company_key) != before:
        raise RebuildTampered(
            "a rebuild changed a blob's id, owner, namespace, company or content; rolled back"
        )


# ─── The identity index ───────────────────────────────────────────────


def entity_type(content: str) -> str:
    """The ``Entity type`` a blob's ``#IDENTIFIERS`` block states, upper case; '' when none."""
    inside = False
    for raw in (content or "").splitlines():
        line = raw.strip()
        if line.upper().startswith("#IDENTIFIERS"):
            inside = True
            continue
        if inside and line.startswith("#"):
            break
        if inside and line.lower().startswith("entity type:"):
            return line.split(":", 1)[1].strip().upper()
    return ""


def reindex_identifiers(owner_id: str, *, apply: bool = False) -> Dict[str, int]:
    """Index the exact identifiers of the PERSON and COMPANY rows ``owner_id`` can see.

    Answers ``{"entities", "missing", "indexed"}``: the rows read, the
    identifier rows the index lacks, and the rows written (0 on a dry run).
    With ``apply`` the rows are written through ``add_identifiers`` and the
    mutation sequence is bumped once when any was.
    """
    from zylch.memory import associations
    from zylch.memory.company_key import entity_namespace, require_company_key
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.memory.mnemonic.wiring import parse_identifiers_block
    from zylch.memory.scope import blob_visible
    from zylch.memory.store import bump_mutation_seq
    from zylch.storage.models import PersonIdentifier

    key = require_company_key()
    counts = {"entities": 0, "missing": 0, "indexed": 0}
    with company_transaction(write=apply) as session:
        with guarded(session, key):
            rows = (
                session.query(Blob.id, Blob.content)
                .filter(blob_visible(owner_id, key), Blob.namespace == entity_namespace(key))
                .order_by(Blob.id)
                .all()
            )
            for blob_id, content in rows:
                if entity_type(content) not in ENTITY_TYPES:
                    continue
                identifiers = associations.identifiers_from(parse_identifiers_block(content))
                if not identifiers:
                    continue
                counts["entities"] += 1
                present = {
                    (str(k), str(v))
                    for k, v in session.query(PersonIdentifier.kind, PersonIdentifier.value).filter(
                        PersonIdentifier.company_key == key, PersonIdentifier.blob_id == blob_id
                    )
                }
                counts["missing"] += len(set(identifiers) - present)
                if apply:
                    counts["indexed"] += associations.add_identifiers(
                        session,
                        owner_id=owner_id,
                        blob_id=str(blob_id),
                        identifiers=identifiers,
                        company_key=key,
                    )
            if counts["indexed"]:
                bump_mutation_seq(session)
    logger.info(f"[rebuilds] identifier reindex owner={owner_id} apply={apply} {counts}")
    return counts


# ─── The source links ─────────────────────────────────────────────────


def _descriptions(events: Any) -> List[str]:
    if not isinstance(events, list):
        try:
            events = json.loads(events or "[]")
        except (TypeError, ValueError):
            return []
    out: List[str] = []
    for item in events or []:
        desc = item.get("description") if isinstance(item, dict) else item
        if isinstance(desc, str):
            out.append(desc.strip())
    return out


def rebuild_source_links() -> Dict[str, int]:
    """One-shot reconstruction of the email_blobs / calendar_blobs
    index from the legacy blob.events descriptions.

    Runs on every init_db but exits cheaply when the index is already
    populated (or there are no blobs to migrate). Moved here from
    ``storage/database.py`` with milestone 8, which deleted the standalone
    ``scripts/backfill_email_blobs.py`` it once mirrored: that script wrote
    the profile file, where these tables no longer live.

    A calendar description names its event by summary: it is linked only
    when exactly one of this profile's events carries that summary; an
    ambiguous one is counted in ``ambiguous`` and left unlinked. The blobs'
    rows are guarded (:func:`guarded`). Answers the counts; a failure is
    logged and answered as ``{"failed": 1}``, because a boot goes on without
    the index.
    """
    from zylch.cli.utils import get_owner_id
    from zylch.memory.company_key import current_company_key
    from zylch.storage.database import get_session_factory
    from zylch.storage.models import CalendarBlob, CalendarEvent, Email, EmailBlob

    owner_id = get_owner_id()
    company_key = current_company_key()
    counts = {"email": 0, "calendar": 0, "ambiguous": 0}
    session = get_session_factory()()
    try:
        # Per-profile guard: under a shared store "the index is populated"
        # must mean populated FOR THIS PROFILE'S MAIL, or only whichever
        # profile boots first is ever backfilled. Provenance says who wrote
        # a link, so the guard is on the writer, not on the table.
        existing_links = (
            session.query(EmailBlob.email_id).filter(EmailBlob.owner_id == owner_id).limit(1).first()
        )
        blob_scan = session.query(Blob)
        if company_key:
            blob_scan = blob_scan.filter(Blob.company_key == company_key)
        if existing_links is not None or blob_scan.with_entities(Blob.id).limit(1).first() is None:
            return counts
        email_ids = {str(r[0]) for r in session.query(Email.id).all() if r[0]}
        by_summary: Dict[str, List[str]] = {}
        for eid, summary in (
            session.query(CalendarEvent.id, CalendarEvent.summary)
            .filter(CalendarEvent.summary.isnot(None))
            .all()
        ):
            by_summary.setdefault(str(summary or ""), []).append(str(eid))
        with guarded(session, company_key or ""):
            # The company's blobs, joined against THIS profile's mail (the
            # `email_ids` set above is per-profile); the link rows carry the
            # indexing profile as provenance, not the blob's contributor.
            for blob in blob_scan.all():
                blob_id = str(blob.id)
                for desc in _descriptions(blob.events):
                    found = _EMAIL_EVENT.match(desc)
                    if found:
                        if found.group(1).strip() in email_ids:
                            session.merge(
                                EmailBlob(email_id=found.group(1).strip(), blob_id=blob_id, owner_id=owner_id)
                            )
                            counts["email"] += 1
                        continue
                    found = _CALENDAR_EVENT.match(desc)
                    if found:
                        events = by_summary.get(found.group(1).strip(), [])
                        if len(events) > 1:
                            counts["ambiguous"] += 1
                        elif events:
                            session.merge(
                                CalendarBlob(event_id=events[0], blob_id=blob_id, owner_id=owner_id)
                            )
                            counts["calendar"] += 1
        if counts["email"] or counts["calendar"]:
            session.commit()
            logger.info(f"[backfill] populated email_blobs index: {counts}")
        else:
            session.rollback()
        return counts
    except Exception as e:  # noqa: BLE001 - a boot goes on without the index
        session.rollback()
        logger.warning(f"[backfill] email_blobs index backfill failed: {e}")
        return {**counts, "failed": 1}
    finally:
        session.close()


__all__ = [
    "ENTITY_TYPES",
    "RebuildTampered",
    "entity_type",
    "guarded",
    "rebuild_source_links",
    "reindex_identifiers",
    "scope_digest",
]
