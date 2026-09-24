"""The bounded, read-only retrieval set the mnemonic role is shown.

Three candidates, never more — the same bound the existing merge path uses, so
the role never sees a wider comparison set than the code it replaces. An exact
visible target named by the caller is pinned first and counts *inside* that
bound rather than widening it.

Two token sets, and the difference between them is the difference between
finding a memory and being allowed to touch it:

- **retrieval tokens** (:func:`event_identifiers`) — every structured
  identifier the event states, names and companies included. They select and
  rank candidates and they are what the role is told a candidate shares.
- **identity tokens** (:func:`identity_tokens`) — emails, phones and lids
  only. They are the evidence the validator's PERSON corroboration accepts:
  two people called Mario Rossi are two people, and a shared company is not a
  shared identity.

Both come from the caller's hint when it states them. The observation is
mined only for an **interactive** event whose hint states no identity — the
chat and solve adapters, for which the observation is the human's own words
and is mined exactly as before. An automatic event's observation is the whole
channel message it came from, and its identity is what its hint states and
nothing else: mining the message would make the sender's address corroborate
every entity it mentions — the sender-injection defect under another name —
and a name-only entity is exactly the child whose hint states no address.

Corroboration counts are carried through ``workers/memory_candidates``: how
many retrieval tokens a candidate actually shares with the event. That is
mechanical parsing of explicit identity fields, not a judgment about meaning.
Index proximity travels as ordering only. Neither authorizes a mutation: the
validator refuses an uncorroborated merge however similar the retrieval
thought the rows were.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Optional, Sequence, Set, Tuple

from zylch.workers.memory_candidates import merge_shortlist

from .contracts import AUTOMATIC, MAX_CANDIDATES, Candidate, MemoryEvent

_IDENTIFIER_LINE = re.compile(
    r"^(?:name|email|e-mail|phone|mobile|tel|telephone|company|domain|vat|id)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A phone is a run of digits with separators. The lookarounds keep it from
# reading the local part of an email or of a WhatsApp ``<digits>@lid`` as a
# phone: that is the digit-strip ``_normalise_phone`` guards against, and a
# lid's digits must never compare equal to somebody's number.
_PHONE = re.compile(r"(?<![\w@])\+?\d[\d\s().-]{6,}\d(?![\w@])")

# What a phone value may contain before its narrative tail ("(cell)", "home").
_PHONE_CHARS = frozenset("+0123456789 .-()/")
# A clipped run shorter than this is not a phone; the value is kept whole so a
# company called "3M" does not become the token "3".
_MIN_PHONE_DIGITS = 7


def _normalize(value: str) -> str:
    """The one comparison form, applied to both sides of every intersection.

    A phone-shaped value — starting with ``+`` or a digit and carrying no
    ``@`` — is clipped at its first non-phone character, exactly as
    ``workers.memory._normalise_phone`` clips the values it indexes, so
    ``Phone: +39 333 1200000 (cell)`` in a blob and ``+393331200000`` in a hint
    compare equal. A value containing ``@`` is never clipped: an email keeps its
    domain and a lid keeps its discriminator. Separators are then stripped and
    a leading ``00`` becomes ``+``, again as the index does.
    """
    value = (value or "").strip()
    if value and "@" not in value and (value[0] == "+" or value[0].isdigit()):
        run = []
        for ch in value:
            if ch in _PHONE_CHARS:
                run.append(ch)
            else:
                break
        clipped = "".join(run)
        if sum(ch.isdigit() for ch in clipped) >= _MIN_PHONE_DIGITS:
            value = clipped
    value = re.sub(r"[\s().\-/]", "", value).strip().lower()
    if value.startswith("00") and value[2:].isdigit():
        value = "+" + value[2:]
    return value


def _is_identity_token(token: str) -> bool:
    """An email, a lid or a phone — never a name, a company or a category."""
    if "@" in token:
        return True
    digits = token[1:] if token.startswith("+") else token
    return digits.isdigit() and len(digits) >= _MIN_PHONE_DIGITS


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


def identity_tokens_of(content: str) -> set:
    """The identity tokens a blob's text states: its emails, phones and lids."""
    return {token for token in parse_identifiers(content) if _is_identity_token(token)}


