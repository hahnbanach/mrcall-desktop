import copy
import importlib.util
import json
from pathlib import Path

import pytest

S = importlib.util.spec_from_file_location(
    "aggregate", Path(__file__).resolve().parents[2] / "scripts/summarize_model_quality.py"
)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)
OPUS, K3 = "synthetic/baseline", "synthetic/comparison"


def fixture(tmp_path, scenarios):
    packed = []
    grades = []
    mapping = {}
    rubrics = {}
    for i, scenario in enumerate(scenarios):
        cid = f"case{i}"
        rubrics[cid] = {"task_disposition_class": "positive" if i % 2 else "negative"}
        for model, spec in zip([OPUS, K3], scenario):
            semantic, contract, complete, present, graded = spec
            label = f"{i}-{model}"
            packed.append(
                {
                    "label": label,
                    "case_id": cid,
                    "stage": "task.detect",
                    "stratum": "a" if i % 2 else "b",
                    "content": [] if present else None,
                    "completion": complete,
                    "production_parser_accepted": complete,
                }
            )
            mapping[label] = {"model": model, "case_id": cid}
            if graded:
                grades.append(
                    {
                        "label": label,
                        "case_id": cid,
                        "semantic_verdict": semantic,
                        "contract_verdict": contract,
                    }
                )

    def run():
        for filename, data in [
            ("blind-map.json", mapping),
            ("rubrics.json", rubrics),
            ("blind-group-1.json", packed),
            ("grades.json", grades),
        ]:
            (tmp_path / filename).write_text(json.dumps(data))
        return M.summarize(tmp_path, [tmp_path / "grades.json"], "synthetic", OPUS)

    return packed, grades, mapping, run


PASS = ("acceptable", "acceptable", True, True, True)
FAIL = ("unacceptable", "acceptable", True, True, True)


def test_pair_denominators_and_subgroups(tmp_path):
    scenarios = [
        (PASS, PASS),
        (FAIL, FAIL),
        (PASS, FAIL),
        (FAIL, PASS),
        (PASS, ("acceptable", "acceptable", False, False, False)),
        (PASS, ("acceptable", "acceptable", True, True, False)),
        (PASS, ("indeterminate", "acceptable", True, True, True)),
        (PASS, ("acceptable", "indeterminate", True, True, True)),
        (PASS, ("acceptable", "unacceptable", True, True, True)),
    ]
    _, _, _, run = fixture(tmp_path, scenarios)
    r = run()
    pair = next(p for p in r["pairs"] if p["model"] == K3)
    assert pair["counts"] == {
        "planned_pairs": 9,
        "determinate_graded_pairs": 6,
        "semantic_tie_pass": 3,
        "usable_response_determinate_pairs": 5,
        "usable_response_tie_pass": 1,
        "semantic_tie_fail": 1,
        "usable_response_tie_fail": 1,
        "semantic_loss": 1,
        "usable_response_loss": 2,
        "semantic_win": 1,
        "usable_response_win": 1,
        "missing_response_pairs": 1,
        "ungraded_response_pairs": 1,
        "indeterminate_pairs": 1,
        "usable_response_indeterminate_contract_pairs": 1,
    }
    assert pair["observed_paired_pass_difference"] == -0.2
    for model in [OPUS, K3]:
        totals = next(x for x in r["counts"] if x["model"] == model)
        for dimension in ["stratum", "task_disposition"]:
            groups = [
                g for g in r["subgroups"] if g["model"] == model and g["dimension"] == dimension
            ]
            for key in ["planned", "graded", "model_response", "usable_response_acceptable"]:
                assert sum(g.get(key, 0) for g in groups) == totals.get(key, 0)
    assert M.interval([]) is None


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("duplicate-label", "Duplicate packed label"),
        ("duplicate-cell", "Duplicate case/model cell"),
        ("map-case", "Case identity mismatch"),
        ("grade-case", "Case identity mismatch"),
        ("phantom-grade", "Grade without model response"),
        ("unmatched-grade", "Unmatched grade label"),
        ("invalid-semantic", "Invalid grade verdict"),
        ("invalid-contract", "Invalid grade verdict"),
        ("inconsistent-grade", "Duplicate inconsistent grade"),
    ],
)
def test_invalid_inputs_refused(tmp_path, mutation, match):
    packed, grades, mapping, run = fixture(tmp_path, [(PASS, PASS)])
    if mutation == "duplicate-label":
        packed.append(copy.deepcopy(packed[0]))
    elif mutation == "duplicate-cell":
        row = copy.deepcopy(packed[0])
        row["label"] = "extra"
        packed.append(row)
        mapping["extra"] = copy.deepcopy(mapping[packed[0]["label"]])
    elif mutation == "map-case":
        mapping[packed[0]["label"]]["case_id"] = "wrong"
    elif mutation == "grade-case":
        grades[0]["case_id"] = "wrong"
    elif mutation == "phantom-grade":
        packed[0]["content"] = None
    elif mutation == "unmatched-grade":
        grades[0]["label"] = "missing"
    elif mutation == "invalid-semantic":
        grades[0]["semantic_verdict"] = "unknown"
    elif mutation == "invalid-contract":
        grades[0]["contract_verdict"] = "unknown"
    elif mutation == "inconsistent-grade":
        row = copy.deepcopy(grades[0])
        row["semantic_verdict"] = "unacceptable"
        grades.append(row)
    with pytest.raises(ValueError, match=match):
        run()


