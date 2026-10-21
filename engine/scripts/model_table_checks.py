"""The daily model-table job's paid checks: make one, record it, push it (`model_table_job.py`).

`Checks` is the part of the job's `Run` that makes a paid check and records
what it bought: the call in the run's ledger row, the measurement's results
judged into the working `measured.json`, and in `results.json` the raw
results, the smoke's outcome and a measurement's time-limit stop
(`model_table_results.py`, `model_table_outcomes.py`), all pushed in one
commit as soon as the check ends (`_checkpoint`). At the run's start the
outcomes that still stand are seeded into the run's state (`_seed`): a
cached smoke is not paid for again, a stopped measurement not tried again.
"""

from __future__ import annotations

from decimal import ROUND_UP, Decimal

import model_table_decide as decide
import model_table_edges as edges_of
import model_table_measured as measured_of
import model_table_outcomes as outcomes
import model_table_records as records
import model_table_results as results_of

STAMP = records.STAMP


class Checks:
    """`Run`'s paid checks (module docstring); it reads `s`, `ctx`, `state`,
    `edges`, `spend`, `results`, `published`, `now` and `uncertain` from the run."""

    def _fp(self, model: str) -> str | None:
        """Today's fingerprint of `model`'s request metadata (`model_table_outcomes`)."""
        direct = (self.ctx["by_id"].get(model) or {}).get("direct_id")
        return outcomes.fingerprint(self.ctx["snapshot"], model, direct)

    def _seed(self) -> None:
        """The cached smoke outcomes and time-limit stops that stand today,
        into the run's state (`model_table_outcomes`, module docstring)."""
        smokes, stops = outcomes.live(self.results, self.now, self._fp, self.ctx["hashes"])
        for model, (outcome, why) in smokes.items():
            if outcome == "uncertain":
                self.uncertain[model] = why
            elif outcome == "retry":
                self.state["resmoke"].add(model)
            else:
                self.state["smokes"][model] = outcome == "passed"
            self.s["notes"].append(f"cached: {model}: {why}")
        for (model, role), why in stops.items():
            self.state["deferred"][decide.Check("measure", model, role)] = why
            self._flag_frozen(model, role, why)

    def _flag_frozen(self, model: str, role: str, why: str) -> None:
        """Flag a stop that freezes its role: on the reference, or on a model
        the role's re-measurement needs. Nothing of the role moves meanwhile."""
        frozen = model == self.ctx["reference"] or (
            decide.stale(self.ctx, role) and model in decide.remeasure_set(self.ctx, role)
        )
        if frozen:
            self.s["flags"].append(
                f"{role} waits on {model}, which {why}: the role is not re-measured "
                "and no challenger of it is judged until then"
            )

    def _cached_smoke(self, check: decide.Check, why: str) -> str | None:
        """Why an entrant's smoke is not retried (a cached uncertain outcome);
        a smoke the publication waits for (metadata changed) always is."""
        if check.kind != "smoke" or why.startswith("metadata changed"):
            return None
        return self.uncertain.get(check.model)

    def _remember_smoke(self, check, at: str, spent: Decimal, passed, detail) -> None:
        """Keep a smoke's outcome in `results.json`, unless it sent nothing."""
        fp = self._fp(check.model)
        if spent <= 0 or fp is None:  # nothing sent; or no metadata to key it by
            return
        outcome = {True: "passed", False: "failed"}.get(passed, "uncertain")
        self.results = outcomes.add_smoke(
            self.results, self.spend.run, check.model, fp, at, outcome, detail
        )

    def _remember_stop(self, check, at: str, err) -> None:
        """Keep a measurement's time-limit stop for each role it measured."""
        fp = self._fp(check.model)
        for role in err.roles or (check.role,):
            hashes = self.ctx["hashes"].get(role)
            if hashes is not None and fp is not None:
                self.results = outcomes.add_stop(
                    self.results, self.spend.run, check.model, role, hashes,
                    fp, at, str(err),
                )  # fmt: skip
                why = f"was stopped at its time limit at {at}; not tried again for 14 days"
                self._flag_frozen(check.model, role, why)

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
                self._remember_smoke(check, at, spent, passed, detail)
            else:
                spent, outcome = self._measure(check, at)
        except edges_of.Incomplete as err:  # its own ledger says what it spent
            self.state["deferred"][check] = f"not completed: {err}"
            spent, outcome = err.spent_usd, f"not completed: {err}"
            if err.timed_out:
                self._remember_stop(check, at, err)
        except Exception as err:  # noqa: BLE001 - recorded; its whole bound counts
            self.state["deferred"][check] = f"error: {type(err).__name__}: {err}"
            spent, outcome = check.bound, f"error ({type(err).__name__}), counted at its bound"
            if check.kind == "smoke":
                self._remember_smoke(check, at, spent, None, f"error: {type(err).__name__}")
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
        self.s["calls"].append(call)
        self._checkpoint(check, call, self.spend.spent(call, spent))

    def _checkpoint(self, check: decide.Check, call: dict, ledger: str) -> None:
        """Push the finished check — its call, the reservation lowered to what
        the run spent, its measurement results — before anything else is
        paid for (module docstring, step 4). A push the data branch refuses
        stops the run like a reservation it refuses."""
        files = {"ledger.json": ledger}
        held = self._results_text()
        if held is not None:
            files["results.json"] = held
        message = f"model-table: run {self.spend.run} records {check}: USD {call['spent_usd']}"
        self.edges.push(files, message)
        self.published.update({name: text.encode("utf-8") for name, text in files.items()})

    def _store(self, role: str, model: str, result: dict, at: str) -> tuple[dict | None, str]:
        """Record one role's result of `model`, judged against the role's
        reference (`model_table_measured.record`): the result as stored, or
        None and why it cannot be judged. A completed re-measurement replaces
        its role."""
        req, reference = self.ctx["req"], self.ctx["reference"]
        hashes, rule = self.ctx["hashes"][role], req["roles"][role]
        try:
            where, stored = measured_of.record(
                self.ctx["measured"], role, model, result, hashes, at, rule, reference
            )
        except measured_of.Unjudgeable as err:
            return None, str(err)
        if where == "stage" and decide.remeasured(self.ctx, role):
            measured_of.swap(self.ctx["measured"], role, rule, reference)
            self.s["notes"].append(f"{role} re-measured whole under today's prompt and cases")
        return stored, ""

    def _replayed(self, role: str, model: str, result: dict, at: str) -> str:
        """`model_table_results.replay`'s store: why an entry was not recorded."""
        return self._store(role, model, result, at)[1]

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
        scores = (self.ctx["by_id"].get(check.model) or {}).get("scores", {})
        out = self.edges.measure(check.role, check.model, scores)
        spent, verdicts = Decimal(str(out["spent_usd"])), []
        for role, result in out["results"].items():
            if role not in self.ctx["req"]["roles"]:
                continue
            hashes = self.ctx["hashes"][role] or measured_of.key(
                self.ctx["measured"]["roles"][role]
            )
            # Cached on the data branch with this check's record (`_checkpoint`).
            self.results = results_of.add(
                self.results, self.spend.run, check.model, role, hashes, at, result
            )
            stored, why = self._store(role, check.model, result, at)
            if stored is None:
                self.state["deferred"].setdefault(decide.Check("measure", check.model, role), why)
                verdicts.append(f"{role}: {why}")
                continue
            self.state["fresh"].add((role, check.model))
            verdicts.append(f"{role}: {'passed' if stored['pass'] else 'failed'}")
        return spent, "; ".join(verdicts) or "no result"
