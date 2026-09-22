"""Exercise dashboard HTTP contract, live-session tool wiring and dispatch gate."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from zylch.auth import NoActiveSession
from zylch.tools.base import ToolStatus
from zylch.tools.call_tools import InitiateCallTool
from zylch.tools.session_state import SessionState
from zylch.tools.starchat import StarChatClient


async def client_for(handler):
    client = StarChatClient(
        "https://starchat.invalid", auth_type="firebase", jwt_token="test-token", realm="test-realm"
    )
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=client.base_url,
        headers=client._build_headers(),
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"OK", b'{"accepted":true}', b'"queued"', b"[]"])
async def test_dashboard_request_and_honest_success(body):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=body)

    client = await client_for(handler)
    try:
        result = await client.initiate_outbound_call("+39 (02) 8904-0671", "caller-business")
    finally:
        await client.close()
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/mrcall/v1/test-realm/atom/caller-business/outbound"
    assert request.headers["auth"] == "test-token"
    assert json.loads(request.content) == {"toNumber": "390289040671"}
    assert result["status"] == "submitted"
    assert result["phone_number"] == "+390289040671"
    assert "call_id" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "number", ["0289040671", "+39806123456", "123", "+390289040671x9", "++390289040671"]
)
async def test_bad_destination_never_dispatches(number):
    transport = MagicMock()
    client = await client_for(transport)
    try:
        with pytest.raises(ValueError):
            await client.initiate_outbound_call(number, "caller-business")
    finally:
        await client.close()
    transport.assert_not_called()


@pytest.mark.asyncio
async def test_unsupported_override_never_dispatches():
    transport = MagicMock()
    client = await client_for(transport)
    try:
        with pytest.raises(ValueError, match="overrides unsupported"):
            await client.initiate_outbound_call(
                "+390289040671", "caller", variables={"CALL_PURPOSE": "test"}
            )
    finally:
        await client.close()
    transport.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(401), httpx.Response(500), httpx.Response(200, json={"success": False})],
)
async def test_rejected_requests_are_not_success(response):
    client = await client_for(lambda request: response)
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session",
        return_value=client,
    ):
        result = await InitiateCallTool().execute("+390289040671", "caller")
    assert result.status == ToolStatus.ERROR
    assert client.client.is_closed


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_not_retried():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    client = await client_for(handler)
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session",
        return_value=client,
    ):
        result = await InitiateCallTool().execute("+390289040671", "caller")
    assert result.data == {"status": "unknown"}
    assert "Do not retry" in result.error
    assert len(requests) == 1
    assert client.client.is_closed


@pytest.mark.asyncio
async def test_current_session_and_explicit_caller():
    clients = [await client_for(lambda request: httpx.Response(202)) for _ in range(2)]
    state = SessionState(business_id="selected-caller")
    tool = InitiateCallTool(session_state=state)
    assert tool.approval_input({"business_id": "selected-caller"}) == {
        "business_id": "selected-caller"
    }
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session",
        side_effect=clients,
    ) as factory:
        first = await tool.execute("+390289040671", "selected-caller")
        second = await tool.execute("+390289040671", "explicit-caller")
    assert first.data["business_id"] == "selected-caller"
    assert second.data["business_id"] == "explicit-caller"
    assert factory.call_count == 2
    assert all(client.client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_no_caller_or_session_refuses():
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session",
        side_effect=NoActiveSession("missing"),
    ) as factory:
        result = await InitiateCallTool().execute("+390289040671")
        assert result.status == ToolStatus.ERROR
        factory.assert_not_called()
        result = await InitiateCallTool().execute("+390289040671", "caller")
        assert result.status == ToolStatus.ERROR
        assert "Sign in" in result.error


@pytest.mark.asyncio
async def test_approval_caller_stays_explicit_when_session_changes():
    from zylch.assistant.core import ZylchAIAgent

    state = SessionState(business_id="original-session-caller")
    tool = InitiateCallTool(session_state=state)
    with patch("zylch.assistant.core.make_llm_client", return_value=MagicMock()):
        agent = ZylchAIAgent(tools=[tool])
    block = MagicMock(
        type="tool_use", input={"phone_number": "+390289040671", "business_id": "approved-caller"}
    )
    block.name = "initiate_call"
    block.id = "call-tool-approval"

    async def approve(tool_id, name, data):
        assert data["business_id"] == "approved-caller"
        state.set_business_id("different-caller")
        return True, None

    client = await client_for(lambda request: httpx.Response(202))
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session",
        return_value=client,
    ):
        results, _ = await agent._execute_tools([block], approve)
    assert "approved-caller" in results[0]["content"]
    assert "different-caller" not in results[0]["content"]

    # Missing explicit caller cannot fall back to mutable session state.
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session"
    ) as factory:
        result = await tool.execute("+390289040671")
    factory.assert_not_called()
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_factory_exposes_call_without_legacy_client():
    from zylch.tools.factory import ToolFactory
    from zylch.tools.config import ToolConfig

    with (
        patch("zylch.storage.Storage"),
        patch("zylch.tools.factory.get_shared_engine"),
        patch("zylch.tools.factory.HybridSearchEngine"),
        patch.object(ToolFactory, "_create_imap_client", return_value=None),
        patch.object(ToolFactory, "_create_email_tools", return_value=[]),
        patch.object(ToolFactory, "_create_email_sync_tools", return_value=[]),
        patch.object(ToolFactory, "_create_contact_tools", return_value=[]),
    ):
        tools, state = await ToolFactory.create_all_tools(
            ToolConfig(), current_business_id="caller"
        )
    call = next(tool for tool in tools if tool.name == "initiate_call")
    assert isinstance(call, InitiateCallTool)
    assert call.session_state is state


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, False, True])
async def test_real_call_tool_is_gated_before_http(decision):
    from zylch.assistant.core import ZylchAIAgent

    tool = InitiateCallTool()
    with patch("zylch.assistant.core.make_llm_client", return_value=MagicMock()):
        agent = ZylchAIAgent(tools=[tool])
    block = MagicMock(
        type="tool_use", input={"phone_number": "+390289040671", "business_id": "caller"}
    )
    block.name = "initiate_call"
    block.id = "call-tool-1"
    factory = MagicMock(side_effect=NoActiveSession("missing"))
    callback = None if decision is None else AsyncMock(return_value=(decision, None))
    with patch(
        "zylch.tools.mrcall.outbound_tool.make_starchat_client_from_firebase_session", factory
    ):
        await agent._execute_tools([block], callback)
    assert factory.call_count == (1 if decision else 0)
