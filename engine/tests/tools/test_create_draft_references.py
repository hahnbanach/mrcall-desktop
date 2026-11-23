"""Folded RFC chains survive mailbox creation; malformed header inputs never append."""
import asyncio

import pytest

from mailbox_tools_fixture import OWNER, cleanup_test_data, mailbox, message
from zylch.tools.base import ToolStatus
from zylch.tools.gmail_tools import CreateDraftTool

IDS = ["<first@client.test>", "<second@company.test>", "<third@client.test>"]


def create(mailbox, references, **overrides):
    values = {"to": "customer@example.test", "subject": "Synthetic reply", "body": "Reply body.",
              "in_reply_to": IDS[-1], "references": references, "thread_id": IDS[0]}
    values.update(overrides)
    return asyncio.run(CreateDraftTool(mailbox.storage, OWNER).execute(**values))


@pytest.mark.parametrize("separator", [" ", "\n", "\r\n ", "\n\t", " \n "])
def test_folded_reference_chain_is_saved_as_the_same_native_headers(mailbox, separator):
    result = create(mailbox, separator.join(IDS))
    assert result.status is ToolStatus.SUCCESS, result.error
    assert len(mailbox.state.create_calls) == 1
    saved = message(mailbox.state.create_calls[0])
    assert str(saved["References"]).split() == IDS
    assert str(saved["In-Reply-To"]) == IDS[-1]
    assert "Bcc" not in saved
    mailbox.no_private_drafts()


@pytest.mark.parametrize("field,value", [
    ("in_reply_to", "<third@client.test>\nBcc: other@example.test"),
    ("references", "<first@client.test>\r\nBcc: other@example.test\r\n<third@client.test>"),
    ("references", ["<first@client.test>\nBcc: other@example.test", IDS[-1]]),
])
def test_malformed_or_injected_identifier_refuses_before_any_append(mailbox, field, value):
    result = create(mailbox, " ".join(IDS), **{field: value}) if field != "references" else create(mailbox, value)
    assert result.status is ToolStatus.ERROR
    assert mailbox.state.create_calls == [] and mailbox.state.send_calls == []
    assert mailbox.storage.list_drafts(OWNER) == []
    mailbox.no_private_drafts()
