#!/usr/bin/env python3
"""Derive each role's measured threshold and write ``roles/measured.json`` (milestone 10, D7).

Inputs: ``--results`` (``results.jsonl`` of ``measure_roles.py``, one or
more), ``--corpus`` (the ``<prefix>-manifest.json`` of a corpus record of
``tests/memory/test_mnemonic_corpus_live.py``, one per arm, its
``-results.jsonl`` beside it) and ``--arms`` (the bootstrap arms: the index
score of every arm). Nothing here calls a model.

**Per role and arm** (the first repetition's ``scored`` rows): ``n``,
``passes`` (label matches), ``score`` = passes / n; ``bars_ok`` — every
mechanical bar met on every row; ``critical`` — any critical failure;
``complete`` — a scored row for every case of the role (an error, a cap stop,
a skip or an interruption leaves the arm incomplete). The reference
(``requirements.json``) gives the yardstick from the same run: its score p and
the binomial standard error ``sqrt(p (1 - p) / n)``. An arm **passes** when it
is complete, meets every bar, has no critical failure and scores at least
``p - se``. A role without a complete reference is unmeasured: reported, not
written, so the resolver keeps blocking it.

**The second repetition** (``measure_roles.py --repeat-disagreements``: the
reference again, on the cases where an arm's label result differed from its
own) is recorded and never judged: pass, fail, every count, the yardstick and
the thresholds come from the first repetition alone, and a role's
``second_repetition`` gives, per arm and case answered twice, the first and
the second label result (``{arm: {case: {"first", "second"}}}``), for the
record of the run.

**Thresholds.** A ``maximise`` role gets ``threshold`` null and
``measured_only`` false: the resolver ranks only the arms that passed. A
``satisfice`` role orders its measured arms (complete, with an index score)
by that score; the threshold is the lowest index score at and above which
every measured arm passes. When an arm below it passes too — index and result
disagree — the role accepts measured models only (``measured_only`` true,
``threshold`` null); with no passing arm, ``threshold`` is null.

**Corpus roles.** A corpus run routes all three memory role keys to its arm:
``MNEMONIC`` takes every case of the record, ``MEMORY_EXTRACT`` its automatic
cases (the worker's extraction), ``MEMORY_MERGE`` its automatic cases (decided
through ``MODEL_MEMORY_MERGE``) and the merge canary (``refused`` is
healthy). A row's label match is verdict ``pass``, its critical failure
verdict ``critical_failure``, its bars the model called and no operation left
pending. A dry record is refused.

**Hashes.** Every row of a role must carry one ``case_set_sha256`` and one
``prompt_sha256``, equal to today's — the committed ``requests.json`` of a
harness role; for the corpus roles ``incidents.json`` and the mnemonic or
extraction prompt — or the role is refused: a measurement of other prompts or
cases is not a measurement of these. ``check_measured`` is what the test runs
on the committed file: S2's reader accepts it, its hashes are today's, and its
passes and thresholds are the ones these rules derive from its own results.

    python scripts/derive_thresholds.py --arms ARMS.json --results OUT/results.jsonl \\
        --corpus REC/2026-10-03-mnemonic-corpus-k3-manifest.json ... [--write]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measurement_common as common  # noqa: E402

WRITTEN_BY = "engine/scripts/derive_thresholds.py"
CORPUS_MAP = {"MNEMONIC": "all", "MEMORY_EXTRACT": "automatic", "MEMORY_MERGE": "automatic"}


class Refused(RuntimeError):
    """The results cannot be turned into a measurement of today's prompts and cases."""


def corpus_hashes() -> dict:
    """Today's hashes of the corpus roles: the case set and each role's prompt."""
    common.importable()
    from tests.memory.corpus_live_env import EXTRACTION_PROMPT
    from zylch.memory.mnemonic import prompts

    cases = common.sha256_hex(common.CORPUS_CASES.read_bytes())
    mnemonic = common.sha256_hex(prompts.MNEMONIC_INSTRUCTIONS)
    extraction = common.sha256_hex(EXTRACTION_PROMPT)
    prompt = {"MNEMONIC": mnemonic, "MEMORY_EXTRACT": extraction, "MEMORY_MERGE": mnemonic}
    return {role: (cases, prompt[role]) for role in common.CORPUS_ROLES}


def current_hashes(role: str) -> tuple[str, str]:
    """``(case_set_sha256, prompt_sha256)`` of ``role`` today."""
    if role in common.CORPUS_ROLES:
        return corpus_hashes()[role]
    committed = common.load_requests(role)
    if committed["case_set_sha256"] != common.case_set_sha256(role):
        raise Refused(f"{role}: requests.json was captured from another cases.json")
    return committed["case_set_sha256"], committed["prompt_sha256"]


