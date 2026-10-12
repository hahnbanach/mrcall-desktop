"""Paid outcomes the daily job remembers across runs: smokes and time-limit stops (S5b review).

A smoke's outcome is kept in `results.json` with the fingerprint of the
model's request metadata and stands 7 days while that fingerprint holds: a
passed smoke is not paid for again (a measurement the deadline deferred
follows it the next day), a failed one keeps the model out, an uncertain
entrant's is not retried, but a smoke the publication waits for (metadata
changed) is retried by every run. A measurement stopped at its time limit is
not tried again for 14 days unless the role's hashes or the model's metadata
change. Pruning drops what no longer stands. Fakes only: nothing is paid.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from .model_table_world import CS, GENIUS, K3, NOW, PH, SONNET, load_job
from .test_model_table_interrupted import Rig

job = load_job()
outcomes = job.checks.outcomes
DAY = timedelta(days=1)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def smokes(rig) -> list[tuple[str, str]]:
    return [(e["model"], e["outcome"]) for e in rig.doc("results.json")["smokes"]]


def test_a_passed_smoke_is_not_paid_again_when_the_deadline_deferred_its_measurement(rig):
    assert rig.go("--deadline-minutes", "8") == 0  # the smoke fits, no measurement does
    assert rig.fake.smoked == [GENIUS] and rig.fake.measured == []
    assert smokes(rig) == [(GENIUS, "passed")]
    assert rig.go(files=rig.fake.files, now=NOW + DAY) == 0
    assert rig.fake.smoked == []  # cached: measured straight away
    assert rig.fake.measured == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]
    assert f"cached: {GENIUS}: smoke passed at 2026-10-14T05:17:30Z" in rig.report


def test_a_failed_smoke_keeps_the_model_out_for_a_week_unless_its_metadata_changes(rig):
    assert rig.go(smoke_fails={GENIUS}) == 0
    files = dict(rig.fake.files)
    assert rig.go(files=files, now=NOW + DAY) == 0
    assert rig.fake.smoked == [] and GENIUS not in rig.ranking("economy", "CHAT")
    assert rig.go(files=files, now=NOW + 8 * DAY) == 0  # a week on: smoked again
    assert rig.fake.smoked == [GENIUS]
    rig.world.models[GENIUS]["efforts"] = ["max", "low"]  # a changed model: smoked again
    assert rig.go(files=files, now=NOW + DAY) == 0
    assert rig.fake.smoked == [GENIUS]


def test_an_uncertain_entrant_smoke_is_neither_resent_in_the_run_nor_retried_for_a_week(rig):
    assert rig.go(smoke_errors={GENIUS}) == 0
    assert rig.fake.smoked == [GENIUS]  # once: no call is resent after an uncertain outcome
    assert smokes(rig) == [(GENIUS, "uncertain")]
    assert rig.go(files=rig.fake.files, now=NOW + DAY) == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert f"smoke {GENIUS}: smoke uncertain at 2026-10-14T05:17:30Z: error" in rig.report


def test_a_smoke_the_publication_waits_for_is_retried_whatever_the_cache_says(rig):
    del rig.world.models[GENIUS]
    rig.world.models[SONNET]["efforts"] = ["max"]  # a ranked model's metadata changed
    assert rig.go(smoke_errors={SONNET}) == 1  # unsmoked: nothing published
    assert smokes(rig) == [(SONNET, "uncertain")]
    assert rig.go(files=rig.fake.files, now=NOW + DAY) == 0
    assert rig.fake.smoked == [SONNET]  # retried: the run cannot publish without it


def test_a_measurement_stopped_at_its_time_limit_is_not_tried_again_for_two_weeks(rig):
    assert rig.go(measure_timeouts={("CHAT", GENIUS)}) == 0
    assert rig.fake.measured == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]
    (stop,) = rig.doc("results.json")["stops"]
    assert (stop["model"], stop["role"], stop["case_set_sha256"]) == (GENIUS, "CHAT", CS)
    files = dict(rig.fake.files)
    assert rig.go(files=files, now=NOW + DAY) == 0
    assert rig.fake.measured == []  # not paid for again
    assert f"CHAT on {GENIUS}: stopped at its time limit at 2026-10-14T05:18:30Z" in rig.report
    assert rig.go(files=files, now=NOW + 15 * DAY) == 0  # two weeks on: tried again
    assert ("CHAT", GENIUS) in rig.fake.measured
    rig.world.models[GENIUS]["efforts"] = ["max", "low"]  # or as soon as the model changes
    assert rig.go(files=files, now=NOW + DAY) == 0
    assert ("CHAT", GENIUS) in rig.fake.measured


def with_spent(files: dict, used: str) -> dict:
    """`files` with a settled run of `used` USD added to October's ledger."""
    ledger = json.loads(files["ledger.json"])
    row = {"run": "2026-10-20T05:17:00Z", "opened_at": "2026-10-20T05:17:00Z", "calls": []}
    row.update(reserved_usd=used, spent_usd=used, settled_at="2026-10-20T05:40:00Z")
    ledger["months"]["2026-10"].append(row)
    return dict(files, **{"ledger.json": json.dumps(ledger).encode()})


