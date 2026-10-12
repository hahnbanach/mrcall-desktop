"""Runs and their yardsticks: each arm judged against the reference from its own run (M10, S4b7).

D7 judges an arm against "the binomial standard error of its score, from the
same run": the reference's score in the run that measured the arm, not in
another run chosen afterwards. Two CHAT runs on today's prompt gave K3 10/11
and 11/11; picking either for every arm by its outcome would decide, by
itself, whether Anthropic models pass.

So every row carries a ``run`` (``derive_thresholds.py --run ID@COMMIT=PATH``;
``--results PATH`` rows are the unnamed run ``""``, ``--corpus RUN=MANIFEST``
names a corpus record's run). Per role:

- each arm is measured per run: its first-repetition rows of that run
  (``arm_result``). An arm cut short in any run is no measurement and goes
  under ``incomplete``, run named;
- each run where the reference is complete is a **yardstick**: its p and
  binomial se. An arm of a run without one cannot be judged and goes under
  ``incomplete``;
- each arm's result is judged against its own run's yardstick and records it
  as ``judged_by`` (the run id; a result of the unnamed run carries none).
  An arm measured in more than one run (the reference, which runs in each)
  is judged in each. Its counts are summed,
  and it passes only when it passes in every run; ``runs`` keeps each run's
  own result;
- the role's ``reference`` lists each run's yardstick (``runs``: ``n``,
  ``passes``, ``score``, ``se``), and keeps ``score`` and ``se`` at top level
  when there is one run;
- a reference case that misses a bar and the label (no tool called, an empty
  answer) is credited to the yardstick, not counted against it
  (``bar_misses``, ``yardstick_of``): a reference's mechanical failure never
  lowers the bar its run's arms must clear. The credited cases are named
  (``bar_misses_credited``), and the reference's own result keeps the
  failure, so it does not pass that role in that run.
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path

INCOMPLETE = {
    "cap": "stopped by the cap",
    "skipped": "skipped after two failures in a row",
    "unpriced": "no price",
    "interrupted": "interrupted after its dispatch",
    "refused": "refused before inference, not yet sent again",
    "denied": "the key denied",
    "error": "failed",
    "stale_request": "its shaped request is not today's",
}


def parse_run(text: str) -> tuple[str, str, Path]:
    """``ID@COMMIT=PATH`` as ``(id, commit, path)``."""
    head, sep, path = text.partition("=")
    run, at, commit = head.partition("@")
    if not (sep and at and run and commit and path):
        raise ValueError(f"--run {text!r}: expected ID@COMMIT=PATH")
    return run, commit, Path(path)


def parse_corpus(text: str) -> tuple[str, Path]:
    """``[RUN=]MANIFEST`` as ``(run, path)``; the unnamed run is ``""``."""
    run, sep, path = text.partition("=")
    return (run, Path(path)) if sep else ("", Path(text))


def reference_yardstick(result: dict) -> tuple[Fraction, float]:
    """The reference's score and its binomial standard error, from its own counts."""
    p = Fraction(result["passes"], result["n"])
    return p, math.sqrt(float(p * (1 - p)) / result["n"])


def judged(result: dict, reference: dict) -> tuple[bool, list[str]]:
    """Whether an arm's result passes against the reference of its run."""
    p, se = reference_yardstick(reference)
    reasons = []
    if not result["complete"]:
        reasons.append("incomplete")
    if not result["bars_ok"]:
        reasons.append("mechanical bar")
    if result["critical"]:
        reasons.append("critical failure")
    if result["n"] and float(Fraction(result["passes"], result["n"])) < float(p) - se:
        reasons.append("below the reference less its standard error")
    return not reasons, reasons


def why_incomplete(first: list[dict], cases: list[str]) -> str:
    """Each case an arm's first repetition did not score, under its status; refusals named."""
    by_case = {row["case_id"]: row for row in first}
    groups: dict[str, list[str]] = {}
    for case in cases:
        row = by_case.get(case)
        if row is not None and row["status"] == "scored":
            continue
        if row is None:
            label = "not run"
        elif row["status"] == "error" and row.get("refusals"):
            label = str(row.get("error") or "refused").split(":")[0]
        else:
            label = INCOMPLETE.get(row["status"], row["status"])
        groups.setdefault(label, []).append(case)
    return "; ".join(f"{label}: {', '.join(ids)}" for label, ids in groups.items())


def arm_result(mine: list[dict], cases: list[str]) -> tuple[dict, str | None]:
    """An arm's result in one run, and why it is incomplete (None when complete).

    Judged on the first repetition alone: a second answer is recorded in
    ``second_repetition`` and changes no pass or fail.
    """
    first = [r for r in mine if r.get("repetition", 1) == 1]
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
        "index_score": next((r["arm_score"] for r in mine if r.get("arm_score") is not None), None),
    }
    result["score"] = round(result["passes"] / max(1, result["n"]), 6)
    return result, None if complete else why_incomplete(first, cases)