def index_scores(arms_document: dict) -> dict:
    """``{(model, index): score}`` from the bootstrap arms."""
    out = {}
    for body in arms_document["roles"].values():
        for arm in body["arms"]:
            if arm.get("score") is not None:
                out[(arm["id"], body["index"])] = arm["score"]
    return out


def corpus_rows(manifest_path: Path, scores: dict, rules: dict) -> list[dict]:
    """A corpus record as measure_roles-like rows of the three memory roles."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("mode") != "live":
        raise Refused(f"{manifest_path.name}: a {manifest.get('mode')} record measures no model")
    prefix = manifest_path.name.removesuffix("-manifest.json")
    lines = (manifest_path.parent / f"{prefix}-results.jsonl").read_text(encoding="utf-8")
    records = [json.loads(line) for line in lines.splitlines() if line.strip()]
    arm = manifest.get("arm_id") or manifest["model"]
    out = []
    for role, scope in CORPUS_MAP.items():
        prompt = manifest["prompt_version_sha256"]
        if role == "MEMORY_EXTRACT":
            prompt = manifest["extraction_prompt_sha256"]
        common_fields = {
            "role": role,
            "arm": arm,
            "repetition": 1,
            "status": "scored",
            "arm_score": scores.get((arm, rules[role]["index"])),
            "case_set_sha256": manifest.get("case_set_sha256"),
            "prompt_sha256": prompt,
            "snapshot_version": manifest.get("snapshot_version"),
        }
        for record in records:
            if scope == "automatic" and record["caller_class"] != "automatic_observation":
                continue
            pending = any(o.get("state") == "pending" for o in record.get("operations") or [])
            scoring = {
                "label_match": record["verdict"] == "pass",
                "critical": record["verdict"] == "critical_failure",
                "bars_ok": record.get("calls", 0) >= 1 and not pending,
            }
            out.append({**common_fields, "case_id": record["case_id"], "scoring": scoring})
        canary = (manifest.get("checks") or {}).get("canary")
        if role == "MEMORY_MERGE" and canary:
            healthy = canary.get("verdict") == "refused"
            scoring = {"label_match": healthy, "critical": not healthy, "bars_ok": True}
            out.append({**common_fields, "case_id": "canary", "scoring": scoring})
    return out


def reference_yardstick(result: dict) -> tuple[Fraction, float]:
    """The reference's score and its binomial standard error, from its own counts."""
    p = Fraction(result["passes"], result["n"])
    return p, math.sqrt(float(p * (1 - p)) / result["n"])


def judged(result: dict, reference: dict) -> tuple[bool, list[str]]:
    """Whether an arm's result passes against the reference (module docstring)."""
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


def threshold_of(rule: str, results: dict) -> tuple[float | None, bool]:
    """``(threshold, measured_only)`` of a role from its judged results (module docstring)."""
    if rule == "maximise":
        return None, False
    measured = sorted(
        (r["index_score"], r["pass"])
        for r in results.values()
        if r["complete"] and r["index_score"] is not None
    )
    passing = [score for score, passed in measured if passed]
    if not passing:
        return None, False
    failing = [score for score, passed in measured if not passed]
    threshold = min((s for s in passing if all(f < s for f in failing)), default=None)
    if threshold is None or any(s < threshold for s in passing):
        return None, True
    return threshold, False


def second_answers(rows: list[dict]) -> dict:
    """``{case_id: {"first", "second"}}``: the label results of each case scored twice."""
    seen: dict = {}
    for row in rows:
        if row["status"] == "scored":
            match = bool(row["scoring"]["label_match"])
            seen.setdefault(row["case_id"], {})[row.get("repetition", 1)] = match
    return {
        case: {"first": both.get(1), "second": both[2]}
        for case, both in sorted(seen.items())
        if 2 in both
    }


