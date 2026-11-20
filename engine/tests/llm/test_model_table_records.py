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

from .model_table_world import CS, K3, PH, QWEN, SONNET, load_job, outcome, result

job = load_job()
records, decide, measured_of = job.records, job.decide, job.measured_of
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


def test_a_role_measured_again_under_new_hashes_keeps_each_result_keyed_until_it_is_whole():
    measured = {"schema": 1, "roles": {"CHAT": outcome(passed=[SONNET], ph=STALE)}}
    at, rule, k3 = "2026-10-14T05:17:30Z", {"rule": "maximise", "index": "agentic"}, K3
    for model in (K3, QWEN):  # the reference first, then a model judged against it
        fresh = {key: v for key, v in result(model).items() if key not in ("pass", "reasons")}
        where, _ = measured_of.record(measured, "CHAT", model, fresh, (CS, PH), at, rule, k3)
        assert where == "stage"
    chat = measured["roles"]["CHAT"]
    assert (chat["case_set_sha256"], chat["prompt_sha256"]) == (CS, STALE)  # still published
    hashes = {"CHAT": (CS, PH)}
    assert decide.current(measured, "CHAT", QWEN, hashes) is None  # staged: not ranked on yet
    assert decide.current(measured, "CHAT", SONNET, hashes) is None  # stale: not a cached result
    assert decide.current(measured, "CHAT", SONNET, {"CHAT": None}) is not None  # hashes unknown
    measured_of.swap(measured, "CHAT", rule, k3)
    assert (chat["case_set_sha256"], chat["prompt_sha256"]) == (CS, PH)
    assert decide.current(measured, "CHAT", QWEN, hashes)["measured_at"] == at
    assert SONNET not in chat["results"] and "remeasure" not in measured


def test_the_working_measurement_takes_a_role_the_build_copy_remeasured():
    published = {"schema": 1, "roles": {"CHAT": outcome(passed=[SONNET], ph=STALE)}}
    published["remeasure"] = {"CHAT": {"case_set_sha256": CS, "prompt_sha256": PH, "results": {}}}
    build = {"schema": 1, "roles": {"CHAT": outcome(passed=[QWEN])}}
    work = records.working_measured(published, build, {"CHAT": (CS, PH)})
    assert work["roles"]["CHAT"] == build["roles"]["CHAT"] and work is not build
    assert "remeasure" not in work  # the job's re-measurement is moot: the build copy's is whole
    kept = records.working_measured(published, build, {"CHAT": (STALE, STALE)})
    assert kept["roles"]["CHAT"] == published["roles"]["CHAT"] and kept["remeasure"]
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


# ------------------------------------------- results.json (paid, not yet published)

results_of = job.results_of


def raw(model: str) -> dict:
    return {k: v for k, v in result(model).items() if k not in ("pass", "reasons")}


def test_the_results_file_keeps_one_entry_per_cache_key_in_measuring_order():
    doc = results_of.empty()
    doc = results_of.add(doc, "r1", QWEN, "CHAT", (CS, PH), "2026-10-12T14:20:00Z", raw(QWEN))
    doc = results_of.add(doc, "r1", K3, "CHAT", (CS, PH), "2026-10-12T14:30:00Z", raw(K3))
    doc = results_of.add(doc, "r2", QWEN, "CHAT", (CS, PH), "2026-10-13T05:20:00Z", raw(QWEN))
    doc = results_of.add(doc, "r2", QWEN, "CHAT", (CS, STALE), "2026-10-13T05:30:00Z", raw(QWEN))
    assert [(e["model"], e["run"], e["prompt_sha256"]) for e in doc["results"]] == [
        (K3, "r1", PH),
        (QWEN, "r2", PH),
        (QWEN, "r2", STALE),
    ]
    assert results_of.check(copy.deepcopy(doc)) == doc


ENTRY = {f: "x" for f in ("run", "model", "role", "measured_at", "case_set_sha256")}


@pytest.mark.parametrize(
    "doc, says",
    [
        ({"schema": 2, "results": []}, "schema 1"),
        ({"schema": 1, "results": {}}, "must be a list"),
        ({"schema": 1, "results": [{"model": QWEN}]}, "lacks run"),
        ({"schema": 1, "results": [ENTRY | {"prompt_sha256": PH}]}, "no measurement result"),
    ],
)
def test_a_results_file_the_job_cannot_read_is_refused(doc, says):
    with pytest.raises(ValueError, match=says):
        results_of.check(doc)


def test_replay_records_what_is_pending_under_todays_hashes_once_and_in_order():
    measured = {"schema": 1, "roles": {"CHAT": outcome(passed=[SONNET])}}
    doc = results_of.empty()
    entries = [
        (QWEN, (CS, PH), "2026-10-12T14:20:00Z"),  # pending: recorded
        (SONNET, (CS, PH), "2026-10-12T14:21:00Z"),  # newer than the held (undated) one
        (K3, (CS, STALE), "2026-10-12T14:22:00Z"),  # other hashes: not today's
        ("acme/unjudged", (CS, PH), "2026-10-12T14:23:00Z"),  # its store cannot judge it
    ]
    for model, hashes, at in entries:
        doc = results_of.add(doc, "r1", model, "CHAT", hashes, at, raw(model))
    stored = []

    def store(role, model, result, at):
        if model == "acme/unjudged":
            return "no reference result"
        measured["roles"][role]["results"][model] = {**result, "pass": True, "measured_at": at}
        stored.append(model)
        return ""

    lines = results_of.replay(doc, measured, {"CHAT": (CS, PH)}, store)
    assert stored == [QWEN, SONNET] and lines[-1].endswith("no reference result, kept")
    again = results_of.replay(doc, measured, {"CHAT": (CS, PH)}, store)
    assert stored == [QWEN, SONNET] and len(again) == 1  # never twice; the unjudged retried
    assert results_of.replay(doc, measured, {"CHAT": None}, store) == []  # hashes unknown
    pruned = results_of.prune(doc, measured, {"CHAT": (CS, PH)})
    assert [e["model"] for e in pruned["results"]] == ["acme/unjudged"]  # held and stale gone
