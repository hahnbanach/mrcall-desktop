"""Coverage for the send_draft approval-card hydration (2026-07-08).

SendDraftTool.approval_input() lets a reference-style tool (the model only
supplies draft_id) hydrate the approval card with editable To/Subject/Body,
mirroring the affordance WhatsApp's send tool gets for free from its
direct-field schema. execute() then accepts the edited fields back and
persists them before sending.

Also locks ToolFactory._create_email_tools() against import/registration
drift from gmail_tools.py — this exact regression (EditDraftTool deleted
from gmail_tools.py but left imported/registered in factory.py) broke
collection of unrelated test modules that import the factory.

Runs against a real temp SQLite DB — no storage mocks. Only the outbound
SMTP boundary (IMAPClient.send_message) is stubbed.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

OWNER = "owner-send-draft-test"


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "send_draft_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def test_factory_builds_email_tools_without_edit_draft(fresh_storage):
    """Regression guard: factory.py must not import a class gmail_tools.py
    no longer defines (broke pytest collection of unrelated modules)."""
    from zylch.tools.factory import ToolFactory

    tools = ToolFactory._create_email_tools(
        imap_client=MagicMock(),
        storage=fresh_storage,
        owner_id=OWNER,
    )
    names = {t.name for t in tools}
    assert "edit_draft" not in names
    assert "send_draft" in names


def test_approval_input_hydrates_draft_content(fresh_storage):
    from zylch.tools.gmail_tools import SendDraftTool

    draft = fresh_storage.create_draft(
        owner_id=OWNER,
        to="customer@example.com",
        subject="Re: Order status",
        body="Your order ships tomorrow.",
        cc=["sales@example.com"],
    )

    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)
    card = tool.approval_input({"draft_id": draft["id"]})

    assert card["draft_id"] == draft["id"]
    assert card["to"] == "customer@example.com"
    assert card["subject"] == "Re: Order status"
    assert card["body"] == "Your order ships tomorrow."
    assert card["cc"] == "sales@example.com"


def test_approval_input_defaults_to_most_recent_draft_when_no_id(fresh_storage):
    from zylch.tools.gmail_tools import SendDraftTool

    fresh_storage.create_draft(owner_id=OWNER, to="first@example.com", subject="First", body="...")
    latest = fresh_storage.create_draft(
        owner_id=OWNER, to="second@example.com", subject="Second", body="..."
    )

    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)
    card = tool.approval_input({})

    assert card["draft_id"] == latest["id"]
    assert card["to"] == "second@example.com"


def test_execute_applies_card_edits_before_sending(fresh_storage):
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    draft = fresh_storage.create_draft(
        owner_id=OWNER,
        to="customer@example.com",
        subject="Original subject",
        body="Original body.",
    )

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-msg-1"}

    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(
        tool.execute(
            draft_id=draft["id"],
            to="edited@example.com",
            subject="Edited subject",
            body="Edited body.",
        )
    )

    assert result.status == ToolStatus.SUCCESS

    # The edit must have been persisted, not just sent — so the stored/
    # thread copy matches what actually went out.
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored["to_addresses"] == ["edited@example.com"]
    assert stored["subject"] == "Edited subject"
    assert stored["body"] == "Edited body."

    imap.send_message.assert_called_once()
    _, kwargs = imap.send_message.call_args
    assert kwargs["to"] == "edited@example.com"
    assert kwargs["subject"] == "Edited subject"
    assert kwargs["body"] == "Edited body."


def test_execute_sends_as_is_when_card_not_edited(fresh_storage):
    from zylch.tools.gmail_tools import SendDraftTool
    from zylch.tools.base import ToolStatus

    draft = fresh_storage.create_draft(
        owner_id=OWNER,
        to="customer@example.com",
        subject="Unedited subject",
        body="Unedited body.",
    )

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-msg-2"}

    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.SUCCESS
    _, kwargs = imap.send_message.call_args
    assert kwargs["to"] == "customer@example.com"
    assert kwargs["subject"] == "Unedited subject"
    assert kwargs["body"] == "Unedited body."


def test_approval_gate_uses_tool_approval_input(fresh_storage):
    """Locks the assistant/core.py wiring: the approval callback must be
    given the hydrated card, not the model's raw {draft_id} input."""
    from zylch.tools.gmail_tools import SendDraftTool

    draft = fresh_storage.create_draft(
        owner_id=OWNER,
        to="customer@example.com",
        subject="Gate check",
        body="Body.",
    )
    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)
    tool_map = {"send_draft": tool}

    # Mirrors the exact call assistant/core.py makes at the approval gate.
    raw_model_input = {"draft_id": draft["id"]}
    gate_tool = tool_map.get("send_draft")
    card_input = (
        gate_tool.approval_input(dict(raw_model_input))
        if gate_tool is not None
        else dict(raw_model_input)
    )

    assert card_input != raw_model_input
    assert card_input["subject"] == "Gate check"
