"""The measurement the daily model-table job ranks by: results, the reference, re-measurement.

Pure. The job (`model_table_job.py`) keeps `measured.json` — the engine's
`roles/measured.json` as slice S4b's `derive_thresholds.py` writes it — and adds
what its own measurements find by S4b's own rules (`derive_thresholds.judged`,
`threshold_of`, `reference_yardstick`), so the file stays one whose passes and
thresholds follow from its results, as `derive_thresholds.check_measured` asks.

**A result** is S4b's per-arm dict — `n`, `passes`, `score`, `bars_ok`,
`critical`, `complete`, `index_score` (`aggregate`, from S4b's result rows,
as `derive_thresholds.role_entry` computes it) — with `pass` and `reasons`
(`judged` against the role's reference result) and the `case_set_sha256`,
`prompt_sha256` and `measured_at` it was measured under: the cache key is
(model, role, case-set hash, prompt hash).

**The reference.** Brief D7 judges an arm against the reference's score less
its binomial standard error "from the same run". That binds the one-off
measurement (`measure_roles.py`), where the reference runs beside every arm.
The daily job keeps the reference's recorded result while the role's case-set
and prompt hashes are today's, and measures a challenger alone against it:
re-running the reference beside each challenger would spend most of a role's
USD 2 on the reference (K3 on CHAT projects at about USD 1.82, leaving about
0.18), so no CHAT challenger could ever be measured. When the reference itself
is measured again (the monthly re-sampling counts it as one more model), every
result of the role is judged again against it (`rejudge`).

**A role whose hashes are no longer today's** (its prompt or its case set
changed) is re-measured whole: the reference first, then every model its
published rankings name, each judged against the new reference. The new
results wait in `measured.json`'s top-level `remeasure` (`staged`; the
resolver and `check_measured` read only `roles`) while the published record
keeps ranking on the old ones; once all of them are measured the role's entry
is replaced (`swap`) by the staged results, the new reference's yardstick and
the threshold they give.

After every result recorded under the role's hashes its `threshold` and
`measured_only` are derived again from its results (`rederive`), as
`derive_thresholds.py` derives them: a challenger above the threshold that
fails makes index and result disagree, and the role then accepts measured
models only (D7).
"""

from __future__ import annotations

import derive_thresholds as dt

JUDGEABLE = ("n", "passes", "bars_ok", "critical", "complete")


class Unjudgeable(ValueError):
    """A result that cannot be recorded: no reference to judge it against, or
    a reference measurement that is not complete."""


def key(body: dict) -> tuple[str, str]:
    return body["case_set_sha256"], body["prompt_sha256"]


def result_key(body: dict, result: dict) -> tuple[str, str]:
    """The hashes a result was measured under: its own, else its role's."""
    own = (result.get("case_set_sha256"), result.get("prompt_sha256"))
    return own if None not in own else key(body)


def judgeable(result: dict | None) -> bool:
    return isinstance(result, dict) and all(field in result for field in JUDGEABLE)


def aggregate(rows: list[dict], cases: list[str]) -> dict:
    """One arm's result from its rows of S4b's results (one role), exactly as
    `derive_thresholds.role_entry` aggregates an arm: the latest row per cell;
    `complete` when every case was scored in the first repetition."""
    rows = dt.common.latest_rows(rows)
    first = [r for r in rows if r.get("repetition", 1) == 1]
    # Judged on the first repetition alone, as derive_thresholds.role_entry: a
    # second answer (--repeat-disagreements) changes no pass or fail.
    scored = [r for r in first if r["status"] == "scored"]
    complete = all(r["status"] == "scored" for r in first) and {r["case_id"] for r in first} >= set(
        cases
    )
    result = {
        "n": len(scored),
        "passes": sum(bool(r["scoring"]["label_match"]) for r in scored),
        "bars_ok": all(r["scoring"]["bars_ok"] for r in scored),
        "critical": any(r["scoring"]["critical"] for r in scored),
        "complete": complete,
        "index_score": next((r["arm_score"] for r in rows if r.get("arm_score") is not None), None),
    }
    result["score"] = round(result["passes"] / max(1, result["n"]), 6)
    return result


