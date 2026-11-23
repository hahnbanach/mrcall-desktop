"""Campaign producers keep generated text only in the native mailbox."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from test_mailbox_caller_journey import journey, NativeMailbox, OWNER, parsed
from zylch.rpc import campaign_actions as ca
from zylch.services import campaign_mailbox
from zylch.services.mailbox_draft_mime import build
from zylch.storage import database as db
from zylch.storage.models import Campaign, CampaignContact


def notify(*args):
    pass


def campaign():
    return asyncio.run(ca.campaign_create({"name": "Synthetic campaign"}, notify))


def add(camp, key="campaign-create-key-0001", **extra):
    return asyncio.run(ca.campaign_add_contact({"campaign_id": camp["id"], "email": "recipient@example.test",
        "draft_subject": "Synthetic subject", "draft_body": "Synthetic model composed text",
        "draft_request_key": key, **extra}, notify))


def update(contact, key="campaign-update-key-0001", **fields):
    return asyncio.run(ca.campaign_update_contact({"contact_id": contact["id"],
        "draft_request_key": key, **fields}, notify))


def stored(contact_id):
    with db.get_session() as session:
        return session.query(CampaignContact).filter(CampaignContact.id == contact_id).one().to_dict()


def test_native_create_and_sparse_update_store_only_handle_and_request_hashes(journey):
    contact = add(campaign(), dossier={"research": "Synthetic research"})
    assert contact["draft_body"] is None and contact["draft_subject"] is None
    native_id = contact["dossier"]["mailbox_draft_id"]
    assert native_id.startswith("gmail:") and NativeMailbox.creates == 1
    native = next(iter(NativeMailbox.drafts.values()))
    assert parsed(native["raw"]).get_content().strip() == "Synthetic model composed text"
    native["raw"] = build(OWNER, to=["edited@example.test"], subject="Subject from Gmail", body="Human saved body")
    result = update(contact, draft_subject="New explicit subject")["contact"]
    current = parsed(next(iter(NativeMailbox.drafts.values()))["raw"])
    assert str(current["To"]) == "edited@example.test" and current.get_content().strip() == "Human saved body"
    assert str(current["Subject"]) == "New explicit subject"
    assert result["dossier"]["mailbox_draft_id"] == native_id
    assert result["dossier"]["research"] == "Synthetic research"
    assert result["draft_body"] is None and result["draft_subject"] is None


def test_same_key_replay_preserves_gmail_edits_and_rejects_changed_request(journey):
    camp = campaign()
    contact = add(camp)
    update(contact, draft_body="Explicit update")
    native = next(iter(NativeMailbox.drafts.values()))
    native["raw"] = build(OWNER, to=["human@example.test"], subject="Human subject", body="Later Gmail edit")
    replay = update(contact, draft_body="Explicit update")["contact"]
    assert replay["dossier"]["mailbox_draft_id"] == contact["dossier"]["mailbox_draft_id"]
    assert parsed(native["raw"]).get_content().strip() == "Later Gmail edit"
    with pytest.raises(campaign_mailbox.CampaignMailboxError, match="request_conflict"):
        update(contact, draft_body="Different supplied text")
    assert NativeMailbox.creates == 1


@pytest.mark.parametrize("external", ["sent", "deleted"])
def test_missing_named_native_draft_never_recreates(journey, external):
    contact = add(campaign())
    original = contact["dossier"]["mailbox_draft_id"]
    row = NativeMailbox.drafts.pop(next(iter(NativeMailbox.drafts)))
    if external == "sent":
        NativeMailbox.delivered.append(row["raw"])
    with pytest.raises(campaign_mailbox.CampaignMailboxError, match="named_draft_not_found"):
        update(contact, draft_body="New proposed text")
    assert NativeMailbox.creates == 1 and not NativeMailbox.drafts
    assert stored(contact["id"])["dossier"]["mailbox_draft_id"] == original


def test_conditional_request_key_and_owner_or_closed_campaign_boundaries(journey, monkeypatch):
    camp = campaign()
    with pytest.raises(ValueError, match="draft_request_key"):
        asyncio.run(ca.campaign_add_contact({"campaign_id": camp["id"], "email": "recipient@example.test",
            "draft_body": "Unkeyed text"}, notify))
    monkeypatch.setattr(ca, "_owner_id", lambda: "foreign@example.test")
    with pytest.raises(ValueError, match="campaign not found"):
        add(camp)
    monkeypatch.setattr(ca, "_owner_id", lambda: OWNER)
    with db.get_session() as session:
        session.query(Campaign).filter(Campaign.id == camp["id"]).one().status = "closed"
    with pytest.raises(campaign_mailbox.CampaignMailboxError, match="campaign_closed"):
        add(camp)
    assert NativeMailbox.creates == 0


def test_null_legacy_housekeeping_does_not_clear_native_text_or_binding(journey):
    contact = add(campaign())
    before = next(iter(NativeMailbox.drafts.values()))["raw"]
    result = asyncio.run(ca.campaign_update_contact({"contact_id": contact["id"], "draft_subject": None,
        "draft_body": None, "dossier": {"research": "Updated research"}}, notify))["contact"]
    assert next(iter(NativeMailbox.drafts.values()))["raw"] == before
    assert result["dossier"]["mailbox_draft_id"] == contact["dossier"]["mailbox_draft_id"]
    assert result["dossier"]["mailbox_draft_request"] == contact["dossier"]["mailbox_draft_request"]
    with pytest.raises(ValueError, match="engine-owned"):
        asyncio.run(ca.campaign_update_contact({"contact_id": contact["id"],
            "dossier": {"mailbox_draft_id": "some-other-container"}}, notify))


def test_provider_authorization_failure_never_persists_generated_text(journey, monkeypatch):
    from zylch.email.gmail_auth import GmailError
    def unavailable(owner):
        raise GmailError("gmail_authorization_required")
    monkeypatch.setattr("zylch.email.gmail_mailbox.GmailMailbox", unavailable)
    with pytest.raises(Exception, match="gmail_authorization_required"):
        add(campaign())
    with db.get_session() as session:
        contact = session.query(CampaignContact).one().to_dict()
    assert contact["draft_body"] is None and contact["draft_subject"] is None
    assert "mailbox_draft_id" not in contact["dossier"]
    assert "Synthetic model composed text" not in str(contact)
    assert NativeMailbox.creates == 0


def test_concurrent_adds_and_completed_receipt_before_handle_attachment_keep_one_container(journey, monkeypatch):
    camp = campaign()
    entered, release = Event(), Event()
    real_create = NativeMailbox.create_draft
    def wait_create(self, *args, **kwargs):
        entered.set()
        assert release.wait(5), "Synthetic test release was not signaled"
        return real_create(self, *args, **kwargs)
    monkeypatch.setattr(NativeMailbox, "create_draft", wait_create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(add, camp)
        assert entered.wait(5)
        second = pool.submit(add, camp, "campaign-concurrent-key-0002")
        try:
            with pytest.raises(Exception):
                second.result(timeout=5)
        finally:
            release.set()
        contact = first.result(timeout=5)
    assert NativeMailbox.creates == 1 and len(NativeMailbox.drafts) == 1
    assert stored(contact["id"])["dossier"]["mailbox_draft_id"] == contact["dossier"]["mailbox_draft_id"]

    # A process can die after central receipt completion, before the contact gets its handle.
    other = asyncio.run(ca.campaign_add_contact({"campaign_id": camp["id"], "email": "other@example.test"}, notify))
    real_record = campaign_mailbox._record
    def crash(owner, contact_id, request, state, handle=None):
        if handle is not None:
            raise RuntimeError("Synthetic crash before handle attachment")
        return real_record(owner, contact_id, request, state, handle)
    monkeypatch.setattr(campaign_mailbox, "_record", crash)
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        update(other, key="campaign-crash-key-00001", draft_body="Crash boundary text")
    assert NativeMailbox.creates == 2 and "mailbox_draft_id" not in stored(other["id"])["dossier"]
    monkeypatch.setattr(campaign_mailbox, "_record", real_record)
    recovered = update(other, key="campaign-crash-key-00001", draft_body="Crash boundary text")["contact"]
    assert recovered["dossier"]["mailbox_draft_id"].startswith("gmail:")
    assert NativeMailbox.creates == 2 and len(NativeMailbox.drafts) == 2


def test_public_dispatch_accepts_key_and_reserved_metadata_cannot_rebind(journey):
    import json
    from zylch.rpc.dispatch import dispatch_raw
    camp = campaign()
    response = asyncio.run(dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 1,
        "method": "campaign.add_contact", "params": {"campaign_id": camp["id"],
            "email": "recipient@example.test", "draft_body": "Native campaign text",
            "draft_request_key": "campaign-dispatch-key-0001"}}), notify))
    assert "error" not in response, response
    contact = response["result"]
    assert contact["draft_subject"] is None and contact["draft_body"] is None
    original = stored(contact["id"])["dossier"]
    with pytest.raises(ValueError, match="engine-owned"):
        asyncio.run(ca.campaign_update_contact({"contact_id": contact["id"], "dossier": {
            "mailbox_draft_request": {**original["mailbox_draft_request"], "state": "not_dispatched"}}}, notify))
    assert stored(contact["id"])["dossier"] == original
    assert NativeMailbox.creates == 1


def test_authorization_repair_uses_new_request_without_retaining_failed_text(journey, monkeypatch):
    from zylch.email.gmail_auth import GmailError
    camp = campaign()
    def unavailable(owner):
        raise GmailError("gmail_authorization_required")
    monkeypatch.setattr("zylch.email.gmail_mailbox.GmailMailbox", unavailable)
    with pytest.raises(Exception, match="gmail_authorization_required"):
        add(camp)
    with db.get_session() as session:
        initial = session.query(CampaignContact).one().to_dict()
    assert initial["draft_subject"] is None and initial["draft_body"] is None
    with db.get_engine().connect() as conn:
        receipts = [tuple(row) for row in conn.exec_driver_sql("SELECT payload_digest, result FROM mailbox_operation_receipts")]
    assert "Synthetic model composed text" not in str(receipts)
    monkeypatch.setattr("zylch.email.gmail_mailbox.GmailMailbox", NativeMailbox)
    repaired = add(camp, key="campaign-auth-repaired-0001")
    assert repaired["id"] == initial["id"] and NativeMailbox.creates == 1
    assert repaired["draft_subject"] is None and repaired["draft_body"] is None


def test_native_attachment_update_refuses_and_metadata_only_contact_needs_no_provider(journey, monkeypatch):
    from zylch.email.gmail_auth import GmailError
    camp = campaign()
    contact = add(camp)
    native = next(iter(NativeMailbox.drafts.values()))
    message = parsed(native["raw"])
    message.add_attachment(b"Synthetic attachment", maintype="application", subtype="octet-stream", filename="fixture.bin")
    native["raw"] = message.as_bytes()
    before = native["raw"]
    with pytest.raises(Exception, match="draft_attachments_not_supported"):
        update(contact, draft_subject="Subject-only edit")
    assert native["raw"] == before and NativeMailbox.creates == 1
    assert stored(contact["id"])["draft_body"] is None
    def unavailable(owner):
        raise GmailError("gmail_authorization_required")
    monkeypatch.setattr("zylch.email.gmail_mailbox.GmailMailbox", unavailable)
    ordinary = asyncio.run(ca.campaign_add_contact({"campaign_id": camp["id"],
        "email": "ordinary@example.test", "language": "en"}, notify))
    changed = asyncio.run(ca.campaign_update_contact({"contact_id": ordinary["id"], "language": "fr"}, notify))
    assert changed["contact"]["language"] == "fr" and NativeMailbox.creates == 1


def test_public_pack_queue_preserves_html_cc_and_native_replay(journey):
    import json
    from zylch.rpc.dispatch import dispatch_raw
    camp = campaign()
    contact = asyncio.run(ca.campaign_add_contact({"campaign_id": camp["id"],
        "email": "pack-recipient@example.test"}, notify))
    params = {"contact_id": contact["id"], "draft_subject": "Rendered pack subject",
        "draft_body": "<p>Rendered pack <strong>content</strong>.</p>",
        "draft_body_format": "html", "draft_cc": ["pack-copy@example.test"],
        "draft_request_key": "campaign-pack-queue-key-0001"}
    def invoke():
        return asyncio.run(dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 9,
            "method": "campaign.update_contact", "params": params}), notify))
    response = invoke()
    assert "error" not in response, response
    result = response["result"]["contact"]
    native = next(iter(NativeMailbox.drafts.values()))
    current = parsed(native["raw"])
    assert current.get_content_type() == "text/html"
    assert current.get_content().strip() == params["draft_body"]
    assert str(current["Cc"]) == "pack-copy@example.test"
    assert str(current["To"]) == "pack-recipient@example.test"
    assert result["draft_subject"] is None and result["draft_body"] is None
    native["raw"] = build(OWNER, to=["edited@example.test"], subject="Person's subject", body="Saved Gmail edit")
    again = invoke()
    assert again["result"]["contact"]["dossier"]["mailbox_draft_id"] == result["dossier"]["mailbox_draft_id"]
    assert parsed(native["raw"]).get_content().strip() == "Saved Gmail edit"
    assert NativeMailbox.creates == 1 and NativeMailbox.transmissions == 0


def test_replaying_older_create_or_edit_key_does_not_replace_latest_claim(journey):
    camp = campaign()
    contact = add(camp)
    update(contact, draft_body="Edit B")
    before = stored(contact["id"])["dossier"]
    native = next(iter(NativeMailbox.drafts.values()))
    native["raw"] = build(OWNER, to=["human@example.test"], subject="Human subject", body="Human edit after B")
    add(camp)
    assert stored(contact["id"])["dossier"] == before
    assert parsed(native["raw"]).get_content().strip() == "Human edit after B"
    update(contact, key="campaign-update-key-0003", draft_body="Edit C")
    latest = stored(contact["id"])["dossier"]
    update(contact, draft_body="Edit B")
    assert stored(contact["id"])["dossier"] == latest
    assert parsed(native["raw"]).get_content().strip() == "Edit C"
    with pytest.raises(Exception, match="request_key_payload_conflict"):
        add(camp, draft_body="Wrong replay body")
    assert stored(contact["id"])["dossier"] == latest
    update(contact, key="campaign-update-key-0004", draft_body="Edit D")
    assert parsed(native["raw"]).get_content().strip() == "Edit D"
    assert NativeMailbox.creates == 1 and NativeMailbox.transmissions == 0
