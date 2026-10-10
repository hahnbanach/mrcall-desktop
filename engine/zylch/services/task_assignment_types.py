"""Bounded, canonical task-assignment operations shared by approval and storage."""

import hashlib
import json
import re
import time
import uuid
from typing import Any


class AssignmentError(ValueError):
    def __init__(self, message: str, code: int = -32060) -> None:
        self.code = code
        super().__init__(message)


def canonical(value: Any) -> bytes:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (ValueError, TypeError, UnicodeError):
        raise AssignmentError("Invalid assignment payload", -32602) from None
    if len(raw) > 131072:
        raise AssignmentError("Assignment payload is too large", -32602)
    return raw


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value: Any) -> str:
    if not isinstance(value, str):
        raise AssignmentError("Invalid operation identity", -32602)
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise AssignmentError("Invalid operation identity", -32602) from None
    return value


def text(value: Any, maximum: int, *, empty: bool = False) -> str:
    try:
        size = len(value.encode("utf-8")) if isinstance(value, str) else maximum + 1
    except UnicodeError:
        raise AssignmentError("Invalid assignment text", -32602) from None
    if (
        not isinstance(value, str)
        or size > maximum
        or (not value and not empty)
        or any(ord(c) < 32 for c in value)
    ):
        raise AssignmentError("Invalid assignment text", -32602)
    return value


def thread(value: Any) -> str:
    value = text(value, 998)
    if not re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", value):
        raise AssignmentError("Exact RFC thread root Message-ID required", -32602)
    return value


FIELDS = frozenset(
    {
        "version",
        "operation",
        "operation_id",
        "actor_uid",
        "space_id",
        "thread_key",
        "task_id",
        "expected_revision",
        "assignee_uid",
        "reason",
        "handled_ref",
        "covered_inbound",
        "source_confirmation",
        "source_snapshot",
        "created_at",
        "expires_at",
    }
)


def validate_intent(value: Any, *, fresh: bool = True) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise AssignmentError("Invalid assignment operation", -32602)
    canonical(value)
    start, end = value["created_at"], value["expires_at"]
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 < end - start <= 300
        or start > int(time.time()) + 5
        or (fresh and end <= int(time.time()))
    ):
        raise AssignmentError("Assignment operation expired or invalid")
    for key in ("operation_id", "space_id", "task_id"):
        identifier(value[key])
    text(value["actor_uid"], 128)
    thread(value["thread_key"])
    op = value["operation"]
    if not isinstance(op, str) or op not in {"assign", "reassign", "close"}:
        raise AssignmentError("Invalid assignment operation", -32602)
    rev = value["expected_revision"]
    if type(rev) is not int or rev < 0 or (op != "assign" and rev == 0):
        raise AssignmentError("Invalid assignment revision", -32602)
    if op == "close":
        if value["assignee_uid"] is not None:
            raise AssignmentError("Close cannot change the assignee", -32602)
        text(value["reason"], 1000)
        text(value["handled_ref"], 256)
        if not isinstance(value["source_snapshot"], dict):
            raise AssignmentError("Close requires a complete source snapshot", -32602)
        snapshot = value["source_snapshot"]
        if (
            set(snapshot) != {"digest", "observed_at"}
            or not isinstance(snapshot["digest"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", snapshot["digest"])
            or type(snapshot["observed_at"]) is not int
            or snapshot["observed_at"] > int(time.time()) + 5
            or snapshot["observed_at"] < value["created_at"] - 5
        ):
            raise AssignmentError("Invalid source snapshot identity", -32602)
    else:
        text(value["assignee_uid"], 128)
        text(value["reason"], 1000, empty=True)
        if value["handled_ref"] is not None or value["source_snapshot"] is not None:
            raise AssignmentError("Invalid assignment-only fields", -32602)
    covered = value["covered_inbound"]
    if (
        not isinstance(covered, list)
        or len(covered) > 1000
        or any(not isinstance(item, str) for item in covered)
        or covered != sorted(set(covered))
    ):
        raise AssignmentError("Inbound identities must be canonical and bounded", -32602)
    for item in covered:
        text(item, 2048)
    if op != "close" and covered:
        raise AssignmentError("Only closure may acknowledge inbound coverage", -32602)
    confirmation = value["source_confirmation"]
    if confirmation is not None:
        if op == "close":
            raise AssignmentError("Closure cannot confirm a reply source", -32602)
        if (
            not isinstance(confirmation, dict)
            or set(confirmation) != {"source_id", "digest"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(confirmation["digest"]))
        ):
            raise AssignmentError("Invalid supervised source confirmation", -32602)
        text(confirmation["source_id"], 256)
    return value
