"""Named native handles never fall back to a newer or similarly named draft.

The mailbox-only contract replaces UUID prefix resolution with a complete,
mailbox-bound native handle. The missing-ID and target-versus-decoy risks remain.
"""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from mailbox_tools_fixture import OWNER, cleanup_test_data, mailbox
from zylch.services.mailbox_draft_mime import handle
from zylch.tools.base import ToolStatus


def two_drafts(mailbox):
    return (mailbox.draft(to=["target@example.test"], subject="Target", body="Target body."),
            mailbox.draft(to=["decoy@example.test"], subject="Decoy", body="Decoy body."))


def test_tool_sends_the_named_draft_not_the_newest(mailbox):
    target, decoy = two_drafts(mailbox)
    result = asyncio.run(mailbox.tool().execute(draft_id=target["id"]))
    assert result.status is ToolStatus.SUCCESS, result.error
    sent = mailbox.state.sent_message()
    assert str(sent["To"]) == "target@example.test" and str(sent["Subject"]) == "Target"
    assert mailbox.storage.get_draft(OWNER, target["id"]) is None
    assert mailbox.storage.get_draft(OWNER, decoy["id"])["id"] == decoy["id"]
    mailbox.no_private_drafts()


def test_unknown_full_handle_and_missing_id_send_nothing(mailbox):
    target, decoy = two_drafts(mailbox)
    unknown = asyncio.run(mailbox.tool().execute(draft_id=handle(OWNER, "missing-native-container")))
    missing = asyncio.run(mailbox.tool().execute())
    assert unknown.status is ToolStatus.ERROR and "named_draft_not_found" in unknown.error
    assert missing.status is ToolStatus.ERROR and "draft_id" in missing.error
    assert mailbox.state.send_calls == []
    assert {row["id"] for row in mailbox.storage.list_drafts(OWNER)} == {target["id"], decoy["id"]}


def test_tool_schema_requires_the_full_draft_id(mailbox):
    schema = mailbox.tool().get_schema()["input_schema"]
    assert schema["required"] == ["draft_id"] and "draft_id" in schema["properties"]


@pytest.mark.parametrize("form", ["short", "shared_mailbox_prefix", "unique_prefix", "bare_native_id", "foreign_mailbox"])
def test_partial_or_foreign_handles_never_resolve_or_hydrate(mailbox, form):
    target, decoy = two_drafts(mailbox)
    values = {"short": target["id"][:4],
              "shared_mailbox_prefix": target["id"].rsplit(":", 1)[0] + ":native-draft-",
              "unique_prefix": target["id"][:-5],
              "bare_native_id": target["provider_draft_id"],
              "foreign_mailbox": handle("foreign@example.test", target["provider_draft_id"])}
    value = values[form]
    card = mailbox.tool().approval_input({"draft_id": value})
    result = asyncio.run(mailbox.tool().execute(draft_id=value))
    assert result.status is ToolStatus.ERROR
    assert card == {"draft_id": value}, "A partial handle must not authorize a resolved container through the approval card"
    assert mailbox.state.send_calls == []
    assert len(mailbox.storage.list_drafts(OWNER)) == 2


def test_full_handle_hydrates_current_card_and_sent_handle_has_no_editable_copy(mailbox):
    target, decoy = two_drafts(mailbox)
    tool = mailbox.tool()
    assert tool.approval_input({"draft_id": target["id"]})["to"] == "target@example.test"
    sent = asyncio.run(tool.execute(draft_id=target["id"]))
    assert sent.status is ToolStatus.SUCCESS
    assert tool.approval_input({"draft_id": target["id"]}) == {"draft_id": target["id"]}
    assert mailbox.storage.get_draft(OWNER, decoy["id"]) is not None
    mailbox.no_private_drafts()


def test_slash_send_names_the_same_target_and_refuses_missing_or_unknown_id(mailbox):
    from zylch.services.command_handlers import handle_email
    target, decoy = two_drafts(mailbox)
    missing = asyncio.run(handle_email(["send"], MagicMock(), OWNER))
    unknown = asyncio.run(handle_email(["send", handle(OWNER, "unknown")], MagicMock(), OWNER))
    assert "Missing draft ID" in missing
    assert json.loads(unknown)["cause"] == "named_draft_not_found"
    assert mailbox.state.send_calls == []
    result = json.loads(asyncio.run(handle_email(["send", target["id"]], MagicMock(), OWNER)))
    assert result["ok"] and mailbox.state.sent_message()["To"] == "target@example.test"
    assert mailbox.storage.get_draft(OWNER, decoy["id"]) is not None


def test_matcher_declines_send_rewrites_that_lose_the_named_id():
    from zylch.services.command_matcher import SemanticCommandMatcher
    matcher = SemanticCommandMatcher()
    for pattern in ("send draft {draft_id:text}", "send draft", "send the email"):
        assert matcher._format_email({}, pattern) is None


def test_matcher_preserves_the_complete_opaque_handle():
    from zylch.services.command_matcher import SemanticCommandMatcher
    identifier = handle(OWNER, "native-container")
    assert SemanticCommandMatcher()._format_email({"draft_id": identifier}, "send draft {draft_id:text}") == "/email send " + identifier
