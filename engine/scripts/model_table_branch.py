"""The `model-table` data branch's checkout, as the daily job reads, locks and pushes it.

- `read` returns the bytes of the `v1/` files (None for one it lacks).
- `push` writes files under `v1/`, commits them and pushes the branch with the
  credentials the checkout holds (the workflow token in CI). A push the
  remote refuses (a checkout behind the branch) raises, so a run never pays
  after a reservation it could not record. A commit an earlier push left
  unpushed (HEAD ahead of the remote branch) is pushed with the next call,
  even when that call changes no file: a settlement identical to what the
  checkout already holds still reaches the branch, or the call raises.
- `lock` holds an exclusive `flock` on the checkout for a whole run (in its
  git directory: `git rev-parse --git-path model-table-job.lock`). A second
  run on the same checkout is refused before it reads anything: two runs
  would each rewrite `ledger.json` from their own copy and erase each
  other's rows. Across checkouts the workflow's `concurrency` and, before
  the desktop merge, the coordinator alone keep one publisher at a time.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import subprocess
from pathlib import Path

import resolve_models as rm

logger = logging.getLogger(__name__)
FILES = ("table.json", "snapshot.json", "measured.json", "ledger.json", "results.json")
LOCK = "model-table-job.lock"


class Busy(RuntimeError):
    """Another run holds the checkout's lock."""


class DataBranch:
    """The data branch's checkout (module docstring)."""

    def __init__(self, root: Path, branch: str = "model-table", remote: str = "origin"):
        self.root, self.branch, self.remote = Path(root), branch, remote

    def _git(self, *args: str, check: bool = True) -> str:
        done = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, check=False
        )
        if check and done.returncode != 0:
            raise RuntimeError(
                f"git {args[0]} failed: {done.stderr.strip() or done.stdout.strip()}"
            )
        return done.stdout if done.returncode == 0 else ""

    def read(self) -> dict:
        """`{name: bytes or None}` for the `v1/` files."""
        folder = self.root / "v1"
        return {n: (folder / n).read_bytes() if (folder / n).is_file() else None for n in FILES}

    def _ahead(self) -> bool:
        """Whether HEAD differs from the remote branch as last pushed or fetched."""
        head = self._git("rev-parse", "HEAD").strip()
        ref = f"refs/remotes/{self.remote}/{self.branch}"
        upstream = self._git("rev-parse", "--verify", "-q", ref, check=False).strip()
        return head != upstream

    def push(self, files: dict, message: str) -> None:
        """Write `files` (`{name: text}`) under `v1/`, commit what changed and
        push whenever HEAD is not the remote branch (module docstring)."""
        folder = self.root / "v1"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            rm.write_atomically(folder / name, text)
        self._git("add", "--", *(f"v1/{name}" for name in files))
        if self._git("diff", "--cached", "--name-only").strip():
            self._git("commit", "-q", "-m", message)
        if self._ahead():
            self._git("push", "-q", self.remote, f"HEAD:{self.branch}")
            self._git("update-ref", f"refs/remotes/{self.remote}/{self.branch}", "HEAD")

    @contextlib.contextmanager
    def lock(self):
        """Hold the checkout's exclusive lock for the run, or raise Busy."""
        where = self._git("rev-parse", "--git-path", LOCK, check=False).strip()
        if not where:  # not a git checkout (a dry run on a plain copy): beside its files
            where = f".{LOCK}"
        path = Path(where) if os.path.isabs(where) else self.root / where
        handle = path.open("a")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Busy(f"another run holds the data checkout {self.root} (its lock)") from None
            logger.debug(f"[model-table] lock({self.root}) -> held")
            yield
        finally:
            handle.close()  # closing the descriptor releases the lock
