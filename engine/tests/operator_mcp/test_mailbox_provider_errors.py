"""Public MCP users can identify mailbox authorization failures without a retry."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from cs.operator_read import ReadGrant
from zylch.email.mailbox_errors import MailboxProviderError
from zylch.operator_mcp import server as server_module
from zylch.operator_mcp.auth import GrantVerifier
from zylch.operator_mcp.effects import GrantedEffects
from zylch.operator_mcp.read_port import NativeReadPort, ProfileBinding
from zylch.services.mailbox_draft_mime import handle


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """This public protocol check uses no retired SaaS storage fixture."""
    yield


def test_public_send_preserves_authorization_cause_before_any_send_receipt(monkeypatch):
    async def check():
        binding = ProfileBinding("fixture", "fixture@example.test", "company", frozenset({"mailbox"}), True)
        async def read(params, notify):
            return []
        port = NativeReadPort(lambda: binding, {name: read for name in ("emails.search", "emails.list_by_thread", "drafts.list")})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"active": False}))) as client:
            verifier = GrantVerifier(issuer="https://operator.example", introspection_url="https://operator.example/introspect",
                service_client_id="fixture", service_client_secret="synthetic", resource="https://operator.example/mcp",
                profile_uid="fixture", company_ref="company", allowed_client_ids={"fixture"}, http_client=client,
                instructions_enabled=True, draft_enabled=True, operator_enabled=True)
            effects = GrantedEffects(verifier, port)
            grant = SimpleNamespace(subject="fixture", mailbox_ids={"mailbox"}, client_id="fixture", grant_id="grant")
            monkeypatch.setattr(effects, "_grant", AsyncMock(return_value=(grant, binding)))
            monkeypatch.setattr(server_module, "get_access_token", lambda: SimpleNamespace(token="synthetic"))
            monkeypatch.setattr("zylch.services.mailbox_drafts.MailboxDrafts.__init__", lambda *args, **kwargs: None)
            monkeypatch.setattr("zylch.services.mailbox_drafts.MailboxDrafts.operation", lambda *args: None)
            reads = []
            def unavailable(*args):
                reads.append(1)
                raise MailboxProviderError("imap_authentication_failed")
            monkeypatch.setattr("zylch.services.mailbox_drafts.MailboxDrafts.get", unavailable)
            server = server_module.create_server(verifier, port, path="/mcp", allowed_hosts=["operator.example"], effects=effects)
            with pytest.raises(Exception, match="imap_authentication_failed"):
                await server.call_tool("send_reply", {"request_key": "synthetic-mcp-send-key", "draft_id": handle(binding.email, "native")})
            assert reads == [1]
    asyncio.run(check())


def test_public_draft_list_preserves_authorization_cause(monkeypatch):
    async def check():
        binding = ProfileBinding("fixture", "fixture@example.test", "company", frozenset({"mailbox"}), True)
        async def unavailable(params, notify):
            raise MailboxProviderError("imap_authentication_failed")
        port = NativeReadPort(lambda: binding, {name: unavailable for name in ("emails.search", "emails.list_by_thread", "drafts.list")})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"active": False}))) as client:
            verifier = GrantVerifier(issuer="https://operator.example", introspection_url="https://operator.example/introspect",
                service_client_id="fixture", service_client_secret="synthetic", resource="https://operator.example/mcp",
                profile_uid="fixture", company_ref="company", allowed_client_ids={"fixture"}, http_client=client,
                instructions_enabled=True, draft_enabled=True, operator_enabled=True)
            grant = ReadGrant("fixture", "fixture", "company", "fixture", "https://operator.example/mcp", int(time.time())+300,
                frozenset({"operator.read", "email.read", "draft.read"}), frozenset({"mail", "drafts"}), frozenset({"mailbox"}), "grant")
            monkeypatch.setattr(verifier, "verify_token", AsyncMock(return_value=SimpleNamespace(claims={})))
            monkeypatch.setattr(verifier, "grant", lambda claims: grant)
            monkeypatch.setattr(server_module, "get_access_token", lambda: SimpleNamespace(token="synthetic"))
            server = server_module.create_server(verifier, port, path="/mcp", allowed_hosts=["operator.example"])
            with pytest.raises(Exception, match="imap_authentication_failed"):
                await server.call_tool("list_drafts", {})
    asyncio.run(check())
