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
   and repeats until nothing waits: an entrant without a cached result has
   its measurement projected (free; over the per-role cap of USD 2 it is
   deferred and nothing is sent), is smoked (`model_smoke.py`, admitted
   against USD 0.20: see "The smoke's two figures" below) and then measured
   on the role (at most USD 2: `measure_roles.py`'s loop, through
   `model_table_measure.py`; the memory roles through the M9 corpus runner)
   and judged against the role's reference (below); a cached result, keyed
   by (model, role, case-set hash, prompt hash), costs nothing; a ranked
   model whose snapshot metadata changed is smoked before anything is
   published.
4. **The monthly cap** (USD 10, `MONTHLY_CAP_USD`; `--monthly-cap-usd` may
   only lower it), kept in `ledger.json` (`model_table_records.py`): before
   its first paid call the run appends a run-level reservation and pushes it
   to the data branch; a call the reservation does not cover raises it first
   (pushed again); a call the month's remainder cannot cover is never sent,
   its check deferred and reported. The reservation is settled with what the
   calls spent (an errored call at its whole bound) and pushed with the
   publication, or alone when the run cannot publish. No call is retried.
5. **Re-sampling.** On the month's last day (UTC) each role's current picks
   and its reference, the oldest-measured first, are measured again, as many
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

**The smoke's two figures.** Brief D8's "at most USD 0.05" for a smoke is
the spend a smoke is expected to settle at (the brief prices a request at
USD 0.002 to 0.09), not its admission bound: admission must use the
engine's conservative bound, the full output budget at the model-level
price times the margin, which for a call of a smoke of a model at the
balanced ceiling comes to about USD 0.1 (Opus 5.5 on the 2026-10-02 prices:
0.107, then 0.131; `model_smoke.py`'s journal admits the second call on the
first's settled spend, not on its bound). A smoke is therefore admitted —
reserved against the month, each call journaled before it is sent —
against a per-smoke cap of USD 0.20 (`decide.SMOKE_CAP_USD`): a call whose
bound would cross it is not sent, and that smoke has no result. The report
gives each smoke's settled spend and flags any above USD 0.05
(`decide.SMOKE_EXPECTED_USD`), as does its row in the ledger. The monthly
cap is unchanged.

**The reference.** D7's "from the same run" binds the one-off measurement,
where the reference runs beside every arm. The job reuses the reference's
recorded result while the role's case-set and prompt hashes are today's and
measures a challenger alone against it (beside it, K3's USD 1.82 on CHAT
would leave no CHAT challenger measurable under USD 2); it measures the
reference again only when they are not, and then the whole role
(`model_table_measured.py`). Each measurement's own ledger — S4b's, or the
corpus runner's, whose cap the run's reservation covers before it starts —
says what it spent, and that settled spend is what the month is charged.

The report (markdown, `--report`, also printed) lists the decision and
snapshot changes, the paid checks and the ones not made with each check's
settled spend, the flagged smokes, the spend, the unscored models and the
empty Anthropic rankings.

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
from decimal import ROUND_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))  # the job's modules are its siblings, not a package

import model_table_decide as decide  # noqa: E402
import model_table_edges as edges_of  # noqa: E402
import model_table_measured as measured_of  # noqa: E402
import model_table_records as records  # noqa: E402
import resolve_models as rm  # noqa: E402

MONTHLY_CAP_USD = Decimal("10")
STAMP = records.STAMP
BUILD = ("table.json", "snapshot.json", "measured.json")
LIMIT = 10_000


