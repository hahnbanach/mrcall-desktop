"""Safe observations at ordinary runtime boundaries without business authority."""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import asynccontextmanager
import functools
import inspect
import smtplib
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .observability import context, current_context, store

_FAILURES = contextvars.ContextVar("diagnostic_failure_count", default=0)
HEARTBEAT_INTERVAL_SECONDS = 60.0


def observe(stage: str, status: str, **metadata: Any) -> None:
    """Record only schema-allowlisted metadata, preserving business behavior."""
    try:
        if status == "failed":
            _FAILURES.set(_FAILURES.get() + 1)
        store().emit(stage, status, **metadata)
    except Exception:
        pass


def _numeric_attribute(value: Any, name: str) -> int | None:
    """Read one bounded numeric exception attribute without formatting payloads."""
    try:
        number = getattr(value, name, None)
    except Exception:
        return None
    return number if type(number) is int and -(2**53) < number < 2**53 else None


def _database_cause(error: BaseException) -> tuple[bool, int | None]:
    """Inspect only one known DBAPI original, never chained error content."""
    from sqlalchemy.exc import DBAPIError

    try:
        original = getattr(error, "orig", None)
    except Exception:
        original = None
    known = isinstance(error, (sqlite3.DatabaseError, DBAPIError)) or isinstance(
        original, sqlite3.DatabaseError
    )
    code = _numeric_attribute(error, "sqlite_errorcode")
    if code is None and isinstance(original, sqlite3.DatabaseError):
        code = _numeric_attribute(original, "sqlite_errorcode")
    return known, code


def _failure(stage: str, error: BaseException, **metadata: Any) -> None:
    """Retain safe cause and relative frame facts without exception text."""
    status = _numeric_attribute(error, "status_code")
    database_error, sqlite_code = _database_cause(error)
    if isinstance(error, asyncio.CancelledError):
        reason, label = "cancelled", "CancelledError"
    elif type(error).__name__ == "AuthenticationError" or status == 401:
        reason, label = "auth", "PermissionError"
    elif type(error).__name__ == "PermissionDeniedError" or status == 403:
        reason, label = "permission", "PermissionError"
    elif database_error:
        reason, label = "persistence", "UnknownError"
    elif isinstance(error, smtplib.SMTPAuthenticationError):
        reason, label = "auth", "PermissionError"
    elif isinstance(error, PermissionError):
        reason, label = "permission", "PermissionError"
    elif isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        reason, label = "timeout", "TimeoutError"
    elif isinstance(
        error, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError)
    ):
        reason, label = "provider-rejection", "ConnectionError"
    elif type(error).__name__ in {
        "RateLimitError",
        "InsufficientCreditsError",
        "BudgetExceeded",
        "DailyBudgetExceeded",
    }:
        reason, label = "quota", "UnknownError"
    elif isinstance(error, ConnectionError):
        reason, label = "unknown", "ConnectionError"
    elif isinstance(error, OSError):
        reason, label = "unknown", "OSError"
    elif isinstance(error, RuntimeError):
        reason, label = "unknown", "RuntimeError"
    elif isinstance(error, ValueError):
        reason, label = "incomplete-input", "ValueError"
    else:
        reason, label = "unknown", "UnknownError"
    code = _numeric_attribute(error, "code")
    if code is None:
        code = _numeric_attribute(error, "smtp_code")
    if code is None:
        code = status if status is not None else sqlite_code
    facts = {"reason": reason, "error_class": label}
    if type(code) is int:
        facts["error_code"] = code
    frame = error.__traceback__
    package = Path(__file__).resolve().parent
    while frame is not None:
        try:
            relative = Path(frame.tb_frame.f_code.co_filename).resolve().relative_to(package)
        except ValueError:
            pass
        else:
            facts["error_file"] = str(relative)
            facts["error_line"] = frame.tb_lineno
        frame = frame.tb_next
    observe(stage, "failed", **{**facts, **metadata})


def failure(stage: str, error: BaseException, **metadata: Any) -> None:
    """Never replace a business error when diagnostic extraction itself fails."""
    try:
        _failure(stage, error, **metadata)
    except Exception:
        observe(stage, "failed", reason="unknown")


def copied(function: Callable, *args: Any) -> Callable:
    """Explicitly propagate diagnostic and existing policy context into executors."""
    inherited = contextvars.copy_context()

    def execute():
        old = current_context()
        with context({**old, "parent_span_id": old.get("span_id"), "span_id": uuid.uuid4().hex}):
            return function(*args)

    return functools.partial(inherited.run, execute)


