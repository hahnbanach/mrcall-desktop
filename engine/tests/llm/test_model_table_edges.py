"""The daily job's edges against local stand-ins: a bare git repository, fake script modules.

`scripts/model_table_edges.py` holds what the job reads, pays for and
pushes. The data branch is exercised on a bare repository in a temporary
directory (a push there reaches no network); the smoke and the measurement
adapters run against fake `model_smoke`, `measure_roles` and
`derive_thresholds` modules, so nothing is paid.
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

from .model_table_world import CS, PH, load_job

job = load_job()
edges = job.edges_of


def git(*args, cwd=None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def branch(tmp_path):
    """A bare `origin` holding an orphan `model-table`, and a clone of it."""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git("init", "-q", "--bare", str(origin))
    git("init", "-q", "-b", "model-table", str(seed))
    for where in (seed,):
        git("config", "user.name", "Test", cwd=where)
        git("config", "user.email", "test@example.invalid", cwd=where)
    (seed / "README.md").write_text("the published model table\n")
    git("add", "README.md", cwd=seed)
    git("commit", "-q", "-m", "start", cwd=seed)
    git("push", "-q", str(origin), "model-table", cwd=seed)

    def clone(name: str):
        where = tmp_path / name
        git("clone", "-q", "-b", "model-table", str(origin), str(where))
        git("config", "user.name", "Test", cwd=where)
        git("config", "user.email", "test@example.invalid", cwd=where)
        return where

    return origin, clone


def test_a_push_commits_the_files_under_v1_and_reaches_the_branch(branch):
    origin, clone = branch
    data = edges.DataBranch(clone("data"))
    assert data.read() == dict.fromkeys(edges.FILES)
    data.push({"ledger.json": '{"schema": 1}\n'}, "model-table: reserve")
    data.push({"ledger.json": '{"schema": 1}\n'}, "model-table: nothing new")  # no commit
    data.push({"snapshot.json": "{}\n", "ledger.json": '{"schema": 1, "x": 1}\n'}, "publish")
    log = git("log", "--format=%s", "model-table", cwd=origin)
    assert log.splitlines() == ["publish", "model-table: reserve", "start"]
    assert git("show", "model-table:v1/snapshot.json", cwd=origin) == "{}"
    assert data.read()["ledger.json"] == b'{"schema": 1, "x": 1}\n'


def test_the_default_edges_create_their_work_directory_and_read_the_branch(tmp_path):
    work, data = tmp_path / "runner" / "model-table-job", tmp_path / "data"
    (data / "v1").mkdir(parents=True)
    (data / "v1" / "ledger.json").write_text("{}\n")
    real = edges.default(data, None, work, Decimal("10"))
    assert work.is_dir() and work.stat().st_mode & 0o777 == 0o700
    assert real.smoke.cap == job.decide.SMOKE_CAP_USD == Decimal("0.20")  # the smoke's admission
    read = real.read()
    assert read["ledger.json"] == b"{}\n" and read["table.json"] is None
    assert real.now().utcoffset().total_seconds() == 0


def test_a_push_from_a_checkout_behind_the_branch_is_refused(branch):
    _, clone = branch
    first, second = edges.DataBranch(clone("first")), edges.DataBranch(clone("second"))
    first.push({"ledger.json": "{}\n"}, "first")
    with pytest.raises(RuntimeError, match="git push failed"):
        second.push({"ledger.json": '{"other": 1}\n'}, "second")


@pytest.mark.parametrize(
    "results, spent",
    [
        ([{"cost": 0.25}, {"cost": "0.5"}], Decimal("0.75")),
        ([{"cost": 0.25}, {"usage": {}}], Decimal("2")),  # one cost unknown: the whole cap
        ({"rows": []}, Decimal("2")),
    ],
)
def test_a_measurements_spend_is_its_rows_costs_or_its_whole_cap(results, spent):
    assert edges.cost(results, Decimal("2")) == spent


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A fixture directory with CHAT's captured requests, and fake S4b modules."""
    fixtures = tmp_path / "measurement"
    (fixtures / "CHAT").mkdir(parents=True)
    requests = {"schema": 1, "role": "CHAT", "case_set_sha256": CS, "prompt_sha256": PH}
    (fixtures / "CHAT" / "requests.json").write_text(json.dumps(requests))
    (fixtures / "CHAT" / "cases.json").write_text(json.dumps({"cases": ["c1"]}))
    calls = []

    def run(roles, arms, cap_usd, ledger, transport):
        calls.append(("run", roles, arms, cap_usd, transport))
        return [{"arm": arm, "cost": 0.1} for arm in arms["CHAT"]]

    def derive(results, cases):
        calls.append(("derive", len(results), cases))
        arms = {row["arm"]: {"pass": True, "score": 0.9, "n": 20} for row in results}
        return {"schema": 1, "roles": {"CHAT": {"results": arms}}}

    monkeypatch.setitem(sys.modules, "measure_roles", SimpleNamespace(__name__="m", run=run))
    monkeypatch.setitem(
        sys.modules, "derive_thresholds", SimpleNamespace(__name__="d", derive=derive)
    )
    return fixtures, calls


