"""The daily model-table job's decisions: pure, no I/O (brief D8, AC 7).

`model_table_job.py` reads the published record and the live sources and
performs the paid checks; this module decides, from what it is given, the
rankings to publish and the next paid check a decision is waiting for. It is
called again after every check, so a result (a passed or failed smoke, a
role's measurement of a model) moves the decision until no check is left.

**Challengers.** The resolver ranks only what the measurement admits, so a
model nobody has measured never enters a `maximise` ranking by itself. The
job looks at an optimistic view instead (`view`): every pool model without a
recorded result is taken to pass where the role ranks only models that
passed (`maximise`, or `measured_only`); a `satisfice` role already ranks an
unmeasured model at or above its threshold. What the optimistic view ranks
and the published record does not is a challenger.

**Verified entries** (`_status`). A ranked model is published only when it
is verified for that ranking: it was already in the published ranking (it
was verified when it entered), or it has a passing result for the role under
the current case-set and prompt hashes — cached from an earlier measurement
(that costs nothing) or measured in this run after a passing smoke. Any
other entrant waits for its checks: the smoke (at most USD 0.05) and then
the role's measurement (at most USD 2). A check the run cannot make (the
monthly cap, a dry run, no harness for the role) is deferred and the entrant
is skipped, so the ranking keeps only verified models.

**The incumbent** (`_incumbent`) is the published pick. It stays the pick
while it is eligible — in the pool (still in the catalogue, no announced
expiry, no excluded family, an admitted endpoint), under the ceiling, not
failed by its measurement, its smoke not failed in this run — unless the
challenger beats it: for a `maximise` role, when either score is imputed,
only by leading by more than the imputation's residual deviation; otherwise
(and for every `satisfice` role, which orders by price) by the resolver's
order. An incumbent that fails a gate is replaced by the first ranked model
with a passing result, the verified entries in the resolver's order.

**Metadata.** A ranked model whose request metadata (`reasoning`,
`parameters`, `forced_tool`, in the catalogue or the direct entry) changed
between the published snapshot and the new one is smoked before anything is
published (plan, deviation 2); a failed smoke removes it like any gate.

**Problems** block publication: `measured.json` not covering a role; a
ceiling the optimistic view would already have to raise (a raised ceiling is
never published, so the run stops before any paid call); a main ranking with
no verified model; an Anthropic ranking emptied while its checks were
deferred; a changed model whose smoke could not run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import resolve_models as rm

resolver = rm.resolver
SMOKE_USD = Decimal("0.05")
MEASURE_USD = Decimal("2")
COLUMNS = ("ranking", "anthropic_ranking")
METADATA = ("reasoning", "parameters", "forced_tool")
VERIFIED = "verified"


@dataclass(frozen=True)
class Check:
    """One paid check: the smoke of a model, or a role's measurement of it."""

    kind: str
    model: str
    role: str | None = None

    @property
    def bound(self) -> Decimal:
        """The most the check may cost: its own cap."""
        return SMOKE_USD if self.kind == "smoke" else MEASURE_USD

    def __str__(self) -> str:
        return f"smoke {self.model}" if self.kind == "smoke" else f"{self.role} on {self.model}"


def result_hashes(body: dict, result: dict) -> tuple[str, str]:
    """The case-set and prompt hashes a recorded result was measured under:
    its own when it carries them (the job stamps every result it writes),
    else its role's."""
    return (
        result.get("case_set_sha256", body["case_set_sha256"]),
        result.get("prompt_sha256", body["prompt_sha256"]),
    )


def current(measured: dict, role: str, model: str, hashes: dict) -> dict | None:
    """The cached result of `model` for `role` — the cache key is (model,
    role, case-set hash, prompt hash) — or None. A role whose current hashes
    are unknown (`hashes[role]` None) takes its recorded results as current."""
    body = measured["roles"].get(role)
    result = (body or {}).get("results", {}).get(model)
    if result is None:
        return None
    want = hashes.get(role)
    return result if want is None or result_hashes(body, result) == tuple(want) else None


