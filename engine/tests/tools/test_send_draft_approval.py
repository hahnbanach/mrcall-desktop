"""Approval cards show the current native draft and apply only deliberate edits.

The factory registration risk remains. Approval integration runs the real
assistant tool loop rather than reproducing its hydration branch in a test.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mailbox_tools_fixture import OWNER, cleanup_test_data, mailbox
from zylch.tools.base import ToolStatus


def approved_agent(mailbox, monkeypatch):
    from zylch.assistant.core import ZylchAIAgent
    monkeypatch.setattr("zylch.assistant.core.make_llm_client", lambda: MagicMock())
    return ZylchAIAgent(tools=[mailbox.tool()])


def block(draft):
    return SimpleNamespace(type="tool_use", id="synthetic-send-use", name="send_draft", input={"draft_id": draft["id"]})


def test_factory_builds_the_current_email_tool_set(mailbox):
    from zylch.tools.factory import ToolFactory
    tools = ToolFactory._create_email_tools(imap_client=MagicMock(), storage=mailbox.storage, owner_id=OWNER)
    names = [tool.name for tool in tools]
    assert "edit_draft" not in names
    assert {"create_draft", "list_drafts", "update_draft", "delete_draft", "send_draft"} <= set(names)
    assert len(names) == len(set(names))


def test_approval_input_reads_current_native_content_and_cc(mailbox):
    draft = mailbox.draft(to=["customer@example.test"], subject="Original subject", body="Original body.",
                          cc=["copy@example.test"])
    mailbox.state.edit(draft, to=["saved@example.test"], subject="Saved Gmail subject", body="Saved Gmail body.")
    card = mailbox.tool().approval_input({"draft_id": draft["id"]})
    assert card["draft_id"] == draft["id"] and card["to"] == "saved@example.test"
    assert card["subject"] == "Saved Gmail subject" and card["body"].strip() == "Saved Gmail body."
    assert card["cc"] == "copy@example.test"


def test_approval_input_without_id_never_hydrates_the_newest_draft(mailbox):
    mailbox.draft(subject="First")
    mailbox.draft(subject="Newer")
    assert mailbox.tool().approval_input({}) == {}


def test_execute_applies_explicit_card_edits_to_native_content_before_sending(mailbox):
    draft = mailbox.draft()
    result = asyncio.run(mailbox.tool().execute(draft_id=draft["id"], to="edited@example.test",
        subject="Edited subject", body="Edited body.", cc="copy@example.test", bcc="private@example.test"))
    assert result.status is ToolStatus.SUCCESS, result.error
    sent = mailbox.state.sent_message()
    assert str(sent["To"]) == "edited@example.test" and str(sent["Subject"]) == "Edited subject"
    assert sent.get_content().strip() == "Edited body."
    assert str(sent["Cc"]) == "copy@example.test" and str(sent["Bcc"]) == "private@example.test"
    assert len(mailbox.state.update_calls) == len(mailbox.state.send_calls) == 1
    assert mailbox.storage.get_draft(OWNER, draft["id"]) is None
    mailbox.no_private_drafts()


def test_execute_without_edits_sends_saved_content_without_rewriting_it(mailbox):
    draft = mailbox.draft(subject="Unedited subject", body="Unedited body.")
    result = asyncio.run(mailbox.tool().execute(draft_id=draft["id"]))
    assert result.status is ToolStatus.SUCCESS
    assert mailbox.state.update_calls == []
    sent = mailbox.state.sent_message()
    assert str(sent["Subject"]) == "Unedited subject" and sent.get_content().strip() == "Unedited body."


@pytest.mark.parametrize("body_edit", [None, "Deliberate approval edit."])
def test_actual_approval_loop_hydrates_and_preserves_unedited_gmail_changes(mailbox, monkeypatch, body_edit):
    draft = mailbox.draft(to=["original@example.test"], subject="Original subject", body="Original body.")
    agent = approved_agent(mailbox, monkeypatch)
    observed = []
    async def approve(use_id, name, card):
        observed.append(dict(card))
        assert name == "send_draft" and card["draft_id"] == draft["id"]
        assert card["to"] == "original@example.test" and card["body"].strip() == "Original body."
        mailbox.state.edit(draft, to=["later@example.test"], subject="Later Gmail subject", body="Later Gmail body.")
        answer = dict(card)
        if body_edit is not None:
            answer["body"] = body_edit
        return True, answer
    results, _ = asyncio.run(agent._execute_tools([block(draft)], approve))
    assert observed and len(mailbox.state.send_calls) == 1
    sent = mailbox.state.sent_message()
    assert str(sent["To"]) == "later@example.test" and str(sent["Subject"]) == "Later Gmail subject"
    assert sent.get_content().strip() == (body_edit or "Later Gmail body.")
    assert len(mailbox.state.update_calls) == int(body_edit is not None)


@pytest.mark.parametrize("decision", [None, False])
def test_real_send_tool_cannot_dispatch_without_approval(mailbox, monkeypatch, decision):
    draft = mailbox.draft()
    agent = approved_agent(mailbox, monkeypatch)
    async def refuse(*args):
        return decision, None
    results, _ = asyncio.run(agent._execute_tools([block(draft)], None if decision is None else refuse))
    assert results and mailbox.state.send_calls == [] and mailbox.state.update_calls == []
    assert mailbox.storage.get_draft(OWNER, draft["id"]) is not None


def test_failed_save_of_approval_edits_never_falls_through_to_send(mailbox, monkeypatch):
    draft = mailbox.draft()
    mailbox.state.update_error = RuntimeError("Synthetic lost update acknowledgement")
    async def approve(use_id, name, card):
        return True, {**card, "body": "An explicit edit"}
    results, _ = asyncio.run(approved_agent(mailbox, monkeypatch)._execute_tools([block(draft)], approve))
    assert results and len(mailbox.state.update_calls) == 1
    assert mailbox.state.send_calls == [] and mailbox.state.sent_rows == []
