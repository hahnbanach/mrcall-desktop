"""Async checked document operations with a short serialized final commit."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from sqlalchemy.exc import OperationalError

from zylch.qonto.logging import private_scope
from zylch.workflows import document_process as jobs
from zylch.workflows import document_snapshot as snapshots
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import Identity, check_same, current_identity

REQUEST_ALIVE: ContextVar[Callable[[], bool] | None] = ContextVar(
    "document_request_alive", default=None
)


async def read_capture(identity: Identity, document_id: str) -> snapshots.Capture:
    for attempt in range(3):
        try:
            return snapshots.capture(identity, document_id)
        except OperationalError as exc:
            if not snapshots.busy(exc) or attempt == 2:
                raise
            await asyncio.sleep(0.025)
    raise WorkflowError("operation_failed")


async def serialized_commit(
    identity: Identity,
    before: snapshots.Capture,
    combined: bytes,
    result: dict[str, Any],
    finish: bool,
    deadline: float,
) -> dict[str, Any] | None:
    for attempt in range(3):
        await asyncio.sleep(0)
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError()
        alive = REQUEST_ALIVE.get()
        if alive is not None and not alive():
            raise asyncio.CancelledError()
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError()
        check_same(identity)
        try:
            return snapshots.commit(identity, before, combined, result, finish)
        except OperationalError as exc:
            if not snapshots.busy(exc) or attempt == 2:
                raise
            await asyncio.sleep(0.025)
    raise WorkflowError("operation_failed")


async def operation(
    document_id: str, content: bytes, offset: int | None, finish: bool
) -> dict[str, Any]:
    identity = current_identity()
    deadline = asyncio.get_running_loop().time() + jobs.DEADLINE_SECONDS
    async with asyncio.timeout(jobs.DEADLINE_SECONDS):
        async with jobs.slot(identity.uid):
            initial = await read_capture(identity, document_id)
            if finish and initial.state == "ready":
                check_same(identity)
                return initial.metadata
            before = initial
            for rescan in range(3):
                if (
                    before.database,
                    before.uid,
                    before.name,
                    before.size,
                    before.sha256,
                    before.original,
                ) != (
                    initial.database,
                    initial.uid,
                    initial.name,
                    initial.size,
                    initial.sha256,
                    initial.original,
                ):
                    raise WorkflowError("upload_invalid")
                if finish:
                    if (
                        before.state not in {"uploading", "ready"}
                        or len(before.original) != before.size
                    ):
                        raise WorkflowError("upload_invalid")
                    combined = before.original
                else:
                    if (
                        before.state != "uploading"
                        or offset != len(before.original)
                        or offset + len(content) > before.size
                    ):
                        raise WorkflowError("upload_invalid")
                    combined = before.original + content
                # current_identity/check_same authorize this private profile owner.
                # The isolated parser receives no content blacklist; the complete
                # original capture remains the identity/receipt/CAS commit fence.
                parsed = replace(before, receipts=(), sources=())
                result = await jobs.compute(parsed, combined, finish)
                check_same(identity)
                if finish and result["sha256"] != before.sha256:
                    raise WorkflowError("upload_invalid")
                value = await serialized_commit(
                    identity, before, combined, result, finish, deadline
                )
                if value is not None:
                    check_same(identity)
                    return value
                if rescan == 2:
                    raise WorkflowError("operation_failed")
                before = await read_capture(identity, document_id)
    raise WorkflowError("operation_failed")


async def upload_chunk_async(document_id: str, offset: int, content_base64: str) -> dict[str, Any]:
    from zylch.workflows.documents import MAX_CHUNK_BYTES

    with private_scope():
        try:
            if (
                not isinstance(content_base64, str)
                or len(content_base64) > ((MAX_CHUNK_BYTES + 2) // 3) * 4
                or type(offset) is not int
            ):
                raise WorkflowError("upload_invalid")
            try:
                content = base64.b64decode(content_base64, validate=True)
            except Exception:
                raise WorkflowError("upload_invalid") from None
            if not content or len(content) > MAX_CHUNK_BYTES:
                raise WorkflowError("upload_invalid")
            return await operation(document_id, content, offset, False)
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError("operation_failed") from None


async def finish_upload_async(document_id: str) -> dict[str, Any]:
    with private_scope():
        try:
            return await operation(document_id, b"", None, True)
        except WorkflowError:
            raise
        except Exception:
            raise WorkflowError("operation_failed") from None