def test_the_measurement_runs_the_model_beside_the_reference_under_its_cap(harness, tmp_path):
    fixtures, calls = harness
    measure = edges.Measurement(fixtures, tmp_path, Decimal("2"), "moonshotai/kimi-k3")
    assert measure.measurable("CHAT") and not measure.measurable("MNEMONIC")
    assert measure.hashes("CHAT") == (CS, PH) and measure.hashes("MNEMONIC") is None
    measure.preflight()
    out = measure("CHAT", "acme/genius-2")
    assert out == {"result": {"pass": True, "score": 0.9, "n": 20}, "spent_usd": Decimal("0.2")}
    arms = {"CHAT": ["acme/genius-2", "moonshotai/kimi-k3"]}
    assert calls[0] == ("run", ["CHAT"], arms, 2.0, "openrouter")
    assert calls[1] == ("derive", 2, {"CHAT": {"cases": ["c1"]}})
    measure("CHAT", "moonshotai/kimi-k3")  # the reference is measured once, not twice
    assert calls[2][2] == {"CHAT": ["moonshotai/kimi-k3"]}


def test_a_missing_s4b_call_is_refused_before_anything_is_paid(harness, monkeypatch, tmp_path):
    fixtures, _ = harness
    monkeypatch.setitem(sys.modules, "derive_thresholds", SimpleNamespace(__name__="d"))
    with pytest.raises(RuntimeError, match="d.derive is missing"):
        edges.Measurement(fixtures, tmp_path, Decimal("2"), "k3").preflight()


def test_the_smoke_runs_model_smokes_loop_under_its_own_cap(tmp_path, monkeypatch):
    seen = {}

    class Ledger:
        intents = [{"event": "intent", "call": "1:openrouter:m:1"}]

        def __init__(self, path, cap):
            seen["ledger"] = (path.name, cap)

        def rows(self):
            return list(Ledger.intents)

        def used(self):
            return 3200  # micro-USD

    def profile(where, budget):
        seen.setdefault("profiles", []).append((where.name, budget))

    def smoke_model(client, transport, ledger):
        seen["smoke"] = (client, transport)
        return {"passed": False, "failure": "no lookup_order call (stop_reason=end_turn)"}

    fake = SimpleNamespace(
        Ledger=Ledger,
        _profile=profile,
        _factory=lambda transport, model: f"client {transport} {model}",
        smoke_model=smoke_model,
    )
    monkeypatch.setitem(sys.modules, "model_smoke", fake)
    smoke = edges.Smoke(tmp_path, Decimal("0.05"), Decimal("10"))
    out = smoke("z-ai/glm-flash")
    assert out == {
        "passed": False,
        "spent_usd": Decimal("0.0032"),
        "detail": "no lookup_order call (stop_reason=end_turn)",
    }
    assert seen["ledger"] == ("smoke-1.jsonl", 0.05)
    assert seen["smoke"] == ("client openrouter z-ai/glm-flash", "openrouter")
    smoke("qwen/q-max")
    assert seen["profiles"] == [("smoke-profile", 10.0)]  # one disposable profile per run
    unsent = "not sent: anthropic: bound 85808 + used 0 > cap 50000 micro-USD"
    fake.smoke_model = lambda client, transport, ledger: {"passed": False, "failure": unsent}
    assert smoke("anthropic/claude-opus-9")["passed"] is None  # its cap stopped a call
    Ledger.intents = []  # nothing sent: the engine could not price the first call
    unpriced = "BudgetError: AI paused: OpenRouter model has no verified price ceiling."
    fake.smoke_model = lambda client, transport, ledger: {"passed": False, "failure": unpriced}
    assert smoke("acme/unpriced-1") == {
        "passed": None,
        "spent_usd": Decimal("0.0032"),
        "detail": unpriced,
    }


def test_the_smoke_refuses_without_the_key_and_never_prints_it(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY is not set"):
        edges.Smoke(tmp_path, Decimal("0.05"), Decimal("10")).preflight()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SENTINEL")
    monkeypatch.setitem(sys.modules, "model_smoke", SimpleNamespace())
    edges.Smoke(tmp_path, Decimal("0.05"), Decimal("10")).preflight()
    assert "SENTINEL" not in capsys.readouterr().out
