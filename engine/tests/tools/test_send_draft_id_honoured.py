"""The send paths must honour the draft id they are given, or send nothing.

Both engine send paths used to fall back to "the most recent draft" when no
id reached them: the `send_draft` tool (schema made draft_id optional) and the
`/email send` slash command. A mailbox normally holds several drafts, so that
fallback does not degrade — it mails a different customer.

The id can be lost upstream too: the semantic command matcher declares a
`send draft {draft_id:text}` template, but `_extract_params` has no extractor
for `text`, so an id the user spelled out never lands in `params`. Rewriting
to a bare `/email send` then turned "send THAT draft" into "send whichever
draft the handler picks".

Runs against a real temp SQLite DB — no storage mocks. Only the outbound SMTP
boundary (IMAPClient.send_message) is stubbed.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

OWNER = "owner-send-draft-id-test"


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "send_draft_id_test.db"
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
    """An older target draft and a newer decoy — the decoy is what every
    "most recent" fallback would reach for."""
    target = storage.create_draft(
        owner_id=OWNER,
        to="target@example.com",
        subject="Re: the one the operator meant",
        body="Target body.",
    )
    decoy = storage.create_draft(
        owner_id=OWNER,
        to="decoy@example.com",
        subject="Re: a different customer",
        body="Decoy body.",
    )
    return target, decoy


# --------------------------------------------------------------- send_draft


def test_tool_sends_the_named_draft_not_the_newest(fresh_storage):
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    target, decoy = _two_drafts(fresh_storage)

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-msg-target"}

    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute(draft_id=target["id"]))

    assert result.status == ToolStatus.SUCCESS
    _, kwargs = imap.send_message.call_args
    assert kwargs["to"] == "target@example.com"
    assert kwargs["subject"] == "Re: the one the operator meant"

    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "sent"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_tool_refuses_an_unknown_id_and_sends_nothing(fresh_storage):
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    target, decoy = _two_drafts(fresh_storage)

    imap = MagicMock()
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute(draft_id="9bde5315-0000-0000-0000-000000000000"))

    assert result.status == ToolStatus.ERROR
    assert "not found" in result.error.lower()
    imap.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "draft"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_tool_refuses_a_missing_id_and_sends_nothing(fresh_storage):
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    _two_drafts(fresh_storage)

    imap = MagicMock()
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute())

    imap.send_message.assert_not_called()
    assert result.status == ToolStatus.ERROR
    assert "draft_id" in result.error


def test_tool_schema_requires_the_draft_id(fresh_storage):
    """The model can only pass an id the schema declares as required."""
    from zylch.tools.gmail_tools import SendDraftTool

    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)
    schema = tool.get_schema()

    assert schema["input_schema"]["required"] == ["draft_id"]
    assert "draft_id" in schema["input_schema"]["properties"]


# ------------------------------------------------------- abbreviated handles


def test_an_unambiguous_prefix_resolves_and_sends(fresh_storage):
    """The 8-character handle is the form the operator is actually given —
    `cs review` prints `engine <id[:8]>` and calls it the handle a draft is
    retired by. A send path that only takes the full uuid refuses the only id
    the operator has in front of them."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    target, decoy = _two_drafts(fresh_storage)

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-msg-target"}
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)

    result = _run(tool.execute(draft_id=target["id"][:8]))

    assert result.status == ToolStatus.SUCCESS
    _, kwargs = imap.send_message.call_args
    assert kwargs["to"] == "target@example.com"
    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "sent"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_an_ambiguous_prefix_errors_explicitly_and_sends_nothing(fresh_storage):
    """Two drafts, one prefix: picking either is how "send THAT draft" becomes
    a mail to a different customer."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    shared = "abcd1234"
    first = fresh_storage.create_draft(
        owner_id=OWNER, to="one@example.com", subject="One", body="One body."
    )
    second = fresh_storage.create_draft(
        owner_id=OWNER, to="two@example.com", subject="Two", body="Two body."
    )
    # Force the collision the prefix length makes unlikely but not impossible.
    fresh_storage.update_draft(OWNER, first["id"], {"id": f"{shared}-1111"})
    fresh_storage.update_draft(OWNER, second["id"], {"id": f"{shared}-2222"})

    imap = MagicMock()
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute(draft_id=shared))

    assert result.status == ToolStatus.ERROR
    assert "matches 2 drafts" in result.error
    assert f"{shared}-1111" in result.error and f"{shared}-2222" in result.error
    imap.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, f"{shared}-1111")["status"] == "draft"
    assert fresh_storage.get_draft(OWNER, f"{shared}-2222")["status"] == "draft"


def test_a_too_short_handle_is_refused_rather_than_guessed(fresh_storage):
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    target, decoy = _two_drafts(fresh_storage)

    imap = MagicMock()
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)
    result = _run(tool.execute(draft_id=target["id"][:4]))

    assert result.status == ToolStatus.ERROR
    assert "too short" in result.error
    imap.send_message.assert_not_called()
    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "draft"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_the_approval_card_accepts_the_same_handle_as_execute(fresh_storage):
    """The card and the send must not disagree about which draft an id names."""
    from zylch.tools.gmail_tools import SendDraftTool

    target, _decoy = _two_drafts(fresh_storage)
    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)

    card = tool.approval_input({"draft_id": target["id"][:8]})

    assert card["to"] == "target@example.com"
    assert card["subject"] == "Re: the one the operator meant"
    # The card carries the RESOLVED id back, so the approval the human sees
    # and the send that follows it name the same row without re-resolving an
    # abbreviation that another draft could have joined in the meantime.
    assert card["draft_id"] == target["id"]


def test_a_prefix_of_a_sent_draft_still_hydrates_the_card(fresh_storage):
    """Handle resolution searches every status: hiding rows would answer "no
    such draft" for a draft that plainly exists."""
    from zylch.tools.gmail_tools import SendDraftTool

    target, _decoy = _two_drafts(fresh_storage)
    fresh_storage.mark_draft_sent(OWNER, target["id"], "already-sent")

    tool = SendDraftTool(imap_client=MagicMock(), storage=fresh_storage, owner_id=OWNER)
    card = tool.approval_input({"draft_id": target["id"][:8]})

    assert card["to"] == "target@example.com"


