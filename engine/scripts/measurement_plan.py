"""One derivation's inputs and exclusions, as committed data (milestone 10, S4b10).

S4b8 and S4b9 chose which recorded rows ``derive_thresholds`` read with an
uncommitted script, and it dropped every NARRATION row of the 2026-10-04 run
although only MiMo's request had changed. That selection decided deepseek's
NARRATION result by hand. Now the inputs are a committed **plan**
(``derive_thresholds.py --plan PATH``), and every row left out is accounted
for by a rule in code or by an **exclusion** whose claim the code verifies:

- ``runs``: ``{id, commit, results}``, one ``results.jsonl`` per run, read
  whole (``measurement_runs``);
- ``corpus``: ``{run, manifest}`` corpus records;
- ``arms``: the arms documents that give index scores, the first to score a
  model winning;
- ``rescore``, ``rescore_from``, ``shape_check``: as the flags of the same
  names;
- ``exclusions``: a file of ``{run, role, arms, kind, why}`` entries
  (``arms`` a list or ``"*"``). Each kind states a mechanical claim that
  ``apply_exclusions`` checks, refusing the derivation when it does not hold:

  - ``prompt``: every excluded row was measured on another prompt than
    today's (``prompt_sha256``), so it measures no request sent today. It is
    excluded rather than refused, because the role holds today's rows too;
  - ``denied``: the arm's cells in that run were cut short by a refusal
    before inference (HTTP 401, 402 or 403, nothing answered), and the arm
    answered every case of the role in ``superseded_by``.

Rows that are stale for the shape (``measurement_shape``) need no entry.
``measurement_runs.supersede_stale`` drops them when the same arm has a
complete, current-shape measurement of the role in another run. Otherwise
they leave the arm unmeasured.

Paths in a plan are relative to the plan's own directory. A path never
reaches the document: it records the run ids, commits and exclusions only.
"""

from __future__ import annotations

import json
from pathlib import Path

import measurement_common as common

KINDS = ("prompt", "denied")
DENIED = ("HTTP 401", "HTTP 402", "HTTP 403")


class ExclusionRefused(RuntimeError):
    """An exclusion whose claim the rows do not bear out."""


def from_plan(path: Path) -> dict:
    """The derivation spec of a committed plan (module docstring)."""
    plan = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    exclusions = []
    if plan.get("exclusions"):
        exclusions = json.loads((base / plan["exclusions"]).read_text(encoding="utf-8"))
        exclusions = exclusions["exclusions"]
    return {
        "arms": [base / p for p in plan["arms"]],
        "results": [],
        "runs": [(r["id"], r["commit"], base / r["results"]) for r in plan["runs"]],
        "corpus": [(c["run"], base / c["manifest"]) for c in plan.get("corpus", [])],
        "rescore": bool(plan.get("rescore")),
        "rescore_from": list(plan.get("rescore_from", [])),
        "answered_at": list(plan.get("answered_at", [])),
        "shape_check": bool(plan.get("shape_check")),
        "exclusions": exclusions,
    }


def _matches(row: dict, entry: dict) -> bool:
    arms = entry["arms"]
    return (
        row.get("run", "") == entry["run"]
        and row["role"] == entry["role"]
        and (arms == "*" or row["arm"] in arms)
    )


def _verify(entry: dict, mine: list[dict], rows: list[dict], today_prompt) -> None:
    where = f"exclusion {entry['run']}/{entry['role']}/{entry['arms']}"
    if entry.get("kind") not in KINDS:
        raise ExclusionRefused(f"{where}: kind must be one of {KINDS}")
    if not entry.get("why"):
        raise ExclusionRefused(f"{where}: no reason given")
    if not mine:
        raise ExclusionRefused(f"{where}: excludes no row")
    if entry["kind"] == "prompt":
        current = today_prompt(entry["role"])
        if any(r["prompt_sha256"] == current for r in mine):
            raise ExclusionRefused(f"{where}: a row was measured on today's prompt")
        return
    refused = [
        r for r in mine if r["status"] == "error" and any(s in str(r.get("error")) for s in DENIED)
    ]
    if not refused:
        raise ExclusionRefused(f"{where}: no cell refused before inference (401, 402, 403)")
    later = entry.get("superseded_by")
    cases = {c["id"] for c in common.load_document(entry["role"])["cases"]}
    for arm in {r["arm"] for r in mine}:
        answered = {
            r["case_id"]
            for r in rows
            if r.get("run", "") == later
            and r["role"] == entry["role"]
            and r["arm"] == arm
            and r["status"] == "scored"
        }
        if not later or not answered >= cases:
            raise ExclusionRefused(f"{where}: {arm} is not answered in full in run {later!r}")


def apply_exclusions(rows: list[dict], exclusions: list[dict], today_prompt) -> tuple:
    """``(rows kept, record)``: each entry verified, then its rows dropped."""
    record = []
    for entry in exclusions:
        mine = [r for r in rows if _matches(r, entry)]
        _verify(entry, mine, rows, today_prompt)
        record.append({**entry, "rows": len(mine)})
    kept = [r for r in rows if not any(_matches(r, e) for e in exclusions)]
    return kept, record
