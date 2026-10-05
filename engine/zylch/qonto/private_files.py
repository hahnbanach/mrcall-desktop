"""Private file creation and bounded process locking on POSIX and Windows."""

from __future__ import annotations

import os
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from zylch.qonto.errors import QontoError

_locks: dict[str, threading.RLock] = {}
_registry_lock = threading.Lock()


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.resolve() != path.absolute():
        raise QontoError("encryption_unavailable")
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise QontoError("encryption_unavailable")


def _check_fd(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise QontoError("encryption_unavailable")
    if os.name != "nt" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise QontoError("encryption_unavailable")


def private_read(path: Path) -> bytes:
    if path.is_symlink():
        raise QontoError("encryption_unavailable")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _check_fd(fd)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            value = stream.read(4097)
        if len(value) > 4096:
            raise QontoError("encryption_unavailable")
        return value
    finally:
        os.close(fd)


def exclusive_write(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(value)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    if os.name != "nt":
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


@contextmanager
def private_lock(path: Path, timeout: float = 5.0):
    private_directory(path.parent)
    key = str(path.absolute())
    with _registry_lock:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout):
        raise QontoError("busy")
    fd = None
    acquired = False
    try:
        if path.is_symlink():
            raise QontoError("encryption_unavailable")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        _check_fd(fd)
        if not os.fstat(fd).st_size:
            os.write(fd, b"0")
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise QontoError("busy") from None
                time.sleep(0.01)
        yield
    finally:
        if fd is not None:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        lock.release()