def test_a_model_whose_smoke_failed_reenters_only_after_a_passing_smoke(rig):
    del rig.world.models[GENIUS]
    rig.world.models[SONNET]["efforts"] = ["max"]  # a ranked model changed, and fails
    assert rig.go(smoke_fails={SONNET}) == 0
    assert SONNET not in rig.ranking("economy", "CHAT")
    files, later = dict(rig.fake.files), NOW + 8 * DAY
    assert rig.go(files=files, now=NOW + DAY) == 0  # within the week: not smoked, still out
    assert rig.fake.smoked == [] and SONNET not in rig.ranking("economy", "CHAT")
    # A week on, its old passing measurement does not bring it back by itself:
    assert rig.go(files=with_spent(files, "9.9"), now=later) == 0  # no room for a smoke
    assert rig.fake.smoked == [] and SONNET not in rig.ranking("economy", "CHAT")
    assert rig.go(files=files, now=later, smoke_fails={SONNET}) == 0  # smoked: fails again
    assert rig.fake.smoked == [SONNET] and SONNET not in rig.ranking("economy", "CHAT")
    assert rig.go(files=files, now=later) == 0  # smoked: passes, and re-enters
    assert rig.fake.smoked == [SONNET] and SONNET in rig.ranking("economy", "CHAT")
    assert smokes(rig) == [(SONNET, "passed")]


def test_a_stop_that_freezes_a_role_is_flagged(rig):
    del rig.world.models[GENIUS]
    today = {"CHAT": (CS, "1" * 64)}  # CHAT's prompt changed: its reference is measured first
    assert rig.go(hashes=today, measure_timeouts={("CHAT", K3)}) == 0
    assert rig.fake.measured == [("CHAT", K3)]
    flag = f"CHAT waits on {K3}, which was stopped at its time limit at"
    flags = rig.report.split("## Flags")[1].split("\n## ")[0]
    assert flag in flags
    assert rig.go(files=rig.fake.files, now=NOW + DAY, hashes=today) == 0
    assert rig.fake.measured == []  # not tried again, and said so among the flags
    flags = rig.report.split("## Flags")[1].split("\n## ")[0]
    assert f"CHAT waits on {K3}, which stopped at its time limit at" in flags


def test_a_smoke_that_sent_nothing_is_not_remembered(rig):
    assert rig.go(smoke_unsent={GENIUS}) == 0  # its cap refused the first call
    assert rig.fake.files.get("results.json") is None
    assert rig.go(files=rig.fake.files, now=NOW + DAY) == 0
    assert rig.fake.smoked == [GENIUS]  # tried again: nothing was paid for


