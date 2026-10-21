"""Exact settings/preparation CAS with an explicit external maintenance lease."""

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/m10_acceptance_budget_controls.py"
SPEC = importlib.util.spec_from_file_location("acceptance_controls", PATH)
ctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctl)


def lease_for(*paths, writers=()):
    return dict(
        run_id="control-proof",
        holder=dict(pid=os.getpid(), start=ctl.process_start(os.getpid())),
        paths=[str(p) for p in paths],
        writers=list(writers),
        daemons_stopped=True,
        settings_writers_drained=True,
        scoped_cron_paused=True,
        all_writer_sources_excluded=True,
        evidence=dict(
            daemon_stop="synthetic-child-reaped",
            settings_drain="synthetic-writer-reaped",
            cron_pause="synthetic-launcher-disabled",
        ),
    )


def setup(tmp_path, *, env=True, table=True, row=True, paused=0):
    path, database, directory = tmp_path / ".env", tmp_path / "profile.db", tmp_path / "controls"
    if env:
        path.write_bytes(
            b"# unchanged comment\r\nLLM_DAILY_BUDGET_USD='20'\r\nAUTO_UPDATE_ENABLED=y\r\nMODEL_CHAT=custom-model\r\nLLM_PROVIDER=openrouter\r\nSYNTHETIC_PRIVATE_VALUE=never-echo-this-fixture\r\n"
        )
        path.chmod(0o640)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")
        conn.execute("INSERT INTO unrelated VALUES('retain')")
        if table:
            conn.execute(ctl.sql.SCHEMA)
            if row:
                conn.execute(
                    "INSERT INTO preparation_state(owner,paused,run_id,attempted,completed,failed,item_limit,stop_reason) VALUES('owner',?,'old-run',13,9,4,25,'original reason')",
                    (paused,),
                )
            conn.execute("INSERT INTO preparation_state(owner,attempted) VALUES('other-owner',7)")
    return path, database, directory, lease_for(path, database)


def capture(values):
    path, database, directory, lease = values
    return ctl.capture(str(directory), str(path), str(database), "owner", lease, apply=True)


def dbrow(database):
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM preparation_state WHERE owner='owner'").fetchone())


def test_exact_roundtrip_preserves_bytes_modes_owner_and_permanent_choices(tmp_path):
    values = setup(tmp_path)
    path, database, directory, lease = values
    before, content = ctl.files.snapshot(str(path))
    oldrow = dbrow(database)
    public = capture(values)
    assert "never-echo" not in json.dumps(public)
    assert "never-echo" not in (directory / "journal.json").read_text()
    assert (directory / "env.before").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    ctl.pause(str(directory), lease, apply=True)
    saved = ctl.files.snapshot(str(path))[0]
    assert (saved["mode"], saved["uid"], saved["gid"]) == (
        before["mode"],
        before["uid"],
        before["gid"],
    )
    assert b"LLM_DAILY_BUDGET_USD=0\n" in path.read_bytes()
    assert b"AUTO_UPDATE_ENABLED=n\n" in path.read_bytes()
    assert b"MODEL_CHAT=custom-model\r\n" in path.read_bytes()
    assert dbrow(database)["paused"] == 1
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE preparation_state SET attempted=17,completed=11 WHERE owner='owner'")
    ctl.restore(str(directory), lease, apply=True)
    assert ctl.files.snapshot(str(path)) == (before, content)
    actual = dbrow(database)
    assert actual["attempted"] == 17 and actual["completed"] == 11
    for key in set(oldrow) - set(ctl.sql.STATS):
        assert actual[key] == oldrow[key]
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT attempted FROM preparation_state WHERE owner='other-owner'"
        ).fetchone() == (7,)
        assert conn.execute("SELECT * FROM unrelated").fetchall() == [("retain",)]
    assert ctl.restore(str(directory), lease, apply=True)["phase"] == "restored"
    with pytest.raises(ctl.Refused):
        ctl.pause(str(directory), lease, apply=True)