def view(rule: dict, body: dict, pool: list[str]) -> dict:
    """The optimistic outcome `resolver.qualifies` reads for a role (see the
    module docstring): its recorded results, plus a pass assumed for every
    pool model without one where the role ranks only models that passed."""
    results = dict(body["results"])
    if rule["rule"] == "maximise" or body["measured_only"]:
        for model in pool:
            results.setdefault(model, {"pass": True})
    return {**body, "results": results}


def ordered(rule: dict, options: list[dict], outcome: dict, ceiling: Decimal) -> list[dict]:
    """`resolver.rank` without its cut at five: every option the outcome
    admits at or under `ceiling`, in the role's order."""
    index = rule["index"]
    fit = [
        c
        for c in options
        if c["scores"][index] is not None
        and c["price"] <= ceiling
        and resolver.qualifies(rule, outcome, c)
    ]
    return sorted(fit, key=resolver.order(rule))


def beats(rule: dict, challenger: dict, incumbent: dict) -> bool:
    """Whether `challenger` displaces `incumbent` as the pick (module docstring)."""
    index = rule["index"]
    if rule["rule"] == "maximise":
        deviations = [c["imputed"][index] for c in (challenger, incumbent) if index in c["imputed"]]
        if deviations:
            return challenger["scores"][index] - incumbent["scores"][index] > max(deviations)
    key = resolver.order(rule)
    return key(challenger) < key(incumbent)


def published_ids(table: dict, preset: str, role: str, column: str) -> list[str] | None:
    """The ids of a published ranking in order, or None when the record has none."""
    row = table.get("presets", {}).get(preset, {}).get("roles", {}).get(role)
    return None if row is None else [entry["id"] for entry in row.get(column, [])]


def _status(c: dict, role: str, published: list[str] | None, ctx: dict, run: dict):
    """VERIFIED, or the next Check the entrant `c` waits for (module docstring)."""
    model = c["id"]
    if published is not None and model in published:
        return VERIFIED
    result = current(ctx["measured"], role, model, ctx["hashes"])
    if result is not None and result["pass"] is True:
        return VERIFIED
    if model in run["smokes"] or role not in ctx["measurable"]:
        # No smoke for a role the job cannot measure: the measurement is
        # deferred unpaid, and a smoke alone verifies nothing.
        return Check("measure", model, role)
    return Check("smoke", model)


def _walk(cands: list[dict], published, role: str, ctx: dict, run: dict):
    """(chosen, wants, skipped): the first five verified candidates in order;
    each wanted check of an entrant ahead of the fifth, with whether it stands
    before the first verified one (the pick's place); the deferred checks of
    the entrants skipped."""
    chosen, wants, skipped = [], [], []
    for c in cands:
        status = _status(c, role, published, ctx, run)
        if status == VERIFIED:
            chosen.append(c)
        elif status in run["deferred"]:
            skipped.append(status)
        else:
            wants.append((status, not chosen))
        if len(chosen) == resolver.RANKED:
            break
    return chosen, wants, skipped


def _incumbent(rule, chosen, cands, published, where: str, notes: list) -> list[dict]:
    """`chosen` with the published pick kept first while it holds (module docstring)."""
    if not published or not chosen or chosen[0]["id"] == published[0]:
        return chosen
    held = next((c for c in cands if c["id"] == published[0]), None)
    if held is None or beats(rule, chosen[0], held):
        return chosen
    notes.append(
        f"{where}: {held['id']} stays the pick; {chosen[0]['id']} does not lead it by more "
        "than the imputation's deviation"
    )
    return ([held] + [c for c in chosen if c["id"] != held["id"]])[: resolver.RANKED]


