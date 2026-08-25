"""An approval-listed tool with no gate wired must refuse, not run.

`AssistantCore._execute_tools` used to read
`if approval_callback is not None and tool_name in APPROVAL_TOOLS` — a gate
that stood down whenever nobody had wired it. The RPC always wires one, so the
desktop app and `cs` were covered, but `zylch/telegram/bot.py` passed none at
either `process_message` site: an LLM `send_draft` from Telegram reached SMTP
with no approval notification anywhere.

The condition is now on the TOOL alone. No callback means there is nobody to
ask, and nobody to ask means refuse — the same rule the slash-command and
task-mode gates follow.

The Telegram bot keeps its ability to send: it now builds a real inline-button
approval per conversation. These tests pin both halves — the fail-closed core,
and the wiring that means Telegram never relies on it.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zylch.services.task_executor import APPROVAL_TOOLS


def _run(coro):
    return asyncio.run(coro)


def _tool_use_block(name, tool_input=None):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = tool_input or {}
    block.id = f"toolu_{name}"
    return block


def _agent(tool_name):
    """A ZylchAIAgent with one approval-listed tool and no LLM transport."""
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.base import ToolResult, ToolStatus

    tool = MagicMock()
    tool.name = tool_name
    tool.approval_input = lambda data: dict(data or {})
    with patch("zylch.assistant.core.make_llm_client", return_value=MagicMock()):
        agent = ZylchAIAgent(tools=[tool])
    agent._call_tool = AsyncMock(
        return_value=ToolResult(status=ToolStatus.SUCCESS, data={}, message="done")
    )
    return agent


@pytest.mark.parametrize("tool_name", sorted(APPROVAL_TOOLS))
def test_no_callback_refuses_every_approval_listed_tool(tool_name):
    """The whole list, not just send_draft: `update_memory` and `run_python`
    were ungated on the same surface for the same reason."""
    agent = _agent(tool_name)

    results, _ = _run(agent._execute_tools([_tool_use_block(tool_name)], None))

    agent._call_tool.assert_not_awaited()
    assert "no approval channel" in results[0]["content"]


def test_a_tool_outside_the_list_still_runs_without_a_callback():
    """The gate must not turn into a blanket ban on working without a UI."""
    agent = _agent("search_emails")

    _run(agent._execute_tools([_tool_use_block("search_emails")], None))

    agent._call_tool.assert_awaited_once()


# ------------------------------------------------------------------ telegram


def test_the_telegram_bot_supplies_an_approval_callback():
    """Both bot entry points — free text and slash commands — must pass one."""
    from zylch.telegram import bot as tg

    update = MagicMock()
    update.effective_user.id = 42
    update.message.text = "send the draft"
    update.message.chat.send_action = AsyncMock()
    update.message.reply_text = AsyncMock()

    service = MagicMock()
    service.process_message = AsyncMock(return_value={"response": "ok"})

    with (
        patch.object(tg, "_check_authorized", return_value=True),
        patch.object(tg, "_get_chat_service", return_value=service),
        patch.object(tg, "_get_owner_id", return_value="owner"),
        patch.object(tg, "_send_response", new=AsyncMock()),
    ):
        _run(tg.handle_message(update, MagicMock()))
        _run(tg.handle_slash_command(update, MagicMock()))

    assert service.process_message.await_count == 2
    for call in service.process_message.await_args_list:
        assert call.kwargs["approval_callback"] is not None


def test_a_telegram_approval_that_cannot_be_posted_is_a_refusal():
    """If the card never reaches the human, nothing was approved."""
    from zylch.telegram import bot as tg

    update = MagicMock()
    update.effective_chat.send_message = AsyncMock(side_effect=RuntimeError("network"))
    callback = tg._make_approval_callback(update)

    approved, edited = _run(callback("toolu_1", "send_draft", {"draft_id": "x"}))

    assert approved is False
    assert edited is None
    assert tg._pending_approvals == {}


def test_a_telegram_button_press_resolves_the_waiting_tool_call():
    from zylch.telegram import bot as tg

    async def scenario(answer):
        update = MagicMock()
        update.effective_chat.send_message = AsyncMock()
        callback = tg._make_approval_callback(update)
        task = asyncio.create_task(callback("toolu_2", "send_draft", {"draft_id": "x"}))

        # Let the callback register its future and post the card.
        while "toolu_2" not in tg._pending_approvals:
            await asyncio.sleep(0)

        press = MagicMock()
        press.effective_user.id = 42
        press.callback_query.data = f"{answer}:toolu_2"
        press.callback_query.answer = AsyncMock()
        press.callback_query.edit_message_text = AsyncMock()
        with patch.object(tg, "_check_authorized", return_value=True):
            await tg.handle_approval_press(press, MagicMock())

        return await task

    assert _run(scenario("approve")) == (True, None)
    assert _run(scenario("refuse")) == (False, None)
    assert tg._pending_approvals == {}
