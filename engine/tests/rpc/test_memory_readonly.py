"""Server-enforced read-only chat policy across routing and tool boundaries."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zylch.services.request_policy import policy_scope

OWNER = "read-only-owner"


@pytest.fixture
def engine_db(tmp_path, monkeypatch):
    path = tmp_path / "profile.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(path))
    monkeypatch.setenv("MEMORY_KEY", "read-only-company")
    monkeypatch.setenv("ZYLCH_MEMORY_DIR", str(tmp_path / "memory"))
    from zylch.storage import database as db
    from zylch.storage.storage import Storage

    db.dispose_engine()
    db.init_db()
    Storage._instance = None
    yield path
    Storage._instance = None
    db.dispose_engine()


def _counts(path):
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables
        }


def _database_snapshot(path):
    """Capture complete persisted values, not only row counts."""
    with sqlite3.connect(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            name: conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for name in tables
        }


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "message",
    [
        "/memory store one fact",
        "/memory --store one fact",
        "/memory store one fact --force",
        "/memory delete abc",
        "/memory --delete abc",
        "/memory reset",
        "/memory restore abc v1",
        "/agent memory run",
        "/agent memory --run",
        "/agent memory process",
        "/jobs resume",
        "/jobs --resume",
        "/update",
        "/reset --hard",
        "remember that the price is 12 euro",
        "delete the customer memory",
        "done #1",
    ],
)
def test_read_only_request_refuses_before_any_database_or_model_work(engine_db, message):
    from zylch.services.chat_service import ChatService

    before = _counts(engine_db)
    with patch.object(ChatService, "_initialize_agent", new=AsyncMock()) as initialize:
        with policy_scope("read_only"):
            result = _run(
                ChatService().process_message(
                    user_message=message,
                    user_id=OWNER,
                    context={"user_id": OWNER},
                )
            )
    assert result["metadata"]["blocked_by_read_only_policy"] is True
    initialize.assert_not_awaited()
    assert _counts(engine_db) == before


def test_semantic_rewrite_is_rechecked_before_dispatch(engine_db):
    from zylch.services.chat_service import ChatService

    service = ChatService()
    service._match_semantic_command = MagicMock(return_value="/memory store rewritten")
    service._initialize_agent = AsyncMock()
    before = _counts(engine_db)
    with policy_scope("read_only"):
        result = _run(service.process_message("retain this", OWNER))
    assert result["metadata"]["blocked_by_read_only_policy"] is True
    service._initialize_agent.assert_not_awaited()
    assert _counts(engine_db) == before


def test_help_remains_available_and_does_not_acknowledge_notifications(engine_db):
    from zylch.services.chat_service import ChatService

    service = ChatService()
    service.storage.get_unread_notifications = MagicMock(return_value=[])
    service.storage.mark_notifications_read = MagicMock()
    with policy_scope("read_only"):
        result = _run(service.process_message("/help", OWNER))
    assert result["metadata"].get("blocked_by_read_only_policy") is not True
    assert result["response"]
    service.storage.mark_notifications_read.assert_not_called()


def test_rpc_requires_the_negotiated_policy_version(engine_db, monkeypatch):
    from zylch.rpc import methods

    monkeypatch.setattr(methods, "_owner_id", lambda: OWNER)
    with pytest.raises(ValueError, match="version 1"):
        _run(
            methods.chat_send(
                {"message": "/memory reset", "mutation_policy": "read_only"},
                lambda *_: None,
            )
        )
    caps = _run(methods.system_capabilities({}, lambda *_: None))
    assert caps == {"chat_read_only_policy": 1}


def test_rpc_to_dispatcher_refusal_creates_no_rows(engine_db, monkeypatch):
    from zylch.rpc import methods
    from zylch.rpc.dispatch import dispatch_raw
    from zylch.services.chat_service import ChatService
    from zylch.storage.storage import Storage

    monkeypatch.setattr(methods, "_owner_id", lambda: OWNER)
    before = _database_snapshot(engine_db)
    with (
        patch.object(ChatService, "_initialize_agent", new=AsyncMock()) as initialize,
        patch.object(Storage, "create_background_job", autospec=True) as create_job,
        patch("zylch.llm.budget.reserve") as reserve,
    ):
        response = _run(
            dispatch_raw(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "chat.send",
                        "params": {
                            "message": "/jobs resume",
                            "conversation_id": "read-only-integration",
                            "mutation_policy": "read_only",
                            "policy_version": 1,
                        },
                    },
                ),
                lambda *_: None,
            )
        )
    assert response["result"]["metadata"]["blocked_by_read_only_policy"] is True
    initialize.assert_not_awaited()
    create_job.assert_not_called()
    reserve.assert_not_called()
    assert _database_snapshot(engine_db) == before


@pytest.mark.parametrize("tool_name", ["create_memory", "update_memory", "restore_memory"])
def test_prior_approval_cannot_widen_a_read_only_tool_call(tool_name):
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.base import ToolResult, ToolStatus

    tool = MagicMock()
    tool.name = tool_name
    tool.approval_input = lambda data: data
    with patch("zylch.assistant.core.make_llm_client", return_value=MagicMock()):
        agent = ZylchAIAgent(tools=[tool])
    agent._call_tool = ZylchAIAgent._call_tool.__get__(agent)
    tool.execute = AsyncMock(
        return_value=ToolResult(status=ToolStatus.SUCCESS, data={}, message="written")
    )
    block = types.SimpleNamespace(type="tool_use", name=tool_name, input={"content": "x"}, id="t1")

    approve = AsyncMock(return_value=True)

    with policy_scope("read_only"):
        results, _ = _run(agent._execute_tools([block], approve))
    approve.assert_not_awaited()
    tool.execute.assert_not_awaited()
    assert "read-only request" in results[0]["content"]


def test_search_tool_still_runs_under_read_only_policy():
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.base import ToolResult, ToolStatus

    tool = MagicMock()
    tool.name = "search_local_memory"
    tool.approval_input = lambda data: data
    tool.execute = AsyncMock(
        return_value=ToolResult(status=ToolStatus.SUCCESS, data=[], message="no matches")
    )
    with patch("zylch.assistant.core.make_llm_client", return_value=MagicMock()):
        agent = ZylchAIAgent(tools=[tool])
    block = types.SimpleNamespace(type="tool_use", name=tool.name, input={"query": "x"}, id="t2")
    with policy_scope("read_only"):
        _run(agent._execute_tools([block]))
    tool.execute.assert_awaited_once()


def test_task_orchestrator_cannot_delegate_a_read_only_origin():
    from zylch.agents.task_orchestrator_agent import TaskOrchestratorAgent

    orchestrator = object.__new__(TaskOrchestratorAgent)
    orchestrator._handle_call_agent = AsyncMock(return_value="should not run")
    block = types.SimpleNamespace(
        name="call_agent", input={"agent_name": "emailer", "instructions": "draft it"}
    )
    response = types.SimpleNamespace(stop_reason="tool_use", content=[block])
    with policy_scope("read_only"):
        result = _run(orchestrator._handle_response(response))
    orchestrator._handle_call_agent.assert_not_awaited()
    assert "read-only" in result


def test_deferred_task_executor_refuses_before_approval_or_execution():
    from zylch.services.task_executor import TaskExecutor

    block = types.SimpleNamespace(
        type="tool_use", name="update_memory", input={"content": "x"}, id="deferred-1"
    )
    response = types.SimpleNamespace(stop_reason="tool_use", content=[block])
    client = types.SimpleNamespace(create_message_sync=MagicMock(return_value=response))
    executor = TaskExecutor(client, "system", [], MagicMock(), OWNER, [])

    async def first_event():
        stream = executor.run()
        try:
            return await anext(stream)
        finally:
            await stream.aclose()

    with policy_scope("read_only"):
        event = _run(first_event())
    assert event["type"] == "tool_result"
    assert event["approved"] is False
    assert "read-only request" in event["output"]
    assert executor._pending == {}


def test_real_kernel_client_payload_reaches_dispatcher_and_writes_nothing(engine_db, monkeypatch):
    """Kernel `rpc.chat` -> JSON-RPC dispatch -> ChatService refusal."""
    from zylch.rpc import methods
    from zylch.rpc.dispatch import dispatch_raw

    kernel_root = str(__import__("pathlib").Path(__file__).resolve().parents[4] / "cs-kernel")
    sys.path.insert(0, kernel_root)
    try:
        from cs import rpc as kernel_rpc
    finally:
        sys.path.remove(kernel_root)

    monkeypatch.setattr(methods, "_owner_id", lambda: OWNER)

    class DispatcherClient:
        notifications = []

        def __init__(self, settings, **kwargs):
            self.notifications = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def call(self, method, params=None, timeout=60):
            response = await dispatch_raw(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}),
                lambda name, payload: self.notifications.append(
                    {"method": name, "params": payload}
                ),
            )
            if "error" in response:
                raise RuntimeError(response["error"]["message"])
            return response["result"]

    from zylch.services.chat_service import ChatService
    from zylch.storage.storage import Storage

    before = _database_snapshot(engine_db)
    with (
        patch.object(kernel_rpc, "EngineClient", DispatcherClient),
        patch.object(ChatService, "_initialize_agent", new=AsyncMock()) as initialize,
        patch.object(Storage, "create_background_job", autospec=True) as create_job,
        patch("zylch.llm.budget.reserve") as reserve,
    ):
        out = _run(
            kernel_rpc.chat(
                types.SimpleNamespace(),
                "/memory store forbidden",
                allow_tools=set(),
                read_only=True,
            )
        )
    assert out["result"]["metadata"]["blocked_by_read_only_policy"] is True
    initialize.assert_not_awaited()
    create_job.assert_not_called()
    reserve.assert_not_called()
    assert _database_snapshot(engine_db) == before
