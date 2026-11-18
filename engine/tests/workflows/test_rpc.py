"""Private RPC boundary checks with real transfer and injected failure leaks."""

# ruff: noqa: F811 -- pytest injects imported fixtures by name.

import base64
import hashlib
import json
import logging

import pytest

from zylch.rpc.dispatch import dispatch_raw
from zylch.rpc.methods import METHODS
from test_documents import profile, cleanup_test_data  # noqa: F401


async def call(method, params):
    return await dispatch_raw(
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": method, "params": params}),
        lambda *_: None,
    )


@pytest.mark.asyncio
async def test_rpc_document_original_transfer_and_metadata_only_discovery(profile, caplog):
    caplog.set_level(logging.DEBUG)
    payload = b"private legal dossier with private-bank-marker"
    prepared = await call(
        "workflows.documents.prepare_upload",
        {
            "name": "private-dossier.txt",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    identifier = prepared["result"]["document_id"]
    assert "result" in await call(
        "workflows.documents.upload_chunk",
        {
            "document_id": identifier,
            "offset": 0,
            "content_base64": base64.b64encode(payload).decode(),
        },
    )
    assert (await call("workflows.documents.finish_upload", {"document_id": identifier}))["result"][
        "state"
    ] == "ready"
    read = await call("workflows.documents.download", {"document_id": identifier})
    assert base64.b64decode(read["result"]["content_base64"]) == payload
    listing = (await call("workflows.list", {}))["result"]
    assert len(listing["workflows"]) == 2
    assert all(
        set(row) == {"name", "description", "version", "references"} for row in listing["workflows"]
    )
    assert "private legal dossier" not in caplog.text
    assert "private-dossier.txt" not in caplog.text
    assert base64.b64encode(payload).decode() not in caplog.text


@pytest.mark.asyncio
async def test_rpc_failure_and_rejected_private_keys_do_not_leak(profile, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    marker = "secret-private-dossier-token"

    async def broken(params, notify):
        logging.getLogger("fixture").error(marker, exc_info=True)
        raise RuntimeError(marker)

    monkeypatch.setitem(METHODS, "workflows.list", broken)
    failure = await call("workflows.list", {})
    unknown = await call("workflows.list", {marker: marker})
    unknown_method = await call("workflows." + marker, {})
    assert all("error" in value for value in (failure, unknown, unknown_method))
    assert marker not in json.dumps([failure, unknown, unknown_method])
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_rpc_caller_cannot_assert_legal_admission(profile):
    result = await call(
        "workflows.start",
        {
            "workflow_id": "cs-legal-research",
            "message": "A legal request",
            "origin": "interactive",
            "admission": "caller-grant",
        },
    )
    assert result["error"]["code"] == -32602
