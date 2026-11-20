"""The daily job and the measurement's reference (plan S5c; brief D7, D8).

A challenger is judged against the reference's recorded result while the
role's case-set and prompt hashes are today's: the reference is not measured
beside it (K3 on CHAT would spend most of the role's USD 2). A role whose
hashes changed measures the reference first, then every model its published
rankings name, staged in `measured.json`'s `remeasure` until the role is
whole. A challenger whose projected measurement is over the per-role cap is
deferred and nothing is sent. Each recorded result is judged by S4b's rules
(`derive_thresholds.judged`) and the role's threshold derived again
(`threshold_of`). The world and the fakes are `model_table_world.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from . import model_table_world as world
from .model_table_world import (
    CHEAP,
    CS,
    GENIUS,
    GLM,
    K3,
    MODELS,
    OPUS,
    PH,
    QWEN,
    SONNET,
    load_job,
    measured,
    outcome,
    result,
)

job = load_job()
measured_of = job.measured_of
STALE = "0" * 64
CHALLENGER = {"in": "1", "out": "8", "intelligence": 62, "agentic": 75}
NOVEMBER = datetime(2026, 11, 2, 5, 17, 30, tzinfo=timezone.utc)
BELOW = "below the reference less its standard error"


def rig_for(tmp_path, measurement=None):
    return world.Rig(job, tmp_path, measurement=measurement)


def stale_chat() -> dict:
    """CHAT measured under a prompt that is no longer today's."""
    return measured(CHAT=outcome(passed=list(MODELS), ph=STALE, index="agentic"))


def ledger_with(used: str) -> dict:
    row = {
        "run": "2026-10-02T05:17:00Z",
        "opened_at": "2026-10-02T05:17:00Z",
        "reserved_usd": used,
        "spent_usd": used,
        "settled_at": "2026-10-02T05:40:00Z",
        "calls": [],
    }
    return {"schema": 1, "months": {"2026-10": [row]}}


# ------------------------------------------------------------ the job


def test_the_cached_reference_is_reused_while_the_roles_hashes_are_todays(tmp_path):
    rig = rig_for(tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0
    assert rig.fake.measured == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]  # no K3 beside
    chat = rig.doc("measured.json")["roles"]["CHAT"]
    assert chat["results"][K3] == result(K3, True, "agentic")  # the recorded one, untouched
    assert chat["results"][GENIUS]["pass"] is True and chat["results"][GENIUS]["reasons"] == []
    assert rig.ranking("economy", "CHAT")[0] == GENIUS


