"""Request-scoped mutation policy enforced before chat routing and at tools."""

from __future__ import annotations

import contextlib
import contextvars
import re
from typing import Iterator, Sequence

READ_ONLY_POLICY = "read_only"
READ_ONLY_POLICY_VERSION = 1

_policy: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_mutation_policy", default=None
)

# Tool names are effects, not UI approval names.  A read-only origin cannot
# widen itself through a prior session approval or a deferred executor hop.
MUTATING_TOOLS = frozenset(
    {
        "close_email_threads",
        "compose_email",
        "create_draft",
        "create_memory",
        "delete_draft",
        "initiate_call",
        "restore_memory",
        "run_python",
        "send_draft",
        "send_email",
        "send_sms",
        "send_whatsapp",
        "send_whatsapp_message",
        "sync_emails",
        "update_draft",
        "update_memory",
    }
)

_NATURAL_MUTATION = re.compile(
    r"(?:^|\b(?:please|kindly|can you|could you|would you)\s+)"
    r"(?:remember|memorize|store|save|delete|erase|reset|update|change|close|"
    r"modify|create|write|send|draft|call|sync|process|resume|run|done|complete|finish)\b",
    re.IGNORECASE,
)


class ReadOnlyViolation(PermissionError):
    """A read-only origin attempted an operation with a write effect."""


def current_policy() -> str | None:
    return _policy.get()


def is_read_only() -> bool:
    return current_policy() == READ_ONLY_POLICY


@contextlib.contextmanager
def policy_scope(policy: str | None) -> Iterator[None]:
    token = _policy.set(policy)
    try:
        yield
    finally:
        _policy.reset(token)


def command_effect(cmd: str, args: Sequence[str]) -> str | None:
    """Return the mutation effect for a normalized slash command, if any."""
    cmd = (cmd or "").lower()
    words = [str(arg).lower() for arg in args]
    selectors = [word.lstrip("-") for word in words]
    first = selectors[0] if selectors else ""
    if "--help" in words:
        return None
    if cmd == "/memory" and (
        first in {"store", "delete", "reset", "restore"} or "force" in selectors
    ):
        return "memory_write"
    if cmd == "/agent" and (
        first == "run"
        or (first == "memory" and any(w in {"run", "process"} for w in selectors[1:]))
    ):
        return "agent_run"
    if cmd == "/jobs" and first in {"resume", "run", "retry", "cancel", "delete"}:
        return "job_write"
    if cmd == "/update":
        return "update"
    if cmd == "/reset" and ("hard" in selectors or first == "all"):
        return "hard_reset"
    if cmd == "/tasks" and first in {"close", "complete", "done", "snooze", "skip"}:
        return "task_write"
    if cmd in {"/sync", "/share", "/revoke", "/connect", "/train"}:
        return cmd[1:]
    if cmd == "/email" and first in {"send", "delete", "draft", "create", "update"}:
        return "email_write"
    if cmd == "/calendar" and first in {"create", "update", "delete", "sync"}:
        return "calendar_write"
    return None


def natural_mutation_effect(message: str) -> str | None:
    """Conservative pre-router check for plain-language write requests."""
    return "natural_language_write" if _NATURAL_MUTATION.search(message or "") else None


def assert_tool_allowed(tool_name: str) -> None:
    if is_read_only() and tool_name in MUTATING_TOOLS:
        raise ReadOnlyViolation(f"read-only request cannot run {tool_name}")


def refusal_text(effect: str) -> str:
    return (
        "This request is read-only, so the requested change was refused "
        f"before routing ({effect}). Use a supervised write-capable command instead."
    )
