"""Identity evidence: what lets two memories be called the same subject.

Checked against the actual inputs, never against a proposal's own claim of
confidence or evidence. What counts depends on the family, because the same
overlap means different things:

- a PERSON is judged on identity tokens alone — emails, phones, lids — and
  needs a shared email address, or a shared phone or lid *plus* the same
  stated name. A shared name is never evidence that two people are one person
  (an ingestion child states its name, and two Luca Bianchi with different
  addresses are two people), a shared company name is not either, and neither
  is a number two colleagues both answer. That is the shared-switchboard
  incident exactly: retrieval legitimately found the reception number and the
  company in common, and merging Sara Conti into Marco Blu on that basis is
  the failure this rule exists to stop.
- a COMPANY or FACT may rely on any shared structured identifier — the
  retrieval tokens, names included: a name, a domain or a switchboard
  genuinely does identify the company, and that is what keeps the
  duplicate-CREATE gate live for an extracted company that states a name and
  no address.

The count the role was shown (``shared_identifiers``) is retrieval-side
information for every family; the verdict is this module's, and a PERSON
candidate sharing only a name shows a count of one and is not corroborated.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .candidates import (
    event_identifiers,
    identity_tokens,
    identity_tokens_of,
    is_email_token,
    parse_header,
    parse_identifiers,
)
from .contracts import COMPANY, PERSON, REQUIRED_FAMILY, Candidate, MemoryEvent


def corroborates(event: MemoryEvent, candidate: Candidate, entity_type: Optional[str]) -> bool:
    """Is there real identity evidence between this observation and this row?"""
    if entity_type == PERSON:
        shared = identity_tokens(event) & identity_tokens_of(candidate.content)
        if not shared:
            return False
        # Only an email identifies a person on its own; a phone or a lid is
        # shared by whoever answers it, and needs the same stated name.
        if any(is_email_token(value) for value in shared):
            return True
        stated = (parse_header(candidate.content).get("name") or "").strip().lower()
        hinted = ((event.subject_hint.name if event.subject_hint else "") or "").strip().lower()
        return bool(stated and hinted and stated == hinted)
    shared = event_identifiers(event) & parse_identifiers(candidate.content)
    return bool(shared)


def duplicate_candidates(
    event: MemoryEvent, proposal, candidates: Iterable[Candidate]
) -> List[Candidate]:
    """The shown candidates a CREATE of this proposal would duplicate.

    The role saw a candidate sharing identity evidence with this observation
    and chose to make a second one anyway. That is the duplicate-CREATE
    fallback the brief rules out — "never create a fourth Andrea" — and it is
    the mirror of the merge gate: the same evidence that would authorize
    folding two rows together forbids splitting them apart.

    Only entities, and only against candidates of the same family: a FACT in
    the retrieval set says nothing about whether this person is new. Where the
    evidence is absent — a similar name, a shared switchboard, a shared
    company — nothing fires, which is exactly the unrelated-namesakes and
    shared-switchboard incidents, and they stay CREATE.
    """
    if proposal.entity_type not in (PERSON, COMPANY):
        return []
    family = REQUIRED_FAMILY[proposal.entity_type]
    found = []
    for candidate in candidates:
        same_family = candidate.namespace.split(":", 1)[0].strip().lower() == family
        stated = (candidate.entity_type or "").strip().upper()
        if not same_family or (stated and stated != proposal.entity_type):
            continue
        if corroborates(event, candidate, proposal.entity_type):
            found.append(candidate)
    return found


__all__ = ["corroborates", "duplicate_candidates"]
