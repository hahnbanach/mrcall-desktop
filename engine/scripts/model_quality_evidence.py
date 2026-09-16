"""Offline evidence bindings for human/agent quality review, version 2.

build_evidence(case, clock, content, authorities=()) returns a private bundle.
Only semantic request fields are copied: system, messages, tools, tool_choice,
and the resolved injected clock. Model/provider/effort/output-cap controls are
excluded. `content` must already be masked by the grading preparer. Prompt text
is never redacted here: a model name appearing inside a source email is evidence.

validate_review(bundle, review) raises ValueError on invalid evidence bindings.
Review fields: version=2, case_id, bundle_sha256, coverage (all section IDs),
four DIMENSIONS below, and nonempty claims. Each claim has rationale,
source_refs=[{id, sha256, quote}], and output_quote. Quotes are exact nonempty
substrings of the rendered section/output. Authority refs use the same shape.

This validates declared coverage, quotation presence and consistent categories;
it cannot establish comprehension, authoritative truth, or semantic entailment.
Grounding describes all cited review evidence, including separately timestamped
authorities; it does not mean a fact was present in the original model input.
Later authority records are timestamped separate evidence, never model inputs.
Keep earlier reviews and explicit before/after adjudications when using them.
"""

# ruff: noqa: TRY004 -- JSON validation consistently reports ValueError.

import hashlib
import json
from datetime import datetime

DIMENSIONS = {
    "task_decision": {"acceptable", "unacceptable", "indeterminate", "not_applicable"},
    "explanation_grounding": {"supported", "contradicted", "unsupported", "not_applicable"},
    "claim_truth": {"supported_true", "supported_false", "unknown", "not_applicable"},
    "operational_impact": {"decision_changed", "explanation_only", "unknown", "not_applicable"},
}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("type") == "text":
        # Cache metadata changes transport, not the supplied prompt text.
        if not isinstance(value.get("text"), str):
            raise ValueError("Text block must contain string text")
        return value["text"]
    return _json(value)


def _block(identifier, kind, text, **metadata):
    block = {"id": identifier, "kind": kind, "text": text, **metadata}
    return {**block, "sha256": _digest(block)}


def _nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be a nonempty string")


def _authority(record):
    for name in ("id", "text", "timestamp", "source", "scope"):
        _nonempty(record.get(name), "Authority " + name)
    if not record["id"].startswith("authority:"):
        raise ValueError("Authority ID must start with authority:")
    try:
        parsed = datetime.fromisoformat(record["timestamp"])
    except ValueError as exc:
        raise ValueError("Authority timestamp must be ISO8601 with timezone") from exc
    if parsed.utcoffset() is None:
        raise ValueError("Authority timestamp must include timezone")
    return _block(
        record["id"],
        "authority",
        record["text"],
        timestamp=record["timestamp"],
        source=record["source"],
        scope=record["scope"],
    )


def build_evidence(case, clock, content, authorities=()):
    """Build stable semantic sections for one case/output, with separate authority."""
    _nonempty(case.get("id"), "Case ID")
    _nonempty(clock, "Resolved clock")
    if content is None:
        raise ValueError("Cannot review a missing model response")
    request = case["request"]
    sections = []
    system = request.get("system", [])
    if not isinstance(system, list):
        system = [system]
    for i, value in enumerate(system):
        sections.append(_block(f"system:{i}", "system", _text(value)))
    if not system:
        sections.append(_block("system:empty", "system", "[]"))
    messages = request.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError("Messages must be a list")
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or not isinstance(message.get("role"), str):
            raise ValueError("Message requires a role")
        values = message.get("content", [])
        if not isinstance(values, list):
            values = [values]
        for j, value in enumerate(values or [[]]):
            sections.append(
                _block(f"message:{i}:{j}", "message", _text(value), role=message["role"])
            )
    if not messages:
        sections.append(_block("message:empty", "message", "[]"))
    tools = request.get("tools", [])
    if not isinstance(tools, list):
        raise ValueError("Tools must be a list")
    for i, tool in enumerate(tools):
        sections.append(_block(f"tool:{i}", "tool", _json(tool)))
    if not tools:
        sections.append(_block("tool:empty", "tool", "[]"))
    sections.append(_block("tool-choice", "tool_choice", _json(request.get("tool_choice"))))
    sections.append(_block("clock", "clock", clock))
    inputs = sections.copy()
    rendered = (
        "\n\n".join(_text(b) for b in content) if isinstance(content, list) else _text(content)
    )
    if not rendered:
        rendered = _json(content)
    sections.append(_block("output", "output", rendered))
    authority_blocks = [_authority(record) for record in authorities]
    if len({b["id"] for b in authority_blocks}) != len(authority_blocks):
        raise ValueError("Duplicate authority ID")
    bundle = {
        "version": 2,
        "case_id": case["id"],
        "stage": case.get("stage"),
        "input_sha256": _digest(inputs),
        "output_sha256": sections[-1]["sha256"],
        "sections": sections,
        "authorities": authority_blocks,
    }
    return {**bundle, "bundle_sha256": _digest(bundle)}