@pytest.mark.parametrize("table,row", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("env", [False, True])
def test_original_presence_is_restored(tmp_path, table, row, env):
    values = setup(tmp_path, env=env, table=table, row=row, paused=1)
    path, database, directory, lease = values
    before = ctl.files.snapshot(str(path))
    with sqlite3.connect(database) as conn:
        original = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    ctl.restore(str(directory), lease, apply=True)
    assert ctl.files.snapshot(str(path)) == before
    with sqlite3.connect(database) as conn:
        assert (
            conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table'").fetchall()
            == original
        )
        if table:
            assert conn.execute(
                "SELECT count(*) FROM preparation_state WHERE owner='owner'"
            ).fetchone()[0] == int(row)


@pytest.mark.parametrize(
    "content",
    [
        b'LLM_DAILY_BUDGET_USD="0\n',
        b"A=1\nA=2\n",
        b"export AUTO_UPDATE_ENABLED=y\nAUTO_UPDATE_ENABLED=n\n",
        b"\xff",
    ],
)
def test_malformed_duplicate_settings_refuse_before_any_write(tmp_path, content):
    values = setup(tmp_path)
    path, _, directory, _ = values
    path.write_bytes(content)
    with pytest.raises(ctl.Refused):
        capture(values)
    assert path.read_bytes() == content and not directory.exists()


@pytest.mark.parametrize("phase", ["apply", "restore"])
@pytest.mark.parametrize("drift", ["bytes", "mode", "database", "preparation"])
def test_foreign_drift_refuses_without_overwrite(tmp_path, phase, drift):
    values = setup(tmp_path)
    path, database, directory, lease = values
    capture(values)
    if phase == "restore":
        ctl.pause(str(directory), lease, apply=True)
    if drift == "bytes":
        path.write_bytes(path.read_bytes() + b"# another owner\n")
    elif drift == "mode":
        path.chmod(0o600)
    elif drift == "database":
        database.chmod(0o600)
    else:
        with sqlite3.connect(database) as conn:
            conn.execute(
                "UPDATE preparation_state SET stop_reason='another owner' WHERE owner='owner'"
            )
    before = path.read_bytes()
    with pytest.raises(ctl.Refused):
        (ctl.pause if phase == "apply" else ctl.restore)(str(directory), lease, apply=True)
    assert path.read_bytes() == before


def test_preparation_metadata_drift_retains_saved_cap_zero(tmp_path):
    values = setup(tmp_path)
    path, database, directory, lease = values
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE preparation_state SET run_id='foreign-run' WHERE owner='owner'")
    with pytest.raises(ctl.Refused):
        ctl.restore(str(directory), lease, apply=True)
    assert b"LLM_DAILY_BUDGET_USD=0" in path.read_bytes()
    assert dbrow(database)["paused"] == 1


def test_missing_row_with_new_statistics_is_not_deleted(tmp_path):
    values = setup(tmp_path, row=False)
    path, database, directory, lease = values
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE preparation_state SET attempted=1 WHERE owner='owner'")
    with pytest.raises(ctl.Refused):
        ctl.restore(str(directory), lease, apply=True)
    assert dbrow(database)["attempted"] == 1 and dbrow(database)["paused"] == 1
    assert b"LLM_DAILY_BUDGET_USD=0" in path.read_bytes()


def test_failed_helper_resumes_same_original_journal_without_rebaseline(tmp_path, monkeypatch):
    values = setup(tmp_path)
    path, _, directory, lease = values
    original = path.read_bytes()
    capture(values)
    saved = ctl.sql.pause
    monkeypatch.setattr(
        ctl.sql, "pause", lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic failure"))
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        ctl.pause(str(directory), lease, apply=True)
    assert b"LLM_DAILY_BUDGET_USD=0" in path.read_bytes()
    assert ctl.load(directory)[0]["phase"] == "env_paused"
    monkeypatch.setattr(ctl.sql, "pause", saved)
    ctl.pause(str(directory), lease, apply=True)
    ctl.restore(str(directory), lease, apply=True)
    assert path.read_bytes() == original
    with pytest.raises(FileExistsError):
        capture(values)


def test_restoration_never_invokes_preparation_resume_or_model(tmp_path, monkeypatch):
    from zylch.rpc import preparation
    from zylch.llm.client import LLMClient

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Restoration launched processing")

    monkeypatch.setattr(preparation, "preparation_resume", forbidden)
    monkeypatch.setattr(LLMClient, "create_message_sync", forbidden)
    values = setup(tmp_path)
    capture(values)
    _, _, directory, lease = values
    ctl.pause(str(directory), lease, apply=True)
    assert ctl.restore(str(directory), lease, apply=True)["preparation_resume_called"] is False


def test_running_writer_and_missing_external_exclusion_refuse(tmp_path):
    values = setup(tmp_path)
    path, database, _, lease = values
    writer = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; from pathlib import Path; p=Path(sys.argv[1]); p.write_bytes(p.read_bytes()+b'# writer touched'+bytes([10])); print('ready',flush=True); sys.stdin.read()",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert writer.stdout.readline().strip() == "ready"
        lease["writers"] = [dict(pid=writer.pid, start=ctl.process_start(writer.pid))]
        with pytest.raises(ctl.Refused, match="writer"):
            capture(values)
    finally:
        writer.communicate(timeout=10)
    assert writer.returncode == 0
    capture(values)
    lease["all_writer_sources_excluded"] = False
    with pytest.raises(ctl.Refused, match="exclusion"):
        ctl.pause(str(values[2]), lease, apply=True)
    assert b"LLM_DAILY_BUDGET_USD='20'" in path.read_bytes()
    assert lease["paths"] == [str(path), str(database)]


def test_actual_nonowner_file_refuses_identity_change(tmp_path):
    values = setup(tmp_path)
    path, _, directory, lease = values
    if os.geteuid() == 0:
        pytest.skip("Requires a non-root executor to prove ownership refusal")
    if os.environ.get("M10_ACCEPTANCE_OWNERSHIP_SUDO") != "1":
        pytest.skip(
            "Opt into disposable foreign-owner fixture with M10_ACCEPTANCE_OWNERSHIP_SUDO=1"
        )
    result = subprocess.run(
        ["sudo", "-n", "chown", f"{os.getuid() + 1}:{os.getgid()}", str(path)], capture_output=True
    )
    assert result.returncode == 0, "Disposable ownership fixture needs authorized sudo"
    before = ctl.files.snapshot(str(path))
    capture(values)
    with pytest.raises(ctl.Refused, match="ownership"):
        ctl.pause(str(directory), lease, apply=True)
    assert ctl.files.snapshot(str(path)) == before


@pytest.mark.parametrize(
    "problem", ["dead-holder", "wrong-start", "missing-writers", "missing-scope", "cron-not-paused"]
)
def test_lease_failures_refuse_before_target_changes(tmp_path, problem):
    values = setup(tmp_path)
    path, _, directory, lease = values
    if problem == "dead-holder":
        lease["holder"] = dict(pid=999999999, start=None)
    elif problem == "wrong-start":
        lease["holder"]["start"] = "wrong"
    elif problem == "missing-writers":
        lease.pop("writers")
    elif problem == "missing-scope":
        lease["paths"] = []
    else:
        lease["scoped_cron_paused"] = False
    before = path.read_bytes()
    with pytest.raises(ctl.Refused):
        capture(values)
    assert path.read_bytes() == before and not directory.exists()


def test_interrupted_restore_recovers_without_restarting_work(tmp_path, monkeypatch):
    values = setup(tmp_path)
    path, database, directory, lease = values
    original = path.read_bytes()
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    replace = ctl.files.replace
    monkeypatch.setattr(
        ctl.files, "replace", lambda *_: (_ for _ in ()).throw(RuntimeError("restore interruption"))
    )
    with pytest.raises(RuntimeError):
        ctl.restore(str(directory), lease, apply=True)
    assert ctl.load(directory)[0]["phase"] == "preparation_restored"
    assert b"LLM_DAILY_BUDGET_USD=0" in path.read_bytes()
    assert dbrow(database)["paused"] == 0
    monkeypatch.setattr(ctl.files, "replace", replace)
    ctl.restore(str(directory), lease, apply=True)
    assert path.read_bytes() == original


def test_corrupted_backup_never_overwrites_controls(tmp_path):
    values = setup(tmp_path)
    path, _, directory, lease = values
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    (directory / "env.before").write_bytes(b"forged backup")
    before = path.read_bytes()
    with pytest.raises(ctl.Refused, match="evidence changed"):
        ctl.restore(str(directory), lease, apply=True)
    assert path.read_bytes() == before


def test_repeated_restore_detects_preparation_drift_without_overwrite(tmp_path):
    values = setup(tmp_path)
    path, database, directory, lease = values
    capture(values)
    ctl.pause(str(directory), lease, apply=True)
    ctl.restore(str(directory), lease, apply=True)
    before = path.read_bytes()
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE preparation_state SET paused=1 WHERE owner='owner'")
    with pytest.raises(ctl.Refused, match="drifted"):
        ctl.restore(str(directory), lease, apply=True)
    assert path.read_bytes() == before and dbrow(database)["paused"] == 1
