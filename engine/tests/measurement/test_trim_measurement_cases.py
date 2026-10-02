"""``trim_measurement_cases.py``: IR2's case reduction, its rule, its refusals, its files.

On a synthetic REPLY_NEED of twenty cases in a temporary fixture directory
(``measurement_common.FIXTURES`` pointed at it, a one-line capture harness
beside the cases), these tests hold:

- the rule keeps every critical case, two cases of each label value, then the
  input language with fewer cases kept and in it the lowest-numbered id, so the
  highest-numbered ids go to the reserve first;
- it refuses N below the plan's minimum, below the critical cases, below what
  the critical cases and two of each value need, above the authored cases,
  and a role without a minimum, writing nothing;
- a trim moves the other cases to ``reserve.json`` and captures
  ``requests.json`` again from the kept set (its case-set hash is the kept
  set's); a second trim starts again from every authored case; ``--restore``
  gives back the files byte for byte; a failed capture puts the files back;
- ``--plan`` writes nothing and prices the delta per arm;
- ``--keep-ids`` keeps an exact set as a reviewed exception: refused when it
  drops a critical case, goes below the floors or names no authored case;
  recorded in ``reserve.json`` (who, why, what the rule would keep); a
  ``--keep N`` is refused while it stands, ``--restore`` lifts it;
- every committed case file splits into its cases and back, and each role's
  decision field is the label class its README documents.
"""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_measurement_requests as builder  # noqa: E402
import measurement_common as common  # noqa: E402
import trim_measurement_cases as trim  # noqa: E402

from tests.measurement.case_sets import authored_document  # noqa: E402

ROLE = "REPLY_NEED"
K3 = "moonshotai/kimi-k3"
SONNET = "anthropic/claude-sonnet-5.5"
COMMITTED = common.FIXTURES
# 01-10 Italian, 11-16 English; the two critical cases (19, 20) and the only two
# no-reply cases (17, 18) are among the highest-numbered.
LANGS = {n: "it" if n <= 10 or n in (18, 20) else "en" for n in range(1, 21)}
KEPT_12 = [f"reply_need-{n:02d}" for n in (1, 2, 3, 4, 11, 12, 13, 14, 17, 18, 19, 20)]
CAPTURE = """
def build_requests(document):
    return [
        {
            "case_id": case["id"],
            "request": {
                "model": "measurement/capture",
                "system": "Decide whether the message needs a reply.",
                "messages": [{"role": "user", "content": case["input"]["message"]}],
                "max_tokens": 300,
            },
        }
        for case in document["cases"]
    ]
"""


def case(n, *, needs_reply, critical):
    text = {"it": f"Buongiorno, le scrivo per l'ordine {n}.", "en": f"Hello, about order {n}."}
    return {
        "id": f"reply_need-{n:02d}",
        "lang": LANGS[n],
        "input": {"message": text[LANGS[n]]},
        "label": {"needs_reply": needs_reply},
        "critical": critical,
        "critical_on": ["no_reply"] if critical else [],
        "expect_lang": None,
        "why": "A synthetic case of the trim's tests.",
    }


def cases(critical=(19, 20), no_reply=(17, 18)):
    return [case(n, needs_reply=n not in no_reply, critical=n in critical) for n in range(1, 21)]


def write_role(root, every):
    """The role's files laid out by hand, as the committed ones are: one case per line."""
    role_dir = root / ROLE
    role_dir.mkdir(parents=True)
    head = f'{{\n  "schema": 1,\n  "role": "{ROLE}",\n  "builder": "synthetic",\n  "cases": [\n    '
    body = ",\n    ".join(json.dumps(c, ensure_ascii=False) for c in every)
    (role_dir / "cases.json").write_text(head + body + "\n  ]\n}\n", encoding="utf-8")
    (role_dir / "capture.py").write_text(CAPTURE, encoding="utf-8")
    return role_dir


def files(role_dir):
    return {path.name: path.read_bytes() for path in role_dir.iterdir() if path.is_file()}


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    root = tmp_path / "measurement"
    monkeypatch.setattr(common, "FIXTURES", root)
    return root


