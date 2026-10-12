"""The committed derivation: plan, exclusions and stale-shape supersession (milestone 10, S4b10).

- the committed ``roles/measured.json`` is, byte for byte, what
  ``derive_thresholds.py --plan`` derives from the committed records in
  ``tests/fixtures/measurement/records/2026-10-11/``: no row selection outside
  the repo decides a result;
- an exclusion is applied only when its claim holds: ``prompt`` refuses a
  row measured on today's prompt; ``denied`` needs a cell refused before
  inference and the arm answered in full in ``superseded_by``; an entry
  without a reason, of another kind, or matching no row is refused;
- ``supersede_stale`` drops an arm's stale-shape run only when the arm has a
  complete current-shape run of the role, and never a current-shape row: a
  model that missed a case in a current-shape run keeps that miss (deepseek's
  NARRATION in s4c).
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
import measurement_plan as plan  # noqa: E402
import measurement_runs as runs  # noqa: E402

PLAN = common.ENGINE / "tests/fixtures/measurement/records/2026-10-11/plan.json"
OPUS, K3 = "anthropic/claude-opus-5.5", "moonshotai/kimi-k3"


def test_the_committed_measured_json_is_derived_from_the_committed_plan():
    document, unmeasured = derive.build(plan.from_plan(PLAN))
    assert unmeasured == {}
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    assert text == common.MEASURED.read_text(encoding="utf-8")


def chat_rows(run, arm, prompt, statuses=("scored",) * 3, error=None):
    cases = ["chat-01", "chat-02", "chat-03"]
    return [
        {
            "run": run,
            "role": "CHAT",
            "arm": arm,
            "case_id": case,
            "status": status,
            "prompt_sha256": prompt,
            "error": error if status == "error" else None,
        }
        for case, status in zip(cases, statuses)
    ]


@pytest.fixture
def three_chat_cases(monkeypatch):
    real = common.load_document
    cases = {"cases": [{"id": c} for c in ("chat-01", "chat-02", "chat-03")]}
    monkeypatch.setattr(
        common, "load_document", lambda role: copy.deepcopy(cases) if role == "CHAT" else real(role)
    )


def today(role):
    return "new"


def entry(**fields):
    return {
        "run": "old",
        "role": "CHAT",
        "arms": "*",
        "kind": "prompt",
        "why": "replaced",
        **fields,
    }


def test_a_prompt_exclusion_drops_only_rows_of_another_prompt():
    rows = chat_rows("old", OPUS, "stale") + chat_rows("new", OPUS, "new")
    kept, record = plan.apply_exclusions(rows, [entry()], today)
    assert {r["run"] for r in kept} == {"new"} and record[0]["rows"] == 3
    with pytest.raises(plan.ExclusionRefused, match="today's prompt"):
        plan.apply_exclusions(chat_rows("old", OPUS, "new"), [entry()], today)


@pytest.mark.usefixtures("three_chat_cases")
def test_a_denied_exclusion_needs_a_refused_cell_and_a_complete_later_run():
    cut = chat_rows("r3", OPUS, "new", ("scored", "error", "error"), "BudgetError: (HTTP 402)")
    later = chat_rows("r4", OPUS, "new")
    denied = entry(run="r3", arms=[OPUS], kind="denied", superseded_by="r4")
    kept, _ = plan.apply_exclusions(cut + later, [denied], today)
    assert {r["run"] for r in kept} == {"r4"}
    failed = chat_rows("r3", OPUS, "new", ("scored", "error", "error"), "HTTP 500 upstream")
    with pytest.raises(plan.ExclusionRefused, match="refused before inference"):
        plan.apply_exclusions(failed + later, [denied], today)
    with pytest.raises(plan.ExclusionRefused, match="not answered in full"):
        plan.apply_exclusions(cut + later[:2], [denied], today)


@pytest.mark.parametrize(
    "bad, message",
    [({"why": ""}, "no reason"), ({"kind": "chosen"}, "kind"), ({"run": "none"}, "no row")],
)
def test_an_exclusion_without_reason_kind_or_rows_is_refused(bad, message):
    with pytest.raises(plan.ExclusionRefused, match=message):
        plan.apply_exclusions(chat_rows("old", OPUS, "stale"), [entry(**bad)], today)


def narration(run, arm, statuses, label=True):
    return [
        {
            "run": run,
            "role": "NARRATION",
            "arm": arm,
            "case_id": f"n-{n}",
            "status": status,
            "repetition": 1,
            "scoring": {"label_match": label, "bars_ok": True, "critical": False},
        }
        for n, status in enumerate(statuses)
    ]


def test_a_stale_run_is_superseded_only_by_a_complete_current_run_and_never_a_current_row():
    cases = ["n-0", "n-1"]
    mimo = narration("s4c", "mimo", ["stale_request"] * 2) + narration("r6", "mimo", ["scored"] * 2)
    pro = narration("s4c", "pro", ["stale_request"] * 2)  # never measured again: stays
    deepseek = narration("s4c", "ds", ["scored"] * 2, label=False) + narration(
        "r6", "ds", ["scored"] * 2
    )
    kept, dropped = runs.supersede_stale(mimo + pro + deepseek, cases)
    assert dropped == {"mimo": ["s4c"]}
    assert {(r["arm"], r["run"]) for r in kept} == {
        ("mimo", "r6"),
        ("pro", "s4c"),
        ("ds", "s4c"),
        ("ds", "r6"),
    }
    partial = narration("s4c", "mimo", ["stale_request"] * 2) + narration("r6", "mimo", ["scored"])
    assert runs.supersede_stale(partial, cases)[1] == {}  # the later run is not complete