def test_a_handle_resolved_from_a_prefix_is_what_the_claim_keys_on(fresh_storage):
    """The claim must key on the RESOLVED id. Keyed on the raw argument it
    would silently stop matching the moment a handle is not a full uuid, and
    every chat send would refuse."""
    from zylch.tools.base import ToolStatus
    from zylch.tools.gmail_tools import SendDraftTool

    target, _decoy = _two_drafts(fresh_storage)
    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-msg-target"}
    tool = SendDraftTool(imap_client=imap, storage=fresh_storage, owner_id=OWNER)

    first = _run(tool.execute(draft_id=target["id"][:8]))
    second = _run(tool.execute(draft_id=target["id"][:8]))

    assert first.status == ToolStatus.SUCCESS
    assert second.status == ToolStatus.ERROR
    assert "already been sent" in second.error
    assert imap.send_message.call_count == 1


# -------------------------------------------------------------- /email send


def test_email_send_without_an_id_refuses(fresh_storage):
    from zylch.services.command_handlers import handle_email

    target, decoy = _two_drafts(fresh_storage)

    out = _run(handle_email(["send"], MagicMock(), OWNER))

    assert "Missing draft ID" in out
    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "draft"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


def test_email_send_with_an_unknown_id_refuses(fresh_storage):
    from zylch.services.command_handlers import handle_email

    target, decoy = _two_drafts(fresh_storage)

    out = _run(handle_email(["send", "9bde5315-0000-0000-0000-000000000000"], MagicMock(), OWNER))

    assert "Draft not found" in out
    assert fresh_storage.get_draft(OWNER, target["id"])["status"] == "draft"
    assert fresh_storage.get_draft(OWNER, decoy["id"])["status"] == "draft"


# ---------------------------------------------------------- command matcher


def test_matcher_declines_a_send_rewrite_that_lost_the_draft_id():
    """The id-less rewrite is what actually fired: the message named a draft,
    the matcher emitted `/email send`, and the handler picked another one."""
    from zylch.services.command_matcher import SemanticCommandMatcher

    matcher = SemanticCommandMatcher()

    assert matcher._format_email({}, "send draft {draft_id:text}") is None
    assert matcher._format_email({}, "send draft") is None
    assert matcher._format_email({}, "send the email") is None


def test_matcher_keeps_a_send_rewrite_that_carries_the_draft_id():
    from zylch.services.command_matcher import SemanticCommandMatcher

    matcher = SemanticCommandMatcher()
    out = matcher._format_email({"draft_id": "abc123"}, "send draft {draft_id:text}")

    assert out == "/email send abc123"
