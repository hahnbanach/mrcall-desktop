"""The daily job's pure parts: the spend ledger, the working measurement, the calendar.

`scripts/model_table_records.py` keeps `ledger.json` (a month's use is what
its runs spent, or reserved where one never settled) and the measurement the
job ranks by (results keyed by model, role, case-set hash and prompt hash);
`scripts/model_table_decide.py` decides when the month-end re-sampling runs
and how a challenger beats an incumbent. The job's runs are in
`test_model_table_job.py`.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal

import pytest

from .model_table_world import CS, PH, QWEN, SONNET, load_job, outcome

job = load_job()
records, decide = job.records, job.decide
STALE = "0" * 64


def test_a_months_use_counts_an_unsettled_run_at_its_whole_reservation():
    ledger = records.empty_ledger()
    ledger = records.reserve(ledger, "2026-10", "a", Decimal("3"), "2026-10-01T05:17:00Z")
    ledger = records.settle(ledger, "2026-10", "a", Decimal("0.75"), [], "2026-10-01T05:30:00Z")
    ledger = records.reserve(ledger, "2026-10", "b", Decimal("2"), "2026-10-02T05:17:00Z")
    ledger = records.reserve(ledger, "2026-09", "c", Decimal("9"), "2026-09-30T05:17:00Z")
    assert records.month_used(ledger, "2026-10") == Decimal("2.75")
    assert records.month_used(ledger, "2026-10", skip="b") == Decimal("0.75")
    raised = records.reserve(ledger, "2026-10", "b", Decimal("4"), "2026-10-02T05:20:00Z")
    assert [r["reserved_usd"] for r in raised["months"]["2026-10"]] == ["3", "4"]
    assert records.check_ledger(copy.deepcopy(raised)) == raised


@pytest.mark.parametrize(
    "doc, says",
    [
        ([], "schema 1"),
        ({"schema": 1, "months": []}, "months must be an object"),
        ({"schema": 1, "months": {"October": []}}, "list of runs"),
        ({"schema": 1, "months": {"2026-10": [{"reserved_usd": "1"}]}}, "without a run id"),
        ({"schema": 1, "months": {"2026-10": [{"run": "a", "reserved_usd": 1}]}}, "reserved_usd"),
        (
            {"schema": 1, "months": {"2026-10": [{"run": "a", "reserved_usd": "-1"}]}},
            "reserved_usd",
        ),
        (
            {
                "schema": 1,
                "months": {"2026-10": [{"run": "a", "reserved_usd": "1", "spent_usd": "x"}]},
            },
            "spent_usd",
        ),
    ],
)
def test_a_ledger_the_job_cannot_read_is_refused(doc, says):
    with pytest.raises(ValueError, match=says):
        records.check_ledger(doc)


def test_a_role_measured_again_under_new_hashes_keeps_each_older_result_keyed():
    measured = {"schema": 1, "roles": {"CHAT": outcome(passed=[SONNET], ph=STALE)}}
    records.record_result(measured, "CHAT", QWEN, {"pass": True}, (CS, PH), "2026-10-14T05:17:30Z")
    chat = measured["roles"]["CHAT"]
    assert (chat["case_set_sha256"], chat["prompt_sha256"]) == (CS, PH)
    assert chat["results"][SONNET]["prompt_sha256"] == STALE
    hashes = {"CHAT": (CS, PH)}
    assert decide.current(measured, "CHAT", QWEN, hashes)["measured_at"] == "2026-10-14T05:17:30Z"
    assert decide.current(measured, "CHAT", SONNET, hashes) is None  # stale: not a cached result
    assert decide.current(measured, "CHAT", SONNET, {"CHAT": None}) is not None  # hashes unknown


def test_the_working_measurement_takes_a_role_the_build_copy_remeasured():
    published = {"schema": 1, "roles": {"CHAT": outcome(passed=[SONNET], ph=STALE)}}
    build = {"schema": 1, "roles": {"CHAT": outcome(passed=[QWEN])}}
    work = records.working_measured(published, build, {"CHAT": (CS, PH)})
    assert work["roles"]["CHAT"] == build["roles"]["CHAT"] and work is not build
    kept = records.working_measured(published, build, {"CHAT": (STALE, STALE)})
    assert kept["roles"]["CHAT"] == published["roles"]["CHAT"]
    assert records.working_measured(None, build, {})["roles"] == build["roles"]


@pytest.mark.parametrize(
    "day, due",
    [
        (date(2026, 10, 31), True),
        (date(2026, 10, 30), False),
        (date(2026, 2, 28), True),
        (date(2028, 2, 28), False),
        (date(2026, 12, 31), True),
    ],
)
def test_the_resampling_runs_on_the_months_last_day(day, due):
    assert decide.resample_due(day) is due


def candidate(model: str, score: float, price: str, deviation: float | None = None) -> dict:
    imputed = {"agentic": deviation} if deviation is not None else {}
    scores = {"intelligence": 60, "coding": None, "agentic": score}
    return {"id": model, "price": Decimal(price), "scores": scores, "imputed": imputed}


@pytest.mark.parametrize(
    "challenger, incumbent, beats",
    [
        (candidate("a", 62, "8"), candidate("b", 60, "10", 3.0), False),  # within the deviation
        (candidate("a", 64, "8"), candidate("b", 60, "10", 3.0), True),
        (candidate("a", 62, "8", 3.0), candidate("b", 60, "10"), False),  # either imputed
        (candidate("a", 61, "8"), candidate("b", 60, "10"), True),  # neither: the order
    ],
)
def test_a_challenger_beats_an_imputed_incumbent_only_beyond_the_deviation(
    challenger, incumbent, beats
):
    rule = {"rule": "maximise", "index": "agentic"}
    assert decide.beats(rule, challenger, incumbent) is beats


def test_a_satisfice_role_orders_by_price_whatever_the_imputation():
    rule = {"rule": "satisfice", "index": "agentic"}
    cheap, dear = candidate("a", 50, "2", 9.0), candidate("b", 70, "10")
    assert decide.beats(rule, cheap, dear) is True


def test_ordered_is_the_resolvers_rank_without_its_cut():
    rule = {"rule": "maximise", "index": "agentic"}
    options = [candidate(f"m{i}", 40 + i, "5") for i in range(8)]
    body = {"threshold": None, "measured_only": False, "results": {}}
    view = decide.view(rule, body, [c["id"] for c in options])
    full = decide.ordered(rule, options, view, Decimal("10"))
    assert len(full) == 8 and full[:5] == job.rm.resolver.rank(rule, options, view, Decimal("10"))
