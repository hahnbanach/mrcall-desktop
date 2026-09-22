"""The bounded, read-only retrieval set the mnemonic role is shown.

Three candidates, never more — the same bound the existing merge path uses, so
the role never sees a wider comparison set than the code it replaces. An exact
visible target named by the caller is pinned first and counts *inside* that
bound rather than widening it.

Corroboration is carried through from ``workers/memory_candidates``: how many
structured identifiers a candidate actually shares with the observation. That
is mechanical parsing of explicit identity fields, not a judgment about
meaning. Index proximity travels as ordering only. Neither authorizes a
mutation: the validator refuses an uncorroborated merge however similar the
retrieval thought the rows were.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple

from zylch.workers.memory_candidates import merge_shortlist

from .contracts import MAX_CANDIDATES, Candidate, MemoryEvent

_IDENTIFIER_LINE = re.compile(
    r"^(?:name|email|e-mail|phone|mobile|tel|telephone|company|domain|vat|id)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _normalize(value: str) -> str:
    return re.sub(r"[\s().-]", "", value).strip().lower()


def parse_identifiers(content: str) -> set:
    """Structured identifiers written in a blob's header, as comparable tokens.

    Only header ``Key: value`` lines and unambiguous email/phone shapes count.
    Free prose is not mined for identity — that is the role's judgment, and
    a regex that guessed at it would be exactly the "semantic classification by
    substring" this harness exists to remove.
    """
    found = set()
    for raw in _IDENTIFIER_LINE.findall(content or ""):
        value = _normalize(raw)
        if value:
            found.add(value)
    for match in _EMAIL.findall(content or ""):
        found.add(_normalize(match))
    for match in _PHONE.findall(content or ""):
        found.add(_normalize(match))
    return found


def event_identifiers(event: MemoryEvent) -> set:
    """Identifiers the event itself asserts — hint fields first, then the text.

    The caller's structured hint is authoritative about what it claims; the
    observation is mined only for the unambiguous shapes above.
    """
    found = set()
    hint = event.subject_hint
    if hint:
        for value in (hint.name, hint.email, hint.phone, hint.company):
            if value:
                found.add(_normalize(value))
    found |= parse_identifiers(event.observation)
    return {value for value in found if value}


def gather(
    event: MemoryEvent,
    *,
    get_blob: Callable[[str], Optional[dict]],
    search: Callable[[str, int], Iterable[Any]] = lambda _q, _n: (),
    identifier_blob_ids: Sequence[str] = (),
) -> Tuple[Candidate, ...]:
    """At most :data:`MAX_CANDIDATES` visible blobs, hinted target pinned first.

    ``get_blob`` must already be owner/company scoped — this module never
    widens visibility and never reads a row the caller could not read itself.
    """
    wanted = event_identifiers(event)
    cosine = list(search(event.observation, MAX_CANDIDATES))
    shortlist = merge_shortlist(
        wanted,
        identifier_blob_ids,
        cosine,
        get_blob,
        parse_identifiers,
    )

    hinted_id = event.subject_hint.target_blob_id if event.subject_hint else None
    ordered: list[dict] = []
    if hinted_id:
        hinted = next((row for row in shortlist if row["blob_id"] == hinted_id), None)
        if hinted is None:
            blob = get_blob(hinted_id)
            if blob and blob.get("content"):
                shared = wanted.intersection(parse_identifiers(blob["content"]))
                hinted = {
                    "blob_id": hinted_id,
                    "content": blob["content"],
                    "updated_at": blob.get("updated_at"),
                    "namespace": blob.get("namespace", ""),
                    "source": "caller-hint",
                    "shared_identifiers": len(shared),
                    "score": 0.0,
                }
        if hinted is not None:
            ordered.append(hinted)
            shortlist = [row for row in shortlist if row["blob_id"] != hinted_id]
    ordered.extend(shortlist)

    chosen = []
    for row in ordered[:MAX_CANDIDATES]:
        if not row.get("namespace"):
            # merge_shortlist keeps only what a merge needs; the validator also
            # checks the family a target actually lives in, so read it back.
            blob = get_blob(row["blob_id"]) or {}
            row = {**row, "namespace": blob.get("namespace", "")}
        chosen.append(_as_candidate(row, hinted=row["blob_id"] == hinted_id))
    return tuple(chosen)


def _as_candidate(row: dict, *, hinted: bool) -> Candidate:
    content = row.get("content") or ""
    header = parse_header(content)
    return Candidate(
        blob_id=str(row["blob_id"]),
        content=content,
        updated_at=str(row.get("updated_at") or ""),
        namespace=str(row.get("namespace") or ""),
        entity_type=header.get("entity type"),
        scope=header.get("scope"),
        source=str(row.get("source") or "cosine"),
        shared_identifiers=int(row.get("shared_identifiers") or 0),
        score=float(row.get("score") or 0.0),
        hinted=hinted,
    )


_HEADER_LINE = re.compile(r"^([A-Za-z][A-Za-z ._-]{0,40}):\s*(.*)$")


def parse_header(content: str) -> dict:
    """The ``#IDENTIFIERS`` block as a lowercased key → value map.

    Legacy blobs without a header, and legacy plain rules, simply return what
    they have — usually nothing. That is deliberate: missing metadata is
    interpreted from the family at validation time, never backfilled on read,
    and a legacy blob stays perfectly readable.
    """
    header: dict = {}
    in_block = False
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_block = stripped.upper().startswith("#IDENTIFIERS")
            continue
        if not in_block:
            continue
        match = _HEADER_LINE.match(stripped)
        if match:
            header[match.group(1).strip().lower()] = match.group(2).strip()
    if not header:
        # A pre-header blob may still open with bare Category/Key lines.
        for line in (content or "").splitlines()[:4]:
            match = _HEADER_LINE.match(line.strip())
            if match and match.group(1).strip().lower() in ("category", "key", "entity type"):
                header[match.group(1).strip().lower()] = match.group(2).strip()
    return header
