"""Campaign draft preparation stores mailbox identity and recovery metadata only."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from sqlalchemy import select
from sqlalchemy.orm import Session

from zylch.storage.mailbox_operations import RECEIPTS, digest

HANDLE = "mailbox_draft_id"
REQUEST = "mailbox_draft_request"
RESERVED = {HANDLE, REQUEST}
TERMINAL = {"completed", "not_dispatched"}


class CampaignMailboxError(ValueError):
    code = -32030


@contextmanager
def contact_writer():
    """Serialize metadata claims without retaining a profile writer during Gmail I/O."""
    from zylch.storage.database import get_engine
    with get_engine().connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with Session(bind=conn, expire_on_commit=False) as session:
                yield session
                session.flush()
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def material(params):
    supplied = {}
    for old, native in (("draft_subject", "subject"), ("draft_body", "body")):
        value = params.get(old)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(old + " must be a string or null")
            supplied[native] = value
    if params.get("draft_body_format") is not None:
        if params["draft_body_format"] not in {"plain", "html"}:
            raise ValueError("draft_body_format must be plain or html")
        supplied["body_format"] = params["draft_body_format"]
    if params.get("draft_cc") is not None:
        cc = params["draft_cc"]
        if not isinstance(cc, list) or any(not isinstance(value, str) for value in cc):
            raise ValueError("draft_cc must be an address list")
        supplied["cc"] = cc
    key = params.get("draft_request_key")
    if supplied and (not isinstance(key, str) or not 16 <= len(key) <= 128):
        raise ValueError("stable draft_request_key is required with campaign draft content")
    return supplied, key


def dossier(value, current):
    """Only the engine writes native draft and pending-request bindings."""
    if value is not None and not isinstance(value, dict):
        raise ValueError("dossier must be an object or null")
    existing = dict(current or {})
    incoming = dict(value or {})
    if any(key in incoming and incoming[key] != existing.get(key) for key in RESERVED):
        raise ValueError("mailbox draft bindings are engine-owned")
    return {**{key: val for key, val in incoming.items() if key not in RESERVED},
            **{key: existing[key] for key in RESERVED if key in existing}}


def _contact(session, owner, contact_id, *, preparing=False):
    from zylch.storage.models import Campaign, CampaignContact
    row = session.query(CampaignContact).filter(
        CampaignContact.id == contact_id, CampaignContact.owner_id == owner).one_or_none()
    if row is None:
        raise CampaignMailboxError("campaign_contact_not_found")
    campaign = session.query(Campaign).filter(
        Campaign.id == row.campaign_id, Campaign.owner_id == owner).one_or_none()
    if campaign is None:
        raise CampaignMailboxError("campaign_not_found")
    if preparing and campaign.status != "open":
        raise CampaignMailboxError("campaign_closed")
    return row


def _receipt_key(owner, contact_id, key):
    return "campaign-draft:" + sha256((owner + "\0" + contact_id + "\0" + key).encode()).hexdigest()


def _claim(owner, contact_id, fields, key):
    with contact_writer() as session:
        row = _contact(session, owner, contact_id)
        saved = dict(row.dossier or {})
        prior = saved.get(REQUEST)
        if prior is not None and not isinstance(prior, dict):
            raise CampaignMailboxError("campaign_draft_request_binding_unreadable")
        expected = digest(fields)
        if prior and prior.get("request_key") == key:
            if prior.get("payload_digest") != expected:
                raise CampaignMailboxError("campaign_draft_request_conflict")
            return row.to_dict(), prior, True
        # An older stable request can be replayed after a later edit. Its
        # durable receipt is checked before replacing the contact's current claim.
        receipt_key = _receipt_key(owner, contact_id, key)
        receipt = session.execute(select(RECEIPTS).where(
            RECEIPTS.c.owner == owner, RECEIPTS.c.request_key == receipt_key)).mappings().one_or_none()
        if receipt is not None:
            kind = receipt["kind"]
            if (kind not in {"create", "update"}
                    or kind == "create" and receipt["source"] != "campaign-contact:" + contact_id
                    or kind == "update" and receipt["target"] != saved.get(HANDLE)):
                raise CampaignMailboxError("campaign_draft_receipt_binding_mismatch")
            return row.to_dict(), {"request_key": key, "receipt_key": receipt_key,
                "payload_digest": expected, "kind": kind, "state": receipt["stage"],
                "historical": True}, True
        if prior and (prior.get("state") not in TERMINAL or
                      prior.get("kind") == "create" and prior.get("state") == "completed" and not saved.get(HANDLE)):
            return row.to_dict(), prior, False
        _contact(session, owner, contact_id, preparing=True)
        request = {"request_key": key, "receipt_key": _receipt_key(owner, contact_id, key),
                   "payload_digest": expected, "kind": "update" if saved.get(HANDLE) else "create",
                   "state": "reserved"}
        saved[REQUEST] = request
        row.dossier, row.draft_subject, row.draft_body = saved, None, None
        return row.to_dict(), request, True


def _record(owner, contact_id, request, state, handle=None):
    with contact_writer() as session:
        row = _contact(session, owner, contact_id)
        saved = dict(row.dossier or {})
        current = saved.get(REQUEST)
        if request.get("historical") and (not isinstance(current, dict)
                or current.get("receipt_key") != request["receipt_key"]):
            if handle is None or saved.get(HANDLE) != handle:
                raise CampaignMailboxError("campaign_native_draft_binding_changed")
            return row.to_dict()
        if (not isinstance(current, dict) or current.get("receipt_key") != request["receipt_key"]
                or current.get("payload_digest") != request["payload_digest"]):
            raise CampaignMailboxError("campaign_draft_request_changed")
        if handle is not None:
            if saved.get(HANDLE) not in (None, handle):
                raise CampaignMailboxError("campaign_native_draft_binding_changed")
            saved[HANDLE] = handle
        saved[REQUEST] = {**current, "state": state}
        row.dossier, row.draft_subject, row.draft_body = saved, None, None
        return row.to_dict()


def _recovered(mailbox, owner, contact_id, contact, request):
    receipt = mailbox.operation(request["receipt_key"])
    if receipt is None:
        return None
    if receipt["kind"] != request["kind"]:
        raise CampaignMailboxError("campaign_draft_receipt_binding_mismatch")
    if request["kind"] == "create":
        if receipt["source"] != "campaign-contact:" + contact_id:
            raise CampaignMailboxError("campaign_draft_receipt_binding_mismatch")
    elif receipt["target"] != (contact.get("dossier") or {}).get(HANDLE):
        raise CampaignMailboxError("campaign_native_draft_binding_changed")
    outcome = mailbox.recover(request["receipt_key"])
    if not outcome.get("ok"):
        _record(owner, contact_id, request, receipt["stage"])
        raise CampaignMailboxError(outcome.get("cause") or "campaign_draft_operation_unconfirmed")
    handle = outcome.get("draft_id") or (outcome.get("draft") or {}).get("id") or receipt.get("draft_id")
    if not handle:
        raise CampaignMailboxError("campaign_native_draft_identity_unavailable")
    # Read the current named object without replaying the update or recreating it.
    if mailbox.get(handle) is None:
        raise CampaignMailboxError("campaign_named_draft_not_found:" + handle)
    return _record(owner, contact_id, request, "completed", handle)


def _apply(mailbox, contact_id, contact, fields, request):
    if request["kind"] == "create":
        return mailbox.create(to=[contact["email"]], subject=fields.get("subject", ""),
            body=fields.get("body", ""), body_format=fields.get("body_format", "plain"),
            cc=fields.get("cc"), request_key=request["receipt_key"],
            source_id="campaign-contact:" + contact_id)
    handle = (contact.get("dossier") or {}).get(HANDLE)
    if not handle or mailbox.get(handle) is None:
        raise CampaignMailboxError("campaign_named_draft_not_found:" + str(handle))
    return mailbox.update(handle, request_key=request["receipt_key"], **fields)


def prepare(owner, contact_id, fields, request_key):
    """Create/update once; recovery never reapplies supplied text to a Gmail edit."""
    from .mailbox_drafts import MailboxDrafts
    from .request_policy import assert_tool_allowed
    assert_tool_allowed("create_draft")
    # Install the central receipt schema before opening the metadata writer.
    mailbox = MailboxDrafts(owner)
    contact, request, admitted = _claim(owner, contact_id, fields, request_key)
    if request.get("historical"):
        # The existing central reservation validates the original full payload.
        # Its stable key can only recover; it cannot repeat a completed mutation.
        native = _apply(mailbox, contact_id, contact, fields, request)
        if not isinstance(native, dict) or not native.get("id"):
            raise CampaignMailboxError("campaign_native_draft_identity_unavailable")
        return _record(owner, contact_id, request, "completed", native["id"])
    if not admitted:
        _recovered(mailbox, owner, contact_id, contact, request)
        raise CampaignMailboxError("campaign_prior_draft_operation_pending:" + request["request_key"])
    recovered = _recovered(mailbox, owner, contact_id, contact, request)
    if recovered is not None:
        return recovered
    if request["state"] not in {"reserved", "not_dispatched"}:
        raise CampaignMailboxError("campaign_draft_operation_unconfirmed")
    try:
        native = _apply(mailbox, contact_id, contact, fields, request)
        if not isinstance(native, dict) or not native.get("id"):
            raise CampaignMailboxError("campaign_native_draft_identity_unavailable")
        return _record(owner, contact_id, request, "completed", native["id"])
    except BaseException:
        # No generated text is retained, even if the provider accepted before a crash.
        receipt = mailbox.operation(request["receipt_key"])
        state = ("uncertain" if receipt["stage"] == "completed" else receipt["stage"]) if receipt is not None else "not_dispatched"
        _record(owner, contact_id, request, state)
        raise
