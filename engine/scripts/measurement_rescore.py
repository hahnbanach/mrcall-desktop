"""Re-score recorded answers on today's labels, when only labels changed (milestone 10, S4b5).

The audit of the paid run fixed labels (``critical_on``, the corpus's
``must_preserve`` and ``allowed_actions``) and scorer bugs after the answers
were recorded. A label edit changes the case set's hash, and
``derive_thresholds`` refuses rows of another case set: a measurement of other
cases is not a measurement of these. Re-scoring is legitimate only because no
request changed — the model answered exactly the question it would be asked
today — so this path checks that, case by case, and records what it did.

``derive_thresholds.py --rescore-from OLD_CASE_HASH ...`` (``rescore_rows``,
``corpus``): rows whose ``case_set_sha256`` is one of the given hashes are
taken only when

- their ``prompt_sha256`` is today's, and
- the request of each case is today's request, byte for byte: for a harness
  role the entry of the ``requests.json`` committed with the old case set
  (found in git by its ``case_set_sha256``) against today's, ``request`` and
  ``capture_now`` compared as canonical JSON; for the corpus, each case of the
  ``incidents.json`` committed with the old hash against today's, everything
  but its ``expected`` labels.

A case whose request changed is refused: its rows are dropped (the arm is then
incomplete for it, never failed), and the case is named. The others are scored
again — ``measurement_scoring.score`` on the recorded answer, or
``corpus_live_record.judge`` on the recorded corpus row — and carry today's
hash. The measured document records each role's ``rescored_from``: the old and
new case-set hashes and the refused cases.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import measurement_common as common

CORPUS_REL = "tests/fixtures/mnemonic/incidents.json"


class RescoreRefused(RuntimeError):
    """Rows that cannot be scored again on today's labels (another prompt, no old file)."""


def committed_version(rel: str, wanted) -> bytes | None:
    """The newest committed bytes of ``engine/<rel>`` that ``wanted(bytes)`` accepts."""
    log = subprocess.run(
        ["git", "-C", str(common.ENGINE), "log", "--format=%H", "--", rel],
        capture_output=True,
        text=True,
        check=True,
    )
    for commit in log.stdout.split():
        shown = subprocess.run(
            ["git", "-C", str(common.ENGINE), "show", f"{commit}:./{rel}"], capture_output=True
        )
        if shown.returncode == 0 and wanted(shown.stdout):
            return shown.stdout
    return None


def _same_case_set(old_hash: str):
    def wanted(data: bytes) -> bool:
        try:
            return json.loads(data).get("case_set_sha256") == old_hash
        except ValueError:
            return False

    return wanted


def request_of(entry: dict) -> str:
    """What a model was asked for a case: its request and capture moment, canonical JSON."""
    return common.canonical({"request": entry["request"], "capture_now": entry.get("capture_now")})


def rescore_rows(rows: list[dict], old_hashes: set, record: dict) -> list[dict]:
    """``rows`` with those of an old case set scored again on today's labels (module docstring)."""
    import measurement_scoring as scoring

    out, by_role = [], {}
    for row in rows:
        if row.get("case_set_sha256") in old_hashes:
            by_role.setdefault(row["role"], []).append(row)
        else:
            out.append(row)
    for role, mine in by_role.items():
        today = common.load_requests(role)
        if {r["prompt_sha256"] for r in mine} != {today["prompt_sha256"]}:
            raise RescoreRefused(f"{role}: measured on another prompt; nothing to re-score")
        old_hash = mine[0]["case_set_sha256"]
        rel = f"tests/fixtures/measurement/{role}/requests.json"
        old_bytes = committed_version(rel, _same_case_set(old_hash))
        if old_bytes is None:
            raise RescoreRefused(f"{role}: no committed requests.json of case set {old_hash}")
        old = {e["case_id"]: request_of(e) for e in json.loads(old_bytes)["requests"]}
        new = {e["case_id"]: e for e in today["requests"]}
        changed = sorted(c for c in new if old.get(c) != request_of(new[c]))
        document = common.load_document(role)
        cases = {case["id"]: case for case in document["cases"]}
        for row in mine:
            case_id = row["case_id"]
            if case_id in changed or case_id not in cases:
                continue
            row = {**row, "case_set_sha256": today["case_set_sha256"]}
            if row["status"] == "scored":
                request = new[case_id]["request"]
                row["scoring"] = scoring.score(
                    role, cases[case_id], row["answer"], request, document
                )
            out.append(row)
        record[role] = {
            "case_set_sha256": {"from": old_hash, "to": today["case_set_sha256"]},
            "cases_refused": changed,
        }
    return out


def _inputs(case: dict) -> str:
    return common.canonical({k: v for k, v in case.items() if k != "expected"})


def corpus(manifest_path: Path, old_hashes: set, scores: dict, rules: dict, record: dict):
    """A corpus record's rows; judged again on today's labels when its case set is an old one."""
    import derive_thresholds as derive

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_hash = manifest.get("case_set_sha256")
    if old_hash not in old_hashes:
        return derive.corpus_rows(manifest_path, scores, rules)
    common.importable()
    from tests.memory.corpus_live_record import judge

    today = derive.corpus_hashes()
    prompts = (manifest["prompt_version_sha256"], manifest["extraction_prompt_sha256"])
    if prompts != (today["MNEMONIC"][1], today["MEMORY_EXTRACT"][1]):
        raise RescoreRefused(f"{manifest_path.name}: measured on another prompt")
    old_bytes = committed_version(
        CORPUS_REL, lambda data: hashlib.sha256(data).hexdigest() == old_hash
    )
    if old_bytes is None:
        raise RescoreRefused(f"{manifest_path.name}: no committed incidents.json {old_hash}")
    old = {c["id"]: _inputs(c) for c in json.loads(old_bytes)["cases"]}
    new = {c["id"]: c for c in json.loads(common.CORPUS_CASES.read_text("utf-8"))["cases"]}
    prefix = manifest_path.name.removesuffix("-manifest.json")
    lines = (manifest_path.parent / f"{prefix}-results.jsonl").read_text(encoding="utf-8")
    records, changed = [], set()
    for rec in (json.loads(line) for line in lines.splitlines() if line.strip()):
        spec = new.get(rec["case_id"])
        if spec is None or old.get(rec["case_id"]) != _inputs(spec):
            changed.add(rec["case_id"])
            continue
        ids = rec.get("seeded_ids") or {}
        seeded = SimpleNamespace(real=lambda fixture, ids=ids: ids.get(fixture, fixture))
        records.append({**rec, **judge(spec, rec, seeded)})
    for role in derive.CORPUS_MAP:
        record.setdefault(role, {})[manifest.get("arm_id") or manifest["model"]] = {
            "case_set_sha256": {"from": old_hash, "to": today["MNEMONIC"][0]},
            "cases_refused": sorted(changed),
        }
    return derive.corpus_rows(manifest_path, scores, rules, records)
