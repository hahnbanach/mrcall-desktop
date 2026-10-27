import hashlib
import json
import re
from typing import Any

from .errors import WorkflowError

MAX_EXCERPT = 2000
MAX_RESULTS = 5
MAX_SEARCH = 200
ID_PATTERN = re.compile(
    r"lp1\.(0|[1-9][0-9]{0,6})\.(0|[1-9][0-9]{0,6})\.([0-9a-f]{64})\.([0-9a-f]{64})\.([0-9a-f]{64})"
)


def _source(sources: dict[str, dict[str, Any]], source_id: str) -> tuple[str, str, str]:
    try:
        if not isinstance(source_id, str) or not re.fullmatch(r"source_[0-9a-f]{24}", source_id):
            raise ValueError
        source = sources[source_id]
        text, original_hash = source["text"], source["sha256"]
        if (
            source["id"] != source_id
            or source["source_id"] != source_id
            or not isinstance(text, str)
            or not 1 <= len(text) <= 2_000_000
            or not isinstance(original_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", original_hash)
            or source_id != "source_" + original_hash[:24]
        ):
            raise ValueError
        encoded = source["original_bytes_hex"]
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 8 * 1024 * 1024:
            raise ValueError
        original = bytes.fromhex(encoded)
        if hashlib.sha256(original).hexdigest() != original_hash:
            raise ValueError
        return text, original_hash, hashlib.sha256(text.encode()).hexdigest()
    except (KeyError, TypeError, ValueError):
        raise WorkflowError("invalid_input") from None


def _passage(
    source_id: str, text: str, original_hash: str, text_hash: str, start: int, end: int
) -> dict[str, Any]:
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or end - start > MAX_EXCERPT
    ):
        raise WorkflowError("invalid_input")
    quotation = text[start:end]
    digest = hashlib.sha256(
        json.dumps(
            [source_id, original_hash, text_hash, start, end, quotation],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "passage_id": f"lp1.{start}.{end}.{original_hash}.{text_hash}.{digest}",
        "source_id": source_id,
        "source_sha256": original_hash,
        "text_sha256": text_hash,
        "start": start,
        "end": end,
        "text": quotation,
        "support_scope": "exact_retained_text_only_not_applicability_or_merits",
    }


def search_passages(
    sources: dict[str, dict[str, Any]],
    source_id: str,
    search: str,
    offset: int = 0,
    limit: int = MAX_RESULTS,
    context_characters: int = 200,
) -> dict[str, Any]:
    if (
        not isinstance(search, str)
        or not 1 <= len(search) <= MAX_SEARCH
        or not search.strip()
        or type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= MAX_RESULTS
        or type(context_characters) is not int
        or not 0 <= context_characters <= 900
    ):
        raise WorkflowError("invalid_input")
    text, original_hash, text_hash = _source(sources, source_id)
    if offset > len(text):
        raise WorkflowError("invalid_input")
    passages = []
    cursor = offset
    while len(passages) < limit:
        found = text.find(search, cursor)
        if found < 0:
            break
        end = min(len(text), found + len(search) + context_characters)
        start = max(0, found - context_characters)
        passages.append(_passage(source_id, text, original_hash, text_hash, start, end))
        cursor = found + len(search)
    return {
        "source_id": source_id,
        "passages": passages,
        "next_offset": cursor if passages and text.find(search, cursor) >= 0 else None,
        "coverage": "bounded_literal_matches_in_retained_text_not_exhaustive_legal_research",
    }


def resolve_passage(
    sources: dict[str, dict[str, Any]], source_id: str, passage_id: str
) -> dict[str, Any]:
    if not isinstance(passage_id, str) or len(passage_id) > 240:
        raise WorkflowError("invalid_input")
    matched = ID_PATTERN.fullmatch(passage_id)
    if matched is None:
        raise WorkflowError("invalid_input")
    text, original_hash, text_hash = _source(sources, source_id)
    if matched[3] != original_hash or matched[4] != text_hash:
        raise WorkflowError("invalid_input")
    passage = _passage(source_id, text, original_hash, text_hash, int(matched[1]), int(matched[2]))
    if passage["passage_id"] != passage_id:
        raise WorkflowError("invalid_input")
    return passage
