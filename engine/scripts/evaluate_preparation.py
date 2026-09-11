#!/usr/bin/env python3
"""Offline synthetic preparation evaluation; never invokes a model or network."""

import argparse
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

from zylch.memory.response_validation import complete_memory_text
from zylch.memory.llm_merge import is_no_merge_response
from zylch.workers.memory import MemoryWorker, _parse_identifiers_block

FIXTURES = Path(__file__).resolve().parents[1] / "tests/evaluation/preparation_cases.json"


def _response(raw):
    return SimpleNamespace(
        stop_reason=raw.get("stop_reason"),
        content=[SimpleNamespace(**block) for block in raw.get("content", [])],
    )


def assess(case, raw):
    """Compare explicit human-authored expectations, without inferring semantics."""
    expected = case["expected"]
    try:
        response = _response(raw)
    except (ValueError, TypeError, AttributeError):
        return {"accepted": False, "correct": not expected["accept"]}
    if case["role"] == "task":
        blocks = [
            b
            for b in response.content
            if getattr(b, "type", None) == "tool_use"
            and getattr(b, "name", None) == "task_decision"
        ]
        decision = getattr(blocks[0], "input", None) if len(blocks) == 1 else None
        valid = response.stop_reason == "tool_use" and isinstance(decision, dict)
        if valid:
            valid = (
                type(decision.get("action_required")) is bool
                and isinstance(decision.get("task_action"), str)
                and decision.get("task_action") in {"create", "update", "close", "none"}
                and isinstance(decision.get("urgency"), str)
                and decision.get("urgency") in {"critical", "high", "medium", "low"}
                and isinstance(decision.get("reason"), str)
                and isinstance(decision.get("suggested_action"), str)
            )
        matches = valid and all(
            decision.get(k) == v for k, v in expected.get("decision", {}).items()
        )
        return {
            "accepted": bool(valid),
            "correct": bool(matches if expected["accept"] else not valid),
        }
    try:
        text = complete_memory_text(response)
        refused_merge = case["role"] == "merge" and is_no_merge_response(text)
        blobs = (
            []
            if text.upper() == "SKIP" or refused_merge
            else MemoryWorker._parse_entities(None, text)
        )
        identities = sorted(sorted(_parse_identifiers_block(blob)) for blob in blobs)
        targets = sorted(
            sorted(tuple(pair) for pair in group) for group in expected.get("identities", [])
        )
        correct = expected["accept"] and identities == targets
        if case["role"] == "merge":
            correct = correct and refused_merge == expected["insert"]
        return {"accepted": True, "correct": bool(correct), "identity_exact": identities == targets}
    except (ValueError, RuntimeError, TypeError, AttributeError):
        return {"accepted": False, "correct": not expected["accept"]}


def evaluate(cases, captures, *, reference=False):
    by_id = {row["id"]: row for row in captures}
    if len(by_id) != len(captures):
        raise ValueError("Duplicate capture IDs")
    expected_ids = {case["id"] for case in cases}
    if set(by_id) != expected_ids:
        raise ValueError(
            "Captures must cover exactly the fixture IDs; missing cases cannot disappear"
        )
    totals = defaultdict(lambda: {"cases": 0, "correct": 0, "false_accepts": 0})
    results, cost, configurations = [], Decimal(0), set()
    for case in cases:
        row = by_id[case["id"]]
        for key in ("provider", "model"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Capture {case['id']} needs {key}")
        amount = Decimal(str(row["cost_usd"]))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Cost must be finite and nonnegative")
        cost += amount
        configurations.add((row["provider"], row["model"]))
        result = assess(case, row["response"])
        results.append({"id": case["id"], "role": case["role"], **result})
        summary = totals[case["role"]]
        summary["cases"] += 1
        summary["correct"] += int(result["correct"])
        summary["false_accepts"] += int(result["accepted"] and not case["expected"]["accept"])
    return {
        "evaluation": "reference evaluator self-check"
        if reference
        else "captured-response fixture evaluation",
        "quality": "unmeasured"
        if reference
        else "synthetic fixtures only; not production-quality evidence",
        "cost_usd": str(cost),
        "configurations": [{"provider": p, "model": m} for p, m in sorted(configurations)],
        "roles": dict(totals),
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--captures", type=Path, help="JSON list of recorded model responses")
    source.add_argument("--reference-self-check", action="store_true")
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args()
    cases = json.loads(args.fixtures.read_text())
    captures = (
        json.loads(args.captures.read_text())
        if args.captures
        else [
            {
                "id": case["id"],
                "provider": "reference",
                "model": "human-authored",
                "cost_usd": 0,
                "response": case["reference_response"],
            }
            for case in cases
        ]
    )
    report = evaluate(cases, captures, reference=args.reference_self_check)
    print(json.dumps(report, indent=2))
    return int(any(not row["correct"] for row in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
