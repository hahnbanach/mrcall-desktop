"""The daily job's time limits at its edges, and the run's own work directory (S5b).

A measurement runs in a process of its own and is stopped at its time limit
(`model_table_deadline.limit_minutes`): interrupted first, so its `finally`
blocks delete its key file, then killed; what its ledger recorded is
charged, an open intent at its bound. Each run journals in a directory of
its own, and a key file an earlier, killed run left behind is deleted.
Nothing here reaches the network: the processes are local Python one-liners
or stand-ins.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from .model_table_world import K3, load_job

job = load_job()
edges = job.edges_of
FLASH = "acme/flash-1"

HOLDS_A_KEY = """
import pathlib, sys, time
path = pathlib.Path(sys.argv[1])
path.write_text("not a key")
try:
    time.sleep(60)
finally:
    path.unlink()
"""
IGNORES_INTERRUPTS = """
import signal, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
print("started", flush=True)
time.sleep(60)
"""


def test_a_process_at_its_limit_is_interrupted_and_cleans_up(tmp_path):
    key = tmp_path / ".env"
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        edges.limited_run(
            [sys.executable, "-c", HOLDS_A_KEY, str(key)],
            timeout=1.5,
            capture_output=True,
            text=True,
        )
    assert not key.exists()  # its finally ran: the key file is gone
    assert time.monotonic() - began < 20


def test_a_process_that_ignores_the_interrupt_is_killed_after_the_grace(monkeypatch):
    monkeypatch.setattr(edges, "GRACE_SECONDS", 1)
    began = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        edges.limited_run([sys.executable, "-c", IGNORES_INTERRUPTS], timeout=1, text=True)
    assert time.monotonic() - began < 20


def test_a_process_within_its_limit_is_a_completed_process():
    done = edges.limited_run(
        [sys.executable, "-c", "print('ok')"], timeout=30, capture_output=True, text=True
    )
    assert (done.returncode, done.stdout) == (0, "ok\n")


def stopped(write):
    """A stand-in process: `write(kwargs, command)` leaves its traces, then
    the time limit stops it."""
    seen = {}

    def run(command, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        write(kwargs, command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    return run, seen


def test_a_measurement_stopped_at_its_limit_is_charged_what_its_ledger_holds(tmp_path):
    def intent(kwargs, command):
        out = Path(command[command.index("--out") + 1])
        row = {"event": "intent", "id": "CHAT|x|c1|r1#d0", "cell": "c", "bound_micro_usd": 47265}
        (out / "ledger.jsonl").write_text(json.dumps(row) + "\n")

    run, seen = stopped(intent)
    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=run)
    with pytest.raises(edges.Incomplete, match="stopped at its time limit of 10 min") as raised:
        measure("CHAT", FLASH, {})
    assert raised.value.spent_usd == Decimal("0.047265")  # the open intent at its bound
    assert seen["timeout"] == 600


def test_a_corpus_run_stopped_at_its_limit_counts_its_cap_and_loses_its_key_file(tmp_path):
    def key_file(kwargs, command):
        profile = Path(kwargs["env"]["MNEMONIC_CORPUS_PROFILE_DIR"])
        profile.mkdir(parents=True)
        (profile / ".env").write_text("not a key")

    run, seen = stopped(key_file)
    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=run)
    with pytest.raises(edges.Incomplete, match="stopped at its time limit of 20 min") as raised:
        measure("MEMORY_EXTRACT", FLASH, {})
    assert raised.value.spent_usd == Decimal("2")  # no record: the whole cap counts
    assert seen["timeout"] == 1200
    assert list(tmp_path.rglob(".env")) == []


def test_each_run_journals_apart_and_a_killed_runs_key_file_is_deleted(tmp_path):
    work, data = tmp_path / "work", tmp_path / "data"
    left = work / "run-20261012T141304Z-x" / "measure-51-y" / "profile" / ".env"
    left.parent.mkdir(parents=True)
    left.write_text("not a key")
    kept = work / "notes" / ".env"  # not a measurement profile's: untouched
    kept.parent.mkdir()
    kept.write_text("x")
    first = edges.default(data, None, work, Decimal("10"))
    second = edges.default(data, None, work, Decimal("10"))
    assert not left.exists() and kept.exists()
    for real in (first, second):
        assert real.smoke.work.parent == work and real.smoke.work.name.startswith("run-")
        assert real.measure.work == real.smoke.work
        assert real.smoke.work.stat().st_mode & 0o777 == 0o700
    assert first.smoke.work != second.smoke.work  # smoke-1.jsonl is never reused
