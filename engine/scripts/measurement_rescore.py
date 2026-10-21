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
  role the entry of each ``requests.json`` committed with the old case set
  and the prompt (found in git by their hashes) against today's, ``request`` and
  ``capture_now`` compared as canonical JSON; for the corpus, each case of the
  ``incidents.json`` committed with the old hash against today's, everything
  but its ``expected`` labels.

A case whose request changed is refused: its rows are dropped (the arm is then
incomplete for it, never failed), and the case is named. The others are scored
again — ``measurement_scoring.score`` on the recorded answer, or
``corpus_live_record.judge`` on the recorded corpus row — and carry today's
hash. The measured document records each role's ``rescored_from``: the old and
new case-set hashes, the refused cases and every verdict that changed.

``--rescore`` (``every``, S4b6) also scores again the rows already under
today's case set. A scorer or judge fix changes no hash, so without it a row
recorded before the fix keeps the verdict the old scorer gave (S4b5's re-score
left B1, C4 and C5 out of three roles that way). A harness role's rows are
compared, case by case, with **every** committed ``requests.json`` carrying
their case-set and prompt hashes: the row does not say which commit it was
answered on, so a case any of those versions asked differently is refused.
``--answered-at COMMIT ...`` names the commits the runs were made on (the
corpus manifests record theirs as ``engine_commit``, and the paid runs refused
any other HEAD); where one of them carries the rows' hashes, only those
versions count. TRAIN shows why: before e83d5279 its capture depended on the
hash seed, so an earlier version under the same hashes lists the same items
in another order, a request the 2026-10-04 run, made on 8b18ea69, never sent.
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


def request_of(entry: dict) -> str:
    """What a model was asked for a case: its request and capture moment, canonical JSON."""
    return common.canonical({"request": entry["request"], "capture_now": entry.get("capture_now")})


def committed_versions(rel: str, wanted) -> list[bytes]:
    """Every distinct committed version of ``engine/<rel>`` that ``wanted(bytes)`` accepts."""
    found: list[bytes] = []
    version = committed_version(rel, lambda data: wanted(data) and data not in found)
    while version is not None:
        found.append(version)
        version = committed_version(rel, lambda data: wanted(data) and data not in found)
    return found


def _same_hashes(case_hash: str, prompt_hash: str):
    def wanted(data: bytes) -> bool:
        try:
            document = json.loads(data)
        except ValueError:
            return False
        return (document.get("case_set_sha256"), document.get("prompt_sha256")) == (
            case_hash,
            prompt_hash,
        )

    return wanted


def version_at(commit: str, rel: str) -> bytes | None:
    """``engine/<rel>`` as committed at ``commit``, or None."""
    shown = subprocess.run(
        ["git", "-C", str(common.ENGINE), "show", f"{commit}:./{rel}"], capture_output=True
    )
    return shown.stdout if shown.returncode == 0 else None


def _changed_cases(
    role: str, case_hash: str, prompt_hash: str, today: dict, answered_at=()
) -> list[str]:
    """Today's cases whose request differs from a committed one these rows may have been
    asked: the version at each ``answered_at`` commit carrying their hashes, or, when
    none does, every committed version carrying them."""
    rel = f"tests/fixtures/measurement/{role}/requests.json"
    wanted = _same_hashes(case_hash, prompt_hash)
    pinned = [version_at(commit, rel) for commit in answered_at]
    versions = [data for data in pinned if data is not None and wanted(data)]
    if not versions:
        versions = committed_versions(rel, wanted)
    if not versions:
        raise RescoreRefused(f"{role}: no committed requests.json of case set {case_hash}")
    new = {e["case_id"]: request_of(e) for e in today["requests"]}
    changed = set()
    for data in versions:
        old = {e["case_id"]: request_of(e) for e in json.loads(data)["requests"]}
        changed |= {case for case in new if old.get(case) != new[case]}
    return sorted(changed)


def _verdict(scoring: dict) -> tuple:
    return tuple(bool(scoring.get(k)) for k in ("label_match", "critical", "bars_ok"))


