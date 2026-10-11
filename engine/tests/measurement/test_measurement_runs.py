"""Runs: each arm judged against the reference of its own run; shaped requests checked (S4b7).

- two runs of one role, the reference 22/22 in one and 20/22 in the other:
  an arm scoring 21/22 fails against the first and passes against the
  second, and each result names the run that judged it (``judged_by``);
- the reference, measured in both runs, is judged in each; its result keeps
  both (``runs``), and the role's ``reference`` lists both yardsticks;
- an arm of a run without a complete reference cannot be judged: it goes
  under ``incomplete``;
- ``check_measured`` refuses a result judged by another run's yardstick and a
  reference entry that is not the reference's own results;
- ``measurement_shape``: the headroom fix (code) makes every MiMo v2.6 request at the
  2026-10-04 run's commit and snapshot stale, Sonnet's not, and a request
  shaped on today's commit stale for nobody; the 2026-10-02 snapshot alone
  makes deepseek's CHAT tools stale; a corpus row is checked on the
  decision call's probe; a row with no run commit is refused.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import derive_thresholds as derive  # noqa: E402
import measurement_shape as shape  # noqa: E402
from tests.measurement.test_derive_thresholds import (  # noqa: E402,F401
    K3,
    ROLE,
    rows,
    synthetic_role,
)

MIMO, SONNET = "xiaomi/mimo-v2.6-pro", "anthropic/claude-sonnet-5.5"
RUN_COMMIT, RUN_SNAPSHOT = (
    "8b18ea69",
    "81998270380cb1927ada4bddf4d8869802edb73a9b042fb8560e2db95c610e05",
)


def in_run(run, rows_):
    return [{**row, "run": run} for row in rows_]


def two_runs():
    """Run A: K3 22/22 (p 1, se 0). Run B: K3 20/22 (p 0.909, se 0.061). One arm 21/22 in each."""
    every = in_run("A", rows(K3, 43.6, 22) + rows("opus", 57.6, 21))
    every += in_run("B", rows(K3, 43.6, 20) + rows("sonnet", 56.0, 21))
    document, unmeasured = derive.derive(every, roles={ROLE: {"rule": "satisfice", "index": "x"}})
    assert unmeasured == {}
    return document, document["roles"][ROLE]


@pytest.mark.usefixtures("synthetic_role")
def test_each_arm_is_judged_against_the_reference_of_its_own_run():
    _doc, role = two_runs()
    opus, sonnet = role["results"]["opus"], role["results"]["sonnet"]
    assert (opus["judged_by"], sonnet["judged_by"]) == ("A", "B")
    assert not opus["pass"] and "below the reference less its standard error" in opus["reasons"]
    assert sonnet["pass"]


@pytest.mark.usefixtures("synthetic_role")
def test_the_reference_is_judged_in_every_run_and_lists_each_yardstick():
    _doc, role = two_runs()
    k3 = role["results"][K3]
    assert k3["judged_by"] == ["A", "B"] and set(k3["runs"]) == {"A", "B"}
    assert (k3["n"], k3["passes"], k3["pass"]) == (44, 42, True)
    yardsticks = role["reference"]["runs"]
    assert yardsticks["A"] == {"n": 22, "passes": 22, "score": 1.0, "se": 0.0}
    assert yardsticks["B"]["score"] == pytest.approx(0.909091) and "score" not in role["reference"]


@pytest.mark.usefixtures("synthetic_role")
def test_an_arm_of_a_run_without_its_reference_is_not_judged():
    every = in_run("A", rows(K3, 43.6, 22)) + in_run("C", rows("lonely", 30.0, 22))
    document, _ = derive.derive(every, roles={ROLE: {"rule": "satisfice", "index": "x"}})
    role = document["roles"][ROLE]
    assert "lonely" not in role["results"]
    assert "no complete reference result" in role["incomplete"]["lonely"]


@pytest.mark.usefixtures("synthetic_role")
def test_check_measured_refuses_another_runs_yardstick_and_a_borrowed_reference():
    document, _role = two_runs()
    assert derive.check_measured(document) == []
    moved = copy.deepcopy(document)
    moved["roles"][ROLE]["results"]["opus"]["judged_by"] = "B"
    assert any("opus" in p for p in derive.check_measured(moved))
    borrowed = copy.deepcopy(document)
    borrowed["roles"][ROLE]["reference"]["runs"]["A"]["score"] = 0.5
    assert any("yardsticks" in p for p in derive.check_measured(borrowed))


def narration_row(arm):
    """A NARRATION row of the 2026-10-04 run (8b18ea69, snapshot 81998270)."""
    row = {"role": "NARRATION", "arm": arm, "case_id": "narration-01", "status": "scored"}
    return {**row, "run": "r", "run_commit": RUN_COMMIT, "snapshot_version": RUN_SNAPSHOT}


def test_the_headroom_fix_makes_mimos_old_requests_stale_and_no_one_elses():
    rows_ = [narration_row(MIMO), narration_row(SONNET)]
    record = {}
    out = shape.mark_stale(rows_, record)
    assert [r["status"] for r in out] == ["stale_request", "scored"]
    assert record == {"NARRATION": {f"r|{MIMO}": ["narration-01"]}}
    assert shape.stale_cases("NARRATION", MIMO, "1221b0a4", shape.snapshot(None)["version"]) == ()


def test_a_snapshot_change_alone_makes_a_request_stale():
    """deepseek-v4-flash's CHAT tools were shaped differently on the 2026-10-02 snapshot."""
    deepseek = "deepseek/deepseek-v4-flash"
    assert "chat-01" in shape.stale_cases("CHAT", deepseek, RUN_COMMIT, RUN_SNAPSHOT)
    today = shape.snapshot(None)["version"]
    assert shape.stale_cases("CHAT", deepseek, RUN_COMMIT, today) == ()


def test_a_corpus_row_is_checked_on_the_decision_calls_probe():
    old = {"run_commit": "e9bd6d02", "snapshot_version": RUN_SNAPSHOT}
    row = {"role": "MNEMONIC", "arm": MIMO, "case_id": "global_opening_hours", "status": "scored"}
    record = {}
    (out,) = shape.mark_stale([{**row, **old}], record)
    assert out["status"] == "stale_request" and record["MNEMONIC"]
    (kept,) = shape.mark_stale([{**row, **old, "arm": SONNET}], {})
    assert kept["status"] == "scored"


def test_a_row_without_its_run_commit_is_refused():
    row = {"role": "NARRATION", "arm": MIMO, "case_id": "narration-01", "status": "scored"}
    with pytest.raises(shape.ShapeRefused, match="no run commit"):
        shape.mark_stale([{**row, "snapshot_version": RUN_SNAPSHOT}], {})
