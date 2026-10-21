"""The daily job's measurement adapter on slice S4b's own tooling, on its scripted transports.

`model_table_edges.Measurement` measures a harness role through
`model_table_measure.py` (`measure_roles.py`'s loop, ledger and scoring) and
the memory roles through the M9 corpus runner; here both run for real on
their dry transports (`measurement_dry`, the corpus runner without
`MNEMONIC_CORPUS_EXECUTE`), so nothing reaches the network or is paid. What
is pinned: the model is measured alone, the reference never beside it; what
a measurement spent is what its own ledger says (S4b's: receipts plus the
bound of every missing receipt and open intent; the corpus record's totals),
and that is what the month is charged; a measurement that did not score
every case, or under other hashes, is no result; the corpus arm comes from
the environment, never argv, and the run's reservation covers the runner's
cap before it starts.
"""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from . import model_table_world as world
from .model_table_world import K3, load_job

job = load_job()
edges, measured_of = job.edges_of, job.measured_of
dt = measured_of.dt
FLASH = "xiaomi/mimo-v2.6-flash"
CORPUS = ("MNEMONIC", "MEMORY_EXTRACT", "MEMORY_MERGE")


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def out_of(measure) -> Path:
    command, contract = measure.commands[-1]
    if contract:
        return Path(contract["MNEMONIC_CORPUS_RECORD_DIR"]).parent
    return Path(command[command.index("--out") + 1])


# ------------------------------------------------------------ a harness role


def test_a_harness_role_measures_the_model_alone_and_spends_what_its_ledger_says(tmp_path):
    measure = edges.Measurement(tmp_path / "work", Decimal("2"), K3, dry=True)
    assert measure.measurable("NARRATION") and measure.hashes("CHAT") == dt.current_hashes("CHAT")
    measure.preflight()  # a dry run needs no key
    out = measure("NARRATION", FLASH, {"intelligence": 37.9, "agentic": 20.0})
    command, contract = measure.commands[0]
    assert "--dry-run" in command and command[command.index("--cap") + 1] == "2"
    assert contract == {}  # no corpus variable reaches the driver
    where = out_of(measure)
    assert where.parent == tmp_path / "work" and where.stat().st_mode & 0o777 == 0o700
    rows = lines(where / "results.jsonl")
    cases = [c["id"] for c in dt.common.load_document("NARRATION")["cases"]]
    assert {r["arm"] for r in rows} == {FLASH} and len(rows) == len(cases)  # no reference cell
    from measurement_ledger import Ledger

    ledger = Ledger(where / "ledger.jsonl", 0)
    events = [r["event"] for r in ledger.rows()]
    assert events == ["intent", "settle"] * len(cases)  # an intent before each dispatch
    assert out["spent_usd"] == Decimal(ledger.committed()) / 10**6 > 0
    result = out["results"]["NARRATION"]
    assert result == measured_of.aggregate(rows, cases) and "pass" not in result
    assert result["n"] == len(cases) and result["complete"] and result["index_score"] == 37.9


def test_a_model_the_engine_cannot_price_is_no_result_and_sends_nothing(tmp_path):
    measure = edges.Measurement(tmp_path, Decimal("2"), K3, dry=True)
    with pytest.raises(edges.Incomplete, match="not every case was scored") as raised:
        measure("NARRATION", "acme/unpriced-1", {})
    assert raised.value.spent_usd == 0
    where = out_of(measure)
    assert {r["status"] for r in lines(where / "results.jsonl")} == {"unpriced"}
    assert not (where / "ledger.jsonl").exists() or lines(where / "ledger.jsonl") == []


def test_a_call_the_cap_cannot_cover_is_not_sent_and_the_measurement_is_no_result(tmp_path):
    measure = edges.Measurement(tmp_path, Decimal("0.0001"), K3, dry=True)
    with pytest.raises(edges.Incomplete, match="stopped by the cap") as raised:
        measure("NARRATION", FLASH, {})
    assert raised.value.spent_usd == 0
    assert [r["status"] for r in lines(out_of(measure) / "results.jsonl")] == ["cap"]


