"""``derive_thresholds.py``: passes against the reference, thresholds, and the check of measured.json.

Synthetic result rows of ``TASK_DETECTION`` (a ``satisfice`` role), whose
case list and hashes the ``synthetic_role`` fixture pins to 22 cases and
fixed hashes — the script accepts the rows as a measurement of today's
prompts and case set, and the arithmetic below does not move when the
committed case set is trimmed (``trim_measurement_cases.py``). These tests
hold:

- an arm passes only when complete, within every bar, without a critical
  failure, and at least the reference's score less its binomial standard
  error from the same run;
- a monotone ladder gets the lowest index score at and above which every arm
  passes; a non-monotone one accepts measured models only;
- a second repetition (the reference again on the disputed cases) is recorded
  and changes no count, pass, yardstick or threshold;
- the document is what S2's reader (``resolver.validate_measured``) reads;
- ``check_measured`` refuses a document whose hashes are not today's, whose
  threshold or passes its own results do not give, and the committed
  ``roles/measured.json`` when there is one;
- a corpus record feeds MNEMONIC (every case), MEMORY_EXTRACT and
  MEMORY_MERGE (the automatic cases; the canary too), and a dry one is refused.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import derive_thresholds as derive  # noqa: E402
import measurement_common as common  # noqa: E402

ROLE = "TASK_DETECTION"
K3 = "moonshotai/kimi-k3"
CASE_IDS = [f"task_detection-{n:02d}" for n in range(1, 23)]
HASHES = {"case_set_sha256": "c" * 64, "prompt_sha256": "d" * 64}


@pytest.fixture
def synthetic_role(monkeypatch):
    """TASK_DETECTION as 22 cases with fixed hashes; every other role as committed."""
    document, requests, case_set = (
        common.load_document,
        common.load_requests,
        common.case_set_sha256,
    )

    def pinned(real, value):
        return lambda role: value() if role == ROLE else real(role)

    cases = {"schema": 1, "role": ROLE, "cases": [{"id": i} for i in CASE_IDS]}
    monkeypatch.setattr(common, "load_document", pinned(document, lambda: copy.deepcopy(cases)))
    monkeypatch.setattr(common, "load_requests", pinned(requests, lambda: dict(HASHES)))
    monkeypatch.setattr(
        common, "case_set_sha256", pinned(case_set, lambda: HASHES["case_set_sha256"])
    )


def case_ids():
    return list(CASE_IDS)


def rows(arm, score, passes, *, bars_ok=True, critical=(), errors=()):
    """One scored row per case; the first ``passes`` cases match their label."""
    out = []
    for n, case_id in enumerate(case_ids()):
        row = {
            "role": ROLE,
            "arm": arm,
            "case_id": case_id,
            "repetition": 1,
            "status": "error" if case_id in errors else "scored",
            "arm_score": score,
            **HASHES,
            "snapshot_version": "snap",
        }
        if row["status"] == "scored":
            row["scoring"] = {
                "label_match": n < passes,
                "bars_ok": bars_ok,
                "critical": case_id in critical,
            }
        out.append(row)
    return out


def ladder(*arms):
    """K3 (43.6) passes 20 of 22: p 0.909, se 0.061, so 19 of 22 passes and 18 fails."""
    every = rows(K3, 43.6, 20)
    for arm, score, passes in arms:
        every += rows(arm, score, passes)
    return every


def entry(rows_):
    document, unmeasured = derive.derive(rows_, roles={ROLE: {"rule": "satisfice", "index": "x"}})
    assert unmeasured == {}
    return document, document["roles"][ROLE]


def test_a_monotone_ladder_gets_the_lowest_index_at_and_above_which_every_arm_passes(
    synthetic_role,
):
    _doc, role = entry(ladder(("flash", 24.4, 15), ("mimo", 37.9, 18), ("pro", 46.3, 19)))
    results = role["results"]
    assert [results[a]["pass"] for a in ("flash", "mimo", "pro", K3)] == [False, False, True, True]
    assert role["threshold"] == 43.6 and role["measured_only"] is False
    assert role["reference"]["id"] == K3 and role["reference"]["se"] == pytest.approx(0.0613, 1e-2)


def test_a_non_monotone_ladder_accepts_measured_models_only(synthetic_role):
    _doc, role = entry(ladder(("flash", 24.4, 21), ("mimo", 37.9, 15), ("pro", 46.3, 19)))
    assert role["results"]["flash"]["pass"] and not role["results"]["mimo"]["pass"]
    assert role["threshold"] is None and role["measured_only"] is True


def test_a_bar_a_critical_failure_or_a_missing_case_fails_an_arm_that_scores_well(synthetic_role):
    first = case_ids()[0]
    every = ladder()
    every += rows("bars", 50.0, 22, bars_ok=False)
    every += rows("crit", 51.0, 22, critical={case_ids()[-1]})
    every += rows("gap", 52.0, 22, errors={first})
    _doc, role = entry(every)
    reasons = {arm: role["results"][arm]["reasons"] for arm in ("bars", "crit", "gap")}
    assert reasons == {
        "bars": ["mechanical bar"],
        "crit": ["critical failure"],
        "gap": ["incomplete"],
    }


def test_a_cell_run_again_after_a_resume_counts_once_its_newest_row(synthetic_role):
    stale = rows("pro", 46.3, 19)[:1]
    stale[0].update(status="cap")
    stale[0].pop("scoring")
    _doc, role = entry(stale + ladder(("pro", 46.3, 19)))
    assert role["results"]["pro"]["complete"] and role["results"]["pro"]["n"] == 22


def test_a_second_repetition_is_recorded_and_changes_no_pass_or_fail(synthetic_role):
    every = ladder(("mimo", 37.9, 18), ("pro", 46.3, 19))
    _doc, before = entry(every)
    # The reference again on two disputed cases, both answered otherwise, and an arm's
    # second answers: pooled, they would lower p and let mimo (18 of 22) pass.
    again = rows(K3, 43.6, 0)[:2] + rows("mimo", 37.9, 22)[18:20]
    _doc, after = entry(every + [{**row, "repetition": 2} for row in again])
    assert {arm: after["results"][arm] for arm in (K3, "mimo", "pro")} == before["results"]
    assert not after["results"]["mimo"]["pass"] and after["reference"] == before["reference"]
    assert (after["threshold"], after["measured_only"]) == (before["threshold"], False)
    ids = case_ids()
    assert after["second_repetition"] == {
        K3: {ids[0]: {"first": True, "second": False}, ids[1]: {"first": True, "second": False}},
        "mimo": {
            ids[18]: {"first": False, "second": True},
            ids[19]: {"first": False, "second": True},
        },
    }
    assert before["second_repetition"] == {}


def test_a_role_without_a_complete_reference_is_reported_unmeasured_not_written(synthetic_role):
    every = rows(K3, 43.6, 20, errors={case_ids()[3]}) + rows("pro", 46.3, 22)
    document, unmeasured = derive.derive(every, roles={ROLE: {"rule": "satisfice", "index": "x"}})
    assert ROLE not in document["roles"] and "reference" in unmeasured[ROLE]


def test_the_document_is_what_the_resolver_reads(synthetic_role):
    from zylch.llm.roles import resolver

    document, _role = entry(ladder(("pro", 46.3, 19)))
    requirements = common.requirements()
    assert resolver.validate_measured(document, requirements["roles"]) is document
    assert document["written_by"] == derive.WRITTEN_BY


def test_check_measured_refuses_hashes_thresholds_and_passes_the_results_do_not_give(
    synthetic_role,
):
    document, _role = entry(ladder(("flash", 24.4, 15), ("pro", 46.3, 19)))
    assert derive.check_measured(document) == []
    stale = copy.deepcopy(document)
    stale["roles"][ROLE]["prompt_sha256"] = "0" * 64
    assert any("hashes" in p for p in derive.check_measured(stale))
    typed = copy.deepcopy(document)
    typed["roles"][ROLE]["threshold"] = 40
    assert any("threshold" in p for p in derive.check_measured(typed))
    promoted = copy.deepcopy(document)
    promoted["roles"][ROLE]["results"]["flash"]["pass"] = True
    assert any("flash" in p for p in derive.check_measured(promoted))


def test_the_committed_measured_json_is_the_one_the_script_derives():
    if not common.MEASURED.is_file():
        pytest.skip("no roles/measured.json yet: the paid measurement writes it")
    document = json.loads(common.MEASURED.read_text(encoding="utf-8"))
    assert derive.check_measured(document) == []


def corpus_record(tmp_path, mode="live"):
    hashes = derive.corpus_hashes()
    manifest = {
        "mode": mode,
        "arm_id": K3,
        "model": K3,
        "case_set_sha256": hashes["MNEMONIC"][0],
        "prompt_version_sha256": hashes["MNEMONIC"][1],
        "extraction_prompt_sha256": hashes["MEMORY_EXTRACT"][1],
        "snapshot_version": "snap",
        "checks": {"canary": {"verdict": "refused"}},
    }
    records = [
        {"case_id": "a1", "caller_class": "automatic_observation", "verdict": "pass", "calls": 2},
        {"case_id": "a2", "caller_class": "automatic_observation", "verdict": "critical_failure"},
        {"case_id": "i1", "caller_class": "interactive_turn", "verdict": "noncritical", "calls": 1},
    ]
    path = tmp_path / "p-manifest.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / "p-results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_a_corpus_record_feeds_the_three_memory_roles(tmp_path):
    rules = common.requirements()["roles"]
    found = derive.corpus_rows(corpus_record(tmp_path), {(K3, "intelligence"): 43.6}, rules)
    cases = {
        role: [r["case_id"] for r in found if r["role"] == role] for role in common.CORPUS_ROLES
    }
    assert cases == {
        "MNEMONIC": ["a1", "a2", "i1"],
        "MEMORY_EXTRACT": ["a1", "a2"],
        "MEMORY_MERGE": ["a1", "a2", "canary"],
    }
    scoring = {(r["role"], r["case_id"]): r["scoring"] for r in found}
    assert scoring[("MNEMONIC", "a2")]["critical"] and not scoring[("MNEMONIC", "i1")]["critical"]
    assert not scoring[("MNEMONIC", "i1")]["label_match"]
    assert not scoring[("MNEMONIC", "a2")]["bars_ok"]  # no call recorded
    assert scoring[("MEMORY_MERGE", "canary")] == {
        "label_match": True,
        "critical": False,
        "bars_ok": True,
    }
    assert {r["arm_score"] for r in found} == {43.6}


def test_a_dry_corpus_record_measures_no_model(tmp_path):
    with pytest.raises(derive.Refused, match="dry"):
        derive.corpus_rows(corpus_record(tmp_path, "dry"), {}, common.requirements()["roles"])
