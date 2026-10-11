"""Company-local bank provenance survives profile deletion and ordinary edits."""

from zylch.storage.models import BlobAlias, BlobVersion, FactHistory, MemoryOperation


def excluded_blob_ids(session, company_key):
    operations = (
        session.query(MemoryOperation)
        .filter(
            MemoryOperation.company_key == company_key,
            MemoryOperation.source_ref.like("qonto:%"),
            MemoryOperation.state == "committed",
        )
        .all()
    )
    events = {row.event_id for row in operations}
    excluded = {
        str(pair[0])
        for row in operations
        for pair in dict(row.result or {}).get("committed_ids", [])
        if pair
    }
    versions = session.query(BlobVersion).filter(BlobVersion.company_key == company_key).all()
    excluded.update(str(row.blob_id) for row in versions if row.operation_id in events)
    edges = [
        (str(row.merged_id), str(row.keeper_id))
        for row in session.query(BlobAlias).filter(BlobAlias.company_key == company_key).all()
    ]
    edges.extend(
        (str(row.losing_blob_id), str(row.winning_blob_id))
        for row in session.query(FactHistory).filter(FactHistory.company_key == company_key).all()
        if row.losing_blob_id and row.winning_blob_id
    )
    while True:
        before = len(excluded)
        for left, right in edges:
            if left in excluded or right in excluded:
                excluded.update((left, right))
        if before == len(excluded):
            return excluded


def annotation(blob_id, excluded):
    if str(blob_id) not in excluded:
        return {}
    return {
        "source_kind": "qonto",
        "source_available": False,
        "historical_finance_snapshot": True,
        "source_guidance": (
            "Historical published finance snapshot. Its private bank source is unavailable on "
            "this shared-memory surface. Review current data through authorized Qonto reads. "
            "Remove this memory with /memory delete " + str(blob_id) + "."
        ),
    }


def annotate(session, company_key, value, *, excluded=None):
    roots = excluded_blob_ids(session, company_key) if excluded is None else excluded
    return {**value, **annotation(value.get("id", value.get("blob_id")), roots)}


def guidance(value):
    return value.get("source_guidance", "")
