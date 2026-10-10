"""Operator-owned company membership and public approval material."""

import base64
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .task_assignment_types import AssignmentError, identifier, text

TRUST_DIRECTORY = Path("/etc/mrcalld/assignment-trust")
SIGNING_DIRECTORY = Path("/etc/mrcalld/assignment-signing")


def protected_read(path: Path, *, private: bool = False, missing_ok: bool = False) -> bytes | None:
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise AssignmentError("Assignment trust path refused")
    fd = None
    try:
        flags = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open("/", flags)
        _check(os.fstat(fd), directory=True)
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            _check(os.fstat(fd), directory=True)
        child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        os.close(fd)
        fd = child
        info = os.fstat(fd)
        _check(info, directory=False, private=private)
        if info.st_size > 65536:
            raise AssignmentError("Assignment trust file is too large")
        raw = os.read(fd, 65537)
        if len(raw) > 65536:
            raise AssignmentError("Assignment trust file is too large")
        return raw
    except FileNotFoundError:
        if missing_ok:
            return None
        raise AssignmentError("Assignment trust is unavailable") from None
    except OSError:
        raise AssignmentError("Assignment trust is unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def _check(info: os.stat_result, *, directory: bool, private: bool = False) -> None:
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not expected
        or info.st_uid != 0
        or info.st_mode & 0o022
        or (private and info.st_mode & 0o077)
    ):
        raise AssignmentError("Assignment trust permissions refused")


def load(space_id: str) -> dict[str, Any]:
    identifier(space_id)
    return parse(protected_read(TRUST_DIRECTORY / f"{space_id}.json"), space_id)


def parse(raw: bytes, space_id: str) -> dict[str, Any]:
    identifier(space_id)
    try:
        trust = json.loads(raw)
        if (
            not isinstance(trust, dict)
            or set(trust) != {"version", "issuer", "space_id", "public_key", "members"}
            or type(trust["version"]) is not int
            or trust["version"] != 1
            or trust["space_id"] != space_id
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", trust["issuer"])
            or not isinstance(trust["members"], dict)
            or not trust["members"]
        ):
            raise ValueError
        seen = set()
        for uid, aliases in trust["members"].items():
            text(uid, 128)
            if not isinstance(aliases, list) or not aliases:
                raise ValueError
            for alias in aliases:
                if (
                    not isinstance(alias, str)
                    or alias != alias.strip().lower()
                    or not re.fullmatch(r"[^\s@]+@[^\s@]+", alias)
                    or alias in seen
                ):
                    raise ValueError
                seen.add(alias)
        public_key(trust)
        return trust
    except (ValueError, TypeError, KeyError):
        raise AssignmentError("Assignment trust document refused") from None


def public_key(trust: dict[str, Any]) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(trust["public_key"], validate=True)
        )
    except (ValueError, TypeError, KeyError):
        raise AssignmentError("Assignment approval key refused") from None


def member(trust: dict[str, Any], uid: str, mailbox: str | None = None) -> None:
    text(uid, 128)
    aliases = trust["members"].get(uid)
    if not aliases or (mailbox is not None and mailbox not in aliases):
        raise AssignmentError("Current company membership refused")


def probe(space_id: str) -> dict | None:
    """Only safely inspected ENOENT is absence; malformed/unreadable refuses."""
    identifier(space_id)
    raw = protected_read(TRUST_DIRECTORY / f"{space_id}.json", missing_ok=True)
    return None if raw is None else load(space_id)
