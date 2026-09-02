"""A draft already handed to a transport must not go out a second time.

`storage.get_draft` filters on owner + id and NOT on status, while `/email
send` filters `status == "draft"`. So `send_draft(draft_id=X)` called twice
mailed the same customer the same email twice, and the two send paths
disagreed about which drafts were sendable at all.

The rule all three send paths hold: a draft is sendable unless it has already
been handed to a transport. `sent` refuses, `failed` does not, and `sending`
is decided by `storage.claim_draft_for_send` — a live claim refuses, one
abandoned longer than that draft's own window is taken over, because no
listing shows a `sending` row (`drafts.discard` reads the same window, so such
a row can also be retired). The claim is a conditional UPDATE, so two callers
racing on one id produce one delivery and one refusal rather than two mails.

The matching half of that decision is where a transport error parks the draft:
`draft`, not `failed`, because every surface that lists drafts filters
`status == "draft"` and nothing anywhere reads `failed`, so a failed send used
to vanish from the operator's view entirely. And the rollback stops at the
transport call, is conditional on still holding the claim, and only says
"nothing was sent" when the transport actually said so.

Runs against a real temp SQLite DB — no storage mocks. Only the outbound SMTP
boundary is stubbed.
"""

import asyncio
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

OWNER = "owner-double-send-test"


