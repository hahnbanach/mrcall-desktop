"""Bounded async lifecycle for private document computation processes."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from typing import Any, AsyncIterator

from zylch.workflows.errors import WorkflowError
from zylch.workflows.document_snapshot import Capture

DEADLINE_SECONDS = 45
INPUT_LIMIT = 64 * 1024 * 1024
OUTPUT_LIMIT = 16 * 1024 * 1024
_ACTIVE: Counter[str] = Counter()
_WAITING: Counter[str] = Counter()
PROCESSES: set[asyncio.subprocess.Process] = set()


@asynccontextmanager
async def slot(uid: str) -> AsyncIterator[None]:
    if _WAITING[uid] >= 2 or sum(_WAITING.values()) >= 8:
        raise WorkflowError("operation_failed")
    _WAITING[uid] += 1
    try:
        while _ACTIVE[uid] or sum(_ACTIVE.values()) >= 2:
            await asyncio.sleep(0.025)
        _ACTIVE[uid] += 1
    finally:
        _WAITING[uid] -= 1
        if not _WAITING[uid]:
            del _WAITING[uid]
    try:
        yield
    finally:
        _ACTIVE[uid] -= 1
        if not _ACTIVE[uid]:
            del _ACTIVE[uid]


def environment() -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": ".",
        "TMPDIR": ".",
        "LANG": "C.UTF-8",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    }


async def stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def compute(before: Capture, data: bytes, finish: bool) -> dict[str, Any]:
    parts = [
        data,
        *(source.encode() if isinstance(source, str) else source for source in before.sources),
    ]
    fingerprint = hashlib.sha256(
        json.dumps(before.receipts, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    suffix = Path(before.name).suffix.lower()
    if len(suffix) > 16 or any(c not in ".abcdefghijklmnopqrstuvwxyz0123456789" for c in suffix):
        suffix = ""
    header = json.dumps(
        {
            "operation": "finish" if finish else "scan",
            "expected_size": before.size if finish else len(data),
            "expected_sha256": before.sha256 if finish else hashlib.sha256(data).hexdigest(),
            "suffix": suffix,
            "uid": before.uid,
            "rows": before.receipts,
            "lengths": list({row[5] for row in before.receipts if row[5]}),
            "parts": [len(part) for part in parts],
            "fingerprint": fingerprint,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    if len(header) + sum(map(len, parts)) > INPUT_LIMIT:
        raise WorkflowError("operation_failed")
    expected_hash = hashlib.sha256(data).hexdigest()
    with tempfile.TemporaryDirectory(prefix="mrcall-document-") as scratch:
        os.chmod(scratch, 0o700)
        creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-s",
                "-P",
                "-m",
                "zylch.workflows.document_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=scratch,
                env=environment(),
                close_fds=True,
                limit=OUTPUT_LIMIT + 8,
            )
        )
        try:
            process = await asyncio.shield(creation)
        except asyncio.CancelledError:
            process = await creation
            await stop(process)
            raise
        PROCESSES.add(process)
        try:
            process.stdin.write(struct.pack("!Q", len(header)))
            process.stdin.write(header)
            for part in parts:
                process.stdin.write(part)
                await process.stdin.drain()
            process.stdin.close()
            size = struct.unpack("!Q", await process.stdout.readexactly(8))[0]
            if size > OUTPUT_LIMIT:
                raise WorkflowError("operation_failed")
            response = await process.stdout.readexactly(size)
            if await process.stdout.read(1) or await process.wait() != 0:
                raise WorkflowError("operation_failed")
            result = json.loads(response)
            if not isinstance(result, dict) or result.get("status") != "ok":
                outcome = result.get("status") if isinstance(result, dict) else None
                raise WorkflowError(
                    outcome
                    if outcome in {"bank_evidence_refused", "upload_invalid"}
                    else "operation_failed"
                )
            if (
                set(result) != {"status", "sha256", "fingerprint", "text", "limitations"}
                or result["sha256"] != expected_hash
                or result["fingerprint"] != fingerprint
                or not isinstance(result["text"], str)
                or len(result["text"]) > 2 * 1024 * 1024
                or not isinstance(result["limitations"], list)
                or any(not isinstance(item, str) for item in result["limitations"])
            ):
                raise WorkflowError("operation_failed")
            return result
        finally:
            cleanup = asyncio.create_task(stop(process))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
            finally:
                PROCESSES.discard(process)
