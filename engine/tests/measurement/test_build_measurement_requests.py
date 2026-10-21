"""``build_measurement_requests.py``: one request per case, the two hashes, the committed files.

- A harness that yields no request for a case, two for one case, or whose
  client received two requests for one case, is refused.
- The prompt hash covers the request template: it moves when a prompt, a
  tool schema or ``max_tokens`` changes, and not with a case's own data, the
  captured model, a transport's ``cache_control`` hint, or the order in which
  a trainer lists case items (the TRAIN contact set).
- Every committed ``requests.json`` matches a fresh capture of today's code
  and case set (the measurement replays them; ``--check`` is this test).
- TRAIN's capture is the same bytes in any process: two processes with
  different hash seeds capture its committed ``requests.json`` exactly (the
  harness sorts the trainers' sets; production is unchanged).
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_measurement_requests as builder  # noqa: E402
import measurement_common as common  # noqa: E402

CASES = [
    {"id": "x-1", "input": {"message": "Gentile Chiara, le mando il listino aggiornato."}},
    {"id": "x-2", "input": {"message": "Dear Tom, the samples ship on Friday."}},
]
DOCUMENT = {"schema": 1, "role": "REPLY_NEED", "cases": CASES}


def request(text, *, system="Decide whether a reply is owed.", max_tokens=500, **extra):
    return {
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": f"Message:\n{text}\nAnswer with the tool."}],
        "tools": [{"name": "decide", "input_schema": {"type": "object"}}],
        "max_tokens": max_tokens,
        **extra,
    }


def harness(entries, counts=None):
    def build_requests(cases, *, calls=None):
        if calls is not None and counts:
            calls.update(counts)
        return entries

    return SimpleNamespace(build_requests=build_requests)


def entries(**changes):
    return [
        {"case_id": case["id"], "request": request(case["input"]["message"], **changes)}
        for case in CASES
    ]


def test_a_case_without_a_request_or_with_two_is_refused():
    two = entries()
    with pytest.raises(common.CaptureRefused, match="exactly one per case"):
        common.capture("REPLY_NEED", DOCUMENT, harness(two[:1]))
    with pytest.raises(common.CaptureRefused, match="exactly one per case"):
        common.capture("REPLY_NEED", DOCUMENT, harness(two + two[1:]))
    with pytest.raises(common.CaptureRefused, match="2 requests reached the client"):
        common.capture("REPLY_NEED", DOCUMENT, harness(two, {"x-1": 1, "x-2": 2}))
    captured = common.capture("REPLY_NEED", DOCUMENT, harness(two, {"x-1": 1, "x-2": 1}))
    assert [entry["case_id"] for entry in captured] == ["x-1", "x-2"]
    assert all(entry["capture_now"] == common.default_capture_now() for entry in captured)


def hash_of(captured):
    return common.prompt_sha256(captured, CASES)


def test_the_prompt_hash_follows_the_template_not_the_case_data():
    base = hash_of(entries())
    assert hash_of(entries(model="<role model>")) == base
    hinted = entries()
    for entry in hinted:
        entry["request"]["system"][0].pop("cache_control")
    assert hash_of(hinted) == base
    assert hash_of(entries(system="Decide whether we owe a reply.")) != base
    assert hash_of(entries(max_tokens=600)) != base
    schema = entries()
    schema[0]["request"]["tools"][0]["input_schema"] = {"type": "object", "required": ["a"]}
    assert hash_of(schema) != base
    # Other case data in the same template: the same hash.
    other = [dict(case, input={"message": case["input"]["message"] + " Grazie."}) for case in CASES]
    swapped = [
        {"case_id": case["id"], "request": request(case["input"]["message"])} for case in other
    ]
    assert common.prompt_sha256(swapped, other) == base


def test_the_order_of_listed_case_items_does_not_move_the_prompt_hash():
    """As the task trainer lists its contacts' blobs from a set (train-03, train-04)."""
    memory = ["Anna Riva, buyer at Riva Srl", "Luca Neri, glass supplier"]
    case = {"id": "t-1", "input": {"emails": ["anna@one.example", "luca@two.example"]}}
    case["input"]["memory"] = memory
    blobs = [
        f"--- Blob for {address} ---\n{content}"
        for address, content in zip(case["input"]["emails"], memory)
    ]
    forward = {"case_id": "t-1", "request": request("\n\n".join(blobs))}
    backward = copy.deepcopy(forward)
    backward["request"]["messages"] = request("\n\n".join(blobs[::-1]))["messages"]
    assert forward != backward
    assert common.prompt_sha256([forward], [case]) == common.prompt_sha256([backward], [case])


def test_every_committed_requests_json_matches_a_fresh_capture():
    problems = []
    for role in common.HARNESS_ROLES:
        problems += builder.drift(role, builder.build(role))
    assert problems == []


TRAIN_CAPTURE = (
    "import sys; sys.path.insert(0, 'scripts'); "
    "import build_measurement_requests as builder, measurement_common as common; "
    "sys.stdout.write(common.dump(builder.build('TRAIN')))"
)


def test_train_s_requests_are_the_same_bytes_under_any_hash_seed():
    engine = SCRIPTS.parent
    committed = common.requests_path("TRAIN").read_text(encoding="utf-8")
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(engine)}
        done = subprocess.run(
            [sys.executable, "-c", TRAIN_CAPTURE],
            cwd=engine,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        assert done.stdout == committed, f"PYTHONHASHSEED={seed} captured other bytes"
