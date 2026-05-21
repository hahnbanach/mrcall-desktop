"""Tests for the ListMrCallAssistantsTool LLM tool + prompt anchoring.

The Firebase StarChat client is MOCKED throughout: we monkeypatch
`make_starchat_client_from_firebase_session` (the tool imports it lazily
inside execute(), so we patch it on its source module
`zylch.tools.mrcall.starchat_firebase`) to return a fake whose `.realm`
attribute and async `.client.post(...)` / `.client.aclose()` behave like
StarChat. No network, no real Firebase signin — the live
business/search round-trip can only be exercised with a real signed-in
session, so these tests pin the *proven request shape* (POST
`/mrcall/v1/{realm}/crm/business/search` with `{"from": 0, "size": N}`)
and the graceful-degradation contract instead.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from zylch.auth import NoActiveSession
from zylch.tools.base import ToolStatus
from zylch.tools.call_tools import ListMrCallAssistantsTool

SAMPLE_BUSINESSES = [
    {
        "businessId": "biz-aaa-111",
        "nickname": "Reception Bot",
        "companyName": "Acme SRL",
        "serviceNumber": "+390212345678",
        "emailAddress": "reception@acme.example",
        "userPhoneNumber": "+393331112233",
        "template": "receptionist",
        "subscriptionStatus": "active",
    },
    {
        "id": "biz-bbb-222",
        "nickname": "Sales Line",
        "companyName": "Acme SRL",
        "serviceNumber": "+390298765432",
        "template": "sales",
        "subscriptionStatus": "trial",
    },
]


def _fake_client(businesses=SAMPLE_BUSINESSES, status_code=200):
    """Build a fake StarChat client mirroring the bits the tool touches."""
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=businesses)
    response.raise_for_status = MagicMock()
    if status_code >= 400 and status_code != 401:
        request = httpx.Request("POST", "https://x/mrcall/v1/r/crm/business/search")
        http_response = httpx.Response(status_code, request=request, text="boom")
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("error", request=request, response=http_response)
        )

    client = MagicMock()
    client.realm = "test_realm"
    client.client = MagicMock()
    client.client.post = AsyncMock(return_value=response)
    client.client.aclose = AsyncMock()
    return client


def _session_state(owner_id="owner-1"):
    ss = MagicMock()
    ss.get_owner_id = MagicMock(return_value=owner_id)
    return ss


@pytest.mark.asyncio
async def test_happy_path_lists_with_linked_marker():
    fake = _fake_client()
    fake_storage = MagicMock()
    fake_storage.get_mrcall_link = MagicMock(return_value="biz-bbb-222")

    with (
        patch(
            "zylch.tools.mrcall.starchat_firebase." "make_starchat_client_from_firebase_session",
            return_value=fake,
        ),
        patch("zylch.storage.Storage", return_value=fake_storage),
    ):
        tool = ListMrCallAssistantsTool(session_state=_session_state())
        result = await tool.execute()

    assert result.status == ToolStatus.SUCCESS
    # Proven request shape: from/size, not offset/limit.
    fake.client.post.assert_awaited_once()
    _, kwargs = fake.client.post.call_args
    assert kwargs["json"] == {"from": 0, "size": 100}
    posted_endpoint = fake.client.post.call_args.args[0]
    assert posted_endpoint == "/mrcall/v1/test_realm/crm/business/search"

    msg = result.message
    # Both nicknames present, full ids un-truncated, LINKED marker on bbb.
    assert "Reception Bot" in msg
    assert "Sales Line" in msg
    assert "biz-aaa-111" in msg
    assert "biz-bbb-222" in msg
    assert "← LINKED" in msg
    # The linked marker must be on the Sales Line block, not Reception Bot.
    linked_line = next(line for line in msg.splitlines() if "← LINKED" in line)
    assert "Sales Line" in linked_line

    # Structured data carries the same, with linked flag and no truncation.
    assistants = result.data["assistants"]
    assert len(assistants) == 2
    by_id = {a["business_id"]: a for a in assistants}
    assert by_id["biz-bbb-222"]["linked"] is True
    assert by_id["biz-aaa-111"]["linked"] is False
    assert by_id["biz-aaa-111"]["service_number"] == "+390212345678"
    fake.client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_not_signed_in_returns_friendly_result_not_raise():
    with patch(
        "zylch.tools.mrcall.starchat_firebase." "make_starchat_client_from_firebase_session",
        side_effect=NoActiveSession("no session"),
    ):
        tool = ListMrCallAssistantsTool(session_state=_session_state())
        result = await tool.execute()

    assert result.status == ToolStatus.SUCCESS
    assert result.data == {"signed_in": False}
    assert "sign in" in result.message.lower()


@pytest.mark.asyncio
async def test_401_returns_session_expired():
    fake = _fake_client(status_code=401)
    with patch(
        "zylch.tools.mrcall.starchat_firebase." "make_starchat_client_from_firebase_session",
        return_value=fake,
    ):
        tool = ListMrCallAssistantsTool(session_state=_session_state())
        result = await tool.execute()

    assert result.status == ToolStatus.SUCCESS
    assert result.data == {"signed_in": False}
    assert "expired" in result.message.lower()
    fake.client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_list_points_at_dashboard():
    fake = _fake_client(businesses=[])
    fake_storage = MagicMock()
    fake_storage.get_mrcall_link = MagicMock(return_value=None)
    with (
        patch(
            "zylch.tools.mrcall.starchat_firebase." "make_starchat_client_from_firebase_session",
            return_value=fake,
        ),
        patch("zylch.storage.Storage", return_value=fake_storage),
    ):
        tool = ListMrCallAssistantsTool(session_state=_session_state())
        result = await tool.execute()

    assert result.status == ToolStatus.SUCCESS
    assert result.data["count"] == 0
    assert "No MrCall assistants found" in result.message
    assert "https://dashboard.mrcall.ai" in result.message


@pytest.mark.asyncio
async def test_http_error_is_caught_not_raised():
    fake = _fake_client(status_code=500)
    with patch(
        "zylch.tools.mrcall.starchat_firebase." "make_starchat_client_from_firebase_session",
        return_value=fake,
    ):
        tool = ListMrCallAssistantsTool(session_state=_session_state())
        result = await tool.execute()

    assert result.status == ToolStatus.ERROR
    assert result.error is not None
    # Client still closed despite the error.
    fake.client.aclose.assert_awaited_once()


def test_schema_shape():
    tool = ListMrCallAssistantsTool()
    schema = tool.get_schema()
    assert schema["name"] == "list_mrcall_assistants"
    assert schema["input_schema"]["required"] == []
    assert "limit" in schema["input_schema"]["properties"]


def test_registered_in_factory_unconditionally():
    """ListMrCallAssistantsTool is appended in create_all_tools regardless
    of the legacy OAuth `starchat` client.

    The full factory run needs IMAP/DB/ONNX; we instead assert the
    registration call site directly: the factory imports the class and
    appends it next to the call-tool block. We verify the symbol is
    importable from the factory and that the source registers it
    unconditionally (no `if starchat:` guard around it).
    """
    import inspect

    import zylch.tools.factory as factory

    assert factory.ListMrCallAssistantsTool is ListMrCallAssistantsTool

    src = inspect.getsource(factory.ToolFactory.create_all_tools)
    assert "ListMrCallAssistantsTool(session_state=session_state)" in src
    # The append must sit OUTSIDE the `if starchat:` block — assert it
    # appears after that block closes by checking it's not indented under it.
    append_idx = src.index("tools.append(ListMrCallAssistantsTool")
    # Walk back to the start of that line and confirm 8-space indent
    # (method body level), not the 12-space level of the `if starchat:` body.
    line_start = src.rfind("\n", 0, append_idx) + 1
    indent = append_idx - line_start
    assert indent == 8, f"expected unconditional (8-space) indent, got {indent}"


def test_prompt_contains_dashboard_url_and_tool():
    from zylch.assistant.prompts import SYSTEM_PROMPT_BASE

    assert "dashboard.mrcall.ai" in SYSTEM_PROMPT_BASE
    assert "list_mrcall_assistants" in SYSTEM_PROMPT_BASE
    # Anchor must forbid the hallucinated domain.
    assert "mrcall.it" in SYSTEM_PROMPT_BASE
    assert "/mrcall list" in SYSTEM_PROMPT_BASE
