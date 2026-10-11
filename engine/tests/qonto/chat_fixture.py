"""The actual assistant/factory/billing path with a deterministic priced wire."""

import json
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from zylch.llm import budget
from zylch.llm.client import LLMClient, TextBlock, ToolUseBlock

ASYNC_CREATE = LLMClient.create_message
SYNC_CREATE = LLMClient.create_message_sync
RESERVE = budget.reserve
MODEL = "claude-haiku-4-5-20251001"


class Wire:
    def __init__(self):
        self.calls = []
        self.responses = []
        self.callback = None

    def create(self, **kwargs):
        self.calls.append(kwargs)
        logging.getLogger("fixture_wire").debug("Wire received %s", kwargs)
        if self.callback:
            self.callback(kwargs)
        content = self.responses.pop(0) if self.responses else [TextBlock(text="Finished.")]
        if callable(content):
            content = content(kwargs)
        return SimpleNamespace(
            content=content,
            stop_reason="tool_use" if any(b.type == "tool_use" for b in content) else "end_turn",
            model=MODEL,
            usage={"input_tokens": 5, "output_tokens": 5},
        )

    def tool(self, name, **params):
        self.responses.append(
            [ToolUseBlock(id="use-" + str(len(self.responses)), name=name, input=params)]
        )

    def answer(self, text):
        self.responses.append([TextBlock(text=text)])


def install_client(env, monkeypatch):
    import zylch.llm as llm
    import zylch.assistant.core as core
    import zylch.tools.factory as factory
    from zylch.services.chat_service import ChatService

    wire = Wire()
    client = LLMClient.__new__(LLMClient)
    client.transport, client.model = "direct", MODEL
    client._client = SimpleNamespace(messages=wire)
    monkeypatch.setattr(LLMClient, "create_message", ASYNC_CREATE)
    monkeypatch.setattr(LLMClient, "create_message_sync", SYNC_CREATE)
    monkeypatch.setattr(budget, "reserve", RESERVE)
    monkeypatch.setattr(llm, "make_llm_client", lambda *a, **kw: client)
    monkeypatch.setattr(llm, "try_make_llm_client", lambda *a, **kw: client)
    monkeypatch.setattr(core, "make_llm_client", lambda *a, **kw: client)
    monkeypatch.setattr(factory, "get_shared_engine", lambda *a, **kw: MagicMock())
    monkeypatch.setattr(ChatService, "_match_semantic_command", lambda *a: None)
    monkeypatch.setattr(ChatService, "_auto_sync_triggered", {"display@example.test"})
    with (env.directory / ".env").open("a") as stream:
        stream.write("LLM_DAILY_BUDGET_USD=5\n")
    return wire


def turn(
    env, *, message="Read selected account movements.", conversation="finance-fixture", **extra
):
    async def scenario():
        from zylch.rpc.dispatch import dispatch_raw

        approvals = []

        def notify(method, params):
            if method == "chat.pending_approval":
                approvals.append(
                    asyncio.create_task(
                        env.arpc("chat.approve", tool_use_id=params["tool_use_id"], approved=True)
                    )
                )

        params = dict(
            message=message, conversation_id=conversation, history_mode="managed_finance", **extra
        )
        result = await dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": params}), notify
        )
        if approvals:
            await asyncio.gather(*approvals)
        return result

    return asyncio.run(scenario())


def tool_data(wire, call=1):
    messages = wire.calls[call]["messages"]
    for message in reversed(messages):
        blocks = message.get("content")
        if isinstance(blocks, list):
            for block in blocks:
                if block.get("type") == "tool_result":
                    return json.loads(block["content"])
    raise AssertionError("No actual tool result reached the model")


def reservations():
    from zylch.storage.database import get_engine

    with get_engine().connect() as conn:
        return conn.exec_driver_sql("SELECT count(*) FROM llm_reservations").scalar()
