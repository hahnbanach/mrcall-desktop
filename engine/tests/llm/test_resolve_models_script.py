"""`scripts/resolve_models.py` v2: what it reads, writes, compares and refuses (brief D8, AC 3).

The script reads the catalogue, the benchmarks and the pool's endpoints
(from a fixture or live), writes `snapshot.json` with `--apply` always and
`table.json` only once `measured.json` covers every role, compares only the
decision record with `--check`, prints the measurement's arms with
`--bootstrap`, and exits 1 writing nothing when a source cannot be read.
Every case runs on the committed 2026-10-02 capture with paths of its own:
none reaches the network or writes the engine's build copies.
"""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys

import pytest

from .resolver_fixture import ENGINE, FIXTURE, K3, QWEN, SONNET, measured_all, requirements

SCRIPT = ENGINE / "scripts" / "resolve_models.py"
NAMES = ("models.json", "benchmarks.json", "endpoints.json", "read-at.txt")


def load_script():
    spec = importlib.util.spec_from_file_location("resolve_models_v2_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


@pytest.fixture
def rig(tmp_path):
    """Requirements, snapshot, table and measurement paths of the test's own."""
    paths = {
        "requirements_path": tmp_path / "requirements.json",
        "snapshot_path": tmp_path / "snapshot.json",
        "table_path": tmp_path / "table.json",
        "measured_path": tmp_path / "measured.json",
    }
    paths["requirements_path"].write_text(json.dumps(requirements()), encoding="utf-8")

    def run(*args):
        return script.main([str(a) for a in args], **paths)

    return run, paths


def measure(paths) -> None:
    paths["measured_path"].write_text(json.dumps(measured_all(requirements())), encoding="utf-8")


def copy_fixture(where) -> None:
    where.mkdir()
    for name in NAMES:
        shutil.copy(FIXTURE / name, where / name)


def test_apply_writes_the_snapshot_and_waits_for_the_measurement(rig, capsys):
    run, paths = rig
    assert run("--fixture", FIXTURE, "--apply") == 0
    out = capsys.readouterr().out
    snap = json.loads(paths["snapshot_path"].read_text(encoding="utf-8"))
    script.gates.check_snapshot(snap)
    assert snap["read_at"] == "2026-10-02T13:36:42Z" and len(snap["models"]) == 464
    assert paths["snapshot_path"].read_text(encoding="utf-8") == script.gates.dump(snap, 2) + "\n"
    assert not paths["table_path"].exists()
    assert "table.json not written: measured.json does not cover MNEMONIC" in out


def test_apply_writes_the_table_once_every_role_is_measured(rig, capsys):
    run, paths = rig
    measure(paths)
    assert run("--fixture", FIXTURE, "--apply") == 0
    table = json.loads(paths["table_path"].read_text(encoding="utf-8"))
    snap = json.loads(paths["snapshot_path"].read_text(encoding="utf-8"))
    script.gates.check_table(table, requirements(), snap)
    chat = table["presets"]["economy"]["roles"]["CHAT"]["ranking"]
    assert [e["id"] for e in chat[:2]] == [SONNET, QWEN]
    assert (
        table["measured_sha256"]
        == script.hashlib.sha256(paths["measured_path"].read_bytes()).hexdigest()
    )
    assert "wrote table.json" in capsys.readouterr().out


def test_check_ignores_a_price_and_catches_a_moved_pick(rig, tmp_path, capsys):
    run, paths = rig
    measure(paths)
    assert run("--fixture", FIXTURE, "--apply") == 0
    assert run("--fixture", FIXTURE, "--check") == 0
    repriced = tmp_path / "repriced"
    copy_fixture(repriced)
    catalogue = json.loads((repriced / "models.json").read_text(encoding="utf-8"))
    k3 = next(e for e in catalogue["data"] if e["id"] == K3)
    assert k3["pricing"]["completion"] == "0.0000135"
    k3["pricing"]["completion"] = "0.0000139"
    (repriced / "models.json").write_text(json.dumps(catalogue), encoding="utf-8")
    # K3 is published at its reference endpoint's price (`together`): move that too.
    endpoints = json.loads((repriced / "endpoints.json").read_text(encoding="utf-8"))
    together = next(e for e in endpoints["data"][K3]["endpoints"] if e["tag"] == "together")
    assert together["pricing"]["completion"] == "0.0000135"
    together["pricing"]["completion"] = "0.0000139"
    (repriced / "endpoints.json").write_text(json.dumps(endpoints), encoding="utf-8")
    listed = script.candidates.endpoints_by_model((repriced / "endpoints.json").read_bytes(), [K3])
    price, _ = script.candidates.anchored(k3, listed[K3], script.candidates.policy(requirements()))
    assert price["output"] == script.candidates.per_million("0.0000139")
    capsys.readouterr()
    assert run("--fixture", repriced, "--check") == 0
    assert "no change" in capsys.readouterr().out
    table = json.loads(paths["table_path"].read_text(encoding="utf-8"))
    chat = table["presets"]["economy"]["roles"]["CHAT"]["ranking"]
    chat[0], chat[1] = chat[1], chat[0]
    paths["table_path"].write_text(json.dumps(script.gates.stamped(table)), encoding="utf-8")
    assert run("--fixture", repriced, "--check") == 1
    assert f"economy / CHAT / ranking (pick): {QWEN} > {SONNET}" in capsys.readouterr().out


def test_check_without_a_table_or_a_measurement_is_drift(rig, capsys):
    run, paths = rig
    assert run("--fixture", FIXTURE, "--check") == 1
    assert "no table from this read: measured.json does not cover" in capsys.readouterr().out
    measure(paths)
    assert run("--fixture", FIXTURE, "--check") == 1
    assert "no committed table.json" in capsys.readouterr().out


def test_a_raised_ceiling_writes_the_snapshot_and_no_table(rig, capsys):
    run, paths = rig
    measured = measured_all(requirements())
    measured["roles"]["CHAT"]["results"] = {K3: {"pass": True}}  # 13.5, above economy's 10
    paths["measured_path"].write_text(json.dumps(measured), encoding="utf-8")
    assert run("--fixture", FIXTURE, "--apply") == 1
    assert paths["snapshot_path"].exists() and not paths["table_path"].exists()
    out = capsys.readouterr().out
    assert "raised to $13.5 for this run (never published)" in out
    assert "economy's ceiling of 10 would be raised to 13.5" in out


def test_a_table_failing_its_gates_is_never_written(rig, monkeypatch, capsys):
    run, paths = rig
    measure(paths)
    document = script.resolver.document

    def with_an_alias(ranked, stamps):
        row = ranked["presets"]["balanced"]["roles"]["CHAT"]["ranking"]
        row[-1] = {**row[0], "id": "~anthropic/claude-opus-latest", "direct_id": None}
        return document(ranked, stamps)

    monkeypatch.setattr(script.resolver, "document", with_an_alias)
    assert run("--fixture", FIXTURE, "--apply") == 1
    assert "~anthropic/claude-opus-latest is an alias" in capsys.readouterr().err
    assert paths["snapshot_path"].exists() and not paths["table_path"].exists()


def test_a_snapshot_failing_its_gates_is_never_written(rig, monkeypatch, capsys):
    run, paths = rig
    build = script.snapshot.build

    def unstamped(*args):
        return {**build(*args), "version": "0" * 64}

    monkeypatch.setattr(script.snapshot, "build", unstamped)
    assert run("--fixture", FIXTURE, "--apply") == 1
    assert "is not the content's. Nothing written." in capsys.readouterr().err
    assert not paths["snapshot_path"].exists() and not paths["table_path"].exists()


def test_save_and_replay_carry_the_endpoints(rig, tmp_path):
    run, paths = rig
    saved = tmp_path / "saved"
    assert run("--fixture", FIXTURE, "--save", saved) == 0
    for name in NAMES:
        assert (saved / name).read_bytes() == (FIXTURE / name).read_bytes(), name
    assert not paths["snapshot_path"].exists()  # no --apply, nothing written
    assert run("--fixture", saved, "--apply") == 0


@pytest.mark.parametrize("damage", ["missing", "not json", "a pool model left out"])
def test_an_unreadable_source_exits_1_and_writes_nothing(rig, tmp_path, capsys, damage):
    run, paths = rig
    measure(paths)
    for key in ("snapshot_path", "table_path"):
        paths[key].write_text('{"kept": "byte for byte"}\n', encoding="utf-8")
    broken = tmp_path / "broken"
    copy_fixture(broken)
    endpoints = broken / "endpoints.json"
    if damage == "missing":
        endpoints.unlink()
    elif damage == "not json":
        endpoints.write_bytes(b"<html>502</html>")
    else:
        payload = json.loads(endpoints.read_text(encoding="utf-8"))
        del payload["data"][QWEN]
        endpoints.write_text(json.dumps(payload), encoding="utf-8")
    assert run("--fixture", broken, "--apply") == 1
    assert "Nothing written." in capsys.readouterr().err
    for key in ("snapshot_path", "table_path"):
        assert paths[key].read_text(encoding="utf-8") == '{"kept": "byte for byte"}\n'


def test_a_configuration_error_exits_2(rig):
    run, paths = rig
    bad = requirements()
    bad["roles"]["CHAT"]["floor"] = 40
    paths["requirements_path"].write_text(json.dumps(bad), encoding="utf-8")
    assert run("--fixture", FIXTURE, "--apply") == 2
    paths["requirements_path"].write_text(json.dumps(requirements()), encoding="utf-8")
    paths["measured_path"].write_text('{"schema": 1, "roles": {"SPEED": {}}}', encoding="utf-8")
    assert run("--fixture", FIXTURE, "--apply") == 2
    assert not paths["snapshot_path"].exists()
    with pytest.raises(SystemExit) as exit_:
        run("--apply", "--check")
    assert exit_.value.code == 2


def test_bootstrap_prints_the_arms_and_writes_nothing(rig, capsys):
    run, paths = rig
    assert run("--fixture", FIXTURE, "--bootstrap") == 0
    captured = capsys.readouterr()
    arms = json.loads(captured.out)
    assert arms["reference"] == K3 and arms["read_at"] == "2026-10-02T13:36:42Z"
    chat = {arm["id"]: arm for arm in arms["roles"]["CHAT"]["arms"]}
    assert chat[SONNET]["score"] == 57.73 and chat[SONNET]["imputed_sd"] == 4.69
    assert chat[QWEN]["output_price"] == "6" and chat[QWEN]["imputed_sd"] is None
    assert "catalogue read" in captured.err
    assert not paths["snapshot_path"].exists() and not paths["table_path"].exists()


def test_the_key_comes_from_the_environment_only(rig, tmp_path, monkeypatch, capsys):
    run, paths = rig
    seen = {}
    endpoints = json.loads((FIXTURE / "endpoints.json").read_text(encoding="utf-8"))["data"]

    def urlopen(request, timeout):
        url = request.full_url
        seen[url] = request.get_header("Authorization")
        if url.endswith("/models"):
            return io.BytesIO((FIXTURE / "models.json").read_bytes())
        if url.endswith("/benchmarks"):
            return io.BytesIO((FIXTURE / "benchmarks.json").read_bytes())
        model = url.removeprefix("http://openrouter.test/api/v1/models/").removesuffix("/endpoints")
        return io.BytesIO(json.dumps({"data": endpoints[model]}).encode())

    monkeypatch.setattr(script.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv(script.API_ENV, "http://openrouter.test/api/v1")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=from-a-file\n", encoding="utf-8")
    monkeypatch.delenv(script.KEY_ENV, raising=False)
    assert run("--apply") == 1 and not seen and not paths["snapshot_path"].exists()
    assert "OPENROUTER_API_KEY is not set" in capsys.readouterr().err
    monkeypatch.setenv(script.KEY_ENV, "from-the-environment")
    assert run("--apply", "--save", tmp_path / "live") == 0
    keyed = {url: header for url, header in seen.items() if header}
    assert keyed == {"http://openrouter.test/api/v1/benchmarks": "Bearer from-the-environment"}
    assert len(seen) == 2 + 218
    assert "from-the-environment" not in paths["snapshot_path"].read_text(encoding="utf-8")
    saved = json.loads((tmp_path / "live" / "endpoints.json").read_text(encoding="utf-8"))
    assert saved["data"] == endpoints


def test_the_script_needs_only_the_standard_library(tmp_path):
    run = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), "--fixture", str(FIXTURE)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
        timeout=300,
    )
    assert run.returncode == 0, run.stderr
    assert "economy: ceiling $10" in run.stdout and "nothing written" in run.stdout
