"""The task orchestrator's `send_email` must send the draft it was told about.

`send_email` fires on a bare "send it" and carries no parameters, so the id
recorded by the preceding compose step is the only thing identifying "the
pending draft". It used to fall back to `list_drafts(...)[0]` — the newest row
in the DB — which on a mailbox holding several drafts answers "send it" with a
different customer's email, and then deletes that draft.

The second hazard on this path is ordering: the draft was flipped to
`status="sending"` before the code knew it could send at all. `/email send`
filters `status == "draft"`, so a refusal after that write leaves the draft
unsendable by any later attempt.

Runs against a real temp SQLite DB — no storage mocks. Only the provider
lookup and the outbound Gmail boundary are stubbed.
"""

import asyncio
import importlib.machinery
import importlib.util
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from zylch.tools.session_state import SessionState

OWNER = "owner-orchestrator-send-test"


def _stub_if_absent(name, **attrs):
    """Stand a stub module in for `name`, but only if the tree has none.

    The orchestrator's send path imports three modules this tree does not
    contain: `zylch.agents.mrcall_agent` — whose absence is why the
    orchestrator module cannot be imported at all today — and the OAuth
    transports `zylch.tools.gmail` / `zylch.tools.outlook`. Which draft the
    path picks, and when it writes that draft's status, is independent of all
    three, so stub them rather than lose the coverage. Conditional on purpose:
    the day a real module returns, these tests exercise the real one.
    """
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
    db_path = tmp_path / "orchestrator_send_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def _two_drafts(storage):
    """An older target draft and a newer decoy — the decoy is what any
    "most recent" fallback would reach for."""
    target = storage.create_draft(
        owner_id=OWNER,
        to="target@example.com",
        subject="Re: the one the task was about",
        body="Target body.",
    )
    decoy = storage.create_draft(
        owner_id=OWNER,
        to="decoy@example.com",
        subject="Re: a different customer",
        body="Decoy body.",
    )
    return target, decoy


def _orchestrator(storage, last_action_result=None):
    session_state = SessionState(owner_id=OWNER)
    session_state.enter_task_mode("task-1", {"title": "reply to the customer"})
    if last_action_result is not None:
        session_state.set_last_action_result(last_action_result)

    # The LLM client is never exercised: these tests call _handle_send_email
    # directly, which is the whole send path below the tool dispatch.
    with patch("zylch.agents.task_orchestrator_agent.make_llm_client", return_value=MagicMock()):
        from zylch.agents.task_orchestrator_agent import TaskOrchestratorAgent

        return TaskOrchestratorAgent(
            session_state=session_state,
            owner_id=OWNER,
            storage=storage,
        )


def _compose_result(draft_id):
    """The shape the emailer sub-agent leaves in session state."""
    return {"tool_used": "write_email", "result": {"draft_id": draft_id}}


def _statuses(storage, *drafts):
    return [storage.get_draft(OWNER, d["id"])["status"] for d in drafts]


def test_sends_the_draft_from_last_action_result_not_the_newest(fresh_storage):
    target, decoy = _two_drafts(fresh_storage)
    agent = _orchestrator(fresh_storage, _compose_result(target["id"]))

    gmail = MagicMock()
    gmail.send_message.return_value = {"id": "sent-msg-target"}

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="me@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    assert "Email sent" in out
    _, kwargs = gmail.send_message.call_args
    assert kwargs["to"] == "target@example.com"
    assert kwargs["subject"] == "Re: the one the task was about"

    # The target is consumed by the send; the decoy must be untouched.
    assert fresh_storage.get_draft(OWNER, target["id"]) is None
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_refuses_when_nothing_is_pending_and_strands_no_draft(fresh_storage):
    target, decoy = _two_drafts(fresh_storage)
    agent = _orchestrator(fresh_storage)  # empty session state

    gmail = MagicMock()

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="me@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    gmail.send_message.assert_not_called()
    assert "No pending email draft" in out
    assert _statuses(fresh_storage, target, decoy) == ["draft", "draft"]


def test_refuses_an_unknown_draft_id_and_strands_no_draft(fresh_storage):
    target, decoy = _two_drafts(fresh_storage)
    agent = _orchestrator(fresh_storage, _compose_result("9bde5315-0000-0000-0000-000000000000"))

    gmail = MagicMock()

    with (
        patch("zylch.api.token_storage.get_provider", return_value="google"),
        patch("zylch.api.token_storage.get_email", return_value="me@example.com"),
        patch("zylch.tools.gmail.GmailClient", return_value=gmail),
    ):
        out = _run(agent._handle_send_email())

    gmail.send_message.assert_not_called()
    assert "Draft not found" in out
    assert _statuses(fresh_storage, target, decoy) == ["draft", "draft"]


def test_a_provider_this_code_cannot_drive_leaves_the_draft_sendable(fresh_storage):
    """`imap` is the support@ profile's provider and has no branch here. The
    refusal must not consume the draft's `draft` status on the way out."""
    target, decoy = _two_drafts(fresh_storage)
    agent = _orchestrator(fresh_storage, _compose_result(target["id"]))

    with (
        patch("zylch.api.token_storage.get_provider", return_value="imap"),
        patch("zylch.api.token_storage.get_email", return_value="me@example.com"),
    ):
        out = _run(agent._handle_send_email())

    assert "Unknown email provider" in out
    assert _statuses(fresh_storage, target, decoy) == ["draft", "draft"]


def test_an_expired_microsoft_token_leaves_the_draft_sendable(fresh_storage):
    """The refusal that used to land AFTER the `sending` write: the draft was
    left in a status `/email send` filters out, so no later attempt could
    reach it either."""
    target, decoy = _two_drafts(fresh_storage)
    agent = _orchestrator(fresh_storage, _compose_result(target["id"]))

    with (
        patch("zylch.api.token_storage.get_provider", return_value="microsoft"),
        patch("zylch.api.token_storage.get_email", return_value="me@example.com"),
        patch("zylch.api.token_storage.get_graph_token", return_value=None),
    ):
        out = _run(agent._handle_send_email())

    assert "Microsoft token expired" in out
    assert _statuses(fresh_storage, target, decoy) == ["draft", "draft"]


def test_send_email_tool_declares_no_guessable_draft_id(fresh_storage):
    """The model is never shown a draft id in this flow, so the schema must not
    offer it a field to invent one into."""
    from zylch.agents.task_orchestrator_agent import SEND_EMAIL_TOOL

    assert SEND_EMAIL_TOOL["input_schema"]["properties"] == {}
    assert SEND_EMAIL_TOOL["input_schema"]["required"] == []