def judge(result: dict, reference: dict) -> dict:
    """`result` with `pass` and `reasons` against the reference's result."""
    passed, reasons = dt.judged(result, reference)
    return {**result, "pass": passed, "reasons": reasons}


def yardstick(reference: str, result: dict) -> dict:
    """The role entry's `reference`: the id, its score and binomial standard error."""
    p, se = dt.reference_yardstick(result)
    return {"id": reference, "score": round(float(p), 6), "se": round(se, 6)}


def rederive(body: dict, rule: dict) -> None:
    """The role's threshold and `measured_only`, derived again (S4b's
    `threshold_of`) from its judged results under the role's hashes."""
    results = {
        model: r
        for model, r in body["results"].items()
        if judgeable(r) and "pass" in r and result_key(body, r) == key(body)
    }
    body["threshold"], body["measured_only"] = dt.threshold_of(rule["rule"], results)


def rejudge(body: dict, rule: dict, reference: str) -> None:
    """Every result of the role judged again against its reference's result
    (just measured again), the yardstick and the threshold with them."""
    ref = body["results"][reference]
    for model, r in list(body["results"].items()):
        if model != reference and judgeable(r) and result_key(body, r) == key(body):
            body["results"][model] = judge(r, ref)
    body["reference"] = yardstick(reference, ref)
    rederive(body, rule)


def staged(measured: dict, role: str, hashes, create: bool = False) -> dict | None:
    """The role's re-measurement under `hashes`, or None (`create`: a new one,
    replacing one made under other hashes, which a newer change made stale)."""
    stage = (measured.get("remeasure") or {}).get(role)
    if stage is not None and key(stage) == tuple(hashes):
        return stage
    if not create:
        return None
    stage = {"case_set_sha256": hashes[0], "prompt_sha256": hashes[1], "results": {}}
    measured.setdefault("remeasure", {})[role] = stage
    return stage


def record(measured, role, model, result, hashes, at, rule, reference) -> tuple[str, dict]:
    """Record one model's measured `result` for `role`, judged against the
    role's reference; return where — `role` (its entry, re-derived) or `stage`
    (its re-measurement under new hashes) — and the result as stored. Raises
    Unjudgeable, and then records nothing."""
    body = measured["roles"][role]
    want = tuple(hashes) if hashes is not None else key(body)
    in_role = key(body) == want
    stage = None if in_role else staged(measured, role, want)
    target = body["results"] if in_role else (stage or {"results": {}})["results"]
    if model == reference:
        if not result["complete"]:
            raise Unjudgeable(f"{role}: the reference's measurement is not complete")
        ref = result
    else:
        ref = target.get(reference)
        today = not in_role or (judgeable(ref) and result_key(body, ref) == want)
        if not judgeable(ref) or not today:
            raise Unjudgeable(f"{role}: no reference result under today's hashes to judge {model}")
    stamp = {"case_set_sha256": want[0], "prompt_sha256": want[1], "measured_at": at}
    if not in_role:
        target = staged(measured, role, want, create=True)["results"]
    target[model] = {**judge(result, ref), **stamp}
    if not in_role:
        return "stage", target[model]
    if model == reference:
        rejudge(body, rule, reference)
    else:
        rederive(body, rule)
    return "role", target[model]


def swap(measured: dict, role: str, rule: dict, reference: str) -> None:
    """The role's entry replaced by its completed re-measurement."""
    stage = measured["remeasure"].pop(role)
    if not measured["remeasure"]:
        del measured["remeasure"]
    body = measured["roles"][role]
    body.update(results=stage["results"], case_set_sha256=stage["case_set_sha256"])
    body.update(prompt_sha256=stage["prompt_sha256"])
    body["reference"] = yardstick(reference, stage["results"][reference])
    rederive(body, rule)
