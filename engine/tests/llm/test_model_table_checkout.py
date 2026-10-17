"""The data branch's checkout under the daily job: one run at a time, and no commit left unpushed.

Two runs on one checkout would each rewrite `ledger.json` from their own
copy and erase each other's rows, so a run holds an exclusive `flock` on the
checkout for its whole length and a second one is refused before it reads
anything. A commit an earlier push left behind (HEAD ahead of the remote
branch) is pushed by the next push, even one that changes no file. Local
bare repositories only: nothing reaches the network.
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys

import pytest

from . import model_table_world as world
from .model_table_world import GENIUS, FakeEdges, load_job

job = load_job()
edges = job.edges_of
branch_of = sys.modules["model_table_branch"]
CHALLENGER = {"in": "1", "out": "8", "intelligence": 62, "agentic": 75}


def git(*args, cwd=None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def branch(tmp_path):
    """A bare `origin` holding an orphan `model-table`, and a way to clone it."""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git("init", "-q", "--bare", str(origin))
    git("init", "-q", "-b", "model-table", str(seed))
    git("config", "user.name", "Test", cwd=seed)
    git("config", "user.email", "test@example.invalid", cwd=seed)
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


def test_a_commit_left_unpushed_is_pushed_by_the_next_push_even_with_nothing_new(branch):
    origin, clone = branch
    where = clone("data")
    data = edges.DataBranch(where)
    data.push({"ledger.json": '{"schema": 1}\n'}, "model-table: reserve")
    # A settlement committed whose push failed (the remote was unreachable).
    (where / "v1" / "ledger.json").write_text('{"schema": 1, "settled": 1}\n')
    git("commit", "-q", "-am", "model-table: settles", cwd=where)
    assert git("log", "-1", "--format=%s", "model-table", cwd=origin) == "model-table: reserve"
    data.push({"ledger.json": '{"schema": 1, "settled": 1}\n'}, "model-table: settles again")
    assert git("log", "-1", "--format=%s", "model-table", cwd=origin) == "model-table: settles"
    data.push({"ledger.json": '{"schema": 1, "settled": 1}\n'}, "model-table: nothing")
    assert git("rev-list", "--count", "model-table", cwd=origin) == "3"  # no empty commit


def test_a_second_run_on_one_checkout_is_refused(branch):
    _, clone = branch
    data = edges.DataBranch(clone("data"))
    with data.lock():
        with pytest.raises(branch_of.Busy, match="another run holds the data checkout"):
            with edges.DataBranch(data.root).lock():
                pass
    with data.lock():  # released at the end of the first run
        pass


def test_the_job_refuses_to_start_while_another_run_holds_the_checkout(branch, tmp_path):
    _, clone = branch
    data = edges.DataBranch(clone("data"))
    rig = world.Rig(job, tmp_path)
    rig.world.add(GENIUS, **CHALLENGER)
    fake = FakeEdges(job, rig.world, rig.files)
    real = fake.edges()
    real.lock = data.lock
    lock = data.root / git("rev-parse", "--git-path", "model-table-job.lock", cwd=data.root)
    with lock.open("a") as held:  # another run's lock
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        argv = ["--data", str(data.root), "--report", str(tmp_path / "busy.md")]
        assert job.main(argv, edges=real, roles=rig.roles) == 1
    assert fake.pushes == [] and fake.smoked == [] and fake.measured == []
    assert "another run holds the data checkout" in (tmp_path / "busy.md").read_text()
    assert job.main(argv, edges=real, roles=rig.roles) == 0  # free again: it runs
    assert json.loads(fake.files["ledger.json"])["months"]["2026-10"][0]["settled_at"]