class Failed(Exception):
    """The run cannot publish; the message says why."""


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
        self.s.update(problems=[], notes=[], calls=[], deferred=[], resampled=[], flags=[])
        self.state = {"smokes": {}, "deferred": {}, "fresh": set(), "projected": {}}
        self.unavailable: str | None = None
        self.spend: records.Spend | None = None

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
            "reference": req["reference"],
            "pool": result["pool"],
            "by_id": {c["id"]: c for c in result["pool"]},
            "measured": measured,
            "hashes": hashes,
            "measurable": {role for role in req["roles"] if self.edges.measurable(role)},
            "table": rec["table"],
            "published_snapshot": rec["snapshot"],
            "snapshot": snap,
        }
        self.spend = records.Spend(rec["ledger"], self.now, self.cap, self.edges)
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
        if check.kind == "measure":
            if check.role not in self.ctx["measurable"]:
                return f"no measurement harness for {check.role} in the daily job"
            if (check.role, check.model) not in self.state["projected"]:
                self._project(check)
            if check in self.state["deferred"]:
                return self.state["deferred"][check]
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
            if check.kind == "project":
                self._project(check)
                continue
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
                spent, outcome = self._measure(check, at)
        except edges_of.Incomplete as err:  # its own ledger says what it spent
            self.state["deferred"][check] = f"not completed: {err}"
            spent, outcome = err.spent_usd, f"not completed: {err}"
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
        if check.kind == "smoke" and spent > decide.SMOKE_EXPECTED_USD:
            expected = records.usd(decide.SMOKE_EXPECTED_USD)
            call["flag"] = f"settled at USD {records.usd(spent)}, above the USD {expected} expected"
            self.s["flags"].append(f"{check}: {call['flag']}")
        self.spend.spent(call, spent)
        self.s["calls"].append(call)

    def _project(self, check: decide.Check) -> None:
        """The free projection of a measurement (`edges.project`): one over the
        per-role cap, or one that cannot be projected, is deferred and nothing
        is sent for it, not even its smoke."""
        measure = decide.Check("measure", check.model, check.role)
        scores = (self.ctx["by_id"].get(check.model) or {}).get("scores", {})
        try:
            expected = Decimal(str(self.edges.project(check.role, check.model, scores)))
        except Exception as err:  # noqa: BLE001 - reported; nothing is sent
            self.state["projected"][(check.role, check.model)] = None
            self.state["deferred"][measure] = f"not projected: {type(err).__name__}: {err}"
            return
        self.state["projected"][(check.role, check.model)] = expected
        if expected > decide.MEASURE_USD:
            # Rounded up: a projection over the cap never reads as the cap itself.
            shown = expected.quantize(Decimal("0.01"), rounding=ROUND_UP)
            cap = records.usd(decide.MEASURE_USD)
            why = f"deferred: over the per-role cap (projected USD {shown}, cap USD {cap})"
            self.state["deferred"][measure] = why

    def _measure(self, check: decide.Check, at: str) -> tuple[Decimal, str]:
        """One measurement (a corpus run measures the three memory roles), each
        role's result judged against its reference and recorded
        (`model_table_measured.py`); a completed re-measurement replaces its role."""
        req, reference = self.ctx["req"], self.ctx["reference"]
        scores = (self.ctx["by_id"].get(check.model) or {}).get("scores", {})
        out = self.edges.measure(check.role, check.model, scores)
        spent, verdicts = Decimal(str(out["spent_usd"])), []
        for role, result in out["results"].items():
            if role not in req["roles"]:
                continue
            hashes, rule = self.ctx["hashes"][role], req["roles"][role]
            try:
                where, stored = measured_of.record(
                    self.ctx["measured"], role, check.model, result, hashes, at, rule, reference
                )
            except measured_of.Unjudgeable as err:
                self.state["deferred"].setdefault(
                    decide.Check("measure", check.model, role), str(err)
                )
                verdicts.append(f"{role}: {err}")
                continue
            self.state["fresh"].add((role, check.model))
            verdicts.append(f"{role}: {'passed' if stored['pass'] else 'failed'}")
            if where == "stage" and decide.remeasured(self.ctx, role):
                measured_of.swap(self.ctx["measured"], role, rule, reference)
                self.s["notes"].append(f"{role} re-measured whole under today's prompt and cases")
        return spent, "; ".join(verdicts) or "no result"

    def _resample(self, d: dict) -> dict:
        """The month's last day: the oldest-measured picks and references again."""
        for check in decide.resample_order(self.ctx, d["presets"], self.state):
            if (check.role, check.model) in self.state["fresh"]:
                continue  # measured since (a corpus run measures three roles at once)
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