def with_requests(fixtures):
    role_dir = write_role(fixtures, cases())
    (role_dir / "requests.json").write_bytes(common.dump(builder.build(ROLE)).encode("utf-8"))
    return role_dir


def test_the_rule_keeps_the_critical_two_of_each_value_and_balances_the_languages():
    assert trim.select(ROLE, cases(), 12) == KEPT_12
    assert trim.select(ROLE, cases(), 12) == KEPT_12  # the same inputs, the same cases


def test_the_refusals_name_the_bound_and_write_nothing(fixtures):
    every = cases()
    with pytest.raises(trim.Refused, match="minimum of 12"):
        trim.select(ROLE, every, 11)
    with pytest.raises(trim.Refused, match="more than its 20 authored"):
        trim.select(ROLE, every, 21)
    with pytest.raises(trim.Refused, match="below its 13 critical cases"):
        trim.select(ROLE, cases(critical=range(1, 14)), 12)
    floored = cases(critical=range(1, 12))  # 11 critical, none of them no-reply
    with pytest.raises(trim.Refused, match="below the 13 the rule must keep"):
        trim.select(ROLE, floored, 12)
    assert len(trim.select(ROLE, floored, 13)) == 13
    with pytest.raises(trim.Refused, match="no minimum"):
        trim.select("COMPACTION", every, 5)
    role_dir = write_role(fixtures, every)
    before = files(role_dir)
    assert trim.main(["--role", ROLE, "--keep", "11"]) == 1
    assert trim.main(["--role", "COMPACTION", "--keep", "4"]) == 1
    assert files(role_dir) == before


def test_a_trim_persists_and_a_restore_gives_back_the_same_bytes(fixtures):
    role_dir = with_requests(fixtures)
    before = files(role_dir)
    assert trim.main(["--role", ROLE, "--keep", "12"]) == 0
    assert [c["id"] for c in common.load_document(ROLE)["cases"]] == KEPT_12
    reserve = json.loads((role_dir / "reserve.json").read_text(encoding="utf-8"))
    every = [c["id"] for c in cases()]
    assert [c["id"] for c in reserve["cases"]] == [i for i in every if i not in KEPT_12]
    assert reserve["order"] == every and reserve["kept"] == 12
    assert authored_document(role_dir) == json.loads(before["cases.json"])
    captured = common.load_requests(ROLE)
    assert captured["case_set_sha256"] == common.case_set_sha256(ROLE)
    assert [entry["case_id"] for entry in captured["requests"]] == KEPT_12
    assert builder.drift(ROLE, builder.build(ROLE)) == []
    # A second trim starts again from every authored case.
    assert trim.main(["--role", ROLE, "--keep", "14"]) == 0
    assert [c["id"] for c in common.load_document(ROLE)["cases"]] == trim.select(ROLE, cases(), 14)
    assert trim.main(["--role", ROLE, "--restore"]) == 0
    assert files(role_dir) == before


def test_a_failed_capture_puts_the_files_back(fixtures, monkeypatch):
    role_dir = with_requests(fixtures)
    before = files(role_dir)

    def refused(role):
        raise common.CaptureRefused(f"{role}: no request")

    monkeypatch.setattr(builder, "build", refused)
    with pytest.raises(common.CaptureRefused):
        trim.main(["--role", ROLE, "--keep", "12"])
    assert files(role_dir) == before


def test_the_plan_writes_nothing_and_prices_the_delta(fixtures, tmp_path, capsys):
    role_dir = with_requests(fixtures)
    before = files(role_dir)
    arms = tmp_path / "arms.json"
    body = {"index": "intelligence", "arms": [{"id": SONNET, "score": 56.0}]}
    arms.write_text(json.dumps({"schema": 1, "reference": K3, "roles": {ROLE: body}}))
    assert trim.main(["--role", ROLE, "--keep", "12", "--plan", "--arms", str(arms)]) == 0
    out = capsys.readouterr().out
    assert files(role_dir) == before
    assert "to the reserve (8): reply_need-05 (it, True)" in out and f"{K3} (reference)" in out
    line = next(row for row in out.splitlines() if row.strip().startswith("the role"))
    pairs = [(Decimal(a), Decimal(b)) for a, b in re.findall(r"(\d+\.\d+) -> +(\d+\.\d+)", line)]
    (max_now, max_kept), (expected_now, expected_kept) = pairs
    assert max_kept < max_now and Decimal(0) < expected_kept < expected_now


