"""Public task copies and private user edit/source lifecycle metadata."""

from __future__ import annotations

from copy import deepcopy

from zylch.qonto.errors import QontoError
from zylch.qonto.task_access import marker
from zylch.storage.models import TaskItem


def reject_finance_creation(item):
    sources = item.get("sources") or {}
    if (
        item.get("event_type") == "qonto"
        or item.get("channel") == "qonto"
        or "qonto" in sources
        or "_qonto" in sources
    ):
        raise QontoError("authority_required")


def public_task(row):
    result = deepcopy(row.to_dict())
    metadata = (result.get("sources") or {}).pop("_qonto", None)
    if metadata and metadata.get("deleted"):
        result["source_unavailable"] = True
    return result


def user_edit(row, *fields):
    sources = deepcopy(row.sources or {})
    metadata = sources.get("_qonto")
    if metadata is None:
        return
    metadata["user_edited"] = True
    metadata["edited_fields"] = sorted(set(metadata.get("edited_fields", [])) | set(fields))
    row.sources = sources


def delete_sources(session, uid):
    rows = session.query(TaskItem).filter(TaskItem.owner_id == uid, marker()).all()
    for row in rows:
        metadata = deepcopy((row.sources or {}).get("_qonto") or {})
        if not metadata.get("user_edited"):
            session.delete(row)
            continue
        edited = set(metadata.get("edited_fields", []))
        for field in ("title", "reason", "suggested_action", "urgency"):
            if field not in edited:
                setattr(row, field, "Source unavailable" if field == "title" else None)
        row.contact_email = row.contact_name = row.contact_phone = None
        metadata.pop("generated", None)
        metadata["deleted"] = True
        sources = {"_qonto": metadata}
        for field in ("closes", "snoozes", "skipped_at"):
            if field in (row.sources or {}):
                sources[field] = deepcopy(row.sources[field])
        row.sources = sources
