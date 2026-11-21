"""The send tool exists only for a profile whose policy allows full operator access."""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("mcp")
pytest.importorskip("cs.operator_read")

from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.operator_mcp.server import create_server

RESOURCE = "https://operator.example/operator/alice/mcp"


def server_for(operator_enabled):
    binding = ProfileBinding("alice", "alice@example.test", "company", frozenset({"mailbox"}), True)

    async def handler(params, notify):
        return {"emails": []} if "thread_id" in params else []

    port = NativeReadPort(lambda: binding, {name: handler for name in ("emails.search", "emails.list_by_thread", "drafts.list")})
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"active": False})))
    verifier = GrantVerifier(
        issuer="https://operator.example", introspection_url="https://operator.example/introspect",
        service_client_id="service", service_client_secret="disposable-fixture-secret", resource=RESOURCE,
        profile_uid="alice", company_ref="company", allowed_client_ids={"client"}, http_client=client,
        instructions_enabled=True, draft_enabled=True, operator_enabled=operator_enabled,
    )
    return create_server(verifier, port, path="/mcp", allowed_hosts=["operator.example"]), client


@pytest.mark.parametrize("operator_enabled", [True, False])
def test_send_reply_follows_full_operator_access(operator_enabled):
    server, client = server_for(operator_enabled)
    try:
        names = {tool.name for tool in asyncio.run(server.list_tools())}
    finally:
        asyncio.run(client.aclose())
    assert {"prepare_reply", "recover_reply"} <= names
    assert ("send_reply" in names) is operator_enabled
    if operator_enabled:
        tool = next(tool for tool in asyncio.run(server_for(True)[0].list_tools()) if tool.name == "send_reply")
        assert tool.annotations.destructiveHint is True and tool.annotations.readOnlyHint is False
        assert "explicit instruction" in tool.description