def rescore_rows(
    rows: list[dict], old_hashes: set, record: dict, *, every: bool = False, answered_at=()
) -> list[dict]:
    """``rows`` scored again on today's labels and scorer (module docstring).

    Rows of an old case set (``old_hashes``) always; with ``every``, also the
    rows already under today's case set, so a scorer fix reaches them too.
    ``answered_at``: the commits the rows were answered on, when known.
    """
    import measurement_scoring as scoring

    out, groups = [], {}
    for row in rows:
        today_hash = common.load_requests(row["role"])["case_set_sha256"]
        case_hash = row.get("case_set_sha256")
        if case_hash in old_hashes or (every and case_hash == today_hash):
            key = (row["role"], case_hash, row["prompt_sha256"], row.get("run_commit"))
            groups.setdefault(key, []).append(row)
        else:
            out.append(row)
    for (role, case_hash, prompt_hash, commit), mine in groups.items():
        today = common.load_requests(role)
        if prompt_hash != today["prompt_sha256"]:
            raise RescoreRefused(f"{role}: measured on another prompt; nothing to re-score")
        pins = [commit] if commit else answered_at  # a run names its own commit
        changed = _changed_cases(role, case_hash, prompt_hash, today, pins)
        new = {e["case_id"]: e for e in today["requests"]}
        document = common.load_document(role)
        cases = {case["id"]: case for case in document["cases"]}
        verdicts = []
        for row in mine:
            case_id = row["case_id"]
            if case_id in changed or case_id not in cases:
                continue
            row = {**row, "case_set_sha256": today["case_set_sha256"]}
            if row["status"] == "scored":
                request = new[case_id]["request"]
                fresh = scoring.score(role, cases[case_id], row["answer"], request, document)
                if _verdict(fresh) != _verdict(row["scoring"]):
                    verdicts.append(f"{row['arm']} {case_id} r{row.get('repetition', 1)}")
                row["scoring"] = fresh
            out.append(row)
        entry = record.setdefault(role, {"cases_refused": [], "verdicts_changed": []})
        entry["case_set_sha256"] = {"from": case_hash, "to": today["case_set_sha256"]}
        entry["cases_refused"] = sorted(set(entry["cases_refused"]) | set(changed))
        entry["verdicts_changed"] = sorted(entry["verdicts_changed"] + verdicts)
    return out


def _inputs(case: dict) -> str:
    return common.canonical({k: v for k, v in case.items() if k != "expected"})


def corpus(
    manifest_path: Path,
    old_hashes: set,
    scores: dict,
    rules: dict,
    record: dict,
    *,
    every: bool = False,
):
    """A corpus record's rows; judged again on today's labels when its case set is an old
    one, or with ``every`` also when it is today's (a judge fix reaches it too)."""
    import derive_thresholds as derive

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_hash = manifest.get("case_set_sha256")
    today = derive.corpus_hashes()
    current = every and old_hash == today["MNEMONIC"][0]
    if old_hash not in old_hashes and not current:
        return derive.corpus_rows(manifest_path, scores, rules)
    common.importable()
    from tests.memory.corpus_live_record import judge

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
    records, changed, verdicts = [], set(), []
    for rec in (json.loads(line) for line in lines.splitlines() if line.strip()):
        spec = new.get(rec["case_id"])
        if spec is None or old.get(rec["case_id"]) != _inputs(spec):
            changed.add(rec["case_id"])
            continue
        ids = rec.get("seeded_ids") or {}
        seeded = SimpleNamespace(real=lambda fixture, ids=ids: ids.get(fixture, fixture))
        fresh = judge(spec, rec, seeded)
        if fresh["verdict"] != rec.get("verdict"):
            verdicts.append(f"{rec['case_id']}: {rec.get('verdict')} -> {fresh['verdict']}")
        records.append({**rec, **fresh})
    for role in derive.CORPUS_MAP:
        record.setdefault(role, {})[manifest.get("arm_id") or manifest["model"]] = {
            "case_set_sha256": {"from": old_hash, "to": today["MNEMONIC"][0]},
            "cases_refused": sorted(changed),
            "verdicts_changed": sorted(verdicts),
        }
    return derive.corpus_rows(manifest_path, scores, rules, records)
