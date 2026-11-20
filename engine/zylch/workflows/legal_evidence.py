from datetime import date
import re
from typing import Any

from .errors import WorkflowError
from .legal_passages import resolve_passage


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _source_version(source: dict[str, Any] | None) -> dict[str, Any]:
    metadata = source.get("metadata", {}) if source else {}
    result = {}
    for key in ("identity", "publication_version", "coverage"):
        value = metadata.get(key)
        result[key] = value if isinstance(value, str) and 1 <= len(value) <= 512 else "unknown"
    verified = metadata.get("version_verified")
    result["version_verified"] = verified if type(verified) is bool else None
    consulted = source.get("consulted_at") if source else None
    result["consulted_at"] = (
        consulted if isinstance(consulted, str) and 1 <= len(consulted) <= 64 else "unknown"
    )
    return result


def validate_citations(
    sources: dict[str, dict[str, Any]],
    citations: list[dict[str, Any]],
    event_date: str | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(citations, list) or len(citations) > 100 or len(sources) > 100:
        raise WorkflowError("invalid_input")
    facts = facts or []
    if (
        not isinstance(facts, list)
        or len(facts) > 100
        or any(
            not isinstance(f, dict)
            or not isinstance(f.get("id"), str)
            or len(f["id"]) > 100
            or f.get("status") not in ("resolved", "unresolved")
            or not isinstance(f.get("description", ""), str)
            or len(f.get("description", "")) > 2000
            or type(f.get("material", False)) is not bool
            for f in facts
        )
    ):
        raise WorkflowError("invalid_input")
    material_unresolved = any(
        f.get("material") is True and f["status"] != "resolved" for f in facts
    )
    resolved = {f.get("id") for f in facts if f.get("status") == "resolved"}
    records = []
    for citation in citations:
        if not isinstance(citation, dict):
            raise WorkflowError("invalid_input")
        if "passage_id" in citation:
            passage = resolve_passage(sources, citation.get("source_id"), citation["passage_id"])
            if "quote" in citation and citation["quote"] != passage["text"]:
                raise WorkflowError("invalid_input")
            citation = {**citation, "quote": passage["text"]}
        source = sources.get(citation.get("source_id"))
        exists = source is not None
        quote = citation.get("quote", "")
        supports = bool(
            exists
            and isinstance(quote, str)
            and len(quote.strip()) >= 10
            and _normal(quote) in _normal(source["text"])
        )
        applies = False
        reason = "applicability_unresolved"
        metadata = source.get("metadata", {}) if source else {}
        try:
            event = date.fromisoformat(event_date or "")
            start = date.fromisoformat(metadata.get("valid_from", ""))
            end = date.fromisoformat(metadata["valid_to"]) if metadata.get("valid_to") else None
            consulted = (
                date.fromisoformat(source["consulted_at"][:10])
                if source and source.get("consulted_at")
                else None
            )
            applies = bool(
                metadata.get("version_verified") is True
                and citation.get("version_date") == metadata.get("version_date")
                and start <= event
                and (event <= end if end else consulted is not None and event <= consulted)
            )
            if not applies:
                reason = "temporal_conflict_or_version_unresolved"
        except (TypeError, ValueError):
            pass
        fact_keys = citation.get("fact_keys", [])
        if not isinstance(fact_keys, list) or any(not isinstance(k, str) for k in fact_keys):
            raise WorkflowError("invalid_input")
        facts_resolved = all(key in resolved for key in fact_keys) and not material_unresolved
        interpretation = citation.get("reasoning", "")
        proposition = citation.get("proposition", "")
        if not isinstance(interpretation, str) or not isinstance(proposition, str):
            raise WorkflowError("invalid_input")
        operative = bool(
            exists
            and supports
            and applies
            and facts_resolved
            and interpretation.strip()
            and proposition.strip()
            and citation.get("adverse") is not True
        )
        if not exists:
            reason = "source_missing"
        elif not supports:
            reason = "quotation_mismatch"
        elif not facts_resolved:
            reason = "material_facts_unresolved"
        elif citation.get("adverse") is True:
            reason = "adverse_authority_requires_discussion"
        records.append(
            {
                **citation,
                "exists": exists,
                "supports": supports,
                "applies": applies,
                "facts_resolved": facts_resolved,
                "operative": operative,
                "status": "source_supported_argument" if operative else reason,
                "support_scope": "quotation_match_only_not_judicial_merits",
                "source_sha256": source.get("sha256") if source else None,
                "source_url": source.get("url") if source else None,
                "source_version": _source_version(source),
                "passage": {
                    "quotation": quote,
                    "normalized_character_offset": (
                        _normal(source["text"]).find(_normal(quote)) if supports else None
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "source_versions": [
            {
                "source_id": (
                    source_id if isinstance(source_id, str) and len(source_id) <= 128 else "unknown"
                ),
                **_source_version(source),
            }
            for source_id, source in sources.items()
        ],
        "citations": records,
        "event_date": event_date,
        "limitation": "Passage matching and source version checks do not determine legal merits or exhaustive adverse treatment.",
    }


def render_draft(
    request: str,
    register: dict[str, Any],
    facts: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(request, str)
        or not 1 <= len(request) <= 200
        or any(character in request for character in ("\n", "\r", "\x00"))
    ):
        raise WorkflowError("invalid_input")
    limitations = [] if limitations is None else limitations
    if (
        not isinstance(limitations, list)
        or len(limitations) > 20
        or any(not isinstance(item, str) or not 1 <= len(item) <= 2000 for item in limitations)
        or sum(len(item) for item in limitations) > 16000
    ):
        raise WorkflowError("invalid_input")
    citations = register.get("citations", [])
    grounds = [c for c in citations if c.get("operative") is True]
    unresolved = [c for c in citations if c.get("operative") is not True]
    adverse = [c for c in citations if c.get("adverse") is True]
    unresolved_facts = [f for f in (facts or []) if f.get("status") != "resolved"]
    notes = [
        {
            "review_status": "nonoperative_requires_human_review",
            "source_id": c.get("source_id"),
            "source_url": c.get("source_url"),
            "quotation": c["passage"]["quotation"],
            "unverified_proposition": c.get("proposition", ""),
            "unverified_reasoning": c.get("reasoning", ""),
            "citation_status": c.get("status"),
            "applies": c.get("applies") is True,
            "facts_resolved": c.get("facts_resolved") is True,
            "adverse": c.get("adverse") is True,
            "support_scope": c.get("support_scope"),
            "operative": False,
        }
        for c in unresolved
        if c.get("exists") is True and c.get("supports") is True
    ]
    review_items = [
        {
            "fact_id": f.get("id"),
            "action": "confirm_fact",
            "description": f.get("description") or f.get("id", ""),
            "material": f.get("material") is True,
            "status": "requires_human_confirmation",
        }
        for f in unresolved_facts
    ]
    paragraphs = [
        f"Subject: {request}",
        "Draft for human review. No filing or outreach is authorized.",
    ]
    source_versions = register.get("source_versions", [])
    if source_versions:
        paragraphs.append("Retained source editions and verification (engine metadata):")
        for version in source_versions:
            verified = version["version_verified"]
            paragraphs.append(
                f"Source: {version['source_id']}\n"
                f"Identity: {version['identity']}\n"
                f"Publication edition: {version['publication_version']}\n"
                f"Version verification: {'verified' if verified is True else 'unverified' if verified is False else 'unknown'}\n"
                f"Coverage: {version['coverage']}\n"
                f"Consulted at: {version['consulted_at']}\n"
                "Source edition and textual coverage do not establish current legal applicability."
            )
    paragraphs.extend(
        f"{c['proposition']}\nSource: {c.get('source_url') or c['source_id']}\nReasoning: {c['reasoning']}"
        for c in grounds
    )
    if unresolved:
        paragraphs.append("Unresolved citations are excluded from operative grounds.")
    if notes:
        paragraphs.append(
            "NONOPERATIVE RESEARCH NOTES: matched source passages only. "
            "Interpretations and applicability require human review; these notes are not operative grounds."
        )
        for note in notes:
            paragraphs.append(
                "Research note (NONOPERATIVE; human review required)\n"
                f"Source: {note['source_url'] or note['source_id']}\n"
                f"Exact source quotation: {note['quotation']}\n"
                f"UNVERIFIED proposition: {note['unverified_proposition']}\n"
                f"UNVERIFIED reasoning: {note['unverified_reasoning']}\n"
                f"Review status: {note['citation_status']}\n"
                f"Temporal applicability verified: {note['applies']}\n"
                f"Material facts resolved: {note['facts_resolved']}\n"
                f"Adverse authority: {note['adverse']}"
            )
    unsupported = [
        c for c in unresolved if c.get("exists") is not True or c.get("supports") is not True
    ]
    if unsupported:
        paragraphs.append(
            "Unsupported citations (no supported research note):\n"
            + "\n".join(
                f"Unresolved citation {index}: {c.get('status', 'unresolved')}"
                for index, c in enumerate(unsupported, 1)
            )
        )
    if review_items:
        paragraphs.append(
            "Material facts requiring confirmation — review items:\n"
            + "\n".join(
                f"Confirm fact {item['fact_id']}: {item['description']}" for item in review_items
            )
        )
    if limitations:
        paragraphs.append("Limitations supplied for this report:\n" + "\n".join(limitations))
    return {
        "status": "draft_requires_review",
        "source_versions": source_versions,
        "limitations": list(limitations),
        "text": "\n\n".join(paragraphs),
        "operative_grounds": grounds,
        "research_notes": notes,
        "review_items": review_items,
        "unresolved_citations": unresolved,
        "adverse_evidence": adverse,
        "unresolved_facts": unresolved_facts,
        "limitation": register.get("limitation", ""),
    }