def test_an_outcome_without_a_fingerprint_is_not_remembered(rig, monkeypatch):
    monkeypatch.setattr(outcomes, "fingerprint", lambda snapshot, model, direct: None)
    assert rig.go(measure_timeouts={("CHAT", GENIUS)}) == 0  # a smoke paid, a stop
    doc = rig.doc("results.json")
    assert doc["smokes"] == [] and doc["stops"] == []  # nothing to key them by
    assert rig.go(files=rig.fake.files, now=NOW + DAY) == 0  # the file stays readable


def test_the_publication_prunes_what_no_longer_stands(rig):
    old = (NOW - 8 * DAY).strftime(outcomes.STAMP)
    held = job.results_of.empty()
    held = outcomes.add_smoke(held, "r", "acme/gone-1", "x", old, "failed", "no call")
    held = outcomes.add_stop(held, "r", GENIUS, "CHAT", (CS, "0" * 64), "x", old, "stopped")
    files = dict(rig.files, **{"results.json": json.dumps(held).encode()})
    assert rig.go(files=files) == 0
    doc = rig.doc("results.json")
    assert doc["stops"] == [] and smokes(rig) == [(GENIUS, "passed")]  # the stale ones gone


def test_a_fingerprint_follows_the_request_metadata_and_not_the_price():
    snap = {
        "models": {
            "a/m": {"pricing": {"output": "1"}, "metadata": {"reasoning": 1, "parameters": []}},
        },
        "direct": {"m-direct": {"metadata": {"reasoning": 1, "parameters": ["x"]}}},
    }
    before = outcomes.fingerprint(snap, "a/m", "m-direct")
    snap["models"]["a/m"]["pricing"]["output"] = "2"
    assert outcomes.fingerprint(snap, "a/m", "m-direct") == before
    snap["direct"]["m-direct"]["metadata"]["parameters"] = []
    assert outcomes.fingerprint(snap, "a/m", "m-direct") != before
    assert outcomes.fingerprint(snap, "a/missing", None) is None


@pytest.mark.parametrize(
    "doc, says",
    [
        ({"smokes": {}}, "smokes must be a list"),
        ({"smokes": [{"model": "m"}]}, "smokes entry 1 lacks"),
        (
            {
                "smokes": [
                    dict.fromkeys(outcomes.SMOKE_FIELDS, "x") | {"at": "2026-10-14T05:17:30Z"}
                ]
            },
            "has no outcome",
        ),
        ({"stops": [dict.fromkeys(outcomes.STOP_FIELDS, "x") | {"at": "today"}]}, "not a time"),
    ],
)
def test_outcomes_the_job_cannot_read_are_refused(doc, says):
    with pytest.raises(ValueError, match=says):
        outcomes.check(doc)


def test_an_outcome_stands_for_its_window_only():
    at = datetime(2026, 10, 14, 5, 17, 30, tzinfo=timezone.utc)
    doc = outcomes.add_smoke(
        {"smokes": []}, "r", "m", "fp", at.strftime(outcomes.STAMP), "passed", ""
    )
    doc = outcomes.add_stop(doc, "r", "m", "CHAT", (CS, PH), "fp", at.strftime(outcomes.STAMP), "x")
    fp, hashes = (lambda model: "fp"), {"CHAT": (CS, PH)}
    smoke, stop = outcomes.live(doc, at + 6 * DAY, fp, hashes)
    assert list(smoke) == ["m"] and list(stop) == [("m", "CHAT")]
    smoke, stop = outcomes.live(doc, at + 8 * DAY, fp, hashes)
    assert smoke == {} and list(stop) == [("m", "CHAT")]
    assert outcomes.live(doc, at + 15 * DAY, fp, hashes) == ({}, {})
    assert outcomes.live(doc, at, fp, {"CHAT": (CS, "0" * 64)})[1] == {}  # other hashes
    kept = outcomes.prune(doc, at + 8 * DAY, fp, hashes)
    assert kept["smokes"] == [] and kept["stops"] == doc["stops"]  # the stop still stands
    gone = outcomes.prune(doc, at + 15 * DAY, fp, hashes)
    assert gone["smokes"] == [] and gone["stops"] == []