def test_cli_custom_baseline_and_input_hashes(tmp_path, monkeypatch, capsys):
    import hashlib
    import sys

    packed, grades, _, run = fixture(tmp_path, [(FAIL, PASS)])
    attach_evidence(tmp_path, packed[1], grades[1])
    run()
    output = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summary",
            "--pack-dir",
            str(tmp_path),
            "--grades",
            str(tmp_path / "grades.json"),
            "--cohort",
            "synthetic-cli",
            "--baseline",
            K3,
            "--output",
            str(output),
        ],
    )
    M.main()
    result = json.loads(output.read_text())
    assert result["cohort"] == "synthetic-cli"
    assert result["pairs"][0]["model"] == OPUS
    assert result["pairs"][0]["counts"]["semantic_loss"] == 1
    assert result["pairs"][0]["observed_paired_pass_difference"] == -1
    assert "evidence-by-label.json" in {source["file"] for source in result["input_sha256"]}
    for source in result["input_sha256"]:
        assert (
            source["sha256"] == hashlib.sha256((tmp_path / source["file"]).read_bytes()).hexdigest()
        )
    assert output.stat().st_mode & 0o077 == 0
    assert json.loads(capsys.readouterr().out) == {"cohort": "synthetic-cli", "role_model_rows": 2}


def test_cli_missing_explicit_grade_file_refused(tmp_path, monkeypatch):
    import sys

    output = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summary",
            "--pack-dir",
            str(tmp_path),
            "--grades",
            str(tmp_path / "missing.json"),
            "--cohort",
            "synthetic",
            "--baseline",
            OPUS,
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit):
        M.main()
    assert not output.exists()


def test_unknown_baseline_refused(tmp_path):
    _, _, _, run = fixture(tmp_path, [(PASS, PASS)])
    run()
    with pytest.raises(ValueError, match="Baseline model absent"):
        M.summarize(tmp_path, [tmp_path / "grades.json"], "synthetic", "unknown/model")


@pytest.mark.parametrize("missing_side", ["pack", "map"])
def test_pack_mapping_must_be_bijective(tmp_path, missing_side):
    packed, grades, mapping, run = fixture(tmp_path, [(PASS, PASS)])
    label = packed[-1]["label"]
    if missing_side == "pack":
        packed.pop()
        grades[:] = [g for g in grades if g["label"] != label]
    else:
        del mapping[label]
    with pytest.raises(ValueError, match="[Bb]ijection|[Ll]abel.*match|[Mm]ap.*pack|[Pp]ack.*map"):
        run()


def test_complete_valid_semantics_still_requires_actual_parser_acceptance(tmp_path):
    packed, _, _, run = fixture(tmp_path, [(PASS, PASS)])
    packed[1]["production_parser_accepted"] = False
    result = run()
    row = next(r for r in result["counts"] if r["model"] == K3)
    assert row["completed"] == row["semantic_acceptable"] == 1
    assert row["production_parser_accepted"] == row["usable_response_acceptable"] == 0
    assert result["pairs"][0]["counts"]["semantic_tie_pass"] == 1
    assert result["pairs"][0]["counts"]["usable_response_loss"] == 1
    assert all(
        r["usable_response_acceptable"] == 0 for r in result["subgroups"] if r["model"] == K3
    )


def test_legacy_dimensions_and_missing_parser_are_explicitly_unassessed(tmp_path):
    packed, _, _, run = fixture(tmp_path, [(PASS, PASS)])
    del packed[1]["production_parser_accepted"]
    result = run()
    row = next(r for r in result["counts"] if r["model"] == K3)
    assert row["production_parser_unassessed"] == 1
    assert row["usable_response_acceptable"] == 0
    for field in M.GRADE_DIMENSIONS:
        assert row[field + "_unassessed"] == 1
    assert "task_decision_acceptable" not in row


