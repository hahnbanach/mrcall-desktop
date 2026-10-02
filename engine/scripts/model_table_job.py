#!/usr/bin/env python3
"""The daily model-table job: resolve, verify within the caps, publish (brief D8, AC 7).

`.github/workflows/model-resolution.yml` runs it every day at 05:17 UTC,
before the billing server's 06:00 UTC refresh, and on dispatch; before the
desktop merge only the coordinator runs it, locally, under the same ledger
and caps (plan, S5). One run:

1. **The record.** It reads the requirements in force (this checkout's
   `zylch/llm/roles/requirements.json`) and what the `model-table` data branch
   publishes under `v1/` (`--data`, the branch's checkout): `table.json`,
   `snapshot.json`, `measured.json`, `ledger.json`. A file the branch does not
   hold yet is taken from the build copy beside the requirements: the first
   table is a resolution by hand, reviewed (`resolve_models.py --apply`),
   which has no incumbent, and the job starts from it. Without either the run
   stops.
2. **The read.** It resolves from the live sources with `resolve_models.py`'s
   functions (the catalogue, the benchmarks with `OPENROUTER_API_KEY` from the
   environment and from nowhere else, the pool's endpoints): the pool, its
   scores and the new snapshot, which must pass its static gates; and it
   takes each role's current case-set and prompt hashes from the harness.
3. **The decisions** (`model_table_decide.py`): per preset, role and ranking
   (`ranking`, `anthropic_ranking`), the models the record may publish — the
   incumbent pick kept unless a challenger beats it, a pick that fails a gate
   replaced by the first ranked model with a passing result — and the paid
   checks they wait for. The job makes the most urgent check, decides again,
   and repeats until nothing waits: an entrant without a cached result is
   smoked (at most USD 0.05, `model_smoke.py`) and then measured on the role
   (at most USD 2, slice S4b's `measure_roles.py`); a cached result, keyed by
   (model, role, case-set hash, prompt hash), costs nothing; a ranked model
   whose snapshot metadata changed is smoked before anything is published.
4. **The monthly cap** (USD 10, `MONTHLY_CAP_USD`; `--monthly-cap-usd` may
   only lower it), kept in `ledger.json` (`model_table_records.py`): before
   its first paid call the run appends a run-level reservation and pushes it
   to the data branch; a call the reservation does not cover raises it first
   (pushed again); a call the month's remainder cannot cover is never sent,
   its check deferred and reported. The reservation is settled with what the
   calls spent (an errored call at its whole bound) and pushed with the
   publication, or alone when the run cannot publish. No call is retried.
5. **Re-sampling.** On the month's last day (UTC) the roles whose last
   measurement is oldest are measured again on their current picks, as many
   as the month's remainder covers, and the decisions are made again.
6. **Publish or fail.** The table must pass its static gates against the
   requirements and the new snapshot. A run that moves no pick and no ranking
   order leaves `table.json` untouched — a price-only change updates
   `snapshot.json` alone, without an alarm; otherwise the new decision record
   is published, stamped. `measured.json` is published when the run measured
   something. One commit holds it all. A run that cannot publish — a source
   unreadable, a ranking without a model with a passing result, a raised
   ceiling (never published), a failed gate, a changed model left unsmoked —
   exits 1, and the last published record stays.

The report (markdown, `--report`, also printed) lists the decision and
snapshot changes, the paid checks and the ones not made, the spend, the
unscored models and the empty Anthropic rankings.

    python engine/scripts/model_table_job.py --data model-table --dry-run  # no paid call, no push
    python engine/scripts/model_table_job.py --data model-table            # paid, publishes

Exit codes: 0 published, or nothing to publish; 1 the run could not publish
(the report says why); 2 a configuration error (`requirements.json`, or a
`measured.json` the resolver cannot read).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))  # the job's modules are its siblings, not a package

import model_table_decide as decide  # noqa: E402
import model_table_edges as edges_of  # noqa: E402
import model_table_records as records  # noqa: E402
import resolve_models as rm  # noqa: E402

MONTHLY_CAP_USD = Decimal("10")
STAMP = "%Y-%m-%dT%H:%M:%SZ"
BUILD = ("table.json", "snapshot.json", "measured.json")
LIMIT = 10_000


class Failed(Exception):
    """The run cannot publish; the message says why."""


class Spend:
    """A run's spending under the monthly cap (module docstring, step 4)."""

    def __init__(self, ledger: dict, now: datetime, cap: Decimal, edges: edges_of.Edges):
        self.ledger, self.cap, self.edges = ledger, cap, edges
        self.month, self.run = now.strftime("%Y-%m"), now.strftime(STAMP)
        self.before = records.month_used(ledger, self.month, skip=self.run)
        self.reserved = self.consumed = Decimal(0)
        self.calls: list[dict] = []

    def admit(self, bound: Decimal, pending: Decimal) -> str | None:
        """None when a call of `bound` may be sent — the reservation covering
        it pushed first — else why it may not."""
        room = self.cap - self.before
        need = self.consumed + bound
        if need > room:
            left = records.usd(max(room - self.consumed, Decimal(0)))
            return f"the monthly cap of USD {records.usd(self.cap)} leaves USD {left}"
        if need > self.reserved:
            target = min(room, max(need, self.consumed + pending))
            at = self.edges.now().strftime(STAMP)
            ledger = records.reserve(self.ledger, self.month, self.run, target, at)
            message = f"model-table: run {self.run} reserves USD {records.usd(target)}"
            self.edges.push({"ledger.json": records.dump(ledger)}, message)
            self.ledger, self.reserved = ledger, target
        return None

    def spent(self, call: dict, amount: Decimal) -> None:
        self.consumed += amount
        self.calls.append(call)

    def settled(self) -> str | None:
        """The ledger with this run settled, or None when it reserved nothing."""
        if not self.reserved:
            return None
        at = self.edges.now().strftime(STAMP)
        doc = records.settle(self.ledger, self.month, self.run, self.consumed, self.calls, at)
        return records.dump(doc)

    def summary(self) -> dict:
        return {
            "month": self.month,
            "cap": records.usd(self.cap),
            "used_before": records.usd(self.before),
            "reserved": records.usd(self.reserved),
            "spent": records.usd(self.consumed),
        }


