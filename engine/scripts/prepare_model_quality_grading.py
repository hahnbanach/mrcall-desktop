"""Build blinded offline grading packs from reviewed evaluation journals.

Install the engine's evaluation extra first: pip install -e 'engine[evaluation]'.
Run with --config CONFIG --freeze-approved --freeze-record FREEZE_RECORD.
Paths in CONFIG are explicit local paths; no dataset or profile path is built in.

Config requires sources=[{manifest, results}], rubric and output. Sources are
ordered original then recovery. Each source may supply a bijective cell_map;
otherwise recovery cells use original_cell_id/recovery_of. Optional splits,
stages, case_metadata, paired_variants, legacy_labels, salt_path and seed support
separate cohorts, paired blind arms, and stable incremental refreshes. The parser
is the adjacent repository-relative model_quality_parsers.py, never arbitrary
code from the config. Outputs and identity/operational maps are private files.
"""

import argparse
import collections
import hashlib
import json
import os
import random
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    path.chmod(0o600)


def task_contract(case: dict, raw: dict, rubric: dict) -> list[str]:
    content = raw.get("content", [])
    if not isinstance(content, list):
        return ["Response content must be an array"]
    errors = []
    if any(not isinstance(block, dict) for block in content):
        errors.append("Response content contains a non-object block")
    blocks = [
        b
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "task_decision"
    ]
    if len(blocks) != 1:
        return errors + ["Expected exactly one task_decision"]
    tool = next((x for x in case["request"].get("tools", []) if x["name"] == "task_decision"), None)
    if not tool:
        return ["Captured task_decision schema missing"]
    data = blocks[0].get("input", {})
    errors.extend(e.message for e in Draft202012Validator(tool["input_schema"]).iter_errors(data))
    if not isinstance(data, dict):
        return errors
    action = data.get("task_action")
    target = data.get("target_task_id")
    if target is not None and not isinstance(target, str):
        return errors + ["Target task identifier must be a string"]
    if action in ("update", "close"):
        if not target:
            errors.append("Missing target_task_id for update/close")
        # Independently check actual supplied task context, never accept arbitrary target.
        user = json.dumps(case["request"].get("messages", []), ensure_ascii=False)
        if target and target not in user:
            errors.append("Target task identifier absent from captured input")
        allowed = rubric.get("existing_task_ids")
        if allowed is not None and target not in allowed:
            errors.append("Target task identifier absent from preregistered existing tasks")
    # An optional target on NONE is redundant but schema-permitted and does not mutate.
    return errors


def mask_content(raw: dict, identifiers: set[str]) -> list[dict]:
    # Keep only model-authored semantic text/tool arguments; never transport IDs/usage.
    out = []
    content = raw.get("content", [])
    if not isinstance(content, list):
        content = [content]
        out.append({"type": "malformed_content", "expected": "array"})
    for b in content:
        if not isinstance(b, dict):
            out.append({"type": "malformed_content_block", "value": b})
            continue
        if b.get("type") == "text":
            out.append({"type": "text", "text": b.get("text", "")})
        elif b.get("type") == "tool_use":
            out.append({"type": "tool_use", "name": b.get("name"), "input": b.get("input")})
        else:
            out.append({"type": b.get("type"), "omitted_transport_block": True})

    def clean(x: Any) -> Any:
        if isinstance(x, str):
            for ident in sorted(identifiers, key=len, reverse=True):
                if ident:
                    x = x.replace(ident, "[MODEL_OR_PROVIDER]")
            return x
        if isinstance(x, list):
            return [clean(y) for y in x]
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        return x

    return clean(out)


