"""Fixed bounded stdio computation entry; no profile or service access."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import resource
import socket
import struct
import sys
from typing import Any

INPUT_LIMIT = 64 * 1024 * 1024
OUTPUT_LIMIT = 16 * 1024 * 1024


def denied(*args: object, **kwargs: object) -> None:
    raise PermissionError("Network unavailable")


def exact(size: int) -> bytes:
    value = sys.stdin.buffer.read(size)
    if len(value) != size:
        raise ValueError()
    return value


def run() -> dict[str, Any]:
    from zylch.qonto._receipt_matching import Snapshot, matches, recover

    size = struct.unpack("!Q", exact(8))[0]
    if size > INPUT_LIMIT:
        raise ValueError()
    header = json.loads(exact(size))
    if set(header) != {
        "operation",
        "suffix",
        "uid",
        "rows",
        "lengths",
        "parts",
        "fingerprint",
        "expected_size",
        "expected_sha256",
    }:
        raise ValueError()
    if header["operation"] not in {"scan", "finish"}:
        raise ValueError()
    suffix = header["suffix"]
    if (
        not isinstance(suffix, str)
        or len(suffix) > 16
        or any(c not in ".abcdefghijklmnopqrstuvwxyz0123456789" for c in suffix)
    ):
        raise ValueError()
    sizes = header["parts"]
    if (
        not isinstance(sizes, list)
        or not sizes
        or len(sizes) > 1024
        or any(type(n) is not int or n < 0 for n in sizes)
        or size + sum(sizes) > INPUT_LIMIT
    ):
        raise ValueError()
    parts = [exact(n) for n in sizes]
    if sys.stdin.buffer.read(1):
        raise ValueError()
    data, sources = parts[0], parts[1:]
    rows = tuple(tuple(row) for row in header["rows"])
    fingerprint = hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if fingerprint != header["fingerprint"]:
        raise ValueError()
    patterns = recover(rows, header["uid"], sources)
    snapshot = Snapshot(rows, tuple(header["lengths"]), patterns)

    def reject(value: bytes | str) -> bool:
        if isinstance(value, bytes):
            candidates = [base64.b64encode(value).decode("ascii")]
            try:
                candidates.append(value.decode("utf-8"))
            except UnicodeError:
                pass
        else:
            candidates = [value]
        return next(matches(candidates, snapshot), None) is not None

    value: dict[str, Any] = {
        "status": "ok",
        "sha256": hashlib.sha256(data).hexdigest(),
        "fingerprint": header["fingerprint"],
        "text": "",
        "limitations": [],
    }
    if header["operation"] == "finish" and (
        len(data) != header["expected_size"] or value["sha256"] != header["expected_sha256"]
    ):
        value["status"] = "upload_invalid"
        return value
    if reject(data):
        value["status"] = "bank_evidence_refused"
        return value
    if header["operation"] == "finish":
        from zylch.workflows.document_extraction import extract

        try:
            extracted, limitations = extract(data, suffix)
        except (MemoryError, RecursionError):
            raise
        except Exception:
            extracted, limitations = "", [
                "Extraction failed; original bytes are retained.",
                "Digital signatures have not been verified.",
            ]
        if reject(extracted):
            value["status"] = "bank_evidence_refused"
        else:
            value["text"], value["limitations"] = extracted, limitations
    return value


def main() -> None:
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    socket.socket = denied
    socket.create_connection = denied
    logging.disable(logging.CRITICAL)
    try:
        result = run()
        response = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        if len(response) > OUTPUT_LIMIT:
            raise ValueError()
    except BaseException:
        response = b'{"status":"operation_failed"}'
    sys.stdout.buffer.write(struct.pack("!Q", len(response)) + response)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