def _naive_utcnow():
    """The shape the DateTime columns store (naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


# ------------------------------------------------- the claim, under a race


def test_two_concurrent_sends_mail_the_customer_once(fresh_storage):
    """The second request arrives while the first is inside SMTP.

    This is the window the old check-then-act code lost: both callers read
    `status='draft'`, both wrote `sending`, both sent. Only the caller that
    wins the conditional update may reach the transport.
    """
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    in_smtp = threading.Event()
    may_return = threading.Event()

    def slow_send(**kwargs):
        in_smtp.set()
        assert may_return.wait(10), "second send never completed"
        return {"id": "sent-concurrent"}

    imap = MagicMock()
    imap.send_message.side_effect = slow_send
    tool = _tool(fresh_storage, imap)

    outcome = {}

    def first():
        outcome["first"] = _run(tool.execute(draft_id=draft["id"]))

    worker = threading.Thread(target=first)
    worker.start()
    assert in_smtp.wait(10), "first send never reached the transport"

    second = _run(tool.execute(draft_id=draft["id"]))

    may_return.set()
    worker.join(10)

    assert outcome["first"].status == ToolStatus.SUCCESS
    assert second.status == ToolStatus.ERROR
    assert "already being sent" in second.error
    assert imap.send_message.call_count == 1
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "sent"


def test_only_one_racing_claim_wins(fresh_storage):
    """The guarantee itself, with no transport in the picture."""
    draft = _draft(fresh_storage)
    start = threading.Barrier(4)
    won = []
    lock = threading.Lock()

    def claim():
        start.wait(10)
        ok = fresh_storage.claim_draft_for_send(OWNER, draft["id"])
        with lock:
            won.append(ok)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert won.count(True) == 1, f"expected exactly one winner, got {won}"
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "sending"


def test_a_failed_draft_can_still_be_claimed(fresh_storage):
    """The claim predicate is `('draft','failed')`, not `('draft',)`."""
    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "failed"})

    assert fresh_storage.claim_draft_for_send(OWNER, draft["id"]) is True
    assert fresh_storage.claim_draft_for_send(OWNER, draft["id"]) is False


def test_a_draft_stranded_in_sending_is_recoverable(fresh_storage):
    """A daemon killed mid-send leaves a row no listing shows.

    `drafts.list` filters `status='draft'`, so without a stale window the
    claim would trade a rare double-send for a permanent black hole.
    """
    from zylch.storage.storage import send_claim_window_minutes
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    # One recipient, so one recipient's window — the row decides it.
    stale_after = send_claim_window_minutes(1)
    abandoned = _naive_utcnow() - timedelta(minutes=stale_after + 1)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "sending", "updated_at": abandoned})

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-recovered"}
    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.SUCCESS
    assert imap.send_message.call_count == 1
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "sent"


def test_a_fresh_sending_claim_is_not_treated_as_stale(fresh_storage):
    """The recovery window must not swallow a send that is genuinely running."""
    draft = _draft(fresh_storage)
    assert fresh_storage.claim_draft_for_send(OWNER, draft["id"]) is True
    assert fresh_storage.claim_draft_for_send(OWNER, draft["id"]) is False


def test_the_window_covers_the_send_the_draft_actually_costs(fresh_storage):
    """A window measured for one recipient double-sends a mail to ten.

    Every recipient is one more RCPT TO, each with its own socket deadline, so
    a ten-recipient send can still be inside SMTP long after a one-recipient
    window has expired. If the claim went stale there, a second caller would
    take the row and deliver the same mail again — and no rollback guard can
    undo a delivery.
    """
    from zylch.storage.storage import (
        SMTP_FIXED_ROUND_TRIPS,
        SMTP_TRANSPORT_TIMEOUT_SECONDS,
        send_claim_window_minutes,
    )

    many = _draft(
        fresh_storage,
        to=", ".join(f"person{i}@example.com" for i in range(10)),
    )
    one_recipient_window = send_claim_window_minutes(1)
    assert fresh_storage.claim_draft_for_send(OWNER, many["id"]) is True

    # The moment a one-recipient window would have expired, this draft's send
    # may still be running: its claim must hold.
    fresh_storage.update_draft(
        OWNER,
        many["id"],
        {"updated_at": _naive_utcnow() - timedelta(minutes=one_recipient_window + 1)},
    )
    assert fresh_storage.claim_draft_for_send(OWNER, many["id"]) is False, (
        "a 10-recipient claim went stale after a 1-recipient window — a second"
        " caller would deliver the same mail again"
    )

    # And the window it does get covers the worst case its transport can take.
    worst_case_minutes = (SMTP_FIXED_ROUND_TRIPS + 10) * SMTP_TRANSPORT_TIMEOUT_SECONDS / 60
    assert send_claim_window_minutes(10) >= worst_case_minutes

    # Past its own window it is recoverable, like any other stranded claim.
    fresh_storage.update_draft(
        OWNER,
        many["id"],
        {"updated_at": _naive_utcnow() - timedelta(minutes=send_claim_window_minutes(10) + 1)},
    )
    assert fresh_storage.claim_draft_for_send(OWNER, many["id"]) is True


def test_cc_and_bcc_count_towards_the_window(fresh_storage):
    """One envelope carries To, Cc and Bcc, so each of them is a RCPT TO."""
    from zylch.storage.storage import send_claim_recipient_count

    assert send_claim_recipient_count("a@x.com, b@x.com", ["c@x.com"], ["d@x.com"]) == 4
    # The string and list shapes of `to` count the same.
    assert send_claim_recipient_count(["a@x.com", "b@x.com"]) == 2


def test_a_late_rollback_never_resurrects_a_delivered_draft(fresh_storage):
    """The worst failure this design can have, and it is reachable.

    Caller A's send outlives the stale window; caller B re-claims the row and
    delivers the mail; A then fails and rolls back. An UNGUARDED rollback
    writes `draft` over the delivered row, and the same mail can go out a
    third time — a rare race turned into a repeatable double-send. The
    rollback must therefore be conditional on still holding the claim.
    """
    from zylch.storage.storage import send_claim_window_minutes
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    a_in_smtp = threading.Event()
    a_may_fail = threading.Event()

    def a_send(**kwargs):
        a_in_smtp.set()
        assert a_may_fail.wait(10), "A was never released"
        raise smtplib.SMTPDataError(451, b"try again later")

    imap_a = MagicMock()
    imap_a.send_message.side_effect = a_send
    outcome = {}

    def run_a():
        outcome["a"] = _run(_tool(fresh_storage, imap_a).execute(draft_id=draft["id"]))

    worker = threading.Thread(target=run_a)
    worker.start()
    assert a_in_smtp.wait(10), "A never reached the transport"

    # A's claim ages out while A is still inside SMTP.
    fresh_storage.update_draft(
        OWNER,
        draft["id"],
        {"updated_at": _naive_utcnow() - timedelta(minutes=send_claim_window_minutes(1) + 1)},
    )

    imap_b = MagicMock()
    imap_b.send_message.return_value = {"id": "sent-by-b"}
    b = _run(_tool(fresh_storage, imap_b).execute(draft_id=draft["id"]))
    assert b.status == ToolStatus.SUCCESS

    a_may_fail.set()
    worker.join(10)

    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert (
        stored["status"] == "sent"
    ), "a delivered draft was resurrected to 'draft' and is sendable again"

    third = _run(_tool(fresh_storage, MagicMock()).execute(draft_id=draft["id"]))
    assert third.status == ToolStatus.ERROR


def test_discarding_a_draft_a_live_send_owns_destroys_nothing(fresh_storage, monkeypatch):
    """`drafts.discard` decides on a read; a send can claim in between.

    The row is deleted while the transport is mid-send: the customer gets the
    mail, `mark_draft_sent` updates zero rows, and nothing anywhere records
    that it went out. Reproduced with the exact interleaving — the discard
    reads the draft BEFORE the send claims it — by giving the handler that
    pre-claim snapshot. Everything else, the claim and the delete included,
    runs against the real database.
    """
    import asyncio as _asyncio

    from zylch.rpc import draft_actions
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    snapshot = fresh_storage.get_draft(OWNER, draft["id"])  # read: status 'draft'

    in_smtp = threading.Event()
    may_return = threading.Event()

    def slow_send(**kwargs):
        in_smtp.set()
        assert may_return.wait(10), "the discard never returned"
        return {"id": "sent-while-discarding"}

    imap = MagicMock()
    imap.send_message.side_effect = slow_send
    outcome = {}

    def send():
        outcome["send"] = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    worker = threading.Thread(target=send)
    worker.start()
    assert in_smtp.wait(10), "the send never reached the transport"

    class _StaleRead:
        """Real storage, except the one read that opens the race."""

        def get_draft(self, owner_id, draft_id):
            return dict(snapshot)

        def claim_draft_for_send(self, *args, **kwargs):
            return fresh_storage.claim_draft_for_send(*args, **kwargs)

        def delete_draft(self, *args, **kwargs):
            return fresh_storage.delete_draft(*args, **kwargs)

    monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: _StaleRead())
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)

    result = _asyncio.run(draft_actions.drafts_discard({"draft_id": draft["id"]}, lambda *a: None))

    may_return.set()
    worker.join(10)

    assert result["ok"] is False, "discarded a draft a live send owns"
    assert result["reason"] == "send_in_flight"
    assert outcome["send"].status == ToolStatus.SUCCESS
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored is not None, "the record of a delivered mail was deleted"
    assert stored["status"] == "sent"
    assert stored["sent_message_id"] == "sent-while-discarding"


def test_a_caller_that_lost_the_claim_does_not_rewrite_the_row(fresh_storage):
    """Approval-card edits are persisted INSIDE the claim.

    Editing first would let a losing caller rewrite the recipient or body of a
    row another request is mailing at that moment, so the delivered mail and
    the stored `sent` copy would say different things.
    """
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    assert fresh_storage.claim_draft_for_send(OWNER, draft["id"]) is True  # somebody else

    imap = MagicMock()
    result = _run(
        _tool(fresh_storage, imap).execute(
            draft_id=draft["id"], to="hijack@example.com", body="EDITED BODY"
        )
    )

    assert result.status == ToolStatus.ERROR
    imap.send_message.assert_not_called()
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored["body"] == "Body."
    assert stored["to_addresses"] == ["customer@example.com"]


def test_the_refusal_says_sent_when_the_row_is_sent(fresh_storage):
    """ "Already being sent by another request" is the wrong news for a row
    that has already gone out."""
    draft = _draft(fresh_storage)
    fresh_storage.update_draft(OWNER, draft["id"], {"status": "sent"})

    refusal = _tool(fresh_storage, MagicMock())._claim_refusal(draft["id"])

    assert "already been sent" in refusal


# ------------------------------------------------ what the operator is told


def test_a_server_refusal_says_nothing_was_sent(fresh_storage):
    """The server answered with a code: the mail provably did not go out."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.side_effect = smtplib.SMTPRecipientsRefused(
        {"customer@example.com": (550, b"no such user")}
    )

    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.ERROR
    assert "Nothing was sent" in result.error
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


