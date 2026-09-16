"""Evidence references enforce traceability, never machine-certified understanding."""

import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts" / "model_quality_evidence.py"
spec = importlib.util.spec_from_file_location("quality_evidence", PATH)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


@pytest.fixture
def case():
    return {
        "id": "task-one",
        "stage": "task.detect",
        "request": {
            "model": "secret-model",
            "max_tokens": 8192,
            "provider": {"only": ["secret-provider"]},
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "max"},
            "system": [
                {
                    "type": "text",
                    "text": "Owner: notifications require no reply.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": "Order 1977. Method: shopify_payments.\nMemory: unrelated prospect.",
                }
            ],
            "tools": [{"name": "task_decision", "input_schema": {"type": "object"}}],
            "tool_choice": {"type": "tool", "name": "task_decision"},
        },
    }


def make_review(bundle):
    src = next(b for b in bundle["sections"] if b["kind"] == "message")
    return {
        "version": 2,
        "case_id": bundle["case_id"],
        "bundle_sha256": bundle["bundle_sha256"],
        "coverage": [b["id"] for b in bundle["sections"]],
        "task_decision": "acceptable",
        "explanation_grounding": "unsupported",
        "claim_truth": "unknown",
        "operational_impact": "explanation_only",
        "claims": [
            {
                "rationale": "Method does not establish payment status; no-action is independently correct.",
                "source_refs": [
                    {"id": src["id"], "sha256": src["sha256"], "quote": "Method: shopify_payments"}
                ],
                "output_quote": "Payment confirmed",
            }
        ],
    }


def bundle(case, **kwargs):
    return evidence.build_evidence(
        case,
        "2026-09-16T10:00Z",
        [{"type": "text", "text": "No action. Payment confirmed."}],
        **kwargs,
    )


def test_payment_unknown_not_wrong_task(case):
    b = bundle(case)
    assert evidence.validate_review(b, make_review(b)) is None
    assert "Memory: unrelated prospect." in next(
        s["text"] for s in b["sections"] if s["kind"] == "message"
    )


@pytest.mark.parametrize("kind", ["system", "message", "clock", "tool"])
def test_missing_coverage_rejected(case, kind):
    b = bundle(case)
    r = make_review(b)
    r["coverage"].remove(next(s["id"] for s in b["sections"] if s["kind"] == kind))
    with pytest.raises(ValueError, match="Coverage"):
        evidence.validate_review(b, r)


@pytest.mark.parametrize(
    "field,value", [("quote", "payment settled"), ("quote", " "), ("sha256", "wrong")]
)
def test_fabricated_empty_or_wrong_hash_refs_rejected(case, field, value):
    b = bundle(case)
    r = make_review(b)
    r["claims"][0]["source_refs"][0][field] = value
    with pytest.raises(ValueError):
        evidence.validate_review(b, r)


def test_output_quote_and_tampered_bundle_rejected(case):
    b = bundle(case)
    r = make_review(b)
    r["claims"][0]["output_quote"] = "Order shipped"
    with pytest.raises(ValueError, match="Output quotation"):
        evidence.validate_review(b, r)
    b["sections"][0]["text"] += "fake policy"
    with pytest.raises(ValueError, match="digest"):
        evidence.validate_review(b, make_review(b))


@pytest.mark.parametrize(
    "field,value",
    [
        ("claim_truth", "supported_false"),
        ("claim_truth", "supported_true"),
        ("operational_impact", "decision_changed"),
    ],
)
def test_unsupported_alone_cannot_establish_truth_or_decision_error(case, field, value):
    b = bundle(case)
    r = make_review(b)
    r[field] = value
    with pytest.raises(ValueError, match="Unsupported"):
        evidence.validate_review(b, r)


def test_explicit_contradiction_supported_false(case):
    case["request"]["messages"][0]["content"] += " Payment captured: false."
    b = bundle(case)
    r = make_review(b)
    r.update(explanation_grounding="contradicted", claim_truth="supported_false")
    r["claims"][0]["source_refs"][0]["quote"] = "Payment captured: false."
    evidence.validate_review(b, r)