def prepare(
    config: dict, freeze_record: Path, parser: Callable, provenance: dict | None = None
) -> dict:
    if config.get("paired_variants") and config.get("legacy_labels"):
        raise ValueError("Paired variants cannot use origin-only legacy labels")
    output = Path(config["output"])
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    saltpath = Path(config.get("salt_path", output / "blind-salt"))
    if not saltpath.exists():
        fd = os.open(saltpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(os.urandom(32).hex())
    salt = saltpath.read_text()
    rubrics = json.loads(Path(config["rubric"]).read_text())
    metadata = {}
    if config.get("case_metadata"):
        data = json.loads(Path(config["case_metadata"]).read_text())
        metadata = {c["id"]: c for c in (data["cases"] if isinstance(data, dict) else data)}
    cells = {}
    events = collections.defaultdict(list)
    cases = {}
    audit = []
    identifiers = set()
    source_hashes = []
    for source_index, src in enumerate(config["sources"]):
        manifest = json.loads(Path(src["manifest"]).read_text())
        local = {c["id"]: {**metadata.get(c["id"], {}), **c} for c in manifest["cases"]}
        source_hashes.append({"manifest_sha256": digest(manifest), "source_index": source_index})
        mapping = src.get("cell_map", {})
        arm = src.get("arm", manifest.get("arm", "baseline"))
        if len(local) != len(manifest["cases"]):
            raise ValueError("Duplicate case IDs in source manifest")
        local_ids = [cell["id"] for cell in manifest["cells"]]
        if len(set(local_ids)) != len(local_ids) or not set(mapping) <= set(local_ids):
            raise ValueError("Duplicate cells or unknown recovery mapping key")
        origins = [
            mapping.get(c["id"], c.get("original_cell_id", c.get("recovery_of", c["id"])))
            for c in manifest["cells"]
        ]
        if len(set(origins)) != len(origins):
            raise ValueError("Recovery mapping must be bijective within each source")
        for cell in manifest["cells"]:
            case = local[cell["case_id"]]
            if config.get("splits") and case.get("split") not in config["splits"]:
                continue
            if config.get("stages") and case.get("stage") not in config["stages"]:
                continue
            origin = mapping.get(
                cell["id"], cell.get("original_cell_id", cell.get("recovery_of", cell["id"]))
            )
            key = arm + "::" + origin
            clock = case.get("datetime_line", manifest.get("as_of"))
            identity = (cell["case_id"], cell["model"], digest(case["request"]), clock)
            if origin != cell["id"] and key not in cells:
                raise ValueError("Recovery mapping has no original cell in preceding sources")
            if key in cells and cells[key]["identity"] != identity:
                raise ValueError("Recovery cell identity/request mismatch")
            if (
                case["id"] in cases
                and digest(cases[case["id"]]["request"]) != digest(case["request"])
                and not config.get("paired_variants")
            ):
                raise ValueError("Different arms require explicit paired_variants mode")
            cases[case["id"]] = case
            cells.setdefault(
                key,
                {"cell": cell, "case": case, "arm": arm, "identity": identity, "origin": origin},
            )
            identifiers.add(cell["model"])
        journal = Path(src["results"]) / "attempts.jsonl"
        rawlines = journal.read_text().splitlines() if journal.exists() else []
        source_hashes[-1]["journal_sha256"] = hashlib.sha256(
            "\n".join(rawlines).encode()
        ).hexdigest()
        source_hashes[-1]["journal_missing"] = not journal.exists()
        for number, line in enumerate(rawlines, 1):
            row = json.loads(line)
            cid = row.get("cell_id")
            origin = mapping.get(cid, cid)
            # Map metadata aliases even for journal rows that carry only local ID.
            match = next((c for c in manifest["cells"] if c["id"] == cid), None)
            if match:
                origin = mapping.get(
                    cid, match.get("original_cell_id", match.get("recovery_of", cid))
                )
            key = arm + "::" + str(origin)
            record = {
                "source_index": source_index,
                "line": number,
                "original_key": key,
                "record": row,
            }
            audit.append(record)
            if match is None and cid is not None:
                raise ValueError("Journal references a cell absent from its source manifest")
            if key in cells:
                if (
                    row.get("case_id", cells[key]["cell"]["case_id"])
                    != cells[key]["cell"]["case_id"]
                ):
                    raise ValueError("Journal case does not match cell manifest")
                if row.get("model", cells[key]["cell"]["model"]) != cells[key]["cell"]["model"]:
                    raise ValueError("Journal model does not match cell manifest")
                events[key].append(record)
            policy = row.get("http", {}).get("provider_policy", {})
            for provider in policy.get("only", []):
                identifiers.add(provider)
    masked = []
    blindmap = {}
    inputs_by_label = {}
    for key, meta in cells.items():
        case = meta["case"]
        rubric = rubrics.get(case["id"])
        if rubric is None:
            raise ValueError("Missing preregistered rubric")
        responses = [
            e
            for e in events[key]
            if e["record"].get("event") == "result"
            and isinstance(e["record"].get("response"), dict)
        ]
        selected = responses[0] if responses else None
        raw = selected["record"]["response"] if selected else None
        label_key = meta["origin"] if config.get("legacy_labels") else key
        label = (
            "out-"
            + hashlib.sha256((salt + label_key).encode()).hexdigest()[
                : 12 if config.get("legacy_labels") else 16
            ]
        )
        if label in blindmap:
            raise ValueError("Blind label collision; no identity may be overwritten")
        if config.get("paired_variants"):
            inputs_by_label[label] = {
                "request": case["request"],
                "source_thread": case.get("source_thread"),
                "thread_history_section": case.get("thread_history_section"),
            }
        blindmap[label] = {
            "original_key": key,
            "model": meta["cell"]["model"],
            "case_id": case["id"],
            "arm": meta["arm"],
            "semantic_source": {"source_index": selected["source_index"], "line": selected["line"]}
            if selected
            else None,
            "actual_response_count": len(responses),
            "journal_event_count": len(events[key]),
        }
        accepted = False
        violations = []
        if raw is not None:
            accepted = bool(
                parser(case["stage"], raw, case.get("thread_history_section", "")).get("accepted")
            )
            if case["stage"] == "task.detect":
                violations = task_contract(case, raw, rubric)
        thread = (
            case.get("opaque_thread_id") or case.get("business_cluster") or case.get("thread_id")
        )
        expected_stop = "tool_use" if case["stage"] == "task.detect" else "end_turn"
        masked.append(
            {
                "label": label,
                "case_id": case["id"],
                "thread": thread,
                "stratum": case.get("stratum"),
                "stage": case["stage"],
                "availability": "model_response" if raw is not None else "no_model_response",
                "completion": bool(raw and raw.get("stop_reason") == expected_stop),
                "stop_reason": raw.get("stop_reason") if raw is not None else None,
                "production_parser_accepted": accepted,
                "contract_violations": violations,
                "content": mask_content(raw, identifiers) if raw is not None else None,
            }
        )
    # Balance within strata, keeping all roles/models/repeats for a thread together.
    rng = random.Random(config.get("seed", 20260915))
    strata = collections.defaultdict(set)
    thread_strata = {}
    for row in masked:
        thread = row["thread"]
        if not isinstance(thread, str) or not thread:
            raise ValueError("Every case requires a stable thread or business cluster")
        if thread in thread_strata and thread_strata[thread] != row["stratum"]:
            raise ValueError("A thread cannot belong to multiple strata")
        thread_strata[thread] = row["stratum"]
        strata[row["stratum"]].add(thread)
    groups = [set(), set(), set()]
    for stratum in sorted(strata, key=str):
        threads = sorted(strata[stratum])
        rng.shuffle(threads)
        for thread in threads:
            groups[min(range(3), key=lambda i: len(groups[i]))].add(thread)
    for i, threads in enumerate(groups):
        rows = [r for r in masked if r["thread"] in threads]
        rng.shuffle(rows)
        write(output / f"blind-group-{i + 1}.json", rows)
    if config.get("paired_variants"):
        write(output / "case-inputs-by-label.json", inputs_by_label)
    write(output / "blind-map.json", blindmap)
    write(output / "operational-audit.json", audit)
    write(
        output / "case-inputs.json",
        {
            k: {
                "request": v["request"],
                "source_thread": v.get("source_thread"),
                "thread_history_section": v.get("thread_history_section"),
                "as_of": v.get("as_of"),
            }
            for k, v in cases.items()
        },
    )
    write(output / "rubrics.json", {k: rubrics[k] for k in cases})
    summary = {
        "expected_cells": len(cells),
        "response_cells": sum(r["availability"] == "model_response" for r in masked),
        "missing_cells": sum(r["availability"] == "no_model_response" for r in masked),
        "thread_group_counts": [len(g) for g in groups],
        "operational_events": len(audit),
        "source_hashes": source_hashes,
        "parser_provenance": provenance or {},
        "candidate_freeze_sha256": hashlib.sha256(freeze_record.read_bytes()).hexdigest(),
        "selection_rule": "First actual response per original cell, including malformed/truncated; all attempts preserved in private operational audit.",
    }
    write(output / "preparation-manifest.json", summary)
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--freeze-approved", action="store_true")
    p.add_argument("--freeze-record", type=Path, required=True)
    args = p.parse_args()
    if not args.freeze_approved or not args.freeze_record.is_file():
        p.error(
            "Explicit root candidate-freeze approval artifact is required before reading results"
        )
    config = json.loads(args.config.read_text())
    module = runpy.run_path(str(Path(__file__).resolve().with_name("model_quality_parsers.py")))
    summary = prepare(config, args.freeze_record, module["parse"], module["parser_provenance"]())
    print(json.dumps({k: v for k, v in summary.items() if k not in ["source_hashes"]}))


if __name__ == "__main__":
    main()
