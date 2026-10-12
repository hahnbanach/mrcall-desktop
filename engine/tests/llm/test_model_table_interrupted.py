"""The daily model-table job when a run cannot finish (milestone 10, S5b).

The first live run (2026-10-12) was killed by an outer timeout after 7000 s:
nothing was published, its reservation stayed open on the data branch, and
every result it paid for was lost to the next run. Pinned here, on the
fixture world of `model_table_world` with every edge a fake:

- the deadline: no paid check starts whose time limit would end after it;
  the rest is deferred, unpaid and reported, and the run still decides,
  publishes and settles;
- a hard kill: what the branch holds at that moment is an honest bound of
  the spend (recorded calls plus the bound of the one check in flight) and
  every result already paid for, which the next run takes at no cost;
- recovery: an earlier run left open is settled at its reserved amount,
  marked recovered, before anything is reserved; never twice;
- the monthly cap still holds, a recovered run counted as spent.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from . import model_table_world as world
from .model_table_world import CS, GENIUS, NOW, PH, SONNET, FakeEdges, load_job

job = load_job()
records = job.records
CHALLENGER = {"in": "1", "out": "8", "intelligence": 62, "agentic": 75}
KILLED_RUN = "2026-10-12T14:13:04Z"


class Killed(BaseException):
    """The process is gone: nothing it does afterwards reaches the branch."""


class Interrupted(BaseException):
    """The process is interrupted (SIGINT, as a cancelled workflow is): it
    still runs its handlers, so it settles before it goes."""


class Clocked(FakeEdges):
    """The fake edges with a clock each check moves (`minutes` per kind) and,
    optionally, a hard kill when a given measurement starts."""

    def __init__(self, *args, minutes=None, kill_at=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.minutes = minutes or {"smoke": 1, "measure": 5}
        self.kill_at, self.dead, self.starts, self.hard = kill_at, False, [], True

    def push(self, files, message):
        if not self.dead:
            super().push(files, message)

    def smoke(self, model):
        self.starts.append(("smoke", None, self.now))
        out = super().smoke(model)
        self.now += timedelta(minutes=self.minutes["smoke"])
        return out

    def measure(self, role, model, scores):
        self.starts.append(("measure", role, self.now))
        if (role, model) == self.kill_at:
            self._reserved(f"{role} on {model}", Decimal("2"))
            self.dead = self.hard
            raise Killed() if self.hard else Interrupted()
        out = super().measure(role, model, scores)
        self.now += timedelta(minutes=self.minutes["measure"])
        return out


def open_row(reserved: str, run: str = KILLED_RUN, calls=()) -> dict:
    return {
        "run": run,
        "opened_at": run,
        "reserved_usd": reserved,
        "spent_usd": None,
        "settled_at": None,
        "calls": list(calls),
    }


def ledger_of(*rows, month="2026-10") -> dict:
    return {"schema": 1, "months": {month: list(rows)}}


class Rig(world.Rig):
    def __init__(self, tmp_path):
        super().__init__(job, tmp_path)
        self.world.add(GENIUS, **CHALLENGER)

    def go(self, *flags, files=None, now=NOW, kill_at=None, **knobs) -> int:
        """One run on `Clocked` edges (`knobs` set the fake's, as `Rig.run`);
        `Killed` propagates (no report)."""
        self.fake = Clocked(job, self.world, dict(files or self.files), now=now, kill_at=kill_at)
        for knob, value in knobs.items():
            setattr(self.fake, knob, type(getattr(self.fake, knob))(value))
        self.report_path = self.tmp / "report.md"
        argv = ["--data", str(self.tmp), "--report", str(self.report_path), *flags]
        code = job.main(argv, edges=self.fake.edges(), roles=self.roles)
        self.report = self.report_path.read_text(encoding="utf-8")
        assert self.fake.violations == []
        return code

    def doc(self, name: str) -> dict:
        return json.loads(self.fake.files[name])


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ------------------------------------------------------------- the deadline


def test_no_check_starts_that_could_end_after_the_deadline_and_the_run_still_publishes(rig):
    # Smoke at 0 (limit 3), CHAT at 1 (limit 10, ends by 11), TASK_DETECTION at 6:
    # 6 + 10 > 15, so it is deferred unpaid; the CHAT result is published.
    assert rig.go("--deadline-minutes", "15") == 0
    assert rig.fake.smoked == [GENIUS] and rig.fake.measured == [("CHAT", GENIUS)]
    deadline = NOW + timedelta(minutes=15)
    for kind, role, start in rig.fake.starts:
        assert start + timedelta(minutes=job.deadline_of.limit_minutes(kind, role)) <= deadline
    assert f"TASK_DETECTION on {GENIUS}: deferred: the run's deadline (05:32:30Z, 15 min" in (
        rig.report
    )
    assert "- Deadline 2026-10-14T05:32:30Z: 1 checks deferred by it" in rig.report
    assert rig.ranking("economy", "CHAT")[0] == GENIUS  # decided on what it has
    assert GENIUS not in rig.ranking("economy", "TASK_DETECTION")
    settled = rig.doc("ledger.json")["months"]["2026-10"][0]
    assert settled["settled_at"] is not None and settled["spent_usd"] == "0.51"


def test_the_deadline_defaults_to_ninety_minutes_and_a_long_check_is_deferred_near_it(rig):
    late = NOW + timedelta(minutes=75)  # a corpus run (20 min) would not fit; a smoke would
    deadline = job.deadline_of.Deadline(NOW, job.deadline_of.DEADLINE_MINUTES)
    assert deadline.at == NOW + timedelta(minutes=90)
    assert deadline.late("smoke", None, late) is None
    assert deadline.late("measure", "CHAT", NOW + timedelta(minutes=80)) is None  # ends at 90
    assert "may take 20 min" in deadline.late("measure", "MEMORY_MERGE", late)
    assert rig.go() == 0 and len(rig.fake.measured) == 2  # 90 min: everything fits


def test_a_deadline_that_leaves_no_time_defers_every_check_unpaid(rig):
    assert rig.go("--deadline-minutes", "2") == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert rig.pushed() == [["snapshot.json"]]  # nothing reserved, nothing recorded
    assert f"smoke {GENIUS}: deferred: the run's deadline" in rig.report


# ------------------------------------------------------- a hard-killed run


def kill(rig) -> dict:
    """Run until the TASK_DETECTION measurement, then die; the branch's files."""
    with pytest.raises(Killed):
        rig.go(kill_at=("TASK_DETECTION", GENIUS))
    return dict(rig.fake.files)


def test_a_hard_killed_run_leaves_its_paid_results_and_an_honest_reservation(rig):
    files = kill(rig)
    row = json.loads(files["ledger.json"])["months"]["2026-10"][0]
    # The smoke (0.01) and CHAT (0.5) are recorded; the measurement in flight at its bound.
    assert [c["check"] for c in row["calls"]] == [f"smoke {GENIUS}", f"CHAT on {GENIUS}"]
    assert row["settled_at"] is None and row["reserved_usd"] == "2.51"
    (entry,) = json.loads(files["results.json"])["results"]
    assert (entry["model"], entry["role"]) == (GENIUS, "CHAT")
    assert (entry["case_set_sha256"], entry["prompt_sha256"]) == (CS, PH)
    assert entry["result"]["passes"] == 18 and "pass" not in entry["result"]  # judged on use
    assert files["table.json"] == rig.files["table.json"]  # nothing published


def test_an_interrupted_run_settles_the_check_in_flight_at_its_bound(rig):
    with pytest.raises(Interrupted):  # a cancelled workflow: SIGINT, handlers run
        rig.go(kill_at=("TASK_DETECTION", GENIUS), hard=False)
    row = rig.doc("ledger.json")["months"]["2026-10"][0]
    assert row["settled_at"] is not None and row["spent_usd"] == "2.51"  # 0.51 + its bound 2
    assert "interrupted in flight, counted at its bound USD 2" in row["calls"][-1]["outcome"]
    assert len(rig.doc("results.json")["results"]) == 1  # CHAT's, pushed when it ended


def test_the_next_run_takes_a_killed_runs_paid_results_at_no_cost(rig):
    files = kill(rig)
    later = NOW + timedelta(days=1)
    assert rig.go(files=files, now=later) == 0
    assert rig.fake.measured == [("TASK_DETECTION", GENIUS)]  # CHAT is not paid for again
    assert f"cached: CHAT on {GENIUS} (measured 2026-10-14T05:18:30Z): taken from" in rig.report
    chat = rig.doc("measured.json")["roles"]["CHAT"]["results"][GENIUS]
    assert chat["pass"] is True and chat["measured_at"] == "2026-10-14T05:18:30Z"
    assert rig.ranking("economy", "CHAT")[0] == GENIUS
    assert rig.doc("results.json")["results"] == []  # published: no longer pending


def test_results_wait_in_the_cache_while_a_run_cannot_publish(rig):
    files = kill(rig)
    rig.world.models[SONNET]["efforts"] = ["max"]  # its smoke errs: the run cannot publish
    assert rig.go(files=files, now=NOW + timedelta(days=1), smoke_errors={SONNET}) == 1
    assert rig.fake.measured == [("TASK_DETECTION", GENIUS)]
    assert rig.fake.files["table.json"] == rig.files["table.json"]
    recorded = [sorted(f) for f, message in rig.fake.pushes if "records TASK_DETECTION" in message]
    assert recorded == [["ledger.json", "results.json"]]  # cached the moment it was paid for
    assert rig.pushed()[-1] == ["ledger.json"]  # then settled alone: nothing new to cache
    held = [(e["role"], e["model"]) for e in rig.doc("results.json")["results"]]
    assert held == [("CHAT", GENIUS), ("TASK_DETECTION", GENIUS)]  # kept for a later run


# ---------------------------------------------------------------- recovery


def test_an_open_reservation_is_recovered_at_its_reserved_amount_before_reserving(rig):
    ledger = ledger_of(open_row("4.146243"))
    files = dict(rig.files, **{"ledger.json": json.dumps(ledger).encode()})
    assert rig.go(files=files) == 0
    first, message = rig.fake.pushes[0]
    assert list(first) == ["ledger.json"] and "recovers 1 run(s)" in message
    recovered = json.loads(first["ledger.json"])["months"]["2026-10"][0]
    assert recovered["spent_usd"] == "4.146243" and recovered["recovered"] is True
    assert recovered["settled_at"] == "2026-10-14T05:17:30Z"
    assert recovered["recovered_by"] == "2026-10-14T05:17:30Z"
    assert "reserves USD 0.2" in rig.fake.pushes[1][1]  # then, and only then, reserved
    rows = rig.doc("ledger.json")["months"]["2026-10"]
    assert [r["run"] for r in rows] == [KILLED_RUN, "2026-10-14T05:17:30Z"]
    assert rows[0] == recovered  # the later pushes leave it as recovered
    assert "recovered: run 2026-10-12T14:13:04Z (2026-10) was never settled" in rig.report
    assert "USD 4.146243 used before this run" in rig.report


def test_recovery_never_counts_a_run_twice(rig):
    ledger = ledger_of(
        open_row("3", calls=[{"check": "smoke x", "spent_usd": "0.01"}]),
        dict(open_row("1", run="2026-10-11T05:17:00Z"), spent_usd="0.5", settled_at="x"),
    )
    once, lines = records.recover(ledger, "now", "2026-10-14T05:17:30Z")
    assert len(lines) == 1 and once["months"]["2026-10"][1] == ledger["months"]["2026-10"][1]
    assert records.month_used(once, "2026-10") == records.month_used(ledger, "2026-10")
    assert records.month_used(once, "2026-10") == Decimal("3.5")  # not 3 + 3 + 0.5
    twice, again = records.recover(once, "later", "2026-10-15T05:17:30Z")
    assert twice == once and again == []
    files = dict(rig.files, **{"ledger.json": json.dumps(ledger).encode()})
    assert rig.go(files=files) == 0
    second = dict(rig.fake.files)
    assert rig.go(files=second, now=NOW + timedelta(days=1)) == 0
    assert not any("recovers" in message for _, message in rig.fake.pushes)
    rows = json.loads(second["ledger.json"])["months"]["2026-10"]
    assert sum(r.get("recovered", False) for r in rows) == 1
    assert records.month_used(json.loads(second["ledger.json"]), "2026-10") == Decimal("4.51")


def test_a_run_left_open_last_month_is_settled_in_its_own_month(rig):
    ledger = ledger_of(open_row("2", run="2026-09-30T05:17:00Z"), month="2026-09")
    assert rig.go(files=dict(rig.files, **{"ledger.json": json.dumps(ledger).encode()})) == 0
    doc = rig.doc("ledger.json")
    assert doc["months"]["2026-09"][0]["spent_usd"] == "2"
    assert "USD 0 used before this run" in rig.report  # October owes nothing for it


def test_a_dry_run_recovers_nothing_but_counts_the_open_reservation(rig):
    ledger = ledger_of(open_row("9.9"))
    assert (
        rig.go("--dry-run", files=dict(rig.files, **{"ledger.json": json.dumps(ledger).encode()}))
        == 0
    )
    assert rig.fake.pushes == []
    assert "recovered: run 2026-10-12T14:13:04Z" in rig.report


# ------------------------------------------------------------ the monthly cap


def test_the_monthly_cap_holds_with_a_recovered_run_counted_as_spent(rig):
    ledger = ledger_of(open_row("9.9"))
    assert rig.go(files=dict(rig.files, **{"ledger.json": json.dumps(ledger).encode()})) == 0
    assert rig.fake.smoked == [] and rig.fake.measured == []
    assert f"smoke {GENIUS}: the monthly cap of USD 10 leaves USD 0.1" in rig.report


def test_each_checks_reservation_stays_within_what_the_month_leaves(rig):
    settled = dict(open_row("7.6"), spent_usd="7.6", settled_at="2026-10-02T05:40:00Z")
    files = dict(rig.files, **{"ledger.json": json.dumps(ledger_of(settled)).encode()})
    assert rig.go(files=files) == 0
    assert rig.fake.measured == [("CHAT", GENIUS)]  # 0.51 + 2 > 2.4: TASK_DETECTION deferred
    reserved = [
        Decimal(json.loads(f["ledger.json"])["months"]["2026-10"][1]["reserved_usd"])
        for f, _ in rig.fake.pushes
    ]
    assert reserved == [Decimal("0.2"), Decimal("0.01"), Decimal("2.01"), Decimal("0.51")] + [
        Decimal("0.51")
    ]
    assert max(reserved) <= Decimal("2.4")
    assert records.month_used(rig.doc("ledger.json"), "2026-10") == Decimal("8.11")
