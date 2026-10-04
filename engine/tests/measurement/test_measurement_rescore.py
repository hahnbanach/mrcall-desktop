"""``measurement_rescore``: recorded answers scored again on today's labels, only where no request changed.

- SYNC_ANALYSIS rows of the case set committed before the audit's label edit
  (sync_analysis-11's ``critical_on``) are scored again and carry today's
  hash; the old and new hashes are recorded;
- a case whose request differs from the one committed with the old case set
  is refused: its rows dropped and the case named;
- a corpus record is judged again on today's ``incidents.json`` (REVIEW now
  allowed where the prompt prescribes it), a case whose input changed refused.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import derive_thresholds as derive  # noqa: E402
import measurement_common as common  # noqa: E402
import measurement_rescore as rescore  # noqa: E402

ROLE = "SYNC_ANALYSIS"
K3 = "moonshotai/kimi-k3"
REL = f"tests/fixtures/measurement/{ROLE}/requests.json"


def old_requests() -> dict:
    """The committed SYNC_ANALYSIS requests.json of the case set before today's."""
    today = common.load_requests(ROLE)["case_set_sha256"]
    data = rescore.committed_version(REL, lambda b: json.loads(b)["case_set_sha256"] != today)
    assert data is not None, "no earlier committed case set"
    return json.loads(data)


def rows(old: dict) -> list[dict]:
    """K3 answering every case 'nothing to do' under the old case set's hash."""
    answer = {
        "calls": [{"name": "classify_thread", "input": {"summary": "ok", "open": False}}],
        "text": "",
        "stop_reason": "tool_use",
    }
    return [
        {
            "role": ROLE,
            "arm": K3,
            "case_id": entry["case_id"],
            "repetition": 1,
            "status": "scored",
            "answer": answer,
            "scoring": {"label_match": False, "critical": True, "bars_ok": True},
            "case_set_sha256": old["case_set_sha256"],
            "prompt_sha256": old["prompt_sha256"],
        }
        for entry in old["requests"]
    ]


def test_rows_of_an_old_case_set_are_scored_again_when_no_request_changed():
    old, record = old_requests(), {}
    out = rescore.rescore_rows(rows(old), {old["case_set_sha256"]}, record)
    today = common.load_requests(ROLE)["case_set_sha256"]
    assert len(out) == len(old["requests"]) and {r["case_set_sha256"] for r in out} == {today}
    by_case = {r["case_id"]: r["scoring"] for r in out}
    assert by_case["sync_analysis-11"]["critical"] is False  # today's critical_on
    assert by_case["sync_analysis-01"]["critical"] is True
    assert record[ROLE] == {
        "case_set_sha256": {"from": old["case_set_sha256"], "to": today},
        "cases_refused": [],
    }


def test_a_case_whose_request_changed_is_refused(monkeypatch):
    old, record = old_requests(), {}
    changed = copy.deepcopy(old)
    changed["requests"][0]["request"]["messages"][0]["content"] += " (another question)"
    monkeypatch.setattr(rescore, "committed_version", lambda rel, wanted: json.dumps(changed))
    out = rescore.rescore_rows(rows(old), {old["case_set_sha256"]}, record)
    first = old["requests"][0]["case_id"]
    assert first not in {r["case_id"] for r in out} and len(out) == len(old["requests"]) - 1
    assert record[ROLE]["cases_refused"] == [first]


def test_rows_of_another_prompt_are_refused():
    old = old_requests()
    stale = [{**r, "prompt_sha256": "0" * 64} for r in rows(old)]
    with pytest.raises(rescore.RescoreRefused, match="another prompt"):
        rescore.rescore_rows(stale, {old["case_set_sha256"]}, {})


def test_a_corpus_record_is_judged_again_and_a_changed_case_refused(tmp_path, monkeypatch):
    today = derive.corpus_hashes()
    incidents = json.loads(common.CORPUS_CASES.read_text("utf-8"))
    old = copy.deepcopy(incidents)
    for case in old["cases"]:
        if case["id"] == "global_opening_hours":
            case["original_observation"] += " (edited)"
    monkeypatch.setattr(rescore, "committed_version", lambda rel, wanted: json.dumps(old).encode())
    manifest = {
        "mode": "live",
        "arm_id": K3,
        "model": K3,
        "case_set_sha256": "a" * 64,
        "prompt_version_sha256": today["MNEMONIC"][1],
        "extraction_prompt_sha256": today["MEMORY_EXTRACT"][1],
        "snapshot_version": "snap",
    }
    review = [{"outcome": "review_needed", "reason": "", "parent_event_id": None, "state": "done"}]
    record = {"committed_ids": [], "committed_content": {}, "forbidden_target_hits": []}
    record.update(operations=review, calls=1, verdict="noncritical", critical=[])
    records = [
        {**record, "case_id": case_id, "caller_class": "automatic_observation"}
        for case_id in ("unrelated_same_name_people", "global_opening_hours")
    ]
    path = tmp_path / "r-manifest.json"
    path.write_text(json.dumps(manifest))
    (tmp_path / "r-results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    rules, out = common.requirements()["roles"], {}
    found = rescore.corpus(path, {"a" * 64}, {}, rules, out)
    mnemonic = {r["case_id"]: r for r in found if r["role"] == "MNEMONIC"}
    assert set(mnemonic) == {"unrelated_same_name_people"}
    assert mnemonic["unrelated_same_name_people"]["scoring"]["label_match"] is True
    assert {r["case_set_sha256"] for r in found} == {today["MNEMONIC"][0]}
    assert out["MNEMONIC"][K3]["cases_refused"] == ["global_opening_hours"]
