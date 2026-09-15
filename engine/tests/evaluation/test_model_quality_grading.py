"""Offline grading integrity: operational evidence is never replaced by semantics."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rig(tmp_path):
    module = load_script("prepare_model_quality_grading")
    case = {
        "id": "case-one",
        "stage": "memory.extract",
        "split": "heldout",
        "stratum": "one",
        "opaque_thread_id": "thread-one",
        "request": {"system": "Synthetic source policy", "messages": [], "max_tokens": 100},
    }
    cells = [
        {"id": "cell-one", "case_id": "case-one", "model": "vendor/model-one"},
        {"id": "cell-missing", "case_id": "case-one", "model": "vendor/model-two"},
    ]
    manifest = {"arm": "original", "as_of": "clock-one", "cases": [case], "cells": cells}
    manifest_path = tmp_path / "original.json"
    manifest_path.write_text(json.dumps(manifest))
    results = tmp_path / "results"
    results.mkdir()
    rubric = tmp_path / "rubric.json"
    rubric.write_text(json.dumps({"case-one": {"existing_task_ids": []}}))
    freeze = tmp_path / "freeze.json"
    freeze.write_text('{"approved":true}')
    config = {
        "sources": [{"manifest": str(manifest_path), "results": str(results)}],
        "rubric": str(rubric),
        "output": str(tmp_path / "output"),
    }

    def journal(rows, directory=results):
        directory.mkdir(exist_ok=True)
        (directory / "attempts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))

    def run():
        summary = module.prepare(config, freeze, lambda *args: {"accepted": True})
        outputs = [
            row
            for p in (tmp_path / "output").glob("blind-group-*.json")
            for row in json.loads(p.read_text())
        ]
        return summary, outputs

    return module, config, manifest, journal, run


def response(text="first", stop="end_turn", cell="cell-one"):
    return {
        "event": "result",
        "cell_id": cell,
        "case_id": "case-one",
        "model": "vendor/model-one",
        "response": {
            "model": "vendor/model-one",
            "id": "provider-generation-id",
            "usage": {"cost": 500},
            "stop_reason": stop,
            "content": [{"type": "text", "text": text, "id": "tool-id-secret"}],
        },
    }


def test_first_actual_response_keeps_failed_attempts_and_missing_cells(rig):
    _, config, _, journal, run = rig
    journal(
        [
            {"event": "intent", "cell_id": "cell-one"},
            {"event": "result", "cell_id": "cell-one", "status": "unavailable"},
            response("first truncated", "max_tokens"),
            response("later good"),
        ]
    )
    summary, outputs = run()
    found = next(r for r in outputs if r["availability"] == "model_response")
    assert found["content"][0]["text"] == "first truncated"
    assert found["completion"] is False
    assert summary["expected_cells"] == 2 and summary["missing_cells"] == 1
    assert len(json.loads((Path(config["output"]) / "operational-audit.json").read_text())) == 4
    assert "provider-generation-id" not in json.dumps(outputs)
    assert "tool-id-secret" not in json.dumps(outputs)
    assert "500" not in json.dumps(outputs)
    assert "vendor/model-one" not in json.dumps(outputs)


def add_recovery(rig, tmp_path, change=None, duplicate=False):
    _, config, original, journal, _ = rig
    recovered = copy.deepcopy(original)
    recovered["cells"] = [
        {**original["cells"][0], "id": "recovered", "original_cell_id": "cell-one"}
    ]
    if duplicate:
        recovered["cells"].append({**recovered["cells"][0], "id": "also-recovered"})
    if change:
        change(recovered)
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(recovered))
    result_dir = tmp_path / "recovery-results"
    journal([response("recovered answer", cell="recovered")], result_dir)
    config["sources"].append({"manifest": str(path), "results": str(result_dir)})


def test_recovery_maps_to_original_and_labels_survive_refresh(rig, tmp_path):
    _, _, _, journal, run = rig
    journal([{"event": "result", "cell_id": "cell-one", "status": "unavailable"}])
    _, before = run()
    labels = {r["label"] for r in before}
    add_recovery(rig, tmp_path)
    summary, after = run()
    assert {r["label"] for r in after} == labels
    assert summary["expected_cells"] == 2 and summary["response_cells"] == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m["cases"][0]["request"].update(max_tokens=200),
        lambda m: m.update(as_of="different clock"),
        lambda m: m["cells"][0].update(model="other-model"),
    ],
)
def test_recovery_cannot_change_request_clock_or_model(rig, tmp_path, change):
    add_recovery(rig, tmp_path, change)
    with pytest.raises(ValueError, match="identity/request mismatch"):
        rig[-1]()


def test_many_recoveries_cannot_alias_one_cell(rig, tmp_path):
    add_recovery(rig, tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="bijective"):
        rig[-1]()


def test_orphan_recovery_is_rejected(rig, tmp_path):
    add_recovery(rig, tmp_path)
    rig[1]["sources"] = rig[1]["sources"][1:]
    with pytest.raises(ValueError, match="no original cell"):
        rig[-1]()


def test_journal_cannot_substitute_another_cell_model(rig):
    row = response()
    row["model"] = "different-model"
    rig[3]([row])
    with pytest.raises(ValueError, match="Journal model"):
        rig[-1]()


def test_empty_response_is_a_semantic_attempt_not_missing(rig):
    row = response()
    row["response"] = {}
    rig[3]([row])
    summary, rows = rig[-1]()
    assert summary["response_cells"] == 1
    assert next(r for r in rows if r["availability"] == "model_response")["completion"] is False


def test_paired_variants_require_explicit_mode(rig, tmp_path):
    _, config, original, journal, run = rig
    candidate = copy.deepcopy(original)
    candidate["arm"] = "candidate"
    candidate["cases"][0]["request"]["system"] = "Alternative synthetic policy"
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    result_dir = tmp_path / "candidate-results"
    journal([response("candidate text")], result_dir)
    config["sources"].append({"manifest": str(path), "results": str(result_dir)})
    with pytest.raises(ValueError, match="paired_variants"):
        run()
    config["paired_variants"] = True
    summary, rows = run()
    assert summary["expected_cells"] == 4
    assert all("arm" not in row and "model" not in row for row in rows)


def test_source_drift_propagates_instead_of_failing_a_model(rig):
    module, config, _, journal, _ = rig
    journal([response()])

    def drift(*args):
        raise RuntimeError("source drift")

    with pytest.raises(RuntimeError, match="source drift"):
        module.prepare(config, Path(config["rubric"]), drift)


def test_actual_parser_is_offline_source_relative_and_rejects_truncation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = load_script("model_quality_parsers")
    from zylch.llm.client import LLMClient
    from zylch.storage import database

    def forbidden(*args, **kwargs):
        pytest.fail("Offline parser accessed inference/storage")

    monkeypatch.setattr(LLMClient, "create_message_sync", forbidden)
    monkeypatch.setattr(LLMClient, "create_message", forbidden)
    monkeypatch.setattr(database, "get_engine", forbidden)
    raw = {"content": [{"type": "text", "text": "SKIP"}], "stop_reason": "max_tokens"}
    assert module.parse("memory.extract", raw)["accepted"] is False
    raw["stop_reason"] = "end_turn"
    assert module.parse("memory.extract", raw)["accepted"] is True
    raw = {
        "content": [
            {
                "type": "tool_use",
                "name": "task_decision",
                "input": {
                    "action_required": False,
                    "task_action": "none",
                    "urgency": "low",
                    "reason": "Synthetic source",
                    "suggested_action": "No action",
                },
            }
        ],
        "stop_reason": "tool_use",
    }
    assert module.parse("task.detect", raw)["accepted"] is True
    raw["stop_reason"] = "max_tokens"
    assert module.parse("task.detect", raw)["accepted"] is False
    assert len(module.parser_provenance()["task_validation_ast_sha256"]) == 64


def test_actual_parser_fails_closed_on_signature_or_validation_drift():
    module = load_script("model_quality_parsers")
    source = module.TASK_SOURCE.read_text()
    module.extract_task_validation(source)
    with pytest.raises(module.ParserSourceDrift, match="signature"):
        module.extract_task_validation(
            source.replace('calendar_context: str = "",', 'new_context: str = "",')
        )
    with pytest.raises(module.ParserSourceDrift, match="AST hash"):
        module.extract_task_validation(
            source.replace(
                'response.stop_reason != "tool_use"', 'response.stop_reason != "changed"'
            )
        )


@pytest.mark.parametrize("content", [None, "malformed text", [None], [42]])
def test_malformed_content_remains_first_response_for_grading(rig, content):
    row = response()
    row["response"]["content"] = content
    rig[3]([row, response("later valid")])
    summary, outputs = rig[-1]()
    found = next(r for r in outputs if r["availability"] == "model_response")
    assert summary["response_cells"] == 1
    assert any(b["type"].startswith("malformed") for b in found["content"])
    assert "later valid" not in json.dumps(found)
    assert rig[0].task_contract({}, row["response"], {})


def test_numeric_task_target_is_contract_failure_not_crash(rig):
    case = {
        "request": {
            "tools": [
                {
                    "name": "task_decision",
                    "input_schema": {
                        "type": "object",
                        "properties": {"target_task_id": {"type": "string"}},
                    },
                }
            ]
        }
    }
    raw = {
        "content": [
            {
                "type": "tool_use",
                "name": "task_decision",
                "input": {"task_action": "update", "target_task_id": 123},
            }
        ]
    }
    errors = rig[0].task_contract(case, raw, {})
    assert any("must be a string" in e for e in errors)


def test_paired_legacy_labels_cannot_silently_overwrite_identity(rig):
    rig[1].update(paired_variants=True, legacy_labels=True)
    with pytest.raises(ValueError, match="legacy labels"):
        rig[-1]()


def test_same_thread_cannot_be_assigned_multiple_strata(rig, tmp_path):
    _, config, original, _, run = rig
    extra = copy.deepcopy(original["cases"][0])
    extra.update(id="second-case", stratum="different-stratum")
    original["cases"].append(extra)
    original["cells"].append({"id": "second-cell", "case_id": "second-case", "model": "other"})
    Path(config["sources"][0]["manifest"]).write_text(json.dumps(original))
    Path(config["rubric"]).write_text(json.dumps({"case-one": {}, "second-case": {}}))
    with pytest.raises(ValueError, match="multiple strata"):
        run()


def test_raw_completion_baseline_and_counterfactual_are_separate():
    from types import SimpleNamespace

    from zylch.llm.client import LLMResponse

    module = load_script("model_quality_parsers")
    raw = {
        "stop_reason": "end_turn",
        "content": [
            {
                "type": "tool_use",
                "id": "one",
                "name": "task_decision",
                "input": {
                    "action_required": False,
                    "task_action": "none",
                    "urgency": "low",
                    "reason": "Synthetic source",
                    "suggested_action": "No action",
                },
            }
        ],
    }
    assert module.parse("task.detect", raw)["accepted"] is False
    assert (
        module.parse("task.detect", raw, completion_mode="counterfactual_tool_completion_v1")[
            "accepted"
        ]
        is True
    )
    adapted = LLMResponse(
        SimpleNamespace(**{**raw, "content": [SimpleNamespace(**raw["content"][0])]})
    )
    assert adapted.stop_reason == "tool_use"
    assert module.parse("task.detect", adapted)["accepted"] is False
    raw["stop_reason"] = "max_tokens"
    assert (
        module.parse("task.detect", raw, completion_mode="counterfactual_tool_completion_v1")[
            "accepted"
        ]
        is False
    )
    assert len(module.parser_provenance()["response_adapter_sha256"]) == 64
