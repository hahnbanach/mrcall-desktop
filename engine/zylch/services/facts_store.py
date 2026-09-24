"""Structured business facts, stored as category-tagged blobs.

Facts are volatile business values (prices, hours, SLAs, deliverables)
that an offer or quote must use EXACTLY. Unlike PERSON / COMPANY / STYLE
memory, facts are retrieved by EXACT category membership, never by
embedding similarity: "white-label" and "private-label" terms embed
almost identically, so a similarity search would bleed one category's
facts into the other and contaminate the offer. The solver enumerates
categories, picks the relevant one(s), then loads ALL and ONLY that
category's facts.

Stored in namespace ``facts:<company_key>`` — company knowledge, shared by
every account holding the key — one blob per fact, content::

    Category: <category>
    Key: <short key>
    <value text>

Dedup is by exact, case-insensitive (Category, Key): a changed value
updates the existing blob instead of piling up duplicates.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def facts_namespace(owner_id: str) -> str:
    """The company's facts namespace. ``owner_id`` is accepted for signature
    compatibility and takes no part in it: facts are company knowledge."""
    from zylch.memory.company_key import facts_namespace as _keyed, require_company_key

    return _keyed(require_company_key())


def _parse_field(content: str, field: str) -> str:
    prefix = f"{field}:".lower()
    for line in (content or "").splitlines():
        if line.strip().lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return ""


def parse_category(content: str) -> str:
    return _parse_field(content, "Category")


def parse_key(content: str) -> str:
    return _parse_field(content, "Key")


def parse_value(content: str) -> str:
    """Read a multiline value from legacy flat or sectioned FACT output."""
    lines = (content or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("value:"):
            first = line.split(":", 1)[1].strip()
            value_lines = []
            for following in lines[i + 1 :]:
                if following.strip().upper() in {"#IDENTIFIERS", "#ABOUT", "#HISTORY"}:
                    break
                value_lines.append(following)
            tail = "\n".join(value_lines).strip()
            return (first + ("\n" + tail if tail else "")).strip()
    return ""


def format_fact(category: str, key: str, value: str) -> str:
    return f"Category: {category}\nKey: {key}\n{value}".strip()


def _all_fact_blobs(owner_id: str) -> List[Dict[str, str]]:
    """Every eligible fact row, oldest first — the one read behind every fact read.

    A known customer-shaped FACT (its header states an entity scope or type,
    or a review restricted it) is left out here, before any category filter or
    count, so it can neither be enumerated nor crowd a valid fact out
    (``zylch.memory.eligibility``).
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    from zylch.memory.company_key import require_company_key
    from zylch.memory.eligibility import ineligible_fact_ids

    ns = facts_namespace(owner_id)
    key = require_company_key()
    with get_session() as session:
        rows = (
            session.query(Blob)
            .filter(Blob.company_key == key, Blob.namespace == ns)
            .order_by(Blob.created_at.asc())
            .all()
        )
        excluded = ineligible_fact_ids(session, key)
        return [
            {"blob_id": str(r.id), "content": r.content or "", "updated_at": _iso(r.updated_at)}
            for r in rows
            if str(r.id) not in excluded
        ]


def _iso(value) -> str:
    """The version form the harness compares on: ``get_blob()["updated_at"]``."""
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def exact_fact(owner_id: str, category: str, key: str) -> Optional[Dict[str, str]]:
    """The eligible fact row with exactly this (Category, Key), or ``None``.

    The exact candidate lookup facts have always used, kept as a read API: the
    ingestion pins a FACT child's row through it and the fact adapter names it
    as the requested target. Case-insensitive on both fields, as dedup was.
    """
    want_cat, want_key = (category or "").strip().lower(), (key or "").strip().lower()
    if not want_cat or not want_key:
        return None
    for blob in _all_fact_blobs(owner_id):
        if (
            parse_category(blob["content"]).lower() == want_cat
            and parse_key(blob["content"]).lower() == want_key
        ):
            return blob
    return None


