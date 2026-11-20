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
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from .model_table_world import K3, load_job

job = load_job()
edges = job.edges_of
FLASH = "acme/flash-1"
CORPUS = ("MNEMONIC", "MEMORY_EXTRACT", "MEMORY_MERGE")

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
    monkeypatch.setattr(job.process, "GRACE_SECONDS", 1)
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


SETTLED = {"intent_id": "a", "settled": True, "calls": 1, "cost_micro_usd": 912}
INTENTS = [
    {"intent_id": "a", "case_id": "one", "bound_micro_usd": 8204},
    SETTLED,
    {"intent_id": "b", "case_id": "two", "bound_micro_usd": 8214},  # open at the stop
]


@pytest.mark.parametrize(
    "journal, charged",
    [
        ("".join(json.dumps(row) + "\n" for row in INTENTS), Decimal("0.009126")),
        ('{"intent_id": "a", "case_id"\n', Decimal("2")),  # unreadable: the whole cap
        (None, Decimal("2")),  # no journal at all: the whole cap
    ],
)
def test_a_corpus_run_stopped_at_its_limit_is_charged_its_intents_and_loses_its_key_file(
    tmp_path, journal, charged
):
    def key_file(kwargs, command):
        profile = Path(kwargs["env"]["MNEMONIC_CORPUS_PROFILE_DIR"])
        profile.mkdir(parents=True)
        (profile / ".env").write_text("not a key")
        if journal is not None:
            (profile / "corpus-intents.jsonl").write_text(journal)

    run, seen = stopped(key_file)
    measure = edges.Measurement(tmp_path, Decimal("2"), K3, run=run)
    with pytest.raises(edges.Incomplete, match="stopped at its time limit of 20 min") as raised:
        measure("MEMORY_EXTRACT", FLASH, {})
    # The first run's killed corpus run: one case settled (912), one open at its bound.
    assert raised.value.spent_usd == charged
    assert raised.value.timed_out and raised.value.roles == CORPUS
    assert seen["timeout"] == 1200
    assert list(tmp_path.rglob(".env")) == []


def test_a_harness_measurement_makes_its_profile_where_the_sweep_finds_it(tmp_path):
    seen = {}

    def run(command, **kwargs):
        seen["tmpdir"] = kwargs["env"]["TMPDIR"]
        seen["out"] = command[command.index("--out") + 1]
        return subprocess.CompletedProcess(command, 1, "", "refused: test")

    with pytest.raises(edges.Incomplete) as raised:
        edges.Measurement(tmp_path, Decimal("2"), K3, run=run)("CHAT", FLASH, {})
    assert seen["tmpdir"] == seen["out"] and not raised.value.timed_out


def test_a_smokes_limit_is_its_worst_case_under_the_engines_http_timeouts():
    limit = job.deadline_of.limit_minutes
    assert limit("smoke", None, FLASH) == 7  # two calls of at most 180 s, and setup
    assert limit("smoke", None, K3) == 21  # the K3 Chat path: two of at most 600 s
    assert limit("smoke", None, None) == 21  # unknown: the worst case
    assert limit("measure", "CHAT") == 10 and limit("measure", "MNEMONIC") == 20
    start = datetime(2026, 10, 14, 5, 17, tzinfo=timezone.utc)
    deadline = job.deadline_of.Deadline(start, 90)
    assert deadline.late("smoke", None, start + timedelta(minutes=83), FLASH) is None
    assert "may take 7 min" in deadline.late("smoke", None, start + timedelta(minutes=84), FLASH)
    assert "may take 21 min" in deadline.late("smoke", None, start + timedelta(minutes=70), K3)
    # Every check ends by the deadline; a stopped one is killed after the grace.
    longest = max(job.deadline_of.LIMIT_MINUTES.values())
    assert longest < 90 and 90 + job.process.GRACE_SECONDS / 60 + 10 <= 120


PARENT = """
import sys
sys.path.insert(0, sys.argv[1])
import model_table_process as process
process.interrupt_on_terminate()
try:
    process.limited_run([sys.executable, "-c", sys.argv[2], sys.argv[3], sys.argv[4]], timeout=120)
except KeyboardInterrupt:
    sys.exit(3)
"""
CHILD = """
import os, pathlib, sys, time
key, pid = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
key.write_text("not a key")
pid.write_text(str(os.getpid()))
try:
    time.sleep(120)
finally:
    key.unlink()
"""


def _alive(pid: int) -> bool:
    """Whether `pid` still runs (a zombie nobody reaped yet does not)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file():
        try:
            return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
    return True


def _started(parent, key: Path, pid: Path) -> int:
    for _ in range(400):
        if pid.exists() and pid.read_text() and key.exists():
            return int(pid.read_text())
        time.sleep(0.05)
    parent.kill()
    raise AssertionError("the measurement process never started")


def _gone(child: int) -> bool:
    for _ in range(200):
        if not _alive(child):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_an_interrupted_job_stops_its_measurement_process_before_it_goes(tmp_path, signum):
    key, pid = tmp_path / ".env", tmp_path / "child.pid"
    scripts = str(Path(job.__file__).parent)
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT, scripts, CHILD, str(key), str(pid)],
        start_new_session=True,  # the signal below reaches the job alone
    )
    try:
        child = _started(parent, key, pid)
        parent.send_signal(signum)  # the job only: `kill -INT <pid>`, a terminate, a hang-up
        assert parent.wait(timeout=30) == 3  # it went on as an interrupt, after the child
        assert _gone(child)  # no orphan with no time limit
        assert not key.exists()  # its finally ran: the key file is gone
    finally:
        parent.kill()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux's")
def test_a_job_killed_outright_takes_its_measurement_process_with_it(tmp_path):
    key, pid = tmp_path / ".env", tmp_path / "child.pid"
    scripts = str(Path(job.__file__).parent)
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT, scripts, CHILD, str(key), str(pid)],
        start_new_session=True,
    )
    child = _started(parent, key, pid)
    try:
        parent.kill()  # SIGKILL: an OOM kill, `timeout -k`; no handler runs
        parent.wait(timeout=30)
        assert _gone(child)  # the kernel killed it with its parent
    finally:
        if _alive(child):
            os.kill(child, signal.SIGKILL)


def test_each_run_journals_apart_and_a_killed_runs_key_file_is_deleted(tmp_path):
    work, data = tmp_path / "work", tmp_path / "data"
    left = work / "run-20261012T141304Z-x" / "measure-51-y" / "profile" / ".env"
    harness = work / "run-20261012T141304Z-x" / "measure-2-z" / "measurement-profile-q" / ".env"
    for path in (left, harness):
        path.parent.mkdir(parents=True)
        path.write_text("not a key")
    kept = work / "notes" / ".env"  # not a measurement profile's: untouched
    kept.parent.mkdir()
    kept.write_text("x")
    first = edges.default(data, None, work, Decimal("10"))
    second = edges.default(data, None, work, Decimal("10"))
    assert not left.exists() and not harness.exists() and kept.exists()
    for real in (first, second):
        assert real.smoke.work.parent == work and real.smoke.work.name.startswith("run-")
        assert real.measure.work == real.smoke.work
        assert real.smoke.work.stat().st_mode & 0o777 == 0o700
    assert first.smoke.work != second.smoke.work  # smoke-1.jsonl is never reused