@pytest.mark.parametrize("role", sorted(trim.MINIMUM))
def test_every_committed_case_file_splits_into_its_cases_and_back(role):
    text = (COMMITTED / role / "cases.json").read_text(encoding="utf-8")
    prefix, texts, separator, suffix = trim.separator_of(text)
    assert prefix + separator.join(texts.values()) + suffix == text
    assert list(texts) == [c["id"] for c in json.loads(text)["cases"]]


def test_each_role_s_decision_field_is_its_label_class():
    def values(role):
        authored = authored_document(COMMITTED / role)["cases"]
        return {str(trim.label_value(role, case)) for case in authored}

    assert values("TASK_DETECTION") == {"create", "update", "close", "none"}
    assert values("REANALYZE") == {"keep", "close", "update"}
    sites = {f"dedup.{s} {k}" for s in ("f8", "f9") for k in ("duplicates", "distinct")}
    assert values("DEDUP") == sites
    assert values("REPLY_NEED") == {"True", "False"}
    assert values("CORRECTION_LEARNING") == {"rule True", "rule False", "fact True", "fact False"}
    assert values("SYNC_ANALYSIS") == {"answer", "reminder", "unlabelled", "none"}
    assert len(values("INTENT")) == 6
    assert values("CHAT") == values("TASK_SOLVE") == {"None"}


WHY = "a synthetic exception: keep reply_need-05 instead of reply_need-04"


def test_keep_ids_is_a_recorded_exception_within_the_floors(fixtures):
    every = cases()
    swapped = [i.replace("reply_need-04", "reply_need-05") for i in KEPT_12]
    assert trim.select_ids(ROLE, every, swapped) == sorted(swapped)
    no_critical = [i for i in swapped if i != "reply_need-20"] + ["reply_need-06"]
    with pytest.raises(trim.Refused, match="drops critical case"):
        trim.select_ids(ROLE, every, no_critical)
    with pytest.raises(trim.Refused, match="below the plan's minimum of 12"):
        trim.select_ids(ROLE, every, swapped[1:])
    one_no_reply = [i for i in swapped if i != "reply_need-18"] + ["reply_need-06"]
    with pytest.raises(trim.Refused, match="holds 1 of False; the rule keeps two"):
        trim.select_ids(ROLE, every, one_no_reply)
    with pytest.raises(trim.Refused, match="authored case"):
        trim.select_ids(ROLE, every, swapped[1:] + ["reply_need-99"])
    role_dir = with_requests(fixtures)
    before = files(role_dir)
    ids = ["--keep-ids", ",".join(swapped)]
    with pytest.raises(SystemExit):  # a reviewed exception says who chose it and why
        trim.main(["--role", ROLE, *ids, "--why", WHY])
    assert trim.main(["--role", ROLE, *ids, "--chosen-by", "IR2 round 1", "--why", WHY]) == 0
    assert [c["id"] for c in common.load_document(ROLE)["cases"]] == sorted(swapped)
    reserve = json.loads((role_dir / "reserve.json").read_text(encoding="utf-8"))
    assert reserve["exception"] == {
        "chosen_by": "IR2 round 1",
        "why": WHY,
        "rule_would_keep": KEPT_12,
    }
    assert builder.drift(ROLE, builder.build(ROLE)) == []
    assert trim.main(["--role", ROLE, "--keep", "12"]) == 1  # not silently undone
    assert trim.main(["--role", ROLE, "--restore"]) == 0
    assert files(role_dir) == before