def metadata_changes(old: dict, new: dict, model: str, direct_id: str | None) -> list[str]:
    """The request-metadata fields of `model` (and of its direct id) that
    differ between two snapshots; [] for a model one of them lacks."""
    changes = []
    for section, key in (("models", model), ("direct", direct_id)):
        before = (old.get(section, {}).get(key) or {}).get("metadata") if key else None
        after = (new.get(section, {}).get(key) or {}).get("metadata") if key else None
        if before is None or after is None:
            continue
        changes += [f"{section} {field}" for field in METADATA if before[field] != after[field]]
    return changes


def snapshot_changes(old: dict, new: dict, table: dict) -> tuple[dict, list[str]]:
    """For the report: the snapshot's change as the ranked models of `table`
    see it (prices, metadata), and the presets and roles whose Anthropic
    ranking is empty."""
    ranked, empty = {}, []
    for preset, body in table["presets"].items():
        for role, row in body["roles"].items():
            for entry in row["ranking"] + row["anthropic_ranking"]:
                ranked.setdefault(entry["id"], entry["direct_id"])
            if not row["anthropic_ranking"]:
                empty.append(f"{preset} / {role}")
    before, after = old["models"], new["models"]
    both = [m for m in ranked if m in before and m in after]
    changes = {m: metadata_changes(old, new, m, ranked[m]) for m in both}
    return {
        "old": old["version"],
        "new": new["version"],
        "added": len(set(after) - set(before)),
        "removed": len(set(before) - set(after)),
        "prices": [
            (m, before[m]["pricing"]["output"], after[m]["pricing"]["output"])
            for m in both
            if before[m]["pricing"] != after[m]["pricing"]
        ],
        "metadata": [(m, fields) for m, fields in changes.items() if fields],
    }, empty


def _raised(req: dict, options: list[dict], views: dict) -> list[str]:
    """The ceilings the optimistic view would already raise: never published."""
    ranked = resolver.rankings(req, options, {"roles": views})
    return [
        f"{preset}'s ceiling of {rm.snapshot.text(body['ceiling'])} would be raised to "
        f"{rm.snapshot.text(body['raised_to'])}, and a raised ceiling is never published"
        for preset, body in ranked["presets"].items()
        if body["raised_to"] is not None
    ]


