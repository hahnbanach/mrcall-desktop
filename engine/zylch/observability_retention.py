"""Bounded private retention for the profile's existing engine log files."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import stat
import time
from pathlib import Path
from typing import Iterator

from .observability_producers import observe


class ProfileLogHandler(logging.Handler):
    """Append under an interprocess lock and enforce existing-log retention."""

    def __init__(
        self,
        profile: Path,
        *,
        max_bytes: int = 128 * 1024**2,
        segment_bytes: int = 16 * 1024**2,
        days: int = 7,
    ):
        super().__init__()
        self.profile = Path(profile).absolute()
        self.max_bytes = max_bytes
        self.segment_bytes = min(segment_bytes, max_bytes)
        self.seconds = days * 86400
        self.last_prune_ok = self.prune()

    def _open(self, path: Path, flags: int) -> int:
        fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            os.close(fd)
            raise PermissionError("Unsafe engine log")
        os.fchmod(fd, 0o600)
        return fd

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        if any(path.is_symlink() for path in (self.profile, *self.profile.parents)):
            raise PermissionError("Unsafe engine profile log path")
        fd = self._open(self.profile / ".engine-log.lock", os.O_RDWR | os.O_CREAT)
        started = time.monotonic()
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started >= 0.05:
                        raise TimeoutError("Engine log lock unavailable")
                    time.sleep(0.001)
            yield
        finally:
            os.close(fd)

    def _files(self) -> list[Path]:
        paths = [
            path
            for path in self.profile.glob("zylch.log*")
            if re.fullmatch(r"zylch\.log(?:\.[0-9]+)?", path.name)
        ]
        if len(paths) > 1024:
            raise ValueError("Engine log inventory exceeds bound")
        for path in paths:
            fd = self._open(path, os.O_RDONLY)
            os.close(fd)
        return sorted(paths, key=lambda path: path.stat().st_mtime)

    def _started(self, path: Path) -> float:
        suffix = path.name.removeprefix("zylch.log.")
        if suffix.isdigit() and len(suffix) >= 16:
            return int(suffix) / 1_000_000_000
        marker = self.profile / ".engine-log-start"
        if path.name == "zylch.log" and marker.exists():
            fd = self._open(marker, os.O_RDONLY)
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(40)
            return int(raw) / 1_000_000_000
        return path.stat().st_mtime

    def _prune(self) -> None:
        paths = self._files()
        total = sum(path.stat().st_size for path in paths)
        removed = 0
        for path in paths:
            if total <= self.max_bytes and time.time() - self._started(path) < self.seconds:
                continue
            total -= path.stat().st_size
            path.unlink()
            removed += 1
        if removed:
            fd = self._open(
                self.profile / ".engine-log-retention.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            )
            with os.fdopen(fd, "w") as stream:
                json.dump({"removed_files": removed, "observed_at": time.time()}, stream)
            observe("cleanup", "result", reason="logging", count=removed)

    def prune(self) -> bool:
        """Maintain only exact known engine log names without business effects."""
        try:
            with self._locked():
                self._prune()
            self.last_prune_ok = True
            return True
        except Exception:
            self.last_prune_ok = False
            observe("cleanup", "failed", reason="logging")
            return False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            data = (self.format(record) + "\n").encode("utf-8", errors="replace")
            if len(data) > self.segment_bytes:
                raise ValueError("Engine log record exceeds bounded segment")
            with self._locked():
                self._prune()
                target = self.profile / "zylch.log"
                if target.exists() and target.stat().st_size + len(data) > self.segment_bytes:
                    target.rename(
                        self.profile / f"zylch.log.{int(self._started(target) * 1_000_000_000)}"
                    )
                if not target.exists():
                    marker = self._open(
                        self.profile / ".engine-log-start", os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                    )
                    with os.fdopen(marker, "w") as stream:
                        stream.write(str(time.time_ns()))
                fd = self._open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                self._prune()
        except Exception:
            observe("cleanup", "failed", reason="logging")


def maintain_profile(profile: Path, owner_uid: str) -> dict:
    """Maintain a fixed deployed profile even while its engine is stopped."""
    from .observability import EventStore

    profile = Path(profile).absolute()
    if profile.name != owner_uid:
        return {"status": "unavailable", "count": 0}
    handler = ProfileLogHandler(profile)
    if not handler.last_prune_ok:
        return {"status": "degraded", "count": 0}
    event_store = EventStore(profile / "observability", owner_uid, component="engine")
    if not event_store.root.exists():
        return {"status": "observed", "count": 0}
    result = event_store.prune()
    return {"status": "observed" if result["complete"] else "degraded", "count": result["removed"]}