def test_acceptable_decision_is_separate_from_unknown_explanatory_claim(tmp_path):
    packed, grades, _, run = fixture(
        tmp_path, [(PASS, ("indeterminate", "acceptable", True, True, True))]
    )
    attach_evidence(tmp_path, packed[1], grades[1])
    grades[1].update(
        version=2,
        task_decision="acceptable",
        explanation_grounding="unsupported",
        claim_truth="unknown",
        operational_impact="explanation_only",
    )
    result = run()
    row = next(r for r in result["counts"] if r["model"] == K3)
    assert row["semantic_indeterminate"] == row["task_decision_acceptable"] == 1
    assert row["explanation_grounding_unsupported"] == row["claim_truth_unknown"] == 1
    assert row["operational_impact_explanation_only"] == 1
    assert row["usable_response_acceptable"] == 0
    for subgroup in result["subgroups"]:
        if subgroup["model"] == K3:
            assert subgroup["task_decision_acceptable"] == subgroup["claim_truth_unknown"] == 1


@pytest.mark.parametrize("field", list(M.GRADE_DIMENSIONS))
def test_invalid_optional_dimension_refused(tmp_path, field):
    packed, grades, _, run = fixture(tmp_path, [(PASS, PASS)])
    attach_evidence(tmp_path, packed[0], grades[0])
    grades[0][field] = "invented"
    with pytest.raises(ValueError, match="Invalid dimension"):
        run()


def attach_evidence(tmp_path, packed, grade):
    import runpy

    module = runpy.run_path(str(Path(M.__file__).with_name("model_quality_evidence.py")))
    bundle = module["build_evidence"](
        {
            "id": packed["case_id"],
            "stage": packed["stage"],
            "request": {"system": "Use confirmed payment status only."},
        },
        "2026-09-16T00:00:00+00:00",
        packed["content"],
    )
    source = bundle["sections"][0]
    grade.update(
        version=2,
        bundle_sha256=bundle["bundle_sha256"],
        coverage=[b["id"] for b in bundle["sections"]],
        task_decision="acceptable",
        explanation_grounding="unsupported",
        claim_truth="unknown",
        operational_impact="explanation_only",
        claims=[
            {
                "rationale": "Correct no-action; explanation unverified.",
                "output_quote": "[]",
                "source_refs": [
                    {"id": source["id"], "sha256": source["sha256"], "quote": source["text"]}
                ],
            }
        ],
    )
    (tmp_path / "evidence-by-label.json").write_text(json.dumps({packed["label"]: bundle}))
    return bundle


@pytest.mark.parametrize("mutation", ["missing", "metadata", "quote", "output", "case", "stage"])
def test_grade_v2_requires_complete_bound_evidence(tmp_path, mutation):
    packed, grades, _, run = fixture(tmp_path, [(PASS, PASS)])
    bundle = attach_evidence(tmp_path, packed[0], grades[0])
    evidence = tmp_path / "evidence-by-label.json"
    if mutation == "missing":
        evidence.unlink()
    elif mutation == "metadata":
        del grades[0]["coverage"]
    elif mutation == "quote":
        grades[0]["claims"][0]["source_refs"][0]["quote"] = "not present"
    elif mutation == "output":
        packed[0]["content"] = [{"type": "text", "text": "different output"}]
    else:
        bundle["case_id" if mutation == "case" else "stage"] = "different"
        evidence.write_text(json.dumps({packed[0]["label"]: bundle}))
    with pytest.raises(ValueError):
        run()


@pytest.mark.parametrize("value", [None, "true", 1, []])
def test_unknown_parser_excludes_usable_pair_but_keeps_semantics(tmp_path, value):
    packed, _, _, run = fixture(tmp_path, [(PASS, PASS)])
    packed[1]["production_parser_accepted"] = value
    result = run()
    pair = result["pairs"][0]["counts"]
    assert pair["semantic_tie_pass"] == 1
    assert pair["usable_response_unassessed_parser_pairs"] == 1
    assert pair.get("usable_response_determinate_pairs", 0) == 0
    assert pair.get("usable_response_loss", 0) == 0


def test_partial_dimensions_cannot_bypass_v2_validation(tmp_path):
    _, grades, _, run = fixture(tmp_path, [(PASS, PASS)])
    grades[0]["task_decision"] = "acceptable"
    with pytest.raises(ValueError, match="requires matching evidence"):
        run()
