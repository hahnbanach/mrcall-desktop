"""Summarize blinded quality grades without substituting missing outputs.

Offline only: inputs are private grading packs and reviewed grade files.
The output contains aggregate counts, never source messages or output text.
"""

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path


def read(p):
    return json.loads(p.read_text())


def interval(values, seed=2174):
    # Conditional resampling of observed thread pairs, not population validity.
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    samples = sorted(sum(rng.choices(values, k=n)) / n for _ in range(10000))
    return [samples[249], samples[9749]]


def summarize(packdir, gradepaths, cohort, baseline):
    mapping = read(packdir / "blind-map.json")
    models = sorted({row["model"] for row in mapping.values()})
    if baseline not in models:
        raise ValueError("Baseline model absent from planned cells")
    packed = {}
    for path in sorted(packdir.glob("blind-group-*.json")):
        for row in read(path):
            if row["label"] in packed:
                raise ValueError("Duplicate packed label")
            packed[row["label"]] = row
    if set(mapping) != set(packed):
        raise ValueError("Blind map and packed labels must match exactly")
    rubrics = read(packdir / "rubrics.json") if (packdir / "rubrics.json").exists() else {}
    grades = {}
    for p in gradepaths:
        if not p.exists():
            continue
        for g in read(p):
            if any(
                g[k] not in ("acceptable", "unacceptable", "indeterminate")
                for k in ("semantic_verdict", "contract_verdict")
            ):
                raise ValueError("Invalid grade verdict")
            if g["label"] in grades and grades[g["label"]] != g:
                raise ValueError("Duplicate inconsistent grade " + g["label"])
            grades[g["label"]] = g
    if set(grades) - set(packed):
        raise ValueError("Unmatched grade label")
    bycell = {}
    counts = collections.defaultdict(collections.Counter)
    subgroups = collections.defaultdict(collections.Counter)
    for label, b in packed.items():
        m = mapping[label]
        g = grades.get(label)
        if m["case_id"] != b["case_id"] or (g and g["case_id"] != b["case_id"]):
            raise ValueError("Case identity mismatch")
        if g and b["content"] is None:
            raise ValueError("Grade without model response")
        if (m["case_id"], m["model"]) in bycell:
            raise ValueError("Duplicate case/model cell")
        key = (m["model"], b["stage"])
        s = counts[key]
        s["planned"] += 1
        returned = b["content"] is not None
        s["model_response"] += int(returned)
        s["completed"] += int(bool(b["completion"]))
        s["graded"] += int(g is not None)
        if g:
            s["semantic_" + g["semantic_verdict"]] += 1
            s["contract_" + g["contract_verdict"]] += 1
            s["usable_response_acceptable"] += int(
                b["completion"]
                and g["semantic_verdict"] == "acceptable"
                and g["contract_verdict"] == "acceptable"
            )
        elif returned:
            s["ungraded_responses"] += 1
        bycell[(m["case_id"], m["model"])] = (b, g)
        dimensions = {"stratum": b.get("stratum", "unknown")}
        if b["stage"] == "task.detect":
            dimensions["task_disposition"] = (
                rubrics.get(b["case_id"], {}).get("task_disposition_class") or "unspecified"
            )
        for dimension, value in dimensions.items():
            sub = subgroups[(m["model"], b["stage"], dimension, value)]
            sub["planned"] += 1
            sub["model_response"] += int(returned)
            sub["graded"] += int(g is not None)
            if g:
                sub["semantic_" + g["semantic_verdict"]] += 1
                sub["usable_response_acceptable"] += int(
                    b["completion"]
                    and g["semantic_verdict"] == "acceptable"
                    and g["contract_verdict"] == "acceptable"
                )
    pairs = []
    for stage in sorted({k[1] for k in counts}):
        for model in (m for m in models if m != baseline):
            c = collections.Counter()
            deltas = []
            for (cid, mo), (b, g) in bycell.items():
                if mo != model or b["stage"] != stage:
                    continue
                base = bycell.get((cid, baseline))
                if not base:
                    continue
                ob, og = base
                c["planned_pairs"] += 1
                if b["content"] is None or ob["content"] is None:
                    c["missing_response_pairs"] += 1
                    continue
                if not g or not og:
                    c["ungraded_response_pairs"] += 1
                    continue
                if "indeterminate" in (g["semantic_verdict"], og["semantic_verdict"]):
                    c["indeterminate_pairs"] += 1
                    continue
                c["determinate_graded_pairs"] += 1
                passed = g["semantic_verdict"] == "acceptable"
                opassed = og["semantic_verdict"] == "acceptable"
                c[
                    "semantic_"
                    + (
                        "win"
                        if passed and not opassed
                        else "loss"
                        if opassed and not passed
                        else "tie_pass"
                        if passed
                        else "tie_fail"
                    )
                ] += 1
                if "indeterminate" in (g["contract_verdict"], og["contract_verdict"]):
                    c["usable_response_indeterminate_contract_pairs"] += 1
                    continue
                c["usable_response_determinate_pairs"] += 1
                ep = passed and b["completion"] and g["contract_verdict"] == "acceptable"
                oe = opassed and ob["completion"] and og["contract_verdict"] == "acceptable"
                c[
                    "usable_response_"
                    + (
                        "win"
                        if ep and not oe
                        else "loss"
                        if oe and not ep
                        else "tie_pass"
                        if ep
                        else "tie_fail"
                    )
                ] += 1
                deltas.append(int(ep) - int(oe))
            pairs.append(
                {
                    "stage": stage,
                    "model": model,
                    "counts": dict(c),
                    "observed_paired_pass_difference": sum(deltas) / len(deltas)
                    if deltas
                    else None,
                    "conditional_bootstrap_95": interval(deltas),
                }
            )
    return {
        "cohort": cohort,
        "counts": [dict(model=k[0], stage=k[1], **v) for k, v in sorted(counts.items())],
        "pairs": pairs,
        "subgroups": [
            dict(model=k[0], stage=k[1], dimension=k[2], value=k[3], **v)
            for k, v in sorted(subgroups.items())
        ],
        "unmatched_grades": sorted(set(grades) - set(packed)),
        "notes": "Intervals resample observed determinate thread pairs and are conditional descriptive sensitivity, not population/equivalence guarantees. Missing and indeterminate pairs remain explicit. Usable response includes explicitly reviewed gateway recovery; it is not first-attempt availability.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--grades", type=Path, nargs="+", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(not p.is_file() for p in args.grades):
        parser.error("Every explicitly supplied grade file must exist")
    result = summarize(args.pack_dir, args.grades, args.cohort, args.baseline)
    inputs = (
        sorted(args.pack_dir.glob("blind-group-*.json"))
        + [args.pack_dir / "blind-map.json"]
        + args.grades
    )
    if (args.pack_dir / "rubrics.json").exists():
        inputs.append(args.pack_dir / "rubrics.json")
    result["input_sha256"] = [
        {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in inputs
    ]
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps({"cohort": args.cohort, "role_model_rows": len(result["counts"])}))


if __name__ == "__main__":
    main()