def _doc(raw: bytes | None, what: str):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise Failed(f"{what} cannot be read: not JSON") from None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Run:
    """One run of the job (module docstring); `__call__` returns its summary."""

    def __init__(self, edges: edges_of.Edges, roles: Path, cap: Decimal, dry_run: bool):
        self.edges, self.roles, self.cap, self.dry_run = edges, roles, cap, dry_run
        self.now = edges.now()
        self.s = {"run": self.now.strftime(STAMP), "status": "failed", "code": 1}
        self.s.update(problems=[], notes=[], calls=[], deferred=[], resampled=[])
        self.state = {"smokes": {}, "deferred": {}, "fresh": set()}
        self.unavailable: str | None = None
        self.spend: Spend | None = None

    def __call__(self) -> dict:
        try:
            self._run()
        except rm.resolver.ConfigError as err:
            self.s.update(status="configuration error", code=2)
            self.s["problems"].append(str(err))
        except (Failed, rm.candidates.Refused, rm.gates.GateError, RuntimeError, OSError) as err:
            self.s["problems"].append(str(err))
        finally:
            self.s["deferred"] = [(str(c), why) for c, why in self.state["deferred"].items()]
            if self.spend is not None:
                self.s["spend"] = self.spend.summary()
        return self.s

    def _record(self) -> dict:
        """The requirements in force and the record the run compares with."""
        req_bytes = (self.roles / "requirements.json").read_bytes()
        try:
            req = rm.resolver.validate_requirements(json.loads(req_bytes))
        except (ValueError, UnicodeDecodeError) as err:
            if isinstance(err, rm.resolver.ConfigError):
                raise
            raise rm.resolver.ConfigError(f"requirements.json: {err}") from None
        published = self.edges.read()
        rec = {"req": req, "req_bytes": req_bytes, "published": published}
        for name in BUILD:
            path = self.roles / name
            build = path.read_bytes() if path.is_file() else None
            if published.get(name) is None and build is not None:
                self.s["notes"].append(
                    f"the data branch holds no {name} yet: the build copy stands in"
                )
            rec[name] = _doc(published.get(name), f"the published {name}")
            rec[f"build {name}"] = _doc(build, f"the build {name}")
        table = rec["table.json"] or rec["build table.json"]
        snap = rec["snapshot.json"] or rec["build snapshot.json"]
        if table is None or snap is None:
            raise Failed(
                "no table.json or snapshot.json on the data branch and no build copy: the first "
                "table is resolved by hand (resolve_models.py --apply) and reviewed"
            )
        if rm.gates.schema_errors(table, "table"):
            raise Failed("the published table.json fails its schema")
        rm.gates.check_snapshot(snap)
        for name in ("measured.json", "build measured.json"):
            if rec[name] is not None:
                rm.resolver.validate_measured(rec[name], req["roles"], name)
        ledger = _doc(published.get("ledger.json"), "ledger.json")
        try:
            ledger = records.empty_ledger() if ledger is None else records.check_ledger(ledger)
        except ValueError as err:
            raise Failed(str(err)) from None
        rec.update(table=table, snapshot=snap, ledger=ledger)
        return rec

    def _run(self) -> None:
        rec = self._record()
        req = rec["req"]
        sources = rm.resolver.read(req, self.edges.sources(req))
        result = rm.resolver.pool(req, sources)
        self.s.update(read_at=sources["read_at"], benchmarks_as_of=sources["benchmarks_as_of"])
        self.s["unscored"] = result["unscored"]
        rules = rm.candidates.policy(req)
        snap = rm.snapshot.build(
            sources["catalogue"], sources["endpoints"], rules, sources["read_at"]
        )
        rm.gates.check_snapshot(snap)
        hashes = {role: self.edges.hashes(role) for role in req["roles"]}
        unknown = [role for role, pair in hashes.items() if pair is None]
        if unknown:
            self.s["notes"].append(
                f"no current hashes for {', '.join(unknown)}: their recorded measurement is "
                "taken as current, and the job does not measure them"
            )
        measured = records.working_measured(
            rec["measured.json"], rec["build measured.json"], hashes
        )
        if measured is None:
            raise Failed("no measured.json on the data branch and no build copy")
        self.ctx = {
            "req": req,
            "pool": result["pool"],
            "measured": measured,
            "hashes": hashes,
            "measurable": {role for role in req["roles"] if self.edges.measurable(role)},
            "table": rec["table"],
            "published_snapshot": rec["snapshot"],
            "snapshot": snap,
        }
        self.spend = Spend(rec["ledger"], self.now, self.cap, self.edges)
        try:
            d = self._verify()
            if not d["problems"] and decide.resample_due(self.now.date()):
                d = self._resample(d)
            self._finish(rec, snap, d)
        except BaseException:
            self._settle_alone()  # what was reserved is recorded before the error goes on
            raise

    def _blocked(self, check: decide.Check, pending: Decimal) -> str | None:
        """Why `check` cannot be made now (None: it may, its reservation pushed)."""
        if check.kind == "measure" and check.role not in self.ctx["measurable"]:
            return f"no measurement harness for {check.role} in the daily job"
        if self.dry_run:
            return f"dry run (at most USD {records.usd(check.bound)})"
        if self.unavailable is None:
            try:
                self.edges.preflight()
                self.unavailable = ""
            except Exception as err:  # noqa: BLE001 - reported; nothing is sent
                self.unavailable = f"unavailable: {type(err).__name__}: {err}"
        return self.unavailable or self.spend.admit(check.bound, pending)

    def _verify(self) -> dict:
        """Decide, make the most urgent check, decide again, until none waits."""
        for _ in range(LIMIT):
            d = decide.decide(self.ctx, self.state)
            if d["fatal"] or not d["needs"]:
                return d
            check, why = d["needs"][0]
            pending = sum((c.bound for c, _ in d["needs"]), Decimal(0))
            reason = self._blocked(check, pending)
            if reason:
                self.state["deferred"][check] = reason
            else:
                self._perform(check, why)
        raise RuntimeError("the decisions did not settle")

    def _perform(self, check: decide.Check, why: str) -> None:
        """Make one paid check and record it; an error is no result, never retried."""
        at = self.edges.now().strftime(STAMP)
        try:
            if check.kind == "smoke":
                out = self.edges.smoke(check.model)
                spent, passed, detail = Decimal(str(out["spent_usd"])), out["passed"], out["detail"]
                if passed is None:  # not completed under its cap: no result, like an error
                    self.state["deferred"][check] = f"not completed: {detail}"
                    outcome = f"not completed: {detail}"
                else:
                    self.state["smokes"][check.model] = passed is True
                    outcome = "passed" if passed is True else f"failed: {detail or 'no detail'}"
            else:
                out = self.edges.measure(check.role, check.model)
                spent, result = Decimal(str(out["spent_usd"])), out["result"]
                if not isinstance(result, dict) or not isinstance(result.get("pass"), bool):
                    raise ValueError("the measurement gave no pass or fail")
                hashes = self.ctx["hashes"][check.role]
                records.record_result(
                    self.ctx["measured"], check.role, check.model, result, hashes, at
                )
                self.state["fresh"].add((check.role, check.model))
                outcome = "passed" if result["pass"] else "failed"
        except Exception as err:  # noqa: BLE001 - recorded; its whole bound counts
            self.state["deferred"][check] = f"error: {type(err).__name__}: {err}"
            spent, outcome = check.bound, f"error ({type(err).__name__}), counted at its bound"
        call = {
            "check": str(check),
            "kind": check.kind,
            "model": check.model,
            "role": check.role,
            "why": why,
            "at": at,
            "bound_usd": records.usd(check.bound),
            "spent_usd": records.usd(spent),
            "outcome": outcome,
        }
        self.spend.spent(call, spent)
        self.s["calls"].append(call)

    def _resample(self, d: dict) -> dict:
        """The month's last day: the oldest-measured roles again on their picks."""
        for check in decide.resample_order(
            self.ctx["req"], self.ctx["measured"], d["presets"], self.state
        ):
            reason = self._blocked(check, check.bound)
            if reason:
                self.s["notes"].append(f"re-sampling {check} not made: {reason}")
                continue
            self._perform(check, "monthly re-sampling")
            self.s["resampled"].append(str(check))
            d = self._verify()
        return d

    def _settle_alone(self) -> None:
        """Push the settlement by itself (a run that cannot publish)."""
        text = self.spend.settled() if self.spend is not None else None
        if text is None:
            return
        try:
            message = (
                f"model-table: run {self.spend.run} settles USD {records.usd(self.spend.consumed)}"
            )
            self.edges.push({"ledger.json": text}, message)
        except Exception as err:  # noqa: BLE001 - its reservation stays counted in full
            self.s["problems"].append(f"the settlement could not be pushed: {err}")

    def _finish(self, rec: dict, snap: dict, d: dict) -> None:
        """Publish, or fail with the last published record kept."""
        problems = list(d["problems"])
        self.s["notes"] += d["notes"]
        files, table = {}, rec["table"]
        if not problems:
            try:
                files, table = self._files(rec, snap, d)
            except rm.gates.GateError as err:
                problems.append(str(err))
        changes = decide.snapshot_changes(rec["snapshot"], snap, table)
        self.s["snapshot"], self.s["empty_anthropic"] = changes
        if problems:
            self.s["problems"] += problems
            if not self.dry_run:
                self._settle_alone()
            return
        if self.dry_run:
            self.s.update(status=f"dry run: would publish {', '.join(sorted(files))}", code=0)
            return
        settled = self.spend.settled()
        if settled is not None:
            files["ledger.json"] = settled
        if all(rec["published"].get(n) == text.encode("utf-8") for n, text in files.items()):
            self.s.update(status="unchanged: nothing to publish", code=0)
            return
        changed = "decision changed" if "table.json" in files else "snapshot only"
        message = f"model-table: {changed}; snapshot {snap['version']}"
        self.edges.push(files, message)
        self.s.update(status=f"published ({changed})", code=0)

    def _files(self, rec: dict, snap: dict, d: dict) -> tuple[dict, dict]:
        """The files to publish and the table in force after them."""
        measured, source = self.ctx["measured"], rec["published"].get("measured.json")
        source = source if source is not None else (self.roles / "measured.json").read_bytes()
        unchanged = measured == json.loads(source)
        text = source.decode("utf-8") if unchanged else records.dump(measured)
        stamps = {
            "resolved_at": self.now.strftime(STAMP),
            "catalogue_read_at": snap["read_at"],
            "requirements_sha256": _sha(rec["req_bytes"]),
            "measured_sha256": _sha(text.encode("utf-8")),
        }
        fresh = rm.resolver.document(d, stamps)
        lines = rm.differences(rm.resolver.decision(rec["table"]), rm.resolver.decision(fresh))
        self.s["decision"] = lines
        table = fresh if lines else rec["table"]
        rm.gates.check_table(table, rec["req"], snap)
        published = rec["published"]
        files = {"snapshot.json": rm.gates.dump(snap, 2) + "\n"}
        if lines or published.get("table.json") is None:
            files["table.json"] = rm.gates.dump(table, 4) + "\n"
        if published.get("measured.json") is None or not unchanged:
            files["measured.json"] = text
        return files, table


