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
a skip, a denied key or an interruption leaves the arm incomplete). A cell
the provider refused before inference twice (or mid-turn, or once with the
run stopped before its second time) is a failed cell like any other: not
scored, the arm incomplete. **An incomplete arm is not a measurement**: it
is kept out of ``results`` and named under the role's ``incomplete``
(``{arm: why}``, each unscored case under its status, refusals named), so
the resolver's ``qualifies`` treats the model as unmeasured, as it treats a
model never measured, instead of as one that failed; thresholds derive from
complete arms only. The reference (``requirements.json``) gives the
yardstick from the same run: its score p and the binomial standard error
``sqrt(p (1 - p) / n)``. An arm **passes** when it is complete, meets every
bar, has no critical failure and scores at least ``p - se``. A role without
a complete reference is unmeasured: reported, not written, so the resolver
keeps blocking it.

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
on the committed file: S2's reader accepts it, its hashes are today's, no
result in it is incomplete, and its passes and thresholds are the ones these
rules derive from its own results.

**The plan** (``--plan PATH``, ``measurement_plan``): the committed inputs
of a derivation (runs, corpus records, arms, re-score, shape check) and its
exclusions, each a claim the code verifies. ``roles/measured.json`` is
derived from ``tests/fixtures/measurement/records/2026-10-11/plan.json``,
and ``test_measurement_plan`` checks it byte for byte.

**Runs** (``--run ID@COMMIT=PATH``, ``--corpus RUN=MANIFEST``,
``measurement_runs``): every arm is judged against the reference from its
own run, and each result names it (``judged_by``); the role's ``reference``
lists each run's yardstick. **The shaped request** (``--shape-check``,
``measurement_shape``): a row whose request, shaped as the run's commit and
snapshot shaped it, is not the one today's code and build snapshot send, is
no measurement of today's request (``stale_request``, the arm incomplete).

**Re-scoring** (``--rescore-from OLD_CASE_HASH ...``, ``measurement_rescore``):
rows recorded under an older case set, after a label edit, are scored again
on today's labels only where every request is still today's, byte for byte;
a case whose request changed is refused, and the document's ``rescored_from``
records the old and new hashes. ``--rescore`` scores every recorded answer
again, those of today's case set too, so a scorer fix reaches rows recorded
before it; ``--answered-at COMMIT ...`` names the commits the runs were made
on. ``--out`` writes the document elsewhere than
``roles/measured.json`` (a candidate for review).

    python scripts/derive_thresholds.py --arms ARMS.json --results OUT/results.jsonl \\
        --corpus REC/2026-10-03-mnemonic-corpus-k3-manifest.json ... [--write]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measurement_common as common  # noqa: E402
import measurement_runs as runs  # noqa: E402
from measurement_runs import (  # noqa: E402
    arm_result,
    judge_runs,
    reference_entry,
)
from measurement_runs import judged, reference_yardstick  # noqa: E402,F401 (model_table_*)

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


def fill_scores(rows: list[dict], scores: dict, rules: dict) -> list[dict]:
    """``rows`` with a missing ``arm_score`` taken from ``scores`` (``--arms``).

    An arms file written by hand for a re-measure may carry no score (S4b9:
    rerun 7's and rerun 8's entrants). A complete arm without an index score
    sits outside ``threshold_of``'s ladder, so a failing entrant scored above
    a passing one could not make the role ``measured_only``. A recorded score
    is never replaced.
    """
    out = []
    for row in rows:
        if row.get("arm_score") is None and row["role"] in rules:
            score = scores.get((row["arm"], rules[row["role"]]["index"]))
            if score is not None:
                row = {**row, "arm_score": score}
        out.append(row)
    return out