def list_categories(owner_id: str) -> List[Dict[str, object]]:
    """Distinct categories with a fact count, sorted by name."""
    counts: Dict[str, int] = {}
    display: Dict[str, str] = {}
    for blob in _all_fact_blobs(owner_id):
        cat = parse_category(blob["content"])
        if not cat:
            continue
        norm = cat.lower()
        counts[norm] = counts.get(norm, 0) + 1
        display.setdefault(norm, cat)
    return [{"category": display[k], "count": counts[k]} for k in sorted(counts)]


def get_facts_by_category(owner_id: str, category: str) -> List[Dict[str, str]]:
    """Return ALL and ONLY facts whose Category matches exactly (case-insensitive)."""
    want = (category or "").strip().lower()
    if not want:
        return []
    out: List[Dict[str, str]] = []
    for blob in _all_fact_blobs(owner_id):
        if parse_category(blob["content"]).lower() == want:
            out.append(
                {
                    "blob_id": blob["blob_id"],
                    "key": parse_key(blob["content"]),
                    "content": blob["content"],
                }
            )
    return out


def upsert_fact(
    owner_id: str,
    category: str,
    key: str,
    value: str,
    event_description: Optional[str] = None,
    *,
    entry=None,
) -> Optional[str]:
    """Submit one business fact to the harness, deduped by exact (Category, Key).

    The exact row with this category and key, when one exists, is pinned as the
    event's target and named as the requested write; the mnemonic role decides
    the final text and whether the value is company knowledge at all — a
    customer's price is that customer's memory, and the role may say so, in
    which case the departure is recorded. There is no fallback create and no
    caller-owned classification: a proposal the harness cannot admit is
    refused, never written another way.

    ``entry`` is the admission and source the caller runs under
    (``zylch.memory.mnemonic.entry``); a caller that passes none gets the
    current turn's, or a refusal when it is inside a preparation run with no
    admitted item.

    Returns the committed blob id, or ``None``. Never raises.
    """
    category = (category or "").strip()
    key = (key or "").strip()
    value = (value or "").strip()
    if not category or not key or not value:
        logger.debug(
            f"[facts] upsert skipped (missing field): "
            f"category={category!r} key={key!r} has_value={bool(value)}"
        )
        return None

    content = format_fact(category, key, value)
    try:
        from zylch.memory.company_key import require_company_key
        from zylch.memory.mnemonic import submit
        from zylch.memory.mnemonic.approval import RequestedWrite
        from zylch.memory.mnemonic.contracts import (
            COMPANY_SCOPE,
            CREATE,
            FACT,
            OPERATOR_DELEGATED,
            UPDATE,
            MemoryEvent,
            SubjectHint,
        )
        from zylch.memory.mnemonic.entry import EntryRefused, entry_for

        try:
            entry = entry or entry_for(fallback=content)
        except EntryRefused as exc:
            logger.warning(f"[facts] {category}/{key} refused: {exc}")
            return None
        row = exact_fact(owner_id, category, key)
        event = MemoryEvent(
            owner_id=owner_id,
            company_key=require_company_key(),
            caller_class=OPERATOR_DELEGATED,
            origin=entry.origin,
            source_kind=entry.source_kind,
            source_id=entry.source_id,
            source_revision=entry.source_revision,
            observation=entry.observation,
            subject_hint=SubjectHint(entity_type=FACT, target_blob_id=row["blob_id"] if row else None),
            explicit_request=False,
            stage=entry.stage,
            cancellation=entry.cancellation,
        ).with_model_arguments({"content": content})
        requested = (
            RequestedWrite(
                action=UPDATE,
                blob_id=row["blob_id"],
                entity_type=FACT,
                scope=COMPANY_SCOPE,
                subject_is_authoritative=True,
            )
            if row
            else RequestedWrite(action=CREATE, entity_type=FACT, scope=COMPANY_SCOPE)
        )
        result = submit(event, requested=requested)
        if result.outcome == "committed":
            blob_id = result.committed_ids[0][0]
            logger.info(f"[facts] {category}/{key} -> {blob_id} (event {event.event_id})")
            return blob_id
        logger.info(f"[facts] {category}/{key} not written: {result.outcome} {result.reason}")
        return None
    except Exception as e:
        logger.warning(f"[facts] upsert failed for {category}/{key}: {e}")
        return None
