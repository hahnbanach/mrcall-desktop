"""Which memories consolidation pairs: the entity family, clustered by identity.

Consolidation asks the mnemonic role about memories that may be the same
subject. This module finds them, without asking anything: the company's
entity-family blobs, united (union-find) when they share an identity-index row
or the canonical ``Name:`` of their ``#IDENTIFIERS`` header, each cluster
listed keeper-first by length. What it reads leaves out two kinds of blob, so
consolidation can never put them into play:

- **sinks** — blobs whose count of versions is over the threshold (see
  :mod:`zylch.memory.blob_versions`): they wait for their owner, as keeper and
  as donor;
- **restricted rows** — every blob id a review in this company's journal
  restricted (:func:`zylch.memory.eligibility.restricted_ids`).

It proposes pairs; it decides nothing. Whether two members are one subject is
the role's decision, checked by the validator and committed by
:mod:`zylch.memory.mnemonic.commit`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


def entity_family(
    company_key: str, *, exclude: Iterable[str] = ()
) -> Tuple[List[Dict[str, Any]], Dict[str, set]]:
    """This company's entity-family blobs and their identity-index rows.

    Read in one transaction on the company store, oldest first, so a run pairs
    in the same order every time. ``exclude`` names the blobs consolidation
    must not pair — the sinks — and every blob a review restricted is left out
    with them, read in the same transaction. Returns the blobs as
    ``{"id", "content"}`` and each one's ``(kind, value)`` rows.
    """
    from zylch.memory.company_key import entity_namespace
    from zylch.memory.eligibility import restricted_ids
    from zylch.memory.mnemonic.session import company_transaction
    from zylch.storage.models import Blob, PersonIdentifier

    with company_transaction() as session:
        left_out = {str(b) for b in exclude} | restricted_ids(session, company_key)
        rows = (
            session.query(Blob.id, Blob.content)
            .filter(
                Blob.company_key == company_key, Blob.namespace == entity_namespace(company_key)
            )
            .order_by(Blob.created_at, Blob.id)
            .all()
        )
        ident_rows = (
            session.query(PersonIdentifier.blob_id, PersonIdentifier.kind, PersonIdentifier.value)
            .filter(PersonIdentifier.company_key == company_key)
            .all()
        )
    blobs = [{"id": str(r[0]), "content": r[1] or ""} for r in rows if str(r[0]) not in left_out]
    identifiers: Dict[str, set] = {}
    for bid, kind, value in ident_rows:
        if str(bid) not in left_out:
            identifiers.setdefault(str(bid), set()).add((str(kind), str(value)))
    return blobs, identifiers


def _extract_canonical_name(content: str) -> Optional[str]:
    """Pull a canonical entity name from a blob's structured-format body.

    The merge prompt mandates an `#IDENTIFIERS\\nEntity type: ...\\nName: ...`
    layout, so we can rely on a "Name:" line being present in any
    well-formed blob. Falls back to None when the line is missing or
    empty (e.g. legacy blobs with free-form content).

    The line format is structured by us, not free-form prose, so a
    line-prefix check is allowed under the engine's parsing rules.
    """
    if not content:
        return None
    for line in content.splitlines():
        s = line.strip()
        if s.lower().startswith("name:"):
            value = s[5:].strip()
            if value and value.lower() not in ("[name]", "(unknown)", "n/a"):
                return value.lower()
    return None


def _build_dedup_clusters(
    blobs: List[Dict[str, Any]],
    blob_identifiers: Dict[str, set],
) -> List[List[Dict[str, Any]]]:
    """Cluster blobs that share at least one identity key.

    Identity keys come from two sources, OR-merged via union-find:
      * structured identifiers from the ``person_identifiers`` index —
        ``("id", kind, value)`` tuples (Phase 1a/1b);
      * canonical Name from the blob's ``#IDENTIFIERS`` block —
        ``("name", lowercased name)`` tuple (legacy reconsolidation
        path, kept as a fallback for blobs without structured email /
        phone / lid).

    A chain like "A and B share email; B and C share phone" yields one
    cluster {A, B, C}. Returns clusters with ≥ 2 blobs each; singletons
    are dropped.
    """
    parent: Dict[str, str] = {b["id"]: b["id"] for b in blobs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Build key → [blob_id] index from BOTH identifier table AND name.
    key_to_blobs: Dict[tuple, List[str]] = {}
    for b in blobs:
        bid = b["id"]
        # Name key (legacy fallback for blobs without structured ids)
        name = _extract_canonical_name(b["content"])
        if name:
            key_to_blobs.setdefault(("name", name), []).append(bid)
        # Identifier keys (Phase 1a/1b)
        for kind, value in blob_identifiers.get(bid, set()):
            key_to_blobs.setdefault(("id", kind, value), []).append(bid)

    # Union every blob set sharing a key
    for bids in key_to_blobs.values():
        if len(bids) < 2:
            continue
        for i in range(1, len(bids)):
            union(bids[0], bids[i])

    # Group by root
    clusters_by_root: Dict[str, List[Dict[str, Any]]] = {}
    for b in blobs:
        root = find(b["id"])
        clusters_by_root.setdefault(root, []).append(b)

    return [c for c in clusters_by_root.values() if len(c) >= 2]


__all__ = ["entity_family"]