def test_a_dropped_socket_admits_that_delivery_is_unknown(fresh_storage):
    """A socket that dies mid-DATA may have died AFTER the server took the
    message. Claiming "nothing was sent" there is a confident lie, and
    re-opening the draft invites a duplicate of a mail already delivered."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.side_effect = ConnectionResetError("connection reset by peer")

    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    from zylch.storage.storage import send_claim_window_minutes

    assert result.status == ToolStatus.ERROR
    assert "NOT known" in result.error
    assert "Nothing was sent" not in result.error
    # And it names the hold rather than pointing at an action that will be
    # refused for the whole window.
    assert f"{send_claim_window_minutes(1)} minutes" in result.error
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored["status"] == "sending"
    assert "connection reset" in (stored.get("error_message") or "")


def test_a_missing_attachment_is_a_refusal_not_an_unknown(fresh_storage):
    """`IMAPClient.send` reads attachments while BUILDING the message, before
    any socket exists, so a file that moved since the draft was written raises
    `FileNotFoundError` — an OSError like a dead socket, but nothing was ever
    offered to a server. Calling it "delivery unknown" parks a mail that never
    left in `sending`, where for the whole claim window it can be neither sent
    nor discarded."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.side_effect = FileNotFoundError("Attachment not found: /tmp/quote.pdf")

    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.ERROR
    assert "Nothing was sent" in result.error
    stored = fresh_storage.get_draft(OWNER, draft["id"])
    assert stored["status"] == "draft", "a mail that never left parked in `sending`"