def role_entry(role: str, rows: list[dict], cases: list[str], rule: dict, reference: str) -> dict:
    """One role of measured.json from its rows, or Refused."""
    hashes = {(r["case_set_sha256"], r["prompt_sha256"]) for r in rows}
    if len(hashes) != 1:
        raise Refused(f"{role}: rows from {len(hashes)} different case sets or prompts")
    if hashes != {current_hashes(role)}:
        raise Refused(f"{role}: measured on other cases or prompts than today's")
    results, second = {}, {}
    for arm in sorted({r["arm"] for r in rows}):
        mine = [r for r in rows if r["arm"] == arm]
        # Judged on the first repetition alone (module docstring): a second
        # answer is recorded in second_repetition and changes no pass or fail.
        first = [r for r in mine if r.get("repetition", 1) == 1]
        scored = [r for r in first if r["status"] == "scored"]
        complete = all(r["status"] == "scored" for r in first) and {
            r["case_id"] for r in first
        } >= set(cases)
        again = second_answers(mine)
        if again:
            second[arm] = again
        results[arm] = {
            "n": len(scored),
            "passes": sum(bool(r["scoring"]["label_match"]) for r in scored),
            "bars_ok": all(r["scoring"]["bars_ok"] for r in scored),
            "critical": any(r["scoring"]["critical"] for r in scored),
            "complete": complete,
            "index_score": next(
                (r["arm_score"] for r in mine if r.get("arm_score") is not None), None
            ),
        }
        results[arm]["score"] = round(results[arm]["passes"] / max(1, results[arm]["n"]), 6)
    if reference not in results or not results[reference]["complete"]:
        raise Refused(f"{role}: the reference {reference} is not completely measured")
    for result in results.values():
        result["pass"], result["reasons"] = judged(result, results[reference])
    threshold, measured_only = threshold_of(rule["rule"], results)
    p, se = reference_yardstick(results[reference])
    versions = sorted({str(r.get("snapshot_version")) for r in rows})
    return {
        "rule": rule["rule"],
        "index": rule["index"],
        "threshold": threshold,
        "measured_only": measured_only,
        "results": results,
        "reference": {"id": reference, "score": round(float(p), 6), "se": round(se, 6)},
        "second_repetition": second,
        "case_set_sha256": rows[0]["case_set_sha256"],
        "prompt_sha256": rows[0]["prompt_sha256"],
        "snapshot_version": versions[0] if len(versions) == 1 else versions,
    }


def derive(rows: list[dict], *, roles: dict | None = None) -> tuple[dict, dict]:
    """``(measured.json document, {role: why it is unmeasured})`` from every row."""
    requirements = common.requirements()
    rules, reference = roles or requirements["roles"], requirements["reference"]
    out, unmeasured = {}, {}
    rows = common.latest_rows(rows)  # a cell re-run after a resume counts once
    for role in [r for r in common.PRIORITY if r in rules]:
        mine = [r for r in rows if r["role"] == role]
        if not mine:
            unmeasured[role] = "no results"
            continue
        if role in common.CORPUS_ROLES:
            cases = sorted({r["case_id"] for r in mine})
        else:
            cases = [case["id"] for case in common.load_document(role)["cases"]]
        try:
            out[role] = role_entry(role, mine, cases, rules[role], reference)
        except Refused as refused:
            unmeasured[role] = str(refused)
    return {"schema": 1, "written_by": WRITTEN_BY, "roles": out}, unmeasured


def check_measured(document: dict) -> list[str]:
    """Why ``document`` is not a measured.json this script would write today (empty: it is)."""
    common.importable()
    from zylch.llm.roles import resolver

    requirements = common.requirements()
    try:
        resolver.validate_measured(document, requirements["roles"])
    except resolver.ConfigError as err:
        return [str(err)]
    problems = []
    for role, body in document["roles"].items():
        try:
            today = current_hashes(role)
        except (Refused, OSError) as err:
            problems.append(f"{role}: {err}")
            continue
        if (body["case_set_sha256"], body["prompt_sha256"]) != today:
            problems.append(f"{role}: its hashes are not today's case set and prompt")
        reference = (body.get("reference") or {}).get("id")
        results = body["results"]
        if reference not in results:
            problems.append(f"{role}: no reference result")
            continue
        for arm, result in results.items():
            if result.get("pass") != judged(result, results[reference])[0]:
                problems.append(f"{role}: {arm}'s pass is not the one its results give")
        rule = requirements["roles"][role]["rule"]
        if (body["threshold"], body["measured_only"]) != threshold_of(rule, results):
            problems.append(f"{role}: threshold not derived from its results")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write roles/measured.json from the results.")
    parser.add_argument("--arms", type=Path, required=True)
    parser.add_argument("--results", type=Path, nargs="*", default=[])
    parser.add_argument("--corpus", type=Path, nargs="*", default=[])
    parser.add_argument("--write", action="store_true", help=f"write {common.MEASURED.name}")
    args = parser.parse_args(argv)
    rows = []
    for path in args.results:
        rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rules = common.requirements()["roles"]
    scores = index_scores(json.loads(args.arms.read_text(encoding="utf-8")))
    try:
        for manifest in args.corpus:
            rows += corpus_rows(manifest, scores, rules)
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    document, unmeasured = derive(rows)
    for role, why in unmeasured.items():
        print(f"unmeasured, blocks the table: {role}: {why}")
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    if args.write:
        common.MEASURED.write_text(text, encoding="utf-8")
        print(f"wrote {common.MEASURED}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
