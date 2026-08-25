"""A draft already handed to a transport must not go out a second time.

`storage.get_draft` filters on owner + id and NOT on status, while `/email
send` filters `status == "draft"`. So `send_draft(draft_id=X)` called twice
mailed the same customer the same email twice, and the two send paths
disagreed about which drafts were sendable at all.

The rule both paths now hold: a draft is sendable unless it has already been
handed to a transport — `sent` and `sending` refuse, `failed` does not. The
matching half of that decision is where a transport error parks the draft:
`draft`, not `failed`, because every surface that lists drafts filters
`status == "draft"` and nothing anywhere reads `failed`, so a failed send used
to vanish from the operator's view entirely.

Runs against a real temp SQLite DB — no storage mocks. Only the outbound SMTP
boundary is stubbed.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

OWNER = "owner-double-send-test"


@pytest.fixture
def fresh_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "double_send_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod
    from zylch.storage.storage import Storage

    db_mod.dispose_engine()
    db_mod.init_db()
    yield Storage()
    db_mod.dispose_engine()


def _run(coro):
    return asyncio.run(coro)


def _draft(storage, **kw):
    return storage.create_draft(
        owner_id=OWNER,
        to=kw.get("to", "customer@example.com"),
        subject=kw.get("subject", "Re: your request"),
        body=kw.get("body", "Body."),
    )


def _tool(storage, imap):
    from zylch.tools.gmail_tools import SendDraftTool

    return SendDraftTool(imap_client=imap, storage=storage, owner_id=OWNER)


# ------------------------------------------------------------- send_draft


def test_sending_the_same_draft_twice_mails_the_customer_once(fresh_storage):
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-1"}
    tool = _tool(fresh_storage, imap)

    first = _run(tool.execute(draft_id=draft["id"]))
    second = _run(tool.execute(draft_id=draft["id"]))

    assert first.status == ToolStatus.SUCCESS
    assert second.status == ToolStatus.ERROR
    assert "already been sent" in second.error
    assert imap.send_message.call_count == 1


def test_a_draft_stuck_in_sending_is_refused(fresh_storage):
    """`sending` means another request already owns this draft."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "sending"})

    imap = MagicMock()
    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.ERROR
    imap.send_message.assert_not_called()


def test_a_failed_draft_is_still_retryable_by_id(fresh_storage):
    """A transport error is exactly the case where a retry is wanted."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "failed"})

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-retry"}
    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.SUCCESS
    assert imap.send_message.call_count == 1
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "sent"


def test_a_transport_error_leaves_the_draft_visible_and_sendable(fresh_storage):
    """`failed` hid the draft from every listing; `draft` keeps it in view."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.side_effect = RuntimeError("SMTP 421 service unavailable")

    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.ERROR
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored["status"] == "draft"
    assert "421" in (stored.get("error_message") or "")
    assert draft["id"] in [d["id"] for d in fresh_storage.list_drafts(OWNER)]


def test_the_approval_card_still_hydrates_a_sent_draft(fresh_storage):
    """The guard belongs in `execute`, not in `get_draft`: a lookup that hid
    rows would leave the card hydrator with nothing to show."""
    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "sent"})

    card = _tool(fresh_storage, MagicMock()).approval_input({"draft_id": draft["id"]})

    assert card["to"] == "customer@example.com"
    assert card["subject"] == "Re: your request"


# ------------------------------------------------------------ /email send


def _imap_env(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "secret")


def test_email_send_agrees_that_a_failed_draft_is_sendable(fresh_storage, monkeypatch):
    from zylch.services.command_handlers import handle_email

    _imap_env(monkeypatch)
    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "failed"})

    client = MagicMock()
    client.send_message.return_value = {"id": "sent-via-slash"}
    with (
        patch("zylch.api.token_storage.get_provider", return_value="imap"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.email.imap_client.IMAPClient", return_value=client),
    ):
        out = _run(handle_email(["send", draft["id"]], MagicMock(), OWNER))

    assert "Email sent" in out
    assert client.send_message.call_count == 1


def test_email_send_refuses_a_draft_already_sent(fresh_storage, monkeypatch):
    from zylch.services.command_handlers import handle_email

    _imap_env(monkeypatch)
    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "sent"})

    client = MagicMock()
    with (
        patch("zylch.api.token_storage.get_provider", return_value="imap"),
        patch("zylch.api.token_storage.get_email", return_value="support@example.com"),
        patch("zylch.email.imap_client.IMAPClient", return_value=client),
    ):
        out = _run(handle_email(["send", draft["id"]], MagicMock(), OWNER))

    assert "not found" in out.lower()
    client.send_message.assert_not_called()
