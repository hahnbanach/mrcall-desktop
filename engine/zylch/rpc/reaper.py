"""Reap zombie children leaked by the whatsmeow Go c-shared library.

The whatsmeow Go runtime is loaded into this Python process via ``ctypes``
by ``neonize``. Running as a guest c-shared library rather than the main
program, it occasionally ``fork``+``exec``s a ``/bin/sh`` helper and never
``wait()``s it. Such a child is a DIRECT child of this process; with
Python's default ``SIGCHLD`` disposition (``SIG_DFL``) the kernel never
auto-reaps it, so it lingers as ``[sh] <defunct>``.

Both engine transports load whatsmeow and therefore need this janitor:
the stdio server (``zylch.rpc.server``, embedded by the desktop app and
the standalone CLI) and the WebSocket ``serve`` daemon
(``zylch.rpc.server_ws``, the multi-tenant VPS backend). Each starts
``reap_orphans_loop`` as a background task for its process lifetime.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _own_zombie_pids() -> set[int]:
    """PIDs of our own direct children currently in zombie (``Z``) state.

    Reads ``/proc`` rather than calling ``waitpid`` — it OBSERVES, it does
    not reap. The comm field in ``/proc/<pid>/stat`` can contain spaces and
    parentheses (``pid (comm) state ppid ...``), so we parse from the right
    of the last ``)``.
    """
    me = str(os.getpid())
    zombies: set[int] = set()
    try:
        names = os.listdir("/proc")
    except OSError:
        return zombies
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", encoding="ascii", errors="replace") as fh:
                data = fh.read()
        except OSError:
            continue  # process vanished or unreadable — ignore
        rparen = data.rfind(")")
        if rparen == -1:
            continue
        rest = data[rparen + 2 :].split()
        if len(rest) < 2:
            continue
        state, ppid = rest[0], rest[1]
        if state == "Z" and ppid == me:
            try:
                zombies.add(int(name))
            except ValueError:
                continue
    return zombies


async def reap_orphans_loop(interval: float = 30.0) -> None:
    """Reap leaked zombie children that nothing else will ``wait()`` on.

    The whatsmeow Go runtime (see the module docstring) leaves
    ``[sh] <defunct>`` zombies parented to this process. We can't make the
    Go side ``wait()``, but we are the parent, so we can.

    The hazard is our OWN ``subprocess.run`` children (the ``run_python`` /
    ``tasks.solve`` tool execution): if we ``waitpid()`` one of those before
    the ``subprocess`` module does, it gets ``ECHILD`` and reports
    ``returncode == 0``, masking a real failure. To stay clear of that race
    we ONLY reap a zombie that has survived a FULL ``interval``: the
    ``subprocess`` module reaps its own children within microseconds of
    exit, so anything still defunct a whole interval later is genuinely
    orphaned. Leaked Go shells sit forever and are always caught (within two
    intervals).
    """
    seen: set[int] = set()
    while True:
        try:
            await asyncio.sleep(interval)
            current = _own_zombie_pids()
            # Defunct for >= one full interval ⇒ not a live subprocess child.
            aged = current & seen
            for pid in aged:
                try:
                    reaped, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue  # already reaped elsewhere
                except OSError as e:
                    logger.debug(f"[reaper] waitpid({pid}) failed: {e}")
                    continue
                if reaped:
                    logger.info(f"[reaper] reaped leaked zombie pid={pid} (status={status})")
            # Carry forward only the young zombies so they age into the next
            # pass; the aged ones we just reaped are gone.
            seen = current - aged
        except asyncio.CancelledError:
            logger.info("[reaper] cancelled — exiting loop")
            raise
        except Exception:
            logger.exception("[reaper] tick crashed — continuing")
