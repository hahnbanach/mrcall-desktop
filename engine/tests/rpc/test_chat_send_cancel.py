"""A cancelled chat turn stops; it does not finish quietly in the dark.

When the WebSocket carrying a `chat.send` dies, the engine now cancels
the turn instead of draining it. What that has to mean, and what this
file pins down: the turn reaches no further tool call, it leaves no
entry behind in `_active_chats` or `_pending_approvals`, and a turn
parked on an approval card unwinds without raising anything but
`CancelledError`.

It also pins the operator-facing half. The desktop app reconnects on its
own and the approval card survives the drop, so the click that follows
lands on a turn that no longer exists. The answer to that click has to
say so — "that turn is gone, nothing was sent" — rather than "unknown
tool_use_id".

And it pins the guarantee that costs the most to get wrong: a turn
cancelled while `compose_email` is talking to the LLM writes NO draft.
That one runs the real tool against a real temp SQLite and looks for the
row, because the interesting failure is a side effect that lands after
the caller has already been told the turn is over.

Mocks are at the outbound boundaries only (ONNX loader, IMAP socket,
Anthropic SDK). Two tests additionally replace `_call_tool` to observe
which tools a turn *tried* to reach — those cancel during the LLM call,
never during a tool body, which is why the draft test above does not
replace it.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
import time
import types
from typing import Any, Dict, List

import numpy as np
import pytest

OWNER = "owner-chat-cancel"


# ─── Outbound boundary fakes ──────────────────────────────────────────


class _FakeTextEmbedding:
    def __init__(self, *_args, **_kwargs):
        pass

    def embed(self, texts, **_kwargs):
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
            yield rng.standard_normal(384).astype(np.float32)


class _FakeIMAPConnection:
    def __init__(self, *_args, **_kwargs):
        pass

    def login(self, *_args, **_kwargs):
        return ("OK", [b"logged in"])

    def noop(self):
        return ("OK", [b""])

    def logout(self):
        return ("BYE", [b""])


class _FakeUsage:
    input_tokens = 1
    output_tokens = 1
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _Step:
    """One scripted Anthropic response, optionally held open."""

    def __init__(self, blocks, stop_reason: str, gate: threading.Event | None = None):
        self.blocks = blocks
        self.stop_reason = stop_reason
        self.gate = gate
        self.entered = threading.Event()


class _ScriptedMessages:
    """Answers `messages.create` from a script, repeating the last step."""

    def __init__(self, blocks=None, stop_reason: str = "end_turn", gate=None, steps=None):
        self.steps = steps if steps is not None else [_Step(blocks or [], stop_reason, gate)]
        self.calls = 0

    @property
    def entered(self) -> threading.Event:
        return self.steps[0].entered

    def create(self, **_kwargs):
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        step.entered.set()
        if step.gate is not None:
            # Blocks the LLM call the way a slow API would. The timeout
            # keeps a cancelled test from leaking the thread forever.
            step.gate.wait(timeout=10)
        return types.SimpleNamespace(
            content=step.blocks,
            stop_reason=step.stop_reason,
            model="fake-model",
            usage=_FakeUsage(),
        )


class _ScriptedAnthropic:
    messages_impl: _ScriptedMessages

    def __init__(self, *_args, **_kwargs):
        self.messages = type(self).messages_impl


def _text_block(text: str):
    return types.SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_use_id: str, name: str, tool_input: Dict[str, Any]):
    return types.SimpleNamespace(type="tool_use", id=tool_use_id, name=name, input=tool_input)


# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def engine_env(tmp_path, monkeypatch):
    db_path = tmp_path / "chat_cancel_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    monkeypatch.setenv("EMAIL_ADDRESS", "owner@example.test")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("OWNER_ID", OWNER)

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()

    import anthropic
    import imaplib

    from zylch.memory import embeddings as emb_mod
    from zylch.memory import reset_shared_engines
    from zylch.rpc import methods
    from zylch.services.command_matcher import SemanticCommandMatcher
    from zylch.tools.factory import ToolFactory

    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = _FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)
    monkeypatch.setattr(imaplib, "IMAP4_SSL", _FakeIMAPConnection)
    monkeypatch.setattr(anthropic, "Anthropic", _ScriptedAnthropic)
    monkeypatch.setattr(emb_mod, "_persistent_cache_dir", lambda: str(tmp_path / "fe-cache"))

    reset_shared_engines()
    SemanticCommandMatcher.reset_template_index()
    ToolFactory._imap_clients.clear()
    ToolFactory._imap_client_keys.clear()
    ToolFactory._session_state = None
    methods._pending_approvals.clear()
    methods._active_chats.clear()
    methods._approval_meta.clear()
    methods._abandoned_approvals.clear()

    yield

    reset_shared_engines()
    SemanticCommandMatcher.reset_template_index()
    ToolFactory._imap_clients.clear()
    ToolFactory._imap_client_keys.clear()
    methods._pending_approvals.clear()
    methods._active_chats.clear()
    methods._approval_meta.clear()
    methods._abandoned_approvals.clear()
    db_mod.dispose_engine()


@pytest.fixture
def tool_calls(monkeypatch):
    """Record every tool the agent tries to run, without running it."""
    from zylch.assistant.core import ZylchAIAgent
    from zylch.tools.base import ToolResult, ToolStatus

    seen: List[str] = []

    async def _record(self, name, input_data):
        seen.append(name)
        return ToolResult(status=ToolStatus.SUCCESS, data={}, message="recorded")

    monkeypatch.setattr(ZylchAIAgent, "_call_tool", _record)
    return seen


def _notifications() -> tuple:
    received: List[tuple] = []

    def notify(method: str, params: Dict[str, Any]) -> None:
        received.append((method, params))

    return notify, received


async def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


# ─── Cancelling inside a real tool ────────────────────────────────────


def _draft_rows() -> List[str]:
    from zylch.storage.database import get_session
    from zylch.storage.models import Draft

    with get_session() as session:
        return [str(row.id) for row in session.query(Draft).all()]


def test_cancelling_while_compose_email_runs_writes_no_draft(engine_env):
    """The incident, reproduced: an orphaned turn must not leave a draft.

    `compose_email` awaits the LLM and then writes the draft in the same
    `execute`. Nothing stubs the tool here — the cancel lands while the
    real tool body is waiting on its (stubbed) LLM call, and the check is
    for the row itself, after the LLM has been let go and had time to
    return.
    """
    from zylch.rpc import methods

    compose_gate = threading.Event()
    compose_step = _Step(
        blocks=[_text_block("composed")], stop_reason="end_turn", gate=compose_gate
    )
    _ScriptedAnthropic.messages_impl = _ScriptedMessages(
        steps=[
            # The agent decides to compose…
            _Step(
                blocks=[
                    _tool_use_block(
                        "toolu_compose",
                        "compose_email",
                        {"request": "reply to the customer", "recipient_email": "c@example.test"},
                    )
                ],
                stop_reason="tool_use",
            ),
            # …and the emailer's own LLM call is where we cut the turn.
            compose_step,
        ]
    )
    notify, _received = _notifications()

    assert _draft_rows() == []

    async def scenario():
        task = asyncio.create_task(methods.chat_send({"message": "reply to the customer"}, notify))
        assert await _wait_for(lambda: compose_step.entered.is_set())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Let the stubbed LLM finish and give any surviving continuation
        # a generous window to write its draft.
        compose_gate.set()
        await asyncio.sleep(0.5)

    try:
        asyncio.run(scenario())
    finally:
        compose_gate.set()

    # A little longer, in case the side effect landed on a thread.
    time.sleep(0.5)
    assert _draft_rows() == []
    assert methods._active_chats == {}


# ─── Cancelling mid-LLM ───────────────────────────────────────────────


def test_a_cancelled_turn_reaches_no_tool_call(engine_env, tool_calls):
    from zylch.rpc import methods

    gate = threading.Event()
    _ScriptedAnthropic.messages_impl = _ScriptedMessages(
        blocks=[_tool_use_block("toolu_never", "send_draft", {"draft_id": "abc"})],
        stop_reason="tool_use",
        gate=gate,
    )
    notify, _received = _notifications()

    async def scenario():
        task = asyncio.create_task(methods.chat_send({"message": "reply to the customer"}, notify))
        assert await _wait_for(lambda: _ScriptedAnthropic.messages_impl.entered.is_set())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Release the stubbed LLM thread before the loop closes: the
        # default executor is drained on shutdown and would otherwise
        # wait on it.
        gate.set()

    try:
        asyncio.run(scenario())
    finally:
        gate.set()

    assert tool_calls == []
    assert methods._active_chats == {}
    assert methods._pending_approvals == {}


# ─── Cancelling while parked on an approval ───────────────────────────


def _park_on_approval(message: str = "reply to the customer"):
    """Run a turn up to its approval card, then cancel it.

    Returns the tool_use_id the card carried.
    """
    from zylch.rpc import methods

    _ScriptedAnthropic.messages_impl = _ScriptedMessages(
        blocks=[_tool_use_block("toolu_parked", "send_draft", {"draft_id": "abc"})],
        stop_reason="tool_use",
        gate=None,
    )
    notify, received = _notifications()

    async def scenario():
        task = asyncio.create_task(methods.chat_send({"message": message}, notify))
        assert await _wait_for(lambda: bool(methods._pending_approvals))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    cards = [params for method, params in received if method == "chat.pending_approval"]
    assert len(cards) == 1
    return cards[0]["tool_use_id"]


def test_a_turn_parked_on_an_approval_cancels_cleanly(engine_env, tool_calls):
    from zylch.rpc import methods

    tool_use_id = _park_on_approval()

    assert tool_use_id == "toolu_parked"
    assert tool_calls == []
    assert methods._pending_approvals == {}
    assert methods._approval_meta == {}
    assert methods._active_chats == {}


def test_approving_into_a_cancelled_turn_says_the_turn_is_gone(engine_env, tool_calls):
    from zylch.rpc import methods

    tool_use_id = _park_on_approval()
    notify, _received = _notifications()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(methods.chat_approve({"tool_use_id": tool_use_id, "mode": "once"}, notify))

    message = str(excinfo.value)
    assert "send_draft" in message
    assert "no longer running" in message
    assert "nothing was sent" in message
    assert getattr(excinfo.value, "code", None) == -32602
    # Still no tool ran: approving a dead turn must not send anything.
    assert tool_calls == []


def test_an_id_that_never_existed_still_gets_a_plain_refusal(engine_env):
    from zylch.rpc import methods

    notify, _received = _notifications()

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(methods.chat_approve({"tool_use_id": "toolu_bogus"}, notify))

    assert "no pending approval" in str(excinfo.value)


def test_a_cancelled_conversation_can_be_asked_again(engine_env, tool_calls):
    """`_active_chats` must not keep the conversation marked busy."""
    from zylch.rpc import methods

    _park_on_approval()

    _ScriptedAnthropic.messages_impl = _ScriptedMessages(
        blocks=[_text_block("All done.")],
        stop_reason="end_turn",
        gate=None,
    )
    notify, _received = _notifications()
    result = asyncio.run(methods.chat_send({"message": "try again"}, notify))

    assert "All done." in result["response"]
