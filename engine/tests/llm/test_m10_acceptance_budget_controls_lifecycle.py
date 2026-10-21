"""Installed artifact, four realistic ledgers and explicit process restart proof."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

CONTROLS = Path(__file__).resolve().parents[2] / "scripts/m10_acceptance_budget_controls.py"
BUDGET = CONTROLS.with_name("m10_acceptance_budget.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_installed_four_ledger_control_and_restart_lifecycle(tmp_path):
    executable = os.environ.get("M10_ACCEPTANCE_ARTIFACT_PYTHON")
    if not executable:
        pytest.skip("Set M10_ACCEPTANCE_ARTIFACT_PYTHON for installed M2 proof")
    env = dict(
        PATH="/usr/bin:/bin",
        HOME=str(tmp_path),
        TMPDIR=str(tmp_path),
        ZYLCH_HOME=str(tmp_path / "home"),
        MEMORY_DB_DIR=str(tmp_path / "memory"),
        MEMORY_KEY="synthetic-control-memory",
        OWNER_ID="owner",
        ANTHROPIC_API_KEY="synthetic-only",
        PYTHONDONTWRITEBYTECODE="1",
    )
    command = [
        executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        "--journey",
        str(CONTROLS),
        str(BUDGET),
        str(tmp_path),
    ]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
    (tmp_path / "M2-installed-stdout.log").write_text(result.stdout)
    (tmp_path / "M2-installed-stderr.log").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads((tmp_path / "M2-installed-proof.json").read_text())
    assert proof["bytecode_disabled"] and proof["isolated"]
    assert proof["baseline_sizes"] == [127, 24, 3, 3]
    assert proof["cached_before_restart"] is True
    assert proof["new_process_after_pause"] is False
    assert proof["new_process_after_restore"] is True
    assert proof["preparation_resumed"] is False


def daemon(env_path):
    import socket

    def deny(*_args, **_kwargs):
        raise RuntimeError("External networking disabled")

    socket.socket.connect = deny
    socket.getaddrinfo = deny
    from dotenv import load_dotenv

    load_dotenv(env_path, override=True)
    os.environ["ZYLCH_PROFILE_DIR"] = str(Path(env_path).parent)
    from zylch.rpc.server_ws import _auto_update_enabled
    from zylch.llm.budget import _budget

    for line in sys.stdin:
        if line.strip() == "read":
            print(
                json.dumps(
                    dict(
                        auto=_auto_update_enabled(),
                        budget=_budget(),
                        bytecode_disabled=bool(sys.flags.dont_write_bytecode),
                    )
                ),
                flush=True,
            )


def journey(controls_path, budget_path, directory):
    import socket

    def deny(*_args, **_kwargs):
        raise RuntimeError("External networking disabled")

    socket.socket.connect = deny
    socket.getaddrinfo = deny
    with pytest.raises(RuntimeError):
        socket.create_connection(("8.8.8.8", 443))
    ctl, guard = load(controls_path, "control_journey"), load(budget_path, "budget_journey")
    directory = Path(directory)
    from sqlalchemy import create_engine

    from zylch.llm import budget
    from zylch.storage import database
    from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

    allocations, baselines, control_runs = [], {}, []
    sizes, usages = [127, 24, 3, 3], [10000, 6000, 32, 32]
    for index, amount in enumerate((2000000, 2000000, 500000, 500000)):
        profile = directory / str(index)
        profile.mkdir()
        path = profile / "profile.db"
        env_path = profile / ".env"
        env_path.write_bytes(
            b"LLM_DAILY_BUDGET_USD=20\nAUTO_UPDATE_ENABLED=y\nMODEL_CHAT=unchanged-custom\nLLM_PROVIDER=anthropic\n"
        )
        env_path.chmod(0o640)
        engine = create_engine(f"sqlite:///{path}")
        database.Base.metadata.create_all(
            engine,
            tables=[m.__table__ for m in (LlmReservation, LlmUsage, LlmBillingAuthorization)],
        )
        engine.dispose()
        with sqlite3.connect(path) as conn:
            conn.executemany(
                "INSERT INTO llm_reservations VALUES(?, 'owner','2000-01-01 00:00:00','claude-haiku-4-5','direct','historical',200000,NULL)",
                [(f"old-{i}",) for i in range(sizes[index])],
            )
            conn.executemany(
                "INSERT INTO llm_usage(id,owner_id,ts,call_site,transport,model,est_cost_usd) VALUES(?,'owner','2000-01-01 00:00:00','old','direct','claude-haiku-4-5',0.001)",
                [(f"usage-{i}",) for i in range(usages[index])],
            )
            baseline = dict(
                reservations=conn.execute("SELECT * FROM llm_reservations ORDER BY id").fetchall(),
                usage=conn.execute("SELECT * FROM llm_usage ORDER BY id").fetchall(),
            )
            baselines[str(index)] = hashlib.sha256(json.dumps(baseline).encode()).hexdigest()
        info = path.stat()
        allocations.append(
            dict(
                allocation_id=f"fixture-{index}",
                owner_id="owner",
                path=str(path),
                device=info.st_dev,
                inode=info.st_ino,
                micro_usd=amount,
            )
        )
        lease = dict(
            run_id=f"control-{index}",
            holder=dict(pid=os.getpid(), start=ctl.process_start(os.getpid())),
            paths=[str(path), str(env_path)],
            writers=[],
            daemons_stopped=True,
            settings_writers_drained=True,
            scoped_cron_paused=True,
            all_writer_sources_excluded=True,
            evidence=dict(
                daemon_stop="synthetic-lifecycle-no-writer",
                settings_drain="synthetic-no-settings-writer",
                cron_pause="synthetic-no-launcher",
            ),
        )
        control_runs.append((str(profile / "controls"), str(env_path), lease))
    manifest = dict(run_id="M2-realistic", allocations=allocations)
    for row in allocations:
        guard.activate(manifest, row["allocation_id"], apply=True)
    for index, row in enumerate(allocations):
        assert guard.activate(manifest, row["allocation_id"], apply=True)["resumed"]
        with sqlite3.connect(row["path"]) as conn:
            baseline = dict(
                reservations=conn.execute("SELECT * FROM llm_reservations ORDER BY id").fetchall(),
                usage=conn.execute("SELECT * FROM llm_usage ORDER BY id").fetchall(),
            )
            assert (
                hashlib.sha256(json.dumps(baseline).encode()).hexdigest() == baselines[str(index)]
            )
        control_dir, env_path, lease = control_runs[index]
        ctl.capture(control_dir, env_path, row["path"], "owner", lease, apply=True)
        ctl.pause(control_dir, lease, apply=True)
        os.environ["ZYLCH_DB_PATH"] = row["path"]
        os.environ["ZYLCH_PROFILE_DIR"] = str(Path(env_path).parent)
        database.dispose_engine()
        with pytest.raises(budget.BudgetError):
            budget.reserve(
                dict(
                    model="claude-haiku-4-5",
                    messages=[dict(role="user", content="synthetic")],
                    max_tokens=32,
                ),
                "direct",
            )
    for index, row in enumerate(allocations):
        control_dir, env_path, lease = control_runs[index]
        ctl.admit(control_dir, lease, manifest, apply=True)
        os.environ["ZYLCH_DB_PATH"] = row["path"]
        os.environ["ZYLCH_PROFILE_DIR"] = str(Path(env_path).parent)
        database.dispose_engine()
        admitted = budget.reserve(
            dict(
                model="claude-haiku-4-5",
                messages=[dict(role="user", content="synthetic")],
                max_tokens=32,
            ),
            "direct",
        )
        budget.settle(admitted, dict(input_tokens=20, output_tokens=3))
    for control_dir, env_path, lease in control_runs:
        ctl.pause(control_dir, lease, apply=True)
    for index, row in enumerate(allocations):
        control_dir, env_path, lease = control_runs[index]
        os.environ["ZYLCH_DB_PATH"] = row["path"]
        os.environ["ZYLCH_PROFILE_DIR"] = str(Path(env_path).parent)
        database.dispose_engine()
        old = budget.Reservation(
            "old-0", "owner", "claude-haiku-4-5", "direct", 200000, "historical"
        )
        budget.settle(old, dict(input_tokens=20, output_tokens=3))
        assert guard.inspect(manifest, row["allocation_id"])["additional_committed_micro_usd"] == 37
        assert guard.deactivate(manifest, row["allocation_id"], apply=True, intake_stopped=True)[
            "audit_retained"
        ]
        assert guard.inspect(manifest, row["allocation_id"])["reactivation_allowed"] is False
        ctl.restore(control_dir, lease, apply=True)
        with sqlite3.connect(row["path"]) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM llm_usage WHERE id LIKE 'usage-%'").fetchone()[0]
                == usages[index]
            )
            assert (
                conn.execute("SELECT COUNT(*) FROM llm_reservations").fetchone()[0]
                == sizes[index] + 1
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM _m10_acceptance_usage WHERE baseline=1"
                ).fetchone()[0]
                == usages[index]
            )
    database.dispose_engine()
    control_dir, env_path, lease = control_runs[0]
    original = Path(env_path).read_bytes()
    script = str(Path(__file__).resolve())

    def start():
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", script, "--daemon", env_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process

    def read(process):
        process.stdin.write("read\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, process.stderr.read()
        value = json.loads(line)
        assert value["bytecode_disabled"]
        return value

    def stop(process):
        process.communicate(timeout=10)
        assert process.returncode == 0

    old_process = start()
    assert read(old_process)["auto"] is True
    Path(env_path).write_bytes(ctl.files.paused_content(original))
    cached = read(old_process)["auto"]
    assert cached is True
    Path(env_path).write_bytes(original)
    old_identity = dict(pid=old_process.pid, start=ctl.process_start(old_process.pid))
    stop(old_process)
    lease["writers"] = [old_identity]
    restart_directory = str(directory / "restart-controls")
    ctl.capture(restart_directory, env_path, allocations[0]["path"], "owner", lease, apply=True)
    ctl.pause(restart_directory, lease, apply=True)
    paused_process = start()
    paused = read(paused_process)
    assert paused["auto"] is False and paused["budget"] == 0
    stop(paused_process)
    ctl.restore(restart_directory, lease, apply=True)
    restored_process = start()
    restored = read(restored_process)["auto"]
    stop(restored_process)
    proof = dict(
        isolated=bool(sys.flags.isolated),
        bytecode_disabled=bool(sys.flags.dont_write_bytecode),
        baseline_sizes=sizes,
        baseline_usage_rows=usages,
        baseline_hashes=baselines,
        cached_before_restart=cached,
        new_process_after_pause=paused["auto"],
        new_process_after_restore=restored,
        preparation_resumed=False,
        allocations=manifest,
        modules={
            name: dict(
                path=module.__file__,
                sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
            )
            for name, module in [("budget", budget), ("database", database)]
        },
    )
    for module in proof["modules"].values():
        assert Path(module["path"]).resolve().is_relative_to(Path(sys.prefix))
    (directory / "M2-installed-proof.json").write_text(json.dumps(proof, indent=2))
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    if sys.argv[1] == "--daemon":
        daemon(sys.argv[2])
    elif sys.argv[1] == "--journey":
        journey(sys.argv[2], sys.argv[3], sys.argv[4])
