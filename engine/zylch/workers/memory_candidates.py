"""Bound semantic merge work without treating channel provenance as identity."""

from collections.abc import Callable, Iterable

MAX_MERGE_CANDIDATES = 3


def merge_shortlist(
    identifiers: Iterable[tuple],
    identifier_blob_ids: Iterable[str],
    cosine_candidates: Iterable,
    get_blob: Callable,
    parse_identifiers: Callable,
) -> list[dict]:
    """Rank corroborated identifiers first, with cosine as a bounded fallback.

    Old indexes can contain a message sender's address on unrelated entities.
    Validate index hints against the LLM-authored structured identity before
    allowing them to create paid comparisons. This is mechanical parsing of
    explicit identifiers, not a heuristic judgment about entity meaning; the
    merge LLM remains the final authority on identity.

    More shared identifiers outrank fewer. Cosine score breaks ties, then blob
    ID makes ordering deterministic. All candidate sources share one limit.
    """
    wanted = set(identifiers)
    cosine = {str(c.blob_id): c for c in cosine_candidates}
    candidates = []
    for bid in dict.fromkeys([*map(str, identifier_blob_ids), *cosine]):
        blob = get_blob(bid)
        if not blob or not blob.get("content"):
            continue
        shared = wanted.intersection(parse_identifiers(blob["content"]))
        similarity = cosine.get(bid)
        if not shared and similarity is None:
            continue
        score = float(similarity.hybrid_score) if similarity is not None else 0.0
        candidates.append(
            {
                "blob_id": bid,
                "content": blob["content"],
                "updated_at": blob.get("updated_at"),
                "source": (
                    "identifier+cosine"
                    if shared and similarity
                    else ("identifier-only" if shared else "cosine")
                ),
                "shared_identifiers": len(shared),
                "score": score,
            }
        )
    candidates.sort(key=lambda c: (-c["shared_identifiers"], -c["score"], c["blob_id"]))
    return candidates[:MAX_MERGE_CANDIDATES]