def driver(write, code: int = 0, said: str = ""):
    """A stand-in for the driver's process: `write(out)` fills its output directory."""

    def run(command, **kwargs):
        write(Path(command[command.index("--out") + 1]))
        return subprocess.CompletedProcess(command, code, "", said)

    return run


def test_the_spend_is_receipts_plus_every_missing_receipt_and_open_intent_at_its_bound(tmp_path):
    from measurement_ledger import Ledger

    def write(out):
        ledger = Ledger(out / "ledger.jsonl", 10_000)
        ledger.settle(ledger.admit("NARRATION|m|n-1|r1", 0, 1000, "m"), 80, {})
        ledger.fail(ledger.admit("NARRATION|m|n-2|r1", 0, 1100, "m"), "ReadTimeout")  # open
        ledger.settle(ledger.admit("NARRATION|m|n-3|r1", 0, 1200, "m"), None, {})  # no receipt

    said = "stopped by the cap: NARRATION|m|n-4|r1: committed 0.002380 + bound 0.001300 > cap"
    measure = edges.Measurement(tmp_path, Decimal("0.003"), K3, run=driver(write, 3, said))
    with pytest.raises(edges.Incomplete, match="stopped by the cap") as raised:
        measure("NARRATION", "m", {})
    assert raised.value.spent_usd == Decimal("0.00238")


def test_rows_under_other_hashes_than_todays_are_no_result(tmp_path):
    cases = [c["id"] for c in dt.common.load_document("NARRATION")["cases"]]
    scoring = {"label_match": True, "bars_ok": True, "critical": False}

    def write(out):
        row = {"role": "NARRATION", "arm": "m", "status": "scored", "scoring": scoring}
        row.update(arm_score=40, case_set_sha256="0" * 64, prompt_sha256="0" * 64)
        text = "".join(json.dumps({**row, "case_id": c, "repetition": 1}) + "\n" for c in cases)
        (out / "results.jsonl").write_text(text)

    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=driver(write))
    with pytest.raises(edges.Incomplete, match="other cases or prompts than today's"):
        measure("NARRATION", "m", {})


def test_a_paid_measurement_needs_the_key_and_never_prints_it(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
        edges.Measurement(tmp_path, Decimal("2"), K3).preflight()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SENTINEL")
    edges.Measurement(tmp_path, Decimal("2"), K3).preflight()
    assert "SENTINEL" not in capsys.readouterr().out


def test_the_projection_is_s4bs_and_sends_nothing(tmp_path):
    import measure_roles
    import measurement_projection as projection

    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=lambda *a, **k: pytest.fail())
    arm = {"id": FLASH, "score": None, "index": "intelligence", "reference": False}
    run = measure_roles.load_runs(["NARRATION"], {"NARRATION": [arm]}, check_fresh=False)[0]
    assert measure.project("NARRATION", FLASH, {}) == projection.role_arm(run, FLASH)[2]
    assert measure.project("MEMORY_MERGE", FLASH, {}) == projection.corpus_arm(FLASH)[2] > 0
    assert measure.commands == [] and list(tmp_path.iterdir()) == []


# ------------------------------------------------------------ the memory roles


def corpus_measurement() -> dict:
    """The three memory roles measured under today's hashes, K3 among them."""
    roles = {}
    for role, (cs, ph) in dt.corpus_hashes().items():
        if role == "MEMORY_EXTRACT":
            roles[role] = world.ladder(cs=cs, ph=ph)
        else:
            roles[role] = world.outcome(passed=list(world.MODELS), cs=cs, ph=ph)
    return {"schema": 1, "roles": roles}


