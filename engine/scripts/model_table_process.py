"""The daily model-table job's processes: a time limit that never orphans a child, interrupts.

- `limited_run` is `subprocess.run` for a measurement process. The child is
  started in a session of its own, so a terminal's Ctrl-C or a runner's
  signal to the job's process group reaches the job alone, and the job
  passes on exactly one interrupt. At its time limit the child is
  interrupted (SIGINT: its `finally` blocks run, so a measurement profile's
  key file is deleted), then killed after `GRACE_SECONDS`; TimeoutExpired is
  raised. When the job itself is interrupted while it waits (SIGINT, or
  SIGTERM through `interrupt_on_terminate`), the child is interrupted too and
  killed after `INTERRUPTED_GRACE_SECONDS`, short enough that the job can
  still push its settlement inside a cancelled workflow's window (SIGINT,
  then SIGTERM 7.5 s later, then SIGKILL); then the interrupt goes on.
  When the job dies without a chance to do so (SIGKILL: an OOM kill,
  `timeout -k`), the child dies with it: on Linux it asks the kernel, before
  it runs, for SIGKILL on its parent's death (`prctl(PR_SET_PDEATHSIG)`,
  `_die_with_parent`). Its key file is then left to the next run's sweep (in
  CI the runner's temporary directory goes with the job). Elsewhere the call
  works without that guard. No child outlives the call.
- `interrupt_on_terminate` makes SIGTERM and SIGHUP raise KeyboardInterrupt,
  as SIGINT does, so a terminated or hung-up run settles itself
  (`model_table_job.py`) when it is given the time; otherwise the next run
  recovers its reservation.
- `sweep_keys` deletes the key files an earlier run, killed before its own
  clean-up, left in the measurement profiles under the work directory: a
  corpus run's `profile/.env` and a harness run's
  `measurement-profile-*/.env` (the harness profile is created there:
  `TMPDIR` is the measurement's directory).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
GRACE_SECONDS = 30
INTERRUPTED_GRACE_SECONDS = 5
PR_SET_PDEATHSIG = 1  # linux/prctl.h


def _stop(proc: subprocess.Popen, grace: float):
    """Interrupt `proc`, wait `grace` seconds, kill it; its output."""
    if proc.poll() is None:
        proc.send_signal(signal.SIGINT)
    try:
        return proc.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.communicate()


def _die_with_parent(parent: int):
    """The child's `preexec_fn` on Linux: SIGKILL when the job dies; and
    exit at once if the job already died before the request was made."""

    def arm() -> None:
        import ctypes

        try:
            libc = ctypes.CDLL(None, use_errno=True)
            libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        except (OSError, AttributeError):
            return  # no prctl: the guard is lost, the call still works
        if os.getppid() != parent:
            os._exit(1)

    return arm


def limited_run(command, *, timeout=None, **kwargs):
    """`subprocess.run` under a time limit (module docstring)."""
    kwargs.pop("check", None)
    if kwargs.pop("capture_output", False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if sys.platform.startswith("linux"):
        kwargs["preexec_fn"] = _die_with_parent(os.getpid())
    proc = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        out, err = _stop(proc, GRACE_SECONDS)
        raise subprocess.TimeoutExpired(command, timeout, out, err) from None
    except BaseException:
        logger.debug(f"[model-table] limited_run interrupted: stopping child {proc.pid}")
        _stop(proc, INTERRUPTED_GRACE_SECONDS)
        raise
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def _interrupt(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def interrupt_on_terminate() -> None:
    """SIGTERM and SIGHUP raise KeyboardInterrupt from now on (module docstring)."""
    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGHUP, _interrupt)


def sweep_keys(work: Path) -> int:
    """Delete the measurement profiles' key files under `work`; how many."""
    stale = [
        path
        for path in work.rglob(".env")
        if path.parent.name == "profile" or path.parent.name.startswith("measurement-profile-")
    ]
    for path in stale:
        path.unlink(missing_ok=True)
    logger.debug(f"[model-table] sweep_keys({work}) -> {len(stale)} stale key files deleted")
    return len(stale)