def validate_review(bundle, review):
    """Validate evidence integrity and declared review consistency; return None."""
    if bundle.get("version") != 2 or review.get("version") != 2:
        raise ValueError("Evidence and review require version 2")
    if bundle.get("bundle_sha256") != _digest(
        {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    ):
        raise ValueError("Bundle digest mismatch")
    sections = bundle["sections"]
    authorities = bundle["authorities"]
    blocks = sections + authorities
    index = {b["id"]: b for b in blocks}
    if len(index) != len(blocks):
        raise ValueError("Duplicate evidence ID")
    for block in blocks:
        if block["sha256"] != _digest({k: v for k, v in block.items() if k != "sha256"}):
            raise ValueError("Section digest mismatch")
    if {b["kind"] for b in sections} != {
        "system",
        "message",
        "tool",
        "tool_choice",
        "clock",
        "output",
    }:
        raise ValueError("Missing complete evidence categories")
    if (
        sum(b["kind"] == "output" for b in sections) != 1
        or index.get("output", {}).get("kind") != "output"
    ):
        raise ValueError("Exactly one output section required")
    if bundle["input_sha256"] != _digest([b for b in sections if b["kind"] != "output"]):
        raise ValueError("Input digest mismatch")
    if bundle["output_sha256"] != index["output"]["sha256"]:
        raise ValueError("Output digest mismatch")
    for block in authorities:
        if _authority(block) != block:
            raise ValueError("Malformed authority block")
    if (
        review.get("case_id") != bundle["case_id"]
        or review.get("bundle_sha256") != bundle["bundle_sha256"]
    ):
        raise ValueError("Review is bound to different case or evidence")
    coverage = review.get("coverage")
    if (
        not isinstance(coverage, list)
        or not all(isinstance(x, str) for x in coverage)
        or len(set(coverage)) != len(coverage)
        or set(coverage) != {b["id"] for b in sections}
    ):
        raise ValueError("Coverage must acknowledge every section exactly once")
    for name, allowed in DIMENSIONS.items():
        if not isinstance(review.get(name), str) or review[name] not in allowed:
            raise ValueError("Invalid dimension: " + name)
    if bundle.get("stage") == "task.detect" and review["task_decision"] == "not_applicable":
        raise ValueError("Task detection requires an assessed task decision")
    if bundle.get("stage") == "memory.extract" and review["task_decision"] != "not_applicable":
        raise ValueError("Memory extraction has no task decision")
    grounding, truth, impact = (
        review[k] for k in ("explanation_grounding", "claim_truth", "operational_impact")
    )
    if grounding == "unsupported" and (
        truth in {"supported_true", "supported_false"} or impact == "decision_changed"
    ):
        raise ValueError("Unsupported alone cannot establish truth or changed decision")
    if truth == "supported_false" and grounding != "contradicted":
        raise ValueError("Supported false requires contradictory evidence")
    if review["task_decision"] == "unacceptable" and impact != "decision_changed":
        raise ValueError("Unacceptable task requires a grounded changed-decision judgment")
    if impact == "decision_changed" and (
        review["task_decision"] != "unacceptable" or grounding not in {"supported", "contradicted"}
    ):
        raise ValueError("Changed decision requires grounded unacceptable task judgment")
    claims = review.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("Review requires substantive claims with quotations")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Claim must be an object")
        _nonempty(claim.get("rationale"), "Claim rationale")
        _nonempty(claim.get("output_quote"), "Output quotation")
        if claim["output_quote"] not in index["output"]["text"]:
            raise ValueError("Output quotation absent")
        refs = claim.get("source_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("Claim requires source quotations")
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
                raise ValueError("Invalid source reference")
            source = index.get(ref["id"])
            if (
                source is None
                or source["kind"] == "output"
                or ref.get("sha256") != source["sha256"]
            ):
                raise ValueError("Invalid source identity/hash")
            _nonempty(ref.get("quote"), "Source quotation")
            if ref["quote"] not in source["text"]:
                raise ValueError("Source quotation absent")