def main(
    argv: list[str] | None = None, *, edges: edges_of.Edges | None = None, roles: Path = rm.ROLES
) -> int:
    """Run the job; see the module docstring for what it does and its exit codes."""
    ap = argparse.ArgumentParser(description="Resolve, verify and publish the model table.")
    ap.add_argument("--data", type=Path, required=True, help="the model-table branch's checkout")
    ap.add_argument("--report", type=Path, default=Path("model-table-report.md"))
    ap.add_argument("--fixture", type=Path, help="read the sources from a fixture directory")
    ap.add_argument("--work", type=Path, help="where the paid checks keep their journals")
    ap.add_argument("--dry-run", action="store_true", help="no paid call and no push")
    ap.add_argument("--monthly-cap-usd", type=Decimal, default=MONTHLY_CAP_USD)
    args = ap.parse_args(argv)
    if not Decimal(0) < args.monthly_cap_usd <= MONTHLY_CAP_USD:
        ap.error(f"the monthly cap is at most USD {MONTHLY_CAP_USD}")
    edges = edges or edges_of.default(args.data, args.fixture, args.work, args.monthly_cap_usd)
    summary = Run(edges, roles, args.monthly_cap_usd, args.dry_run)()
    text = records.report(summary)
    args.report.write_text(text, encoding="utf-8")
    print(text)
    return summary["code"]


if __name__ == "__main__":
    sys.exit(main())