def test_later_authority_does_not_retrofit_inputs(case):
    before = copy.deepcopy(case)
    original = bundle(case)
    authority = {
        "id": "authority:cto-20260916",
        "text": "Our product is shelf stable for twelve months.",
        "timestamp": "2026-09-16T11:00:00+00:00",
        "source": "CTO statement",
        "scope": "Company cold brew",
    }
    later = bundle(case, authorities=[authority])
    r = make_review(later)
    a = later["authorities"][0]
    r.update(explanation_grounding="supported", claim_truth="supported_true")
    r["claims"][0]["source_refs"] = [{"id": a["id"], "sha256": a["sha256"], "quote": a["text"]}]
    evidence.validate_review(later, r)  # Presence is verified, NOT relevance or truth.
    assert later["input_sha256"] == original["input_sha256"]
    assert later["bundle_sha256"] != original["bundle_sha256"]
    assert case == before
    with pytest.raises(ValueError, match="different case or evidence"):
        evidence.validate_review(later, make_review(original))


def test_control_changes_blinded_but_real_prompt_and_clock_bound(case):
    b = bundle(case)
    changed = copy.deepcopy(case)
    changed["request"].update(
        model="other", max_tokens=2048, thinking={"type": "disabled"}, provider={}
    )
    changed["request"].pop("output_config")
    assert bundle(changed) == b
    assert "secret-model" not in str(b) and "secret-provider" not in str(b)
    changed["request"]["system"][0]["text"] += " Different owner rule."
    assert bundle(changed)["input_sha256"] != b["input_sha256"]
    assert evidence.build_evidence(case, "next-day", [])["input_sha256"] != b["input_sha256"]


def test_missing_response_rejected_but_empty_response_reviewable(case):
    with pytest.raises(ValueError, match="missing model response"):
        evidence.build_evidence(case, "clock", None)
    b = evidence.build_evidence(case, "clock", [])
    r = make_review(b)
    r["claims"][0]["output_quote"] = "[]"
    evidence.validate_review(b, r)


def test_legacy_review_rejected_not_inferred(case):
    b = bundle(case)
    with pytest.raises(ValueError, match="version"):
        evidence.validate_review(b, {"semantic_verdict": "acceptable"})


@pytest.mark.parametrize("timestamp", ["2026-09-16", "2026-09-16T11:00:00", "not-a-date"])
def test_authority_requires_dated_timezone_provenance(case, timestamp):
    with pytest.raises(ValueError, match="timestamp"):
        bundle(
            case,
            authorities=[
                {
                    "id": "authority:one",
                    "text": "Fact",
                    "timestamp": timestamp,
                    "source": "CTO",
                    "scope": "Current products",
                }
            ],
        )


def test_task_dimension_respects_role(case):
    b = bundle(case)
    r = make_review(b)
    r["task_decision"] = "not_applicable"
    with pytest.raises(ValueError, match="Task detection"):
        evidence.validate_review(b, r)
    case["stage"] = "memory.extract"
    b = bundle(case)
    r = make_review(b)
    with pytest.raises(ValueError, match="Memory extraction"):
        evidence.validate_review(b, r)
    r["task_decision"] = "not_applicable"
    evidence.validate_review(b, r)


def test_explanatory_payment_uncertainty_cannot_be_bad_task(case):
    b = bundle(case)
    r = make_review(b)
    r["task_decision"] = "unacceptable"
    with pytest.raises(ValueError, match="Unacceptable task"):
        evidence.validate_review(b, r)
    r["operational_impact"] = "decision_changed"
    with pytest.raises(ValueError, match="Unsupported"):
        evidence.validate_review(b, r)


def test_changed_decision_requires_grounding_and_nonempty_rationale(case):
    b = bundle(case)
    r = make_review(b)
    r.update(
        task_decision="unacceptable",
        operational_impact="decision_changed",
        explanation_grounding="contradicted",
        claim_truth="supported_false",
    )
    r["claims"][0]["rationale"] = " "
    with pytest.raises(ValueError, match="rationale"):
        evidence.validate_review(b, r)
