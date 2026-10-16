"""Exact private file snapshots and replacement under an external maintenance lease."""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import stat
import tempfile

from dotenv.parser import parse_stream


class Refused(RuntimeError):
    """Controls must remain paused until their owner resolves drift."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(path: str) -> tuple[dict, bytes]:
    target = Path(path)
    if not target.is_absolute() or target.parent.resolve() != target.parent:
        raise Refused("Control path must be canonical and absolute")
    try:
        info = target.lstat()
    except FileNotFoundError:
        parent = target.parent.stat()
        return (
            dict(present=False, sha256=None, mode=0o600, uid=parent.st_uid, gid=parent.st_gid),
            b"",
        )
    if not stat.S_ISREG(info.st_mode):
        raise Refused("Control file must be regular, never a symlink")
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (actual.st_dev, actual.st_ino):
            raise Refused("Control identity changed while opening")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read()
    finally:
        os.close(fd)
    return (
        dict(
            present=True,
            sha256=digest(content),
            mode=stat.S_IMODE(info.st_mode),
            uid=info.st_uid,
            gid=info.st_gid,
        ),
        content,
    )


def paused_content(content: bytes) -> bytes:
    try:
        bindings = list(parse_stream(io.StringIO(content.decode("utf-8"))))
    except UnicodeError as exc:
        raise Refused("Saved settings are not valid UTF-8") from exc
    keys = [row.key for row in bindings if row.key is not None]
    if any(row.error for row in bindings) or len(keys) != len(set(keys)):
        raise Refused("Malformed or duplicate saved setting keys")
    replacements = {"LLM_DAILY_BUDGET_USD": "0", "AUTO_UPDATE_ENABLED": "n"}
    result = []
    for row in bindings:
        if row.key in replacements:
            result.append(f"{row.key}={replacements.pop(row.key)}\n")
        else:
            result.append(row.original.string)
    text = "".join(result)
    if replacements and text and not text.endswith(("\n", "\r")):
        text += "\n"
    text += "".join(f"{key}={value}\n" for key, value in replacements.items())
    return text.encode("utf-8")


def exact(path: str, expected: dict) -> None:
    if snapshot(path)[0] != expected:
        raise Refused("Saved control file drift; no overwrite authorized")


def replace(path: str, expected: dict, content: bytes | None, identity: dict) -> dict:
    exact(path, expected)
    if os.geteuid() != 0 and (
        identity["uid"] != os.geteuid() or identity["gid"] not in {os.getegid(), *os.getgroups()}
    ):
        raise Refused("Executor cannot preserve deployment ownership")
    if content is None:
        exact(path, expected)
        Path(path).unlink()
    else:
        fd, temporary = tempfile.mkstemp(prefix=".m10-controls-", dir=Path(path).parent)
        try:
            os.fchown(fd, identity["uid"], identity["gid"])
            os.fchmod(fd, identity["mode"])
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(fd)
            exact(path, expected)
            os.replace(temporary, path)
        finally:
            os.close(fd)
            if Path(temporary).exists():
                Path(temporary).unlink()
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    result = snapshot(path)[0]
    desired = identity | {
        "present": content is not None,
        "sha256": None if content is None else digest(content),
    }
    if result != desired:
        raise Refused("Control replacement metadata verification failed; retain pause")
    return result


def private_write(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    if exclusive and path.exists():
        raise Refused("Existing control evidence cannot be reset")
    if path.exists():
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise Refused("Control evidence ownership/mode changed")
    fd, temporary = tempfile.mkstemp(prefix=".m10-evidence-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(fd)
        if exclusive:
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
    finally:
        os.close(fd)
        if Path(temporary).exists():
            Path(temporary).unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def admitted_content(content: bytes) -> bytes:
    bindings = list(parse_stream(io.StringIO(content.decode("utf-8"))))
    paused_content(content)
    result, found = [], False
    for binding in bindings:
        if binding.key == "AUTO_UPDATE_ENABLED":
            result.append("AUTO_UPDATE_ENABLED=n\n")
            found = True
        else:
            result.append(binding.original.string)
    value = "".join(result)
    if not found:
        if value and not value.endswith(("\n", "\r")):
            value += "\n"
        value += "AUTO_UPDATE_ENABLED=n\n"
    return value.encode()


def original_budget_enabled(content: bytes) -> bool:
    from decimal import Decimal, InvalidOperation

    values = {
        binding.key: binding.value
        for binding in parse_stream(io.StringIO(content.decode("utf-8")))
        if binding.key
    }
    try:
        amount = Decimal(str(values.get("LLM_DAILY_BUDGET_USD") or "").strip() or "10")
    except InvalidOperation as exc:
        raise Refused("Original saved budget is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise Refused("Original saved budget is invalid")
    return amount > 0
