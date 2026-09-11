import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/evaluate_preparation.py"
spec = importlib.util.spec_from_file_location("preparation_evaluation", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def dataset():
    cases = json.loads(module.FIXTURES.read_text())
    captures = [
        {
            "id": c["id"],
            "provider": "reference",
            "model": "human-authored",
            "cost_usd": 0,
            "response": copy.deepcopy(c["reference_response"]),
        }
        for c in cases
    ]
    return cases, captures


def test_reference_checks_evaluator_not_model_quality():
    cases, captures = dataset()
    result = module.evaluate(cases, captures, reference=True)
    assert result["quality"] == "unmeasured"
    assert len(result["cases"]) == 10
    assert all(row["correct"] for row in result["cases"])


def test_sender_identifier_contamination_is_wrong():
    cases, captures = dataset()
    captures[0]["response"]["content"][0]["text"] = captures[0]["response"]["content"][0][
        "text"
    ].replace("Email: luca@example.test", "Email: luca@example.test, anna@example.test")
    assert not module.evaluate(cases, captures)["cases"][0]["correct"]


def test_false_merge_is_wrong_even_with_finished_output():
    cases, captures = dataset()
    captures[5]["response"] = captures[4]["response"]
    assert not module.evaluate(cases, captures)["cases"][5]["correct"]


def test_truncated_task_cannot_be_accepted():
    cases, captures = dataset()
    result = module.evaluate(cases, captures)
    assert result["cases"][-1]["accepted"] is False
    captures[-1]["response"]["stop_reason"] = "tool_use"
    assert module.evaluate(cases, captures)["roles"]["task"]["false_accepts"] == 1


@pytest.mark.parametrize("problem", ["missing", "duplicate", "model", "nan_cost", "negative_cost"])
def test_incomplete_or_unaccountable_capture_set_refused(problem):
    cases, captures = dataset()
    if problem == "missing":
        captures.pop()
    elif problem == "duplicate":
        captures.append(captures[0])
    elif problem == "model":
        captures[0]["model"] = ""
    else:
        captures[0]["cost_usd"] = "NaN" if problem == "nan_cost" else -1
    with pytest.raises(ValueError):
        module.evaluate(cases, captures)


def test_malformed_model_decision_scores_failure_without_aborting_report():
    cases, captures = dataset()
    captures[7]["response"]["content"][0]["input"]["task_action"] = []
    assert not module.evaluate(cases, captures)["cases"][7]["correct"]
    captures[0]["response"]["content"] = None
    assert not module.evaluate(cases, captures)["cases"][0]["correct"]
