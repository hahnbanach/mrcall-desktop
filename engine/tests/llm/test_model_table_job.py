"""The daily model-table job on fixtures: every rule of AC 7 (brief D8, plan S5).

`scripts/model_table_job.py` reads the published record, resolves the live
read, makes the paid checks its decisions wait for within the caps, and
publishes or fails. Here the world is `model_table_world.World` (six models,
Sonnet and Opus imputed on the agentic index), the record is that world
resolved by hand, and every edge is a fake: nothing is paid or pushed. What
is pinned: a changed pick is published only after its smoke and measurement
pass; a cached result is reused at no cost, a stale one is not; a change
that moves no pick or order updates only the snapshot; a pick that fails a
gate is replaced by the first ranked model with a passing result; the
monthly cap stops the run before a paid call, and fails it visibly when no
replacement is verified; a raised ceiling is refused before any paid call;
the reservation is on the data branch before the first paid call and is
settled after; a ranked model whose metadata changed is smoked first; the
incumbent rule; the month-end re-sampling; an error is no result.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from .model_table_world import (
    CHEAP,
    CS,
    GENIUS,
    GLM,
    K3,
    MODELS,
    NOW,
    OPUS,
    PH,
    QWEN,
    SONNET,
    FakeEdges,
    World,
    load_job,
    measured,
    outcome,
    published,
    requirements,
)

job = load_job()
STALE = "0" * 64
LAST_DAY = datetime(2026, 10, 31, 5, 17, 30, tzinfo=timezone.utc)
CHALLENGER = {"in": "1", "out": "8", "intelligence": 62, "agentic": 75}


class Rig:
    """The world, its record resolved by hand, and one run of the job on fakes."""

    def __init__(self, tmp_path, req=None, measurement=None):
        self.tmp, self.req, self.world = tmp_path, req or requirements(), World()
        self.files = published(job, self.world, self.req, measurement or measured())
        self.roles = tmp_path / "roles"
        self.roles.mkdir()
        (self.roles / "requirements.json").write_text(json.dumps(self.req), encoding="utf-8")

    def run(self, *flags, now=NOW, ledger=None, files=None, **script) -> int:
        files = dict(self.files if files is None else files)
        if ledger is not None:
            files["ledger.json"] = json.dumps(ledger).encode()
        self.fake = FakeEdges(job, self.world, files, now=now, measurable=script.get("measurable"))
        self.fake.smoke_fails = set(script.get("smoke_fails", ()))
        self.fake.smoke_errors = set(script.get("smoke_errors", ()))
        self.fake.smoke_unsent = set(script.get("smoke_unsent", ()))
        self.fake.measure_fails = set(script.get("measure_fails", ()))
        report = self.tmp / "report.md"
        argv = ["--data", str(self.tmp / "data"), "--report", str(report), *flags]
        code = job.main(argv, edges=self.fake.edges(), roles=self.roles)
        self.report = report.read_text(encoding="utf-8")
        assert self.fake.violations == []
        return code

    def doc(self, name: str) -> dict:
        return json.loads(self.fake.files[name])

    def ranking(self, preset: str, role: str, column: str = "ranking") -> list[str]:
        return [e["id"] for e in self.doc("table.json")["presets"][preset]["roles"][role][column]]

    def pushed(self) -> list[list[str]]:
        return [sorted(files) for files, _ in self.fake.pushes]

    def pool(self) -> dict:
        sources = job.rm.resolver.read(self.req, self.world.raw())
        return {c["id"]: c for c in job.rm.resolver.pool(self.req, sources)["pool"]}


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def ledger_with(used: str, settled: bool = True) -> dict:
    row = {
        "run": "2026-10-02T05:17:00Z",
        "opened_at": "2026-10-02T05:17:00Z",
        "reserved_usd": used,
        "spent_usd": used if settled else None,
        "settled_at": "2026-10-02T05:40:00Z" if settled else None,
        "calls": [],
    }
    return {"schema": 1, "months": {"2026-10": [row]}}


# ------------------------------------------------------- the decision record


def test_a_price_only_change_updates_only_the_snapshot(rig):
    rig.world.models[K3]["out"] = "13.9"  # ranked under balanced; moves no pick and no order
    assert rig.run() == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert rig.pushed() == [["snapshot.json"]]
    assert rig.fake.files["table.json"] == rig.files["table.json"]  # the record, byte for byte
    assert rig.doc("snapshot.json")["models"][K3]["pricing"]["output"] == "13.9"
    assert "no pick or order changed" in rig.report
    assert f"price of ranked {K3}: 13.5 -> 13.9" in rig.report
    assert "published (snapshot only)" in rig.report and "Problems" not in rig.report


def test_a_changed_pick_is_published_only_after_its_smoke_and_measurement_pass(rig):
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0
    assert rig.fake.smoked == [GENIUS]
    assert rig.fake.measured == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]
    assert rig.ranking("economy", "CHAT") == [GENIUS, SONNET, QWEN, GLM, CHEAP]
    assert rig.ranking("economy", "TASK_DETECTION") == [GLM, QWEN, GENIUS, SONNET]
    assert rig.pushed()[-1] == ["ledger.json", "measured.json", "snapshot.json", "table.json"]
    table = rig.doc("table.json")
    job.rm.gates.check_table(table, rig.req, rig.doc("snapshot.json"))
    assert table["resolved_at"] == "2026-10-14T05:17:30Z"
    result = rig.doc("measured.json")["roles"]["CHAT"]["results"][GENIUS]
    assert result == {
        "pass": True,
        "score": 0.9,
        "n": 20,
        "case_set_sha256": CS,
        "prompt_sha256": PH,
        "measured_at": "2026-10-14T05:17:30Z",
    }
    assert f"economy / CHAT / ranking (pick): {SONNET} > " in rig.report


@pytest.mark.parametrize("failing", ["smoke", "measurement"])
def test_a_challenger_failing_its_smoke_or_measurement_is_not_published(rig, failing):
    rig.world.add(GENIUS, **CHALLENGER)
    if failing == "smoke":
        assert rig.run(smoke_fails={GENIUS}) == 0
        assert rig.fake.measured == []  # no measurement after a failed smoke
        assert rig.fake.files["table.json"] == rig.files["table.json"]
        assert f"| smoke {GENIUS} |" in rig.report and "| failed: no call |" in rig.report
    else:
        assert rig.run(measure_fails={("CHAT", GENIUS)}) == 0
        assert rig.fake.measured == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]
        assert rig.doc("measured.json")["roles"]["CHAT"]["results"][GENIUS]["pass"] is False
        assert rig.ranking("economy", "TASK_DETECTION") == [GLM, QWEN, GENIUS, SONNET]
    assert rig.fake.smoked == [GENIUS]
    assert rig.ranking("economy", "CHAT")[0] == SONNET
    assert GENIUS not in rig.ranking("balanced", "CHAT")


def test_a_cached_result_is_reused_at_no_cost(tmp_path):
    cached = measured(
        CHAT=outcome(passed=list(MODELS) + [GENIUS]),
        TASK_DETECTION=outcome(passed=[GENIUS], threshold=50),
    )
    rig = Rig(tmp_path, measurement=cached)  # measured before, while it was out of the catalogue
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert rig.pushed() == [["snapshot.json", "table.json"]]  # no reservation, nothing paid
    assert rig.ranking("economy", "CHAT")[0] == GENIUS


def test_a_result_under_other_hashes_is_not_cached(tmp_path):
    stale = measured(
        CHAT=outcome(passed=list(MODELS) + [GENIUS], ph=STALE),  # the prompt changed since
        TASK_DETECTION=outcome(passed=[GENIUS], threshold=50),
    )
    rig = Rig(tmp_path, measurement=stale)
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0
    assert rig.fake.smoked == [GENIUS] and rig.fake.measured == [("CHAT", GENIUS)]
    chat = rig.doc("measured.json")["roles"]["CHAT"]
    assert chat["prompt_sha256"] == PH and chat["results"][GENIUS]["prompt_sha256"] == PH
    assert chat["results"][QWEN]["prompt_sha256"] == STALE  # an older result keeps its own key
    assert rig.ranking("economy", "CHAT")[0] == GENIUS


# ------------------------------------------------------------------ gates


@pytest.mark.parametrize("gate", ["above the ceiling", "gone from the catalogue", "expiry"])
def test_a_pick_failing_a_gate_is_replaced_by_the_first_ranked_model_with_a_passing_result(
    rig, gate
):
    if gate == "above the ceiling":
        rig.world.models[SONNET]["out"] = "12"
    elif gate == "gone from the catalogue":
        del rig.world.models[SONNET]
    else:
        rig.world.models[SONNET]["expiry"] = "2026-11-30"
    assert rig.run() == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []  # QWEN was ranked: verified
    assert rig.ranking("economy", "CHAT") == [QWEN, GLM, CHEAP]
    assert rig.ranking("economy", "TASK_DETECTION") == [GLM, QWEN]
    # Sonnet was economy's only Anthropic model: the empty ranking is allowed, and reported.
    assert rig.ranking("economy", "CHAT", "anthropic_ranking") == []
    empty = rig.report.split("## Empty Anthropic rankings")[1].split("##")[0]
    assert "- economy / CHAT" in empty and "- economy / TASK_DETECTION" in empty


@pytest.mark.parametrize("settled", [True, False])
def test_the_monthly_cap_stops_the_run_before_a_paid_call(rig, settled):
    rig.world.add(GENIUS, **CHALLENGER)
    # An earlier run that never settled counts at its whole reservation.
    assert rig.run(ledger=ledger_with("9.98", settled)) == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert rig.pushed() == [["snapshot.json"]]  # no reservation; the record untouched
    assert rig.fake.files["table.json"] == rig.files["table.json"]
    assert f"smoke {GENIUS}: the monthly cap of USD 10 leaves USD 0.02" in rig.report


def test_a_failed_pick_with_no_verified_replacement_fails_visibly_at_the_cap(tmp_path):
    chat = outcome(passed=[SONNET, OPUS], failed=[QWEN, GLM, K3, CHEAP])
    rig = Rig(tmp_path, measurement=measured(CHAT=chat))
    del rig.world.models[SONNET]  # economy's only CHAT model goes
    rig.world.add(GENIUS, **CHALLENGER)  # its replacement would need a smoke
    assert rig.run(ledger=ledger_with("9.98")) == 1
    assert rig.fake.smoked == [] and rig.fake.pushes == []  # the last record stays
    assert (
        "economy / CHAT / ranking: no ranked model with a passing result (deferred: smoke "
        f"{GENIUS}: the monthly cap of USD 10 leaves USD 0.02)"
    ) in rig.report


def test_an_anthropic_ranking_emptied_while_its_checks_wait_fails_visibly(rig):
    del rig.world.models[SONNET]  # economy's only Anthropic model goes
    successor = "anthropic/claude-sonnet-10"
    rig.world.add(successor, **{"in": "2", "out": "10", "intelligence": 68, "agentic": None})
    assert rig.run(ledger=ledger_with("10")) == 1
    assert rig.fake.smoked == [] and rig.fake.pushes == []
    assert "economy / CHAT / anthropic_ranking: emptied while its checks wait (smoke " in (
        rig.report
    )


def test_a_reservation_the_data_branch_refuses_stops_the_run_before_the_call(rig):
    rig.world.add(GENIUS, **CHALLENGER)
    fake = FakeEdges(job, rig.world, rig.files)

    def refuse(files, message):
        raise RuntimeError("git push failed: ! [rejected] (non-fast-forward)")

    fake.push = refuse
    report = rig.tmp / "refused.md"
    argv = ["--data", str(rig.tmp), "--report", str(report)]
    assert job.main(argv, edges=fake.edges(), roles=rig.roles) == 1
    assert fake.smoked == [] and fake.measured == []
    assert "non-fast-forward" in report.read_text(encoding="utf-8")


def test_a_raised_ceiling_is_refused_before_any_paid_call(rig):
    chat = outcome(passed=[OPUS, K3], failed=[SONNET, QWEN, GLM, CHEAP])  # since re-measured
    files = dict(rig.files, **{"measured.json": json.dumps(measured(CHAT=chat)).encode()})
    # An unmeasured challenger under balanced would cost a smoke if the run went on.
    rig.world.add("acme/genius-3", **{"in": "3", "out": "15", "intelligence": 71, "agentic": 80})
    assert rig.run(files=files) == 1
    assert rig.fake.smoked == [] and rig.fake.measured == [] and rig.fake.pushes == []
    assert "economy's ceiling of 10 would be raised to 13.5, and a raised ceiling is never" in (
        rig.report
    )


def test_the_reservation_is_on_the_data_branch_before_the_first_paid_call_and_settled_after(rig):
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run() == 0  # each fake call checks the pushed reservation covers it
    first, message = rig.fake.pushes[0]
    assert list(first) == ["ledger.json"] and "reserves USD 0.05" in message
    row = json.loads(first["ledger.json"])["months"]["2026-10"][0]
    assert row["settled_at"] is None and row["spent_usd"] is None
    settled = rig.doc("ledger.json")["months"]["2026-10"][0]
    assert settled["spent_usd"] == "1.01" and settled["settled_at"] == "2026-10-14T05:17:30Z"
    assert [c["check"] for c in settled["calls"]] == [
        f"smoke {GENIUS}",
        f"CHAT on {GENIUS}",
        f"TASK_DETECTION on {GENIUS}",
    ]
    assert Decimal(settled["reserved_usd"]) >= Decimal("1.01")


# ------------------------------------------------------------- metadata


@pytest.mark.parametrize("field", ["reasoning", "parameters", "forced_tool"])
def test_a_ranked_models_metadata_change_is_smoked_before_publishing(rig, field):
    spec = rig.world.models[SONNET]
    if field == "reasoning":
        spec["efforts"] = ["max", "high", "low"]
    elif field == "parameters":
        spec["parameters"] = spec["parameters"] + ["structured_outputs"]
    else:
        spec["forced"] = True
    assert rig.run() == 0
    assert rig.fake.smoked == [SONNET] and rig.fake.measured == []
    assert rig.fake.files["table.json"] == rig.files["table.json"]
    assert rig.pushed() == [["ledger.json"], ["ledger.json", "snapshot.json"]]
    assert f"metadata of ranked {SONNET}: models {field}" in rig.report


def test_a_ranked_model_failing_its_metadata_smoke_is_replaced(rig):
    rig.world.models[SONNET]["efforts"] = ["max"]
    assert rig.run(smoke_fails={SONNET}) == 0
    assert rig.ranking("economy", "CHAT") == [QWEN, GLM, CHEAP]
    assert SONNET not in rig.ranking("balanced", "CHAT") + rig.ranking("balanced", "TASK_DETECTION")


def test_a_metadata_change_the_cap_leaves_unsmoked_publishes_nothing(rig):
    rig.world.models[SONNET]["efforts"] = ["max"]
    assert rig.run(ledger=ledger_with("10")) == 1
    assert rig.fake.smoked == [] and rig.fake.pushes == []
    assert f"{SONNET}: metadata changed (models reasoning, direct reasoning)" in rig.report


def test_an_error_is_no_result_counts_at_its_bound_and_never_replaces_a_pick(rig):
    rig.world.models[SONNET]["efforts"] = ["max"]
    assert rig.run(smoke_errors={SONNET}) == 1  # left unsmoked: nothing published
    assert rig.pushed() == [["ledger.json"], ["ledger.json"]]  # reserved, then settled alone
    assert rig.fake.files["table.json"] == rig.files["table.json"]
    settled = rig.doc("ledger.json")["months"]["2026-10"][0]
    assert settled["spent_usd"] == "0.05" and "error (ConnectionError)" in str(settled["calls"])
    assert "its smoke could not run (error: ConnectionError: the provider hung up)" in rig.report


def test_a_smoke_its_cap_could_not_send_is_no_result_never_a_failure(rig):
    rig.world.add(GENIUS, **CHALLENGER)
    rig.world.models[SONNET]["efforts"] = ["max"]
    assert rig.run(smoke_unsent={GENIUS, SONNET}) == 1  # Sonnet's change left unsmoked
    assert rig.fake.measured == []  # no measurement without a smoke that ran
    assert rig.fake.files["table.json"] == rig.files["table.json"]  # Sonnet not replaced
    assert f"smoke {GENIUS}: not completed: not sent: bound 85808" in rig.report
    assert f"{SONNET}: metadata changed (models reasoning, direct reasoning) and its smoke" in (
        rig.report
    )


# ---------------------------------------------------- the incumbent rule


def test_the_incumbent_stays_unless_the_challenger_leads_by_more_than_the_deviation(rig):
    rig.world.add(GENIUS, **dict(CHALLENGER, agentic=62))
    pool = rig.pool()
    deviation = pool[SONNET]["imputed"]["agentic"]
    lead = pool[GENIUS]["scores"]["agentic"] - pool[SONNET]["scores"]["agentic"]
    assert 0 < lead <= deviation  # ahead on the score, within the imputation's deviation
    assert rig.run() == 0
    assert rig.ranking("economy", "CHAT") == [SONNET, GENIUS, QWEN, GLM, CHEAP]
    assert f"{SONNET} stays the pick; {GENIUS} does not lead it" in rig.report


# ------------------------------------------------------------ re-sampling


def test_the_months_last_day_resamples_the_oldest_measured_roles_on_their_picks(rig):
    chat = outcome(passed=list(MODELS))
    for result in chat["results"].values():
        result["measured_at"] = "2026-09-30T05:17:00Z"
    files = dict(rig.files, **{"measured.json": json.dumps(measured(CHAT=chat)).encode()})
    assert rig.run(now=LAST_DAY, files=files, measure_fails={("CHAT", SONNET)}) == 0
    # TASK_DETECTION has never been measured by the job: oldest; then CHAT's two picks.
    assert rig.fake.measured == [("TASK_DETECTION", GLM), ("CHAT", SONNET), ("CHAT", OPUS)]
    assert rig.doc("measured.json")["roles"]["TASK_DETECTION"]["results"][GLM]["pass"] is True
    assert rig.ranking("economy", "CHAT") == [QWEN, GLM, CHEAP]  # Sonnet failed its re-sample
    assert "## Monthly re-sampling" in rig.report


def test_resampling_spends_only_what_the_month_leaves(rig):
    # No result carries a date: both roles are oldest, in roster order (CHAT first).
    assert rig.run(now=LAST_DAY, ledger=ledger_with("7.6")) == 0
    assert rig.fake.measured == [("CHAT", SONNET)]  # 0.5 spent: 2.4 - 0.5 < 2
    assert f"re-sampling CHAT on {OPUS} not made: the monthly cap of USD 10 leaves USD 1.9" in (
        rig.report
    )
    assert rig.doc("ledger.json")["months"]["2026-10"][1]["spent_usd"] == "0.5"


def test_no_resampling_before_the_months_last_day(rig):
    assert rig.run() == 0
    assert rig.fake.measured == [] and "Monthly re-sampling" not in rig.report


# --------------------------------------------------- what the job reads


def test_a_role_without_a_harness_is_never_paid_for(tmp_path):
    req = requirements(("MNEMONIC",))
    rig = Rig(tmp_path, req=req, measurement={"schema": 1, "roles": {"MNEMONIC": outcome(MODELS)}})
    rig.world.add(GENIUS, **dict(CHALLENGER, intelligence=75))  # leads MNEMONIC's index
    assert rig.run(measurable=set()) == 0
    assert rig.fake.smoked == [] and rig.fake.measured == [] and rig.pushed() == [["snapshot.json"]]
    assert f"MNEMONIC on {GENIUS}: no measurement harness for MNEMONIC" in rig.report
    assert "no current hashes for MNEMONIC" in rig.report


def test_the_first_run_starts_from_the_reviewed_build_copy(rig):
    for name in ("table.json", "snapshot.json", "measured.json"):
        (rig.roles / name).write_bytes(rig.files[name])
    assert rig.run(files={}) == 0
    assert rig.pushed() == [["measured.json", "snapshot.json", "table.json"]]
    for name in ("table.json", "measured.json"):
        assert rig.fake.files[name] == rig.files[name]  # as reviewed
    assert "the data branch holds no table.json yet: the build copy stands in" in rig.report


def test_without_a_published_or_reviewed_table_the_run_stops(rig):
    assert rig.run(files={}) == 1
    assert rig.fake.pushes == [] and "resolved by hand" in rig.report


@pytest.mark.parametrize(
    "name, content, says",
    [
        ("ledger.json", b'{"schema": 2}', "not a schema 1 ledger"),
        ("ledger.json", b'{"schema": 1, "months": {"2026-10": [{"run": "x"}]}}', "reserved_usd"),
        ("table.json", b"<html>502</html>", "not JSON"),
    ],
)
def test_a_record_the_job_cannot_read_stops_it_before_anything(rig, name, content, says):
    assert rig.run(files=dict(rig.files, **{name: content})) == 1
    assert rig.fake.pushes == [] and says in rig.report


def test_an_unreadable_source_publishes_nothing(rig):
    rig.world.raw = lambda: {"catalogue": b"<html>", "benchmarks": b"", "endpoints": b""}
    assert rig.run() == 1
    assert rig.fake.pushes == [] and "cannot read the catalogue: not JSON" in rig.report


def test_a_measurement_the_resolver_cannot_read_is_a_configuration_error(rig):
    broken = measured(CHAT=dict(outcome(), prompt_sha256="abc"))
    assert rig.run(files=dict(rig.files, **{"measured.json": json.dumps(broken).encode()})) == 2
    assert rig.fake.pushes == []


def test_a_run_with_nothing_new_pushes_nothing(rig):
    assert rig.run() == 0
    assert rig.fake.pushes == [] and "unchanged: nothing to publish" in rig.report


def test_requirements_the_job_cannot_read_are_a_configuration_error(rig):
    (rig.roles / "requirements.json").write_text("{", encoding="utf-8")
    assert rig.run() == 2
    assert rig.fake.pushes == [] and "requirements.json:" in rig.report


def test_a_dry_run_pays_nothing_and_pushes_nothing(rig):
    rig.world.add(GENIUS, **CHALLENGER)
    assert rig.run("--dry-run") == 0
    assert rig.fake.smoked == [] and rig.fake.pushes == []
    assert f"smoke {GENIUS}: dry run (at most USD 0.05)" in rig.report
    assert "dry run: would publish snapshot.json" in rig.report


def test_the_report_lists_unscored_models_and_empty_anthropic_rankings(rig):
    rig.world.add("acme/unknown-1", **dict(CHALLENGER, scored=False))
    assert rig.run() == 0
    unscored = rig.report.split("## Unscored models")[1]
    assert "- acme/unknown-1: no Artificial Analysis record" in unscored
    assert "## Empty Anthropic rankings\n\n- none" in rig.report


def test_the_monthly_cap_may_only_be_lowered(rig, capsys):
    with pytest.raises(SystemExit):
        job.main(["--data", "x", "--monthly-cap-usd", "10.01"], edges=None, roles=rig.roles)
    assert "at most USD 10" in capsys.readouterr().err