def test_a_connection_refused_is_a_refusal_not_an_unknown(fresh_storage):
    """It happens before any message byte is offered, so it is definite —
    even though it is an OSError like the uncertain cases."""
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)
    imap = MagicMock()
    imap.send_message.side_effect = ConnectionRefusedError("connection refused")

    result = _run(_tool(fresh_storage, imap).execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.ERROR
    assert "Nothing was sent" in result.error
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "draft"


# ------------------------------------------- bookkeeping after the transport


def test_a_bookkeeping_failure_after_delivery_leaves_the_draft_sent(fresh_storage, monkeypatch):
    """The rollback must not span the transport call.

    The old handler reset the status to `draft` for ANY exception in the send
    block, including one raised after the mail had gone out — which made a
    delivered mail sendable again.
    """
    from zylch.tools.base import ToolStatus

    draft = _draft(fresh_storage)

    def boom(*args, **kwargs):
        raise RuntimeError("DB write failed after the SMTP handshake")

    monkeypatch.setattr(fresh_storage, "mark_draft_sent", boom)

    imap = MagicMock()
    imap.send_message.return_value = {"id": "sent-then-crash"}
    tool = _tool(fresh_storage, imap)

    result = _run(tool.execute(draft_id=draft["id"]))

    assert result.status == ToolStatus.SUCCESS
    assert fresh_storage.get_draft(OWNER, draft["id"])["status"] == "sent"

    # And the delivered mail is not sendable a second time.
    second = _run(tool.execute(draft_id=draft["id"]))
    assert second.status == ToolStatus.ERROR
    assert imap.send_message.call_count == 1


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
