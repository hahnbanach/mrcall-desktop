"""Task mode's `send_email` must ask the same gate as every other send.

`_process_task_mode_message` never received the caller's `approval_callback`,
so `TaskOrchestratorAgent._handle_send_email` ran with no approval gate at
all — a second ungated route to a transport, reachable from the same
`chat.send` RPC, and one that flips the draft to `status="sending"` on its way.

Task mode is dead code in this tree: `zylch.agents.mrcall_agent` was deleted
and the orchestrator still imports it, so the module cannot be imported and
neither transport module exists either. That is an accident of what was
removed, not a safety property — restoring those modules must not silently
re-arm an ungated send. These tests stub the missing modules (only where the
tree really has none) so the gate is pinned now rather than after the fact.
"""

import asyncio
import importlib.machinery
import importlib.util
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from zylch.tools.session_state import SessionState

OWNER = "owner-orchestrator-approval-test"


def _stub_if_absent(name, **attrs):
    if name in sys.modules or importlib.util.find_spec(name) is not None:
        return
    stub = types.ModuleType(name)
    stub.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    for key, value in attrs.items():
        setattr(stub, key, value)
    sys.modules[name] = stub


@pytest.fixture(autouse=True)
def _orchestrator_importable():
    _stub_if_absent("zylch.agents.mrcall_agent", MrCallAgent=MagicMock, MRCALL_AGENT_TOOLS=[])
    _stub_if_absent("zylch.tools.gmail", GmailClient=MagicMock)
    _stub_if_absent("zylch.tools.outlook", OutlookClient=MagicMock)
    yield


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "orchestrator_approval_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def _orchestrator(storage, draft_id, approval_callback):
    from zylch.agents.task_orchestrator_agent import TaskOrchestratorAgent

    state = SessionState()
    state.enter_task_mode("task-1", {"id": "task-1", "contact_email": "customer@example.com"})
    state.set_last_action_result({"tool_used": "write_email", "result": {"draft_id": draft_id}})

    with (
        patch("zylch.llm.make_llm_client", return_value=MagicMock()),
        patch("zylch.agents.task_orchestrator_agent.make_llm_client", return_value=MagicMock()),
    ):
        return TaskOrchestratorAgent(
            session_state=state,
            owner_id=OWNER,
            storage=storage,
            approval_callback=approval_callback,
        )


def _draft(storage, to="customer@example.com"):
    return storage.create_draft(owner_id=OWNER, to=to, subject="Re: your call", body="Body.")


def _approver(approved, edited=None):
    seen = []

    async def callback(tool_use_id, tool_name, tool_input):
        seen.append({"tool": tool_name, "input": tool_input})
        return (approved, edited)

    callback.seen = seen
    return callback


def test_no_callback_refuses_and_leaves_the_draft_untouched(fresh_storage):
    """Headless there is nobody to ask, so the send does not happen."""
    draft = _draft(fresh_storage)
    gmail = MagicMock()
    agent = _orchestrator(fresh_storage, draft["id"], None)

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    assert "approval" in out.lower()
    gmail.send_message.assert_not_called()
    # Not even the `sending` write: a status that no listing shows would
    # strand the draft for a send that never happened.
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_a_declined_send_sends_nothing(fresh_storage):
    draft = _draft(fresh_storage)
    gmail = MagicMock()
    callback = _approver(False)
    agent = _orchestrator(fresh_storage, draft["id"], callback)

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    assert "not approved" in out.lower()
    assert callback.seen[0]["tool"] == "send_email"
    assert callback.seen[0]["input"]["to"] == "customer@example.com"
    gmail.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_an_approved_send_goes_out(fresh_storage):
    draft = _draft(fresh_storage)
    gmail = MagicMock()
    gmail.send_message.return_value = {"id": "sent-task-mode"}
    agent = _orchestrator(fresh_storage, draft["id"], _approver(True))

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    assert "Email sent" in out
    assert gmail.send_message.call_count == 1


def test_an_edit_made_in_the_card_reaches_the_wire(fresh_storage):
    draft = _draft(fresh_storage, to="wrong@example.com")
    gmail = MagicMock()
    gmail.send_message.return_value = {"id": "sent-edited"}
    agent = _orchestrator(fresh_storage, draft["id"], _approver(True, {"to": "right@example.com"}))

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        _run(agent._handle_send_email())

    _, kwargs = gmail.send_message.call_args
    assert kwargs["to"] == "right@example.com"


def test_chat_service_hands_the_callback_to_the_orchestrator(fresh_storage):
    """The wiring is the whole point: an orchestrator built without the
    caller's gate is an orchestrator that cannot ask anyone."""
    from zylch.services.chat_service import ChatService
    from zylch.tools import ToolFactory

    state = SessionState()
    state.enter_task_mode("task-1", {"id": "task-1"})
    built = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            built.update(kwargs)
            self.approval_callback = kwargs.get("approval_callback")

        async def process_message(self, user_message, context=None):
            return "ok"

    module = types.ModuleType("zylch.agents.task_orchestrator_agent")
    module.TaskOrchestratorAgent = FakeOrchestrator
    callback = _approver(True)

    service = ChatService()
    with (
        patch.dict(sys.modules, {"zylch.agents.task_orchestrator_agent": module}),
        patch.object(ToolFactory, "_session_state", state),
    ):
        out = _run(service._process_task_mode_message("send it", OWNER, None, callback))

    assert out == "ok"
    assert built["approval_callback"] is callback
    assert service._task_orchestrator.approval_callback is callback
