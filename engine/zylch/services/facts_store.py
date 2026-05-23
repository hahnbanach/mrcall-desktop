"""Structured business facts, stored as category-tagged blobs.

Facts are volatile business values (prices, hours, SLAs, deliverables)
that an offer or quote must use EXACTLY. Unlike PERSON / COMPANY / STYLE
memory, facts are retrieved by EXACT category membership, never by
embedding similarity: "white-label" and "private-label" terms embed
almost identically, so a similarity search would bleed one category's
facts into the other and contaminate the offer. The solver enumerates
categories, picks the relevant one(s), then loads ALL and ONLY that
category's facts.

Stored in namespace ``facts:<owner_id>``, one blob per fact, content::

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
    return f"facts:{owner_id}"


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
    """Return the text after a ``Value:`` marker (may span lines)."""
    lines = (content or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("value:"):
            first = line.split(":", 1)[1].strip()
            tail = "\n".join(lines[i + 1 :]).strip()
            return (first + ("\n" + tail if tail else "")).strip()
    return ""


def format_fact(category: str, key: str, value: str) -> str:
    return f"Category: {category}\nKey: {key}\n{value}".strip()


def _all_fact_blobs(owner_id: str) -> List[Dict[str, str]]:
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    ns = facts_namespace(owner_id)
    with get_session() as session:
        rows = (
            session.query(Blob)
            .filter(Blob.owner_id == owner_id, Blob.namespace == ns)
            .order_by(Blob.created_at.asc())
            .all()
        )
        return [{"blob_id": str(r.id), "content": r.content or ""} for r in rows]


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
) -> Optional[str]:
    """Create or update a fact, deduped by exact (Category, Key).

    Returns the blob_id, or None on failure. Never raises.
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
        from zylch.memory import EmbeddingEngine, MemoryConfig
        from zylch.memory.blob_storage import BlobStorage
        from zylch.storage.database import get_session

        blob_store = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))

        want_cat, want_key = category.lower(), key.lower()
        for blob in _all_fact_blobs(owner_id):
            if (
                parse_category(blob["content"]).lower() == want_cat
                and parse_key(blob["content"]).lower() == want_key
            ):
                blob_store.update_blob(
                    blob_id=blob["blob_id"],
                    owner_id=owner_id,
                    content=content,
                    event_description="Fact updated",
                )
                logger.debug(f"[facts] updated {category}/{key} -> {blob['blob_id']}")
                return blob["blob_id"]

        blob = blob_store.store_blob(
            owner_id=owner_id,
            namespace=facts_namespace(owner_id),
            content=content,
            event_description="Fact created",
        )
        blob_id = str(blob["id"])
        logger.debug(f"[facts] created {category}/{key} -> {blob_id}")
        return blob_id
    except Exception as e:
        logger.warning(f"[facts] upsert failed for {category}/{key}: {e}")
        return None