def corpus_rows(
    manifest_path: Path, scores: dict, rules: dict, records: list | None = None
) -> list[dict]:
    """A corpus record as measure_roles-like rows of the three memory roles.

    ``records`` replaces the record's own results: ``measurement_rescore``'s, the
    same answers judged again on today's labels, under today's case-set hash.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("mode") != "live":
        raise Refused(f"{manifest_path.name}: a {manifest.get('mode')} record measures no model")
    prefix = manifest_path.name.removesuffix("-manifest.json")
    if records is None:
        lines = (manifest_path.parent / f"{prefix}-results.jsonl").read_text(encoding="utf-8")
        records = [json.loads(line) for line in lines.splitlines() if line.strip()]
    else:
        manifest["case_set_sha256"] = corpus_hashes()["MNEMONIC"][0]
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
            "run_commit": manifest.get("engine_commit"),
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
    rows, superseded = runs.supersede_stale(rows, cases)
    second, incomplete, per_run = {}, {}, {}
    for run in sorted({r.get("run", "") for r in rows}):
        for arm in sorted({r["arm"] for r in rows if r.get("run", "") == run}):
            mine = [r for r in rows if r["arm"] == arm and r.get("run", "") == run]
            again = second_answers(mine)
            if again:
                second.setdefault(arm, {}).update(again)
            result, why = arm_result(mine, cases)
            if arm == reference and runs.bar_misses(mine):
                result["bar_misses"] = runs.bar_misses(mine)  # credited to its yardstick
            if why is None:
                named = {"judged_by": run} if run else {}  # the unnamed run: the daily job's shape
                per_run.setdefault(run, {})[arm] = {**result, **named}
            else:  # cut short: no measurement of this model (module docstring)
                incomplete[arm] = f"run {run}: {why}" if run else why
    yardsticks = {
        run: runs.yardstick_of(arms[reference])
        for run, arms in per_run.items()
        if reference in arms
    }
    if not yardsticks:
        why = incomplete.get(reference, "no results")
        raise Refused(f"{role}: the reference {reference} is not completely measured: {why}")
    results = judge_runs(per_run, yardsticks, incomplete)
    threshold, measured_only = threshold_of(rule["rule"], results)
    versions = sorted({str(r.get("snapshot_version")) for r in rows})
    entry = {"superseded_stale": superseded} if superseded else {}  # none: the daily job's shape
    return {
        **entry,
        "rule": rule["rule"],
        "index": rule["index"],
        "threshold": threshold,
        "measured_only": measured_only,
        "results": results,
        "reference": reference_entry(reference, yardsticks),
        "second_repetition": second,
        "incomplete": incomplete,
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
        own = results[reference]  # each run's yardstick is the reference's own result there
        own_runs = own.get("runs") or {own.get("judged_by", ""): own}
        yardsticks = {run: runs.yardstick_of(result) for run, result in own_runs.items()}
        if body["reference"] != reference_entry(reference, yardsticks):
            problems.append(f"{role}: the reference's yardsticks are not its own results")
        for arm, result in results.items():
            if result.get("complete") is False:
                problems.append(f"{role}: {arm} is incomplete; it belongs under incomplete")
            problems += runs.pass_problems(role, arm, result, yardsticks)
        rule = requirements["roles"][role]["rule"]
        if (body["threshold"], body["measured_only"]) != threshold_of(rule, results):
            problems.append(f"{role}: threshold not derived from its results")
    return problems


def build(spec: dict) -> tuple[dict, dict]:
    """``(document, unmeasured)`` from a derivation spec (``measurement_plan``), or Refused."""
    import measurement_plan as plan
    import measurement_rescore as rescore
    import measurement_shape as shape

    def read(path: Path, **fields) -> list[dict]:
        lines = path.read_text().splitlines()
        return [{**json.loads(line), **fields} for line in lines if line.strip()]

    rows = [row for path in spec["results"] for row in read(path)]
    for run, commit, path in spec["runs"]:
        rows += read(path, run=run, run_commit=commit)
    try:
        rows, excluded = plan.apply_exclusions(
            rows, spec["exclusions"], lambda role: current_hashes(role)[1]
        )
    except plan.ExclusionRefused as err:
        raise Refused(str(err)) from err
    rules = common.requirements()["roles"]
    scores: dict = {}
    for path in spec["arms"]:  # a later file fills what an earlier one leaves unscored
        for key, value in index_scores(json.loads(path.read_text(encoding="utf-8"))).items():
            scores.setdefault(key, value)
    rows = fill_scores(rows, scores, rules)
    record: dict = {}
    old, every = set(spec["rescore_from"]), spec["rescore"]
    try:
        rows = rescore.rescore_rows(rows, old, record, every=every, answered_at=spec["answered_at"])
        for run, manifest in spec["corpus"]:
            found = rescore.corpus(manifest, old, scores, rules, record, every=every)
            rows += [{**row, "run": run} for row in found]
    except rescore.RescoreRefused as err:
        raise Refused(str(err)) from err
    stale: dict = {}
    if spec["shape_check"]:
        rows = shape.mark_stale(rows, stale)
    document, unmeasured = derive(rows)
    if record:
        document["rescored_from"] = record
    if spec["shape_check"]:
        document["shape_refused"] = stale
    if excluded:
        document["excluded"] = excluded
    return document, unmeasured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write roles/measured.json from the results.")
    add = parser.add_argument
    add("--plan", type=Path, help="a committed derivation plan (measurement_plan)")
    add("--arms", type=Path, nargs="+", default=[], help="index scores; the first to score wins")
    add("--results", type=Path, nargs="*", default=[])
    add("--run", action="append", default=[], metavar="ID@COMMIT=PATH", help="one run's rows")
    add("--corpus", nargs="*", default=[], metavar="[RUN=]MANIFEST")
    add("--exclusions", type=Path, help="exclusions file (measurement_plan)")
    add("--shape-check", action="store_true", help="refuse stale shaped requests")
    add("--write", action="store_true", help=f"write {common.MEASURED.name}")
    add("--out", type=Path, help="write the document here instead")
    add("--rescore-from", nargs="*", default=[], metavar="OLD_CASE_HASH")
    add("--rescore", action="store_true", help="score every recorded answer again")
    add("--answered-at", nargs="*", default=[], metavar="COMMIT")
    args = parser.parse_args(argv)
    import measurement_plan as plan

    if args.plan:
        spec = plan.from_plan(args.plan)
    else:
        exclusions = []
        if args.exclusions:
            exclusions = json.loads(args.exclusions.read_text(encoding="utf-8"))["exclusions"]
        spec = {
            "arms": args.arms,
            "results": args.results,
            "runs": [runs.parse_run(text) for text in args.run],
            "corpus": [runs.parse_corpus(text) for text in args.corpus],
            "rescore": args.rescore,
            "rescore_from": args.rescore_from,
            "answered_at": args.answered_at,
            "shape_check": args.shape_check,
            "exclusions": exclusions,
        }
    try:
        document, unmeasured = build(spec)
    except Refused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    for role, why in unmeasured.items():
        print(f"unmeasured, blocks the table: {role}: {why}")
    text = json.dumps(document, indent=1, sort_keys=True) + "\n"
    if args.write or args.out:
        target = args.out or common.MEASURED
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