def identity_pairs_of(text: str) -> list:
    """The ``(kind, value)`` pairs a text states, in the identity index's own form.

    Comparison tokens (:func:`_normalize`) strip an email's dots; the index
    stores the address as written, lowercased, so a lookup built from tokens
    missed every dotted domain. This is the form the index is asked in: emails
    as written and lowercased, phones canonical.
    """
    pairs = []
    seen = set()
    for match in _EMAIL.findall(text or ""):
        value = match.strip().lower()
        if value and ("email", value) not in seen:
            seen.add(("email", value))
            pairs.append(("email", value))
    for match in _PHONE.findall(text or ""):
        value = _normalize(match)
        if _is_identity_token(value) and ("phone", value) not in seen:
            seen.add(("phone", value))
            pairs.append(("phone", value))
    return pairs


def _hint_identity(event: MemoryEvent) -> Set[str]:
    hint = event.subject_hint
    if hint is None:
        return set()
    found = {_normalize(value) for _, value in hint.identifiers}
    for value in (hint.email, hint.phone):
        if value:
            found.add(_normalize(value))
    found.discard("")
    return found


def _hint_names(event: MemoryEvent) -> Set[str]:
    hint = event.subject_hint
    if hint is None:
        return set()
    found = {_normalize(value) for value in (hint.name, hint.company) if value}
    found.discard("")
    return found


def _mines_observation(event: MemoryEvent) -> bool:
    """May this event's observation be read for identity at all?

    Only an interactive event whose hint states no identity: a chat turn or a
    solve, where the observation is what the human said. An automatic event's
    observation is a whole channel message and is never mined — its identity is
    its hint's, and a hint that states no address states no identity.
    """
    return event.origin != AUTOMATIC and not _hint_identity(event)


def identity_tokens(event: MemoryEvent) -> set:
    """The evidence side: the event's emails, phones and lids, and nothing else.

    The hint's identifiers when it states any; otherwise, for an interactive
    event, the identity-shaped tokens of the observation — the chat and solve
    case. An automatic event with no stated identity has none.
    """
    stated = _hint_identity(event)
    if stated or not _mines_observation(event):
        return stated
    return identity_tokens_of(event.observation)


def event_identifiers(event: MemoryEvent) -> set:
    """The retrieval side: every identifier the event asserts, names included.

    For an interactive event that states nothing, this is the observation's
    structured identifiers exactly as before. Otherwise it is the hint's names
    and companies plus the identity tokens — which for an ingestion child are
    the entity's own, never the message's sender.
    """
    stated = _hint_names(event) | _hint_identity(event)
    if not stated and _mines_observation(event):
        return parse_identifiers(event.observation)
    return stated | identity_tokens(event)


def retrieval_query(event: MemoryEvent) -> str:
    """What the cosine search is asked: the hint's identifier lines, or the text.

    A hint that names its subject widens retrieval by driving the query: the
    header lines are the stable part of a record where ``#ABOUT`` and
    ``#HISTORY`` drift, so searching on them is what finds an existing blob for
    the same subject. With no hint the observation is the query, as before.
    """
    hint = event.subject_hint
    if hint is None:
        return event.observation
    lines = []
    if hint.name:
        lines.append(f"Name: {hint.name}")
    if hint.company:
        lines.append(f"Company: {hint.company}")
    if hint.email:
        lines.append(f"Email: {hint.email}")
    if hint.phone:
        lines.append(f"Phone: {hint.phone}")
    for kind, value in hint.identifiers:
        lines.append(f"{kind.upper() if kind == 'lid' else kind.capitalize()}: {value}")
    return "\n".join(lines) if lines else event.observation


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
    cosine = list(search(retrieval_query(event), MAX_CANDIDATES))
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