def supersede_stale(rows: list[dict], cases: list[str]) -> tuple[list[dict], dict]:
    """``(rows, {arm: [runs dropped]})``: an arm's stale-shape run, measured again, is dropped.

    A run holding a ``stale_request`` row (``measurement_shape``: the shaped
    request is not today's) is no measurement of that arm. When the same arm
    has another run of the role with no stale row and every case answered, the
    stale run is superseded and its rows leave. Without such a run they stay,
    and the arm is incomplete (unmeasured). The rule is mechanical: it never
    drops a current-shape row, whatever its verdict.
    """
    by_run: dict[tuple, list[dict]] = {}
    for row in rows:
        by_run.setdefault((row["arm"], row.get("run", "")), []).append(row)

    def stale(mine: list[dict]) -> bool:
        return any(r["status"] == "stale_request" for r in mine)

    current = {
        arm
        for (arm, _run), mine in by_run.items()
        if not stale(mine) and arm_result(mine, cases)[1] is None
    }
    kept, dropped = [], {}
    for (arm, run), mine in by_run.items():
        if arm in current and stale(mine):
            dropped.setdefault(arm, []).append(run)
        else:
            kept += mine
    return kept, {arm: sorted(runs) for arm, runs in sorted(dropped.items())}


def judge_runs(per_run: dict, yardsticks: dict, incomplete: dict) -> dict:
    """``{arm: result}``, each run's result judged against that run's yardstick."""
    by_arm: dict[str, dict] = {}
    for run, arms in per_run.items():
        for arm, result in arms.items():
            if run not in yardsticks:
                incomplete[arm] = f"run {run or '(unnamed)'}: no complete reference result"
                continue
            result["pass"], result["reasons"] = judged(result, yardsticks[run])
            by_arm.setdefault(arm, {})[run] = result
    out = {}
    for arm, runs in sorted(by_arm.items()):
        if arm in incomplete:  # cut short in another run: no measurement of this model
            continue
        if len(runs) == 1:
            out[arm] = next(iter(runs.values()))
            continue
        every = list(runs.values())
        merged = {
            "n": sum(r["n"] for r in every),
            "passes": sum(r["passes"] for r in every),
            "bars_ok": all(r["bars_ok"] for r in every),
            "critical": any(r["critical"] for r in every),
            "complete": True,
            "index_score": every[0]["index_score"],
            "pass": all(r["pass"] for r in every),
            "reasons": sorted({reason for r in every for reason in r["reasons"]}),
            "judged_by": sorted(runs),
            "runs": runs,
        }
        merged["score"] = round(merged["passes"] / max(1, merged["n"]), 6)
        out[arm] = merged
    return out


def bar_misses(mine: list[dict]) -> list[str]:
    """The reference's first-repetition cases that missed a bar *and* the label.

    A reference that answers nothing (no tool called, an empty reply) also
    misses the label. Counted as a miss, that mechanical failure would lower
    the yardstick every arm of its run is judged against: in rerun 7, K3's two
    REANALYZE answers without a tool call would have let an arm pass with
    12 of 15. ``yardstick_of`` therefore credits these cases to the yardstick,
    and ``reference_entry`` names them.
    """
    return sorted(
        r["case_id"]
        for r in mine
        if r.get("repetition", 1) == 1
        and r["status"] == "scored"
        and not r["scoring"]["bars_ok"]
        and not r["scoring"]["label_match"]
    )


def yardstick_of(result: dict) -> dict:
    """The reference's result as a yardstick: its bar misses credited, never counted against it.

    A bar failure can therefore only keep the yardstick where it would be or
    raise it, never lower it. The reference's own result is unchanged: it
    still misses that bar, so it does not pass in that run.
    """
    return {**result, "passes": result["passes"] + len(result.get("bar_misses") or ())}


def reference_entry(reference: str, yardsticks: dict) -> dict:
    """The role's ``reference``: each run's yardstick; ``score`` and ``se`` when one run."""
    runs = {}
    for run, result in sorted(yardsticks.items()):
        p, se = reference_yardstick(result)
        runs[run] = {
            "n": result["n"],
            "passes": result["passes"],
            "score": round(float(p), 6),
            "se": round(se, 6),
        }
        if result.get("bar_misses"):
            runs[run]["bar_misses_credited"] = result["bar_misses"]
    entry: dict = {"id": reference, "runs": runs}
    if len(runs) == 1:
        only = next(iter(runs.values()))
        entry.update(score=only["score"], se=only["se"])
    return entry


def pass_problems(role: str, arm: str, result: dict, yardsticks: dict) -> list[str]:
    """Why ``result``'s pass is not the one its own run's yardstick gives (check_measured)."""
    if "runs" in result:
        expected = True
        for run, sub in result["runs"].items():
            if run not in yardsticks:
                return [f"{role}: {arm} was judged by run {run!r}, which has no yardstick"]
            expected &= judged(sub, yardsticks[run])[0]
            if sub.get("pass") != judged(sub, yardsticks[run])[0]:
                return [f"{role}: {arm}'s pass in run {run!r} is not the one its results give"]
    else:
        run = result.get("judged_by", "")
        if run not in yardsticks:
            return [f"{role}: {arm} was judged by run {run!r}, which has no yardstick"]
        expected = judged(result, yardsticks[run])[0]
    if result.get("pass") != expected:
        return [f"{role}: {arm}'s pass is not the one its results give"]
    return []
