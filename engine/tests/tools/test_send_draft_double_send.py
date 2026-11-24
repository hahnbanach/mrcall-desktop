"""Once dispatch may have occurred, only Sent observation can settle the operation.

Private row claims, recipient-sized leases and SMTP bookkeeping are retired.
Their functional risks remain: races, delayed visibility, failed readback,
late cleanup, explicit retries after definite refusal, and editing a live send.
These tests exercise tools/commands with real persistent receipt transactions.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from unittest.mock import MagicMock

import pytest

from mailbox_tools_fixture import OWNER, cleanup_test_data, mailbox
from zylch.email.mailbox_errors import MailboxProviderError
from zylch.tools.base import ToolStatus


def send(mailbox, draft, route="tool", **edits):
    if route == "tool":
        return asyncio.run(mailbox.tool().execute(draft_id=draft["id"], **edits))
    from zylch.services.command_handlers import handle_email
    return json.loads(asyncio.run(handle_email(["send", draft["id"]], MagicMock(), OWNER)))


def test_repeated_send_returns_original_confirmed_message_once(mailbox):
    draft = mailbox.draft()
    first, replay = send(mailbox, draft), send(mailbox, draft)
    assert first.status is replay.status is ToolStatus.SUCCESS
    assert first.data["message_id"] == replay.data["message_id"]
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1
    assert mailbox.storage.get_draft(OWNER, draft["id"]) is None
    mailbox.no_private_drafts()


def test_two_concurrent_requests_share_one_dispatch(mailbox):
    draft = mailbox.draft()
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(5), "Synthetic dispatch was not released"
    mailbox.state.before_send = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(send, mailbox, draft)
        assert entered.wait(5)
        try:
            second = send(mailbox, draft)
            assert second.status is ToolStatus.ERROR and second.data["state"] == "unconfirmed"
            assert len(mailbox.state.send_calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5).status is ToolStatus.SUCCESS
    assert len(mailbox.state.sent_rows) == 1


@pytest.mark.parametrize("recipient_count", [1, 10])
def test_lost_ack_receipt_never_expires_and_storage_reopen_only_rechecks_sent(mailbox, recipient_count):
    from zylch.storage import database as db
    draft = mailbox.draft(to=[f"recipient{n}@example.test" for n in range(recipient_count)],
                          cc=["copy@example.test"], bcc=["hidden@example.test"])
    mailbox.state.sent_visible, mailbox.state.lose_ack = False, True
    first = send(mailbox, draft)
    assert first.status is ToolStatus.ERROR and first.data["state"] == "unconfirmed"
    original_id = first.data["message_id"]
    # Passage of time cannot turn possible dispatch into permission to transmit.
    with db.get_engine().begin() as conn:
        conn.exec_driver_sql("UPDATE mailbox_operation_receipts SET created_at=0, updated_at=0 WHERE kind='send'")
    db.dispose_engine()
    replay = send(mailbox, draft)
    assert replay.status is ToolStatus.ERROR and replay.data["message_id"] == original_id
    assert len(mailbox.state.send_calls) == 1
    mailbox.state.sent_visible = True
    confirmed = send(mailbox, draft)
    assert confirmed.status is ToolStatus.SUCCESS and confirmed.data["message_id"] == original_id
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1
    received = mailbox.state.sent_message()
    assert len(received["To"].addresses) == recipient_count
    assert str(received["Cc"]) == "copy@example.test" and str(received["Bcc"]) == "hidden@example.test"


def test_unknown_wire_failure_and_empty_sent_never_authorize_another_transmission(mailbox):
    draft = mailbox.draft()
    mailbox.state.transport_error = ConnectionResetError("Synthetic connection loss")
    first = send(mailbox, draft)
    assert first.status is ToolStatus.ERROR and first.data["effect_certainty"] == "unconfirmed"
    assert "Nothing was sent" not in first.error
    for _ in range(2):
        assert send(mailbox, draft).data["state"] == "unconfirmed"
    assert len(mailbox.state.send_calls) == 1 and mailbox.state.sent_rows == []
    assert mailbox.storage.get_draft(OWNER, draft["id"]) is not None


@pytest.mark.parametrize("route", ["tool", "slash"])
def test_definite_provider_refusal_stays_visible_and_new_explicit_attempt_can_retry(mailbox, route):
    draft = mailbox.draft()
    error = MailboxProviderError("smtp_recipient_refused", non_dispatch=True)
    error.non_dispatch = True
    mailbox.state.refusal = error
    first = send(mailbox, draft, route)
    outcome = first.data if route == "tool" else first
    assert outcome["state"] == "not_dispatched" and outcome["effect_certainty"] == "not-dispatched"
    assert mailbox.storage.get_draft(OWNER, draft["id"]) is not None
    assert len(mailbox.state.sent_rows) == 0
    mailbox.state.refusal = None
    retry = send(mailbox, draft, route)
    retry_outcome = retry.data if route == "tool" else retry
    assert retry_outcome["ok"] and retry_outcome["state"] == "sent"
    assert retry_outcome["operation_id"] != outcome["operation_id"]
    assert len(mailbox.state.send_calls) == 2 and len(mailbox.state.sent_rows) == 1
    send(mailbox, draft, route)
    assert len(mailbox.state.send_calls) == 2


def test_native_attachment_is_refused_before_dispatch_without_hiding_the_draft(mailbox):
    draft = mailbox.draft()
    native = mailbox.state.native(draft)
    from mailbox_tools_fixture import message
    mime = message(native["raw"])
    mime.add_attachment(b"Synthetic attachment", maintype="application", subtype="octet-stream", filename="fixture.bin")
    native["raw"] = mime.as_bytes()
    result = send(mailbox, draft)
    assert result.status is ToolStatus.ERROR and "draft_attachments_not_supported" in result.error
    assert result.data["effect_certainty"] == "not-dispatched"
    assert mailbox.state.send_calls == []
    assert mailbox.storage.get_draft(OWNER, draft["id"])["attachments"]


def test_lost_ack_is_settled_immediately_when_sent_already_proves_delivery(mailbox):
    draft = mailbox.draft()
    mailbox.state.lose_ack = True
    result = send(mailbox, draft)
    assert result.status is ToolStatus.SUCCESS
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1


def test_sent_read_failure_cannot_reclassify_an_accepted_send_as_not_dispatched(mailbox):
    draft = mailbox.draft()
    error = MailboxProviderError("imap_read_unavailable", non_dispatch=True)
    error.non_dispatch = True  # Even this read error cannot undo an earlier mutation.
    mailbox.state.sent_error = error
    first = send(mailbox, draft)
    assert first.status is ToolStatus.ERROR and first.data["state"] == "unconfirmed"
    assert first.data["effect_certainty"] == "unconfirmed"
    mailbox.state.sent_error = None
    assert send(mailbox, draft).status is ToolStatus.SUCCESS
    assert len(mailbox.state.send_calls) == 1


def test_receipt_write_failure_after_delivery_never_reopens_dispatch(mailbox, monkeypatch):
    from zylch.storage.mailbox_operations import MailboxOperations
    original = MailboxOperations.advance
    fail_once = [True]
    def advance(self, receipt, token, stage, **kwargs):
        if receipt["kind"] == "send" and stage == "completed" and fail_once[0]:
            fail_once[0] = False
            raise RuntimeError("Synthetic receipt completion failure")
        return original(self, receipt, token, stage, **kwargs)
    monkeypatch.setattr(MailboxOperations, "advance", advance)
    draft = mailbox.draft()
    first = send(mailbox, draft)
    assert first.status is ToolStatus.ERROR and first.data["state"] == "unconfirmed"
    replay = send(mailbox, draft)
    assert replay.status is ToolStatus.SUCCESS
    assert replay.data["message_id"] == first.data["message_id"]
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1


def test_explicit_trash_of_draft_cannot_erase_uncertain_send_receipt(mailbox):
    draft = mailbox.draft()
    mailbox.state.lose_ack, mailbox.state.sent_visible = True, False
    first = send(mailbox, draft)
    assert first.data["state"] == "unconfirmed"
    assert mailbox.storage.delete_draft(OWNER, draft["id"]) is True
    assert send(mailbox, draft).data["state"] == "unconfirmed"
    mailbox.state.sent_visible = True
    assert send(mailbox, draft).data["message_id"] == first.data["message_id"]
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1


def test_losing_send_attempt_cannot_apply_edits_to_a_draft_already_dispatching(mailbox):
    draft = mailbox.draft()
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(5)
    mailbox.state.before_send = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(send, mailbox, draft)
        assert entered.wait(5)
        try:
            second = send(mailbox, draft, to="different@example.test", body="A competing edit")
            assert second.status is ToolStatus.ERROR
            assert mailbox.state.update_calls == [], "An active send receipt must fence approval-card updates"
        finally:
            release.set()
        assert first.result(timeout=5).status is ToolStatus.SUCCESS
    assert mailbox.state.sent_message().get_content().strip() == "Saved body."
    assert len(mailbox.state.send_calls) == 1


def test_send_cannot_dispatch_a_draft_while_an_update_is_in_flight(mailbox):
    draft = mailbox.draft()
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(5)
    mailbox.state.before_update = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        updating = pool.submit(mailbox.service().update, draft["id"],
                               request_key="explicit-update-request-0001", body="The approved edit")
        assert entered.wait(5)
        try:
            competing = send(mailbox, draft)
            assert competing.status is ToolStatus.ERROR
            assert "draft_update_operation_unconfirmed" in competing.error
            assert mailbox.state.send_calls == [], "Send must wait until the native update is settled"
        finally:
            release.set()
        updated = updating.result(timeout=5)
        assert updated["body"].strip() == "The approved edit"
    assert send(mailbox, updated).status is ToolStatus.SUCCESS
    assert mailbox.state.sent_message().get_content().strip() == "The approved edit"
    assert len(mailbox.state.send_calls) == len(mailbox.state.sent_rows) == 1


def test_competing_updates_cannot_overwrite_a_native_save_in_flight(mailbox):
    draft = mailbox.draft()
    entered, release = Event(), Event()
    def wait():
        entered.set()
        assert release.wait(5)
    mailbox.state.before_update = wait
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(mailbox.service().update, draft["id"], body="First approved edit")
        assert entered.wait(5)
        try:
            from zylch.services.mailbox_drafts import MailboxDraftError
            with pytest.raises(MailboxDraftError, match="draft_update_operation_unconfirmed"):
                mailbox.service().update(draft["id"], body="A competing overwrite")
            assert len(mailbox.state.update_calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5)["body"].strip() == "First approved edit"


def test_uncertain_update_fence_survives_storage_reopen_and_original_request_replay(mailbox):
    from zylch.storage import database as db
    from zylch.services.mailbox_drafts import MailboxDraftError
    draft = mailbox.draft()
    key = "lost-update-ack-request-0001"
    mailbox.state.update_error = TimeoutError("Synthetic update acknowledgement lost")
    with pytest.raises(MailboxDraftError):
        mailbox.service().update(draft["id"], request_key=key, body="An uncertain edit")
    original = mailbox.service().operation(key)
    assert original["stage"] == "unconfirmed"
    with db.get_engine().begin() as conn:
        conn.exec_driver_sql("UPDATE mailbox_operation_receipts SET created_at=0, updated_at=0 WHERE kind='update'")
    db.dispose_engine()
    mailbox.state.update_error = None
    with pytest.raises(MailboxDraftError) as error:
        mailbox.service().update(draft["id"], request_key=key, body="An uncertain edit")
    replay = error.value.details["outcome"]
    assert replay["operation_id"] == original["id"] and replay["state"] == "unconfirmed"
    assert send(mailbox, draft).status is ToolStatus.ERROR
    with pytest.raises(MailboxDraftError, match="draft_update_operation_unconfirmed"):
        mailbox.service().update(draft["id"], body="A fresh overwrite")
    assert len(mailbox.state.update_calls) == 1 and mailbox.state.send_calls == []
