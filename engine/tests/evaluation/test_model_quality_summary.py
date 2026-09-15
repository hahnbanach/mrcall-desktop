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

    _, _, _, run = fixture(tmp_path, [(FAIL, PASS)])
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