def decide(ctx: dict, run: dict) -> dict:
    """The rankings to publish and the checks they wait for.

    `ctx`: `req` (the requirements in force), `pool` (`resolver.pool`'s),
    `measured` (the job's working `measured.json`), `hashes` (per role the
    current `(case_set_sha256, prompt_sha256)`, or None when unknown),
    `measurable` (the roles the job's harness measures), `table` and
    `published_snapshot` (the record the run compares with),
    `snapshot` (this read's). `run`: `smokes` (model -> passed, this run),
    `deferred` (Check -> why it could not run). Returns `presets` (the
    resolver's `rankings` shape: per preset its ceiling and per role both
    rankings), `needs` (`[(Check, why)]`, the most urgent first), `problems`
    (what blocks publication if the run stopped now), `fatal` (problems no
    check can lift) and `notes`."""
    req, measured = ctx["req"], ctx["measured"]
    uncovered = [role for role in req["roles"] if role not in measured["roles"]]
    if uncovered:
        problem = f"measured.json does not cover {', '.join(uncovered)}"
        return {"presets": {}, "needs": [], "problems": [problem], "fatal": True, "notes": []}
    failed = {model for model, passed in run["smokes"].items() if not passed}
    options = [c for c in ctx["pool"] if c["id"] not in failed]
    names = [c["id"] for c in options]
    views = {
        role: view(rule, measured["roles"][role], names) for role, rule in req["roles"].items()
    }
    raised = _raised(req, options, views)
    if raised:
        return {"presets": {}, "needs": [], "problems": raised, "fatal": True, "notes": []}
    roster, presets = list(req["roles"]), {}
    wanted: dict[Check, tuple] = {}
    problems, notes = [], []
    for p_rank, (preset, spec) in enumerate(req["presets"].items()):
        ceiling = Decimal(str(spec["ceiling"]))
        roles = {}
        for role, rule in req["roles"].items():
            roles[role] = {}
            for c_rank, column in enumerate(COLUMNS):
                where = f"{preset} / {role} / {column}"
                pool = options if column == "ranking" else [c for c in options if c["direct_id"]]
                cands = ordered(rule, pool, views[role], ceiling)
                published = published_ids(ctx["table"], preset, role, column)
                chosen, wants, skipped = _walk(cands, published, role, ctx, run)
                chosen = _incumbent(rule, chosen, cands, published, where, notes)
                roles[role][column] = chosen
                held = bool(chosen) and bool(published) and chosen[0]["id"] == published[0]
                for check, at_pick in wants:
                    if not chosen or (at_pick and published and not held):
                        urgency = 1  # an empty ranking, or a pick that failed a gate
                    else:
                        urgency = 2 if at_pick else 3  # a challenger to the pick, an entrant
                    key = (urgency, roster.index(role), p_rank, c_rank)
                    why = f"{'pick' if at_pick else 'ranking'} of {where}"
                    if check not in wanted or key < wanted[check][0]:
                        wanted[check] = (key, why)
                waiting = "; ".join(f"{check}: {run['deferred'][check]}" for check in skipped)
                if not chosen and column == "ranking":
                    problems.append(
                        f"{where}: no ranked model with a passing result"
                        + (f" (deferred: {waiting})" if waiting else "")
                    )
                elif not chosen and published and skipped:
                    problems.append(f"{where}: emptied while its checks wait ({waiting})")
        presets[preset] = {"ceiling": ceiling, "raised_to": None, "roles": roles}
    _metadata_needs(ctx, run, presets, wanted, problems)
    needs = sorted(wanted.items(), key=lambda item: item[1][0])
    return {
        "presets": presets,
        "needs": [(check, why) for check, (_, why) in needs],
        "problems": problems,
        "fatal": False,
        "notes": notes,
    }


def _metadata_needs(ctx: dict, run: dict, presets: dict, wanted: dict, problems: list) -> None:
    """Add the smoke of every ranked model whose metadata changed (module
    docstring) to `wanted`, most urgent of all; a problem when it was deferred."""
    seen: dict[str, dict] = {}
    for body in presets.values():
        for row in body["roles"].values():
            for column in COLUMNS:
                for c in row[column]:
                    seen.setdefault(c["id"], c)
    for model, c in seen.items():
        changes = metadata_changes(
            ctx["published_snapshot"], ctx["snapshot"], model, c["direct_id"]
        )
        if not changes or model in run["smokes"]:
            continue
        check = Check("smoke", model)
        why = f"metadata changed ({', '.join(changes)})"
        if check in run["deferred"]:
            problems.append(
                f"{model}: {why} and its smoke could not run ({run['deferred'][check]})"
            )
        else:
            wanted[check] = ((0, 0, 0, 0), why)


def resample_due(day: date) -> bool:
    """Whether `day` (UTC) is the month's last: the monthly re-sampling spends
    what the month's cap leaves after the month's decision checks."""
    return (day + timedelta(days=1)).month != day.month


def resample_order(req: dict, measured: dict, presets: dict, run: dict) -> list[Check]:
    """The re-sampling checks: the roles whose last measurement is oldest
    first (a result without `measured_at` counts as oldest; ties in roster
    order), each on its current pick under every preset, never one measured
    in this run."""

    def last(role: str) -> str:
        results = measured["roles"][role]["results"].values()
        return max((r.get("measured_at", "") for r in results), default="")

    roster = list(req["roles"])
    out: list[Check] = []
    for role in sorted(roster, key=lambda role: (last(role), roster.index(role))):
        for body in presets.values():
            ranking = body["roles"][role]["ranking"]
            check = Check("measure", ranking[0]["id"], role) if ranking else None
            if check and check not in out and (role, check.model) not in run["fresh"]:
                out.append(check)
    return out