def _result(stage: str, result: Any, method: str | None) -> None:
    status = getattr(getattr(result, "status", None), "value", None)
    error = (
        status == "error"
        or (isinstance(result, dict) and "error" in result)
        or (
            isinstance(result, dict)
            and (result.get("success") is False or result.get("ok") is False)
        )
    )
    metadata: dict[str, Any] = {"method": method} if method else {}
    data = getattr(result, "data", None)
    if not isinstance(data, dict):
        data = result if isinstance(result, dict) else {}
    if isinstance(data.get("draft_id"), str):
        metadata["draft_id"] = data["draft_id"]
    if isinstance(data.get("message_id"), str):
        metadata["provider_id"] = data["message_id"]
    if isinstance(result, dict) and result.get("busy") is True:
        observe(stage, "deferred", reason="none", **metadata)
    elif error:
        observe(stage, "failed", reason="unknown", **metadata)
    elif stage == "provider":
        observe(stage, "accepted", reason="none", effect_certainty="accepted", **metadata)
    else:
        observe(stage, "result", reason="none", **metadata)


async def _heartbeat() -> None:
    while True:
        observe("launch", "running", method="engine.heartbeat", reason="none")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


@asynccontextmanager
async def service_heartbeat(stage: str, method: str | None):
    """Own deterministic liveness only while the actual service coroutine runs."""
    task = None
    if stage == "launch" and method in {"engine.ws", "engine.stdio"}:
        task = asyncio.create_task(_heartbeat())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def observed(stage: str, method: str | None = None, *, private: bool = False):
    """Observe an async lifecycle while returning the exact original result."""

    def decorate(function: Callable) -> Callable:
        @functools.wraps(function)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            from contextlib import nullcontext
            from zylch.qonto.logging import private_scope

            old = current_context()
            with context(
                {**old, "parent_span_id": old.get("span_id"), "span_id": uuid.uuid4().hex}
            ):
                async with service_heartbeat(stage, method):
                    started = time.monotonic()
                    metadata = {"method": method} if method else {}
                    failed_before = _FAILURES.get()
                    try:
                        arguments = (
                            inspect.signature(function).bind_partial(*args, **kwargs).arguments
                        )
                        for name in ("job_id", "draft_id"):
                            if isinstance(arguments.get(name), str):
                                metadata[name] = arguments[name]
                        root = arguments.get("thread_id") or arguments.get("in_reply_to")
                        if isinstance(root, str):
                            metadata["root_id"] = root
                    except (TypeError, ValueError):
                        pass
                    observe(stage, "start", reason="none", **metadata)
                    try:
                        with private_scope() if private else nullcontext():
                            result = await function(*args, **kwargs)
                    except BaseException as error:
                        failure(
                            stage, error, elapsed_ms=(time.monotonic() - started) * 1000, **metadata
                        )
                        raise
                    try:
                        if _FAILURES.get() > failed_before:
                            if (
                                stage == "provider"
                                and getattr(getattr(result, "status", None), "value", None)
                                == "success"
                            ):
                                observe(
                                    stage,
                                    "delivered-cleanup-incomplete",
                                    reason="persistence",
                                    effect_certainty="accepted",
                                    **metadata,
                                )
                            else:
                                observe(stage, "failed", reason="unknown", **metadata)
                        else:
                            _result(stage, result, method)
                    except Exception:
                        observe(stage, "unknown", reason="logging", **metadata)
                    return result

        return wrapped

    return decorate


def observed_sync(stage: str, method: str, *, private: bool = False):
    """Observe the shared synchronous model boundary without changing dispatch."""

    def decorate(function: Callable) -> Callable:
        @functools.wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            from contextlib import nullcontext
            from zylch.qonto.logging import private_scope

            old = current_context()
            with context(
                {**old, "parent_span_id": old.get("span_id"), "span_id": uuid.uuid4().hex}
            ):
                started = time.monotonic()
                observe(stage, "start", method=method, reason="none")
                try:
                    with private_scope() if private else nullcontext():
                        result = function(*args, **kwargs)
                except BaseException as error:
                    failure(
                        stage, error, method=method, elapsed_ms=(time.monotonic() - started) * 1000
                    )
                    raise
                observe(
                    stage,
                    "result",
                    method=method,
                    reason="none",
                    elapsed_ms=(time.monotonic() - started) * 1000,
                )
                return result

        return wrapped

    return decorate