def test_a_challenger_is_judged_against_the_recorded_reference_and_the_threshold_derived(
    tmp_path,
):
    rig = rig_for(tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run(measure_fails={("TASK_DETECTION", GENIUS)}) == 0
    task = rig.doc("measured.json")["roles"]["TASK_DETECTION"]
    assert task["results"][GENIUS]["reasons"] == [BELOW]  # 8 of 20 against K3's 18 of 20
    # GENIUS (62) fails above GLM (50) and QWEN (60), which pass: index and result
    # disagree, so the role accepts measured models only (S4b's threshold_of).
    assert (task["threshold"], task["measured_only"]) == (None, True)
    assert rig.ranking("economy", "TASK_DETECTION") == [GLM, QWEN, SONNET]


def test_a_role_under_other_hashes_measures_its_reference_first_then_the_whole_role(tmp_path):
    rig = rig_for(tmp_path, stale_chat())
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0
    chat_runs = [model for role, model in rig.fake.measured if role == "CHAT"]
    # The reference, then every model the published CHAT rankings name, then the
    # challenger, judged once the role is whole.
    assert chat_runs == [K3, OPUS, SONNET, QWEN, GLM, CHEAP, GENIUS]
    assert rig.fake.smoked == [GENIUS]  # a published model re-measured is not smoked
    doc = rig.doc("measured.json")
    chat = doc["roles"]["CHAT"]
    assert (chat["case_set_sha256"], chat["prompt_sha256"]) == (CS, PH) and "remeasure" not in doc
    assert {r["prompt_sha256"] for r in chat["results"].values()} == {PH}
    assert chat["reference"] == {"id": K3, "score": 0.9, "se": 0.067082}
    assert "CHAT re-measured whole under today's prompt and cases" in rig.report
    assert rig.ranking("economy", "CHAT")[0] == GENIUS


def test_a_re_measurement_the_cap_cuts_short_waits_in_remeasure_and_resumes(tmp_path):
    rig = rig_for(tmp_path, stale_chat())
    assert rig.run(ledger=ledger_with("8")) == 0  # USD 2 left: the reference alone
    assert rig.fake.measured == [("CHAT", K3)]
    doc = rig.doc("measured.json")
    assert doc["roles"]["CHAT"]["prompt_sha256"] == STALE  # the record still ranks on it
    assert list(doc["remeasure"]["CHAT"]["results"]) == [K3]
    assert doc["remeasure"]["CHAT"]["prompt_sha256"] == PH
    assert rig.fake.files["table.json"] == rig.files["table.json"]
    assert "| re-measure CHAT under today's prompt and cases |" in rig.report
    # A month later the run goes on from the staged reference.
    files = {name: rig.fake.files[name] for name in job.edges_of.FILES}
    assert rig.run(files=files, now=NOVEMBER) == 0
    assert rig.fake.measured == [("CHAT", m) for m in (OPUS, SONNET, QWEN, GLM, CHEAP)]
    doc = rig.doc("measured.json")
    assert doc["roles"]["CHAT"]["prompt_sha256"] == PH and "remeasure" not in doc
    assert doc["roles"]["CHAT"]["results"][K3]["measured_at"] == "2026-10-14T05:17:30Z"


def test_a_challenger_projected_over_the_per_role_cap_is_deferred_and_nothing_is_sent(tmp_path):
    rig = rig_for(tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    over = {("CHAT", GENIUS): Decimal("2.4"), ("TASK_DETECTION", GENIUS): Decimal("2.0004")}
    assert rig.run(projections=over) == 0
    assert rig.fake.projected == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert rig.pushed() == [["snapshot.json"]]  # no reservation: nothing was paid for
    assert (
        f"CHAT on {GENIUS}: deferred: over the per-role cap (projected USD 2.40, cap USD 2)"
        in rig.report
    )
    # Rounded up, a projection just over the cap never reads as the cap itself.
    assert f"TASK_DETECTION on {GENIUS}: deferred: over the per-role cap (projected USD 2.01" in (
        rig.report
    )
    assert rig.ranking("economy", "CHAT")[0] == SONNET


def test_a_reference_projected_over_the_cap_leaves_the_role_on_its_recorded_results(tmp_path):
    rig = rig_for(tmp_path, stale_chat())
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run(projections={("CHAT", K3): Decimal("2.2")}) == 0
    # Without the reference nothing of CHAT can be judged: nothing is measured on it.
    assert [m for role, m in rig.fake.measured if role == "CHAT"] == []
    assert f"CHAT on {K3}: deferred: over the per-role cap (projected USD 2.20" in rig.report
    assert rig.ranking("economy", "CHAT")[0] == SONNET
    assert "remeasure" not in rig.doc("measured.json")


def test_an_incomplete_measurement_is_no_result_and_counts_what_it_spent(tmp_path):
    rig = rig_for(tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    script = {"measure_incomplete": {("CHAT", GENIUS)}, "measure_costs": {GENIUS: Decimal("0.3")}}
    assert rig.run(**script) == 0
    assert GENIUS not in rig.doc("measured.json")["roles"]["CHAT"]["results"]
    assert rig.ranking("economy", "CHAT")[0] == SONNET
    settled = rig.doc("ledger.json")["months"]["2026-10"][0]
    assert settled["spent_usd"] == "0.61"  # its smoke, and 0.3 twice (CHAT and TASK_DETECTION)
    assert f"CHAT on {GENIUS}: not completed: CHAT: not every case was scored" in rig.report


# --------------------------------------------------- the measurement's record


RULE = {"rule": "maximise", "index": "agentic"}
SATISFICE = {"rule": "satisfice", "index": "intelligence"}
AT = "2026-10-14T05:17:30Z"


def counts(model: str, passes: int, n: int = 20, index: str = "agentic") -> dict:
    body = result(model, True, index, n)
    body.update(passes=passes, score=round(passes / n, 6))
    del body["pass"], body["reasons"]
    return body


def test_the_reference_measured_again_rejudges_every_result_of_its_role():
    doc = measured()
    chat = doc["roles"]["CHAT"]
    chat["results"][QWEN] = measured_of.judge(counts(QWEN, 8), chat["results"][K3])
    assert chat["results"][QWEN]["pass"] is False  # 0.4 against 0.9 less 0.067
    where, stored = measured_of.record(doc, "CHAT", K3, counts(K3, 10), (CS, PH), AT, RULE, K3)
    assert where == "role" and stored["measured_at"] == AT
    assert chat["results"][QWEN]["pass"] is True  # 0.4 against 0.5 less 0.112
    assert chat["reference"] == {"id": K3, "score": 0.5, "se": 0.111803}


def test_a_result_is_never_recorded_without_a_complete_reference_under_todays_hashes():
    doc = measured(CHAT=outcome(passed=[SONNET], ph=STALE))
    with pytest.raises(measured_of.Unjudgeable, match="no reference result"):
        measured_of.record(doc, "CHAT", QWEN, counts(QWEN, 18), (CS, PH), AT, RULE, K3)
    unfinished = dict(counts(K3, 18), complete=False)
    with pytest.raises(measured_of.Unjudgeable, match="not complete"):
        measured_of.record(doc, "CHAT", K3, unfinished, (CS, PH), AT, RULE, K3)
    assert doc["roles"]["CHAT"]["results"].keys() == {SONNET, K3} and "remeasure" not in doc


def test_the_threshold_is_derived_again_from_the_roles_results():
    doc = measured()
    task = doc["roles"]["TASK_DETECTION"]
    assert (task["threshold"], task["measured_only"]) == (50, False)
    better = counts("acme/new", 19, index="intelligence") | {"index_score": 48}
    measured_of.record(doc, "TASK_DETECTION", "acme/new", better, (CS, PH), AT, SATISFICE, K3)
    # A pass at 48, above CHEAP's fail at 45: every measured model scored 48 or more
    # passes now, so the threshold comes down to 48.
    assert (task["threshold"], task["measured_only"]) == (48, False)


def test_aggregate_is_derive_thresholds_per_arm_result():
    dt = measured_of.dt
    hashes = dt.current_hashes("NARRATION")
    cases = [case["id"] for case in dt.common.load_document("NARRATION")["cases"]]

    def row(arm: str, case: str, match: bool, repetition: int = 1) -> dict:
        scoring = {"label_match": match, "bars_ok": case != cases[1], "critical": False}
        return {
            "role": "NARRATION",
            "arm": arm,
            "arm_score": 37.9 if arm != K3 else 47.0,
            "case_id": case,
            "repetition": repetition,
            "status": "scored",
            "scoring": scoring,
            "case_set_sha256": hashes[0],
            "prompt_sha256": hashes[1],
        }

    flash = [row("x/flash", c, i % 2 == 0) for i, c in enumerate(cases)]
    flash.append(row("x/flash", cases[0], False, 2))
    rows = [row(K3, c, True) for c in cases] + flash
    rule = {"rule": "satisfice", "index": "intelligence"}
    entry = dt.role_entry("NARRATION", rows, cases, rule, K3)
    mine = measured_of.aggregate(flash, cases)
    assert {**mine, **dict(zip(("pass", "reasons"), dt.judged(mine, entry["results"][K3])))} == (
        entry["results"]["x/flash"]
    )
    assert measured_of.aggregate(flash[1:], cases)["complete"] is False