def test_a_memory_role_is_measured_by_the_corpus_runner_and_its_spend_charged(tmp_path):
    rig = world.Rig(job, tmp_path, req=world.requirements(CORPUS), measurement=corpus_measurement())
    rig.world.add(FLASH, **{"in": "0.1", "out": "0.4", "intelligence": 75, "agentic": 30})
    fake = world.FakeEdges(job, rig.world, rig.files)

    def run(command, **kwargs):  # the run's reservation covers the runner's cap first
        fake._reserved("the corpus run", job.decide.MEASURE_USD)
        return subprocess.run(command, **kwargs)

    measure = edges.Measurement(tmp_path / "work", job.decide.MEASURE_USD, K3, dry=True, run=run)
    real = fake.edges()
    real.hashes, real.measurable = measure.hashes, measure.measurable
    real.measure, real.project = measure, measure.project
    argv = ["--data", str(tmp_path / "data"), "--report", str(tmp_path / "report.md")]
    assert job.main(argv, edges=real, roles=rig.roles) == 0
    assert fake.violations == [] and fake.smoked == [FLASH]
    ((command, contract),) = measure.commands  # one run measured the three roles
    assert FLASH not in " ".join(command)  # the arm comes from the arms file, never argv
    assert contract["MNEMONIC_CORPUS_ARM"] == FLASH and "MNEMONIC_CORPUS_EXECUTE" not in contract
    assert contract["MNEMONIC_CORPUS_CAP_USD"] == "2"
    arms = json.loads(Path(contract["MNEMONIC_CORPUS_ARMS"]).read_text())
    assert {role: [a["id"] for a in body["arms"]] for role, body in arms["roles"].items()} == {
        role: [FLASH] for role in CORPUS
    }
    where = out_of(measure)
    assert not (where / "profile" / ".env").exists()  # the key's one copy on disk is gone
    manifest = json.loads((where / "record" / "measurement-manifest.json").read_text())
    corpus = sum(Decimal(str(v)) for v in manifest["totals_usd"].values())
    settled = json.loads(fake.files["ledger.json"])["months"]["2026-10"][0]
    assert corpus > 0 and Decimal(settled["spent_usd"]) == world.SMOKE_SPENT + corpus
    doc = json.loads(fake.files["measured.json"])
    for role in CORPUS:
        mine = doc["roles"][role]["results"][FLASH]
        assert mine["pass"] is True and mine["complete"] and mine["index_score"] == 75
    assert doc["roles"]["MEMORY_MERGE"]["results"][FLASH]["n"] == 7  # its cases and the canary
    table = json.loads(fake.files["table.json"])
    assert table["presets"]["economy"]["roles"]["MNEMONIC"]["ranking"][0]["id"] == FLASH


def corpus_record(manifest: dict, rows: list):
    """A stand-in for the corpus runner's process, writing the record given."""

    def run(command, **kwargs):
        record = Path(kwargs["env"]["MNEMONIC_CORPUS_RECORD_DIR"])
        if manifest:
            (record / "measurement-manifest.json").write_text(json.dumps(manifest))
            text = "".join(json.dumps(row) + "\n" for row in rows)
            (record / "measurement-results.jsonl").write_text(text)
        return subprocess.CompletedProcess(command, 1, "", "1 failed, 18 passed")

    return run


def test_a_paid_corpus_run_refuses_a_dry_record_and_counts_what_it_says_it_spent(tmp_path):
    hashes = dt.corpus_hashes()
    manifest = {
        "mode": "dry",
        "arm_id": FLASH,
        "case_set_sha256": hashes["MNEMONIC"][0],
        "prompt_version_sha256": hashes["MNEMONIC"][1],
        "extraction_prompt_sha256": hashes["MEMORY_EXTRACT"][1],
        "cases": ["account_feedback"],
        "totals_usd": {"settled": 0.25, "held": 0.0, "open_intents": 0.5},
    }
    rows = [{"case_id": "account_feedback", "caller_class": "x", "verdict": "pass", "calls": 1}]
    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=corpus_record(manifest, rows))
    with pytest.raises(edges.Incomplete, match="a dry record measures no model") as raised:
        measure("MNEMONIC", FLASH, {})
    assert raised.value.spent_usd == Decimal("0.75")
    assert measure.commands[0][1]["MNEMONIC_CORPUS_EXECUTE"] == "1"  # a paid run asks for it
    unread = edges.Measurement(tmp_path, Decimal("2"), K3, run=corpus_record({}, []))
    with pytest.raises(edges.Incomplete, match="wrote no record: 1 failed") as raised:
        unread("MEMORY_EXTRACT", FLASH, {})
    assert raised.value.spent_usd == Decimal("2")  # its ledger unread: the whole cap counts
