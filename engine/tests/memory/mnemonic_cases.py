"""Turn the milestone 0 incident corpus into events and candidate sets.

The corpus in ``tests/fixtures/mnemonic/incidents.json`` is frozen: it records
what each incident *is* and what a safe outcome looks like, independently of
how the harness happens to be built. This module is the adapter between that
frozen description and the milestone 2 contracts, so the tests exercise the
real incidents rather than re-inventing convenient ones.

It is a test helper, not engine code: nothing under ``zylch/`` imports it.
"""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path
from typing import Tuple

from zylch.memory.mnemonic.candidates import event_identifiers, parse_identifiers
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC,
    AUTOMATIC_OBSERVATION,
    INTERACTIVE,
    REQUIRED_FAMILY,
    Candidate,
    MemoryEvent,
    SubjectHint,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mnemonic"

COMPANY_KEY = "AAAAAAAAAAAAAAAAAAAAAA"
OWNER = "owner-a"

# Event ids are unique in production (uuid4) and the harness now budgets paid
# calls PER EVENT, so a fixed id would make one test spend another's allowance.
# The case name stays in the id; a counter keeps each build its own event.
_serial = count(1)


def event_id_for(case_id: str) -> str:
    return f"evt-{case_id}-{next(_serial)}"


# Identifier field name in the corpus → the header line the engine writes.
_HEADER_FIELDS = (("name", "Name"), ("email", "Email"), ("phone", "Phone"), ("company", "Company"))


def load_incidents() -> dict:
    return json.loads((FIXTURES / "incidents.json").read_text())


def load_decisions() -> dict:
    return json.loads((FIXTURES / "decisions.json").read_text())


def case(case_id: str) -> dict:
    for entry in load_incidents()["cases"]:
        if entry["id"] == case_id:
            return entry
    raise KeyError(f"no incident named {case_id!r} in the frozen corpus")


def candidate_content(spec: dict) -> str:
    """The blob text a candidate would actually hold.

    A corpus candidate given as ``content`` is a legacy row and keeps its exact
    legacy shape — including no header at all, which is what makes the legacy
    read-compatibility assertions real.
    """
    if spec.get("content") and not spec.get("identifiers"):
        return spec["content"]
    lines = ["#IDENTIFIERS", f"Entity type: {spec['entity_type']}", f"Scope: {spec['scope']}"]
    identifiers = spec.get("identifiers") or {}
    for key, label in _HEADER_FIELDS:
        if identifiers.get(key):
            lines.append(f"{label}: {identifiers[key]}")
    lines.append("#ABOUT")
    lines.append(spec.get("content") or f"{identifiers.get('name', 'Unknown')} is known to us.")
    return "\n".join(lines)


def namespace_for(entity_type: str) -> str:
    family = REQUIRED_FAMILY[entity_type]
    return f"{family}:{COMPANY_KEY if family in ('user', 'facts') else OWNER}"


def version_of(blob_id: str) -> str:
    return f"2026-09-20T10:00:00-{blob_id}"


def build(case_id: str, *, origin: str = None) -> Tuple[MemoryEvent, Tuple[Candidate, ...]]:
    """One frozen incident as a live event plus its bounded candidate set."""
    spec = case(case_id)
    hint = SubjectHint(**spec["subject_hint"]) if spec.get("subject_hint") else None
    automatic = spec["caller_class"] == AUTOMATIC_OBSERVATION
    origin = origin or (AUTOMATIC if automatic else INTERACTIVE)
    event = MemoryEvent(
        owner_id=OWNER,
        company_key=COMPANY_KEY,
        caller_class=spec["caller_class"],
        origin=origin,
        source_kind="email" if automatic else "chat",
        source_id=f"src-{case_id}",
        source_revision="rev-1",
        observation=spec["original_observation"],
        event_id=event_id_for(case_id),
        subject_hint=hint,
        explicit_request=not automatic,
        stage="email" if origin == AUTOMATIC else None,
    )
    return event, tuple(as_candidate(entry, event) for entry in spec.get("candidates", []))


def as_candidate(spec: dict, event: MemoryEvent) -> Candidate:
    """One corpus row as the engine would actually see it.

    ``entity_type`` and ``scope`` are read from the blob's own header, exactly
    as ``mnemonic/candidates.py`` reads them — never from the corpus's
    description of the row. A legacy blob without a header therefore arrives
    with neither, which is what makes the legacy read-compatibility assertions
    mean something.
    """
    from zylch.memory.mnemonic.candidates import parse_header

    content = candidate_content(spec)
    header = parse_header(content)
    return Candidate(
        blob_id=spec["id"],
        content=content,
        updated_at=version_of(spec["id"]),
        namespace=namespace_for(spec["entity_type"]),
        entity_type=header.get("entity type"),
        scope=header.get("scope"),
        source="identifier+cosine",
        shared_identifiers=len(event_identifiers(event) & parse_identifiers(content)),
        score=0.5,
    )


def build_children(case_id: str = "multi_entity_source") -> list:
    """The multi-entity incident as one child event per expected child.

    Each child keeps the parent's complete observation — the source is what it
    is — and differs only in the subject it is about. Nothing here decides an
    order or drops the remainder; that durable per-child progress is milestone
    3's journal, and this only proves the decision layer handles each child.
    """
    spec = case(case_id)
    children = []
    for child in spec["expected"]["children"]:
        kind, _, identity = child["stable_key"].partition(":")
        hint = SubjectHint(
            entity_type=child["entity_type"],
            email=identity if "@" in identity else None,
            name=None if "@" in identity else identity,
        )
        children.append(
            MemoryEvent(
                owner_id=OWNER,
                company_key=COMPANY_KEY,
                caller_class=spec["caller_class"],
                origin=AUTOMATIC,
                source_kind="email",
                source_id=f"src-{case_id}",
                source_revision="rev-1",
                event_id=event_id_for(f"{case_id}-{kind}"),
                observation=spec["original_observation"],
                subject_hint=hint,
                stage="email",
            )
        )
    return children


def decision_text(case_id: str) -> str:
    """The deterministic model response this incident is exercised with.

    Stored structurally so the fixture stays readable, then serialized to the
    exact wire text a model would emit — so the parser under test still sees a
    real string, not a pre-parsed object. A case whose whole point is a broken
    response carries its literal text instead.
    """
    entry = load_decisions()["decisions"].get(case_id)
    if entry is None:
        return case(case_id)["model_response"]
    if "model_response" in entry:
        return entry["model_response"]
    decision = dict(entry["decision"])
    lines = decision.pop("content_lines", None)
    if lines is not None:
        decision["content"] = "\n".join(lines)
    return json.dumps(decision, ensure_ascii=False, indent=2)
