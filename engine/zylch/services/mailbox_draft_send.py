"""Single native dispatch and Sent reconciliation, without retrying a mutation."""

from datetime import timezone
from email.utils import getaddresses, parsedate_to_datetime

from .mailbox_draft_mime import MailboxDraftError, build, native_id, parse, sending_raw


def confirm(service, receipt):
    # Even a completed local receipt is checked against the provider. It is an
    # operation identity, not an independent archive of what was delivered.
    if receipt["stage"] in {"reserved", "not_dispatched"}:
        return receipt["result"] or service._outcome(receipt, cause="send_not_dispatched")
    try:
        with service.provider() as client:
            matches = client.sent(receipt["message_id"])
        if len(matches) != 1:
            raise MailboxDraftError("sent_not_yet_confirmed" if not matches else "sent_identity_ambiguous")
        result = service._outcome(receipt, ok=True, state="sent", sent={
            "id": matches[0]["message_id"], "message_id": receipt["message_id"],
        })
        service.operations.advance(receipt, None, "completed", result=result)
        return result
    except Exception as error:
        result = service._outcome(receipt, state="unconfirmed", cause=service._cause(error))
        if receipt["stage"] == "dispatch_possible":
            service.operations.advance(receipt, None, "unconfirmed", result=result)
        return result


def send_status(service, draft_id, request_key):
    """Read an existing send operation; absence cannot admit a provider mutation."""
    native_id(service.owner, draft_id)
    previous = service.operation(request_key)
    if previous is not None:
        if previous["kind"] != "send" or previous["target"] != draft_id:
            raise MailboxDraftError("request_key_payload_conflict")
    if previous is None:
        return {"ok": False, "state": "not_found", "cause": "named_send_operation_not_found",
                "draft_id": draft_id, "request_key": request_key, "effect_certainty": "not-dispatched"}
    return confirm(service, previous)


def send(service, draft_id, request_key):
    from .operator_reply_origin import is_scheduled
    if is_scheduled():
        raise MailboxDraftError("scheduled_existing_draft_preserved", draft_id=draft_id)
    identifier = native_id(service.owner, draft_id)
    service._updates_safe(draft_id)
    previous = service.operation(request_key)
    if previous is not None:
        if previous["kind"] != "send" or previous["target"] != draft_id:
            raise MailboxDraftError("request_key_payload_conflict")
        return confirm(service, previous)
    previous = service.operations.for_draft(service.owner, draft_id)
    if previous is not None:
        return confirm(service, previous)
    # The current immutable container is read before claiming the operation so
    # every send path shares the exact RFC inbound identity in its durable fence.
    with service.provider() as client:
        current = client.get_draft(identifier)
    if current is None:
        previous = service.operations.for_draft(service.owner, draft_id)
        if previous is not None:
            return confirm(service, previous)
        provenance = service.operations.provenance(service.owner, draft_id)
        receipt, token = service._reserve(request_key, "send", draft_id,
                                          provenance["source"] if provenance else "", [draft_id])
        if token is None:
            return confirm(service, receipt)
        return service._failure(receipt, token, MailboxDraftError("named_draft_not_found"), dispatched=False)
    draft = service.present(current)
    receipt, token = service._reserve(request_key, "send", draft_id,
                                      draft.get("in_reply_to") or "", [draft_id])
    if token is None:
        return confirm(service, receipt)
    dispatched = False
    try:
        with service.provider() as client:
            current = client.get_draft(identifier)
            if current is None:
                raise MailboxDraftError("named_draft_not_found", draft_id=draft_id)
            draft = service.present(current)
            if (draft.get("in_reply_to") or "") != receipt["source"]:
                raise MailboxDraftError("draft_source_changed_before_send")
            raw = sending_raw(service.owner, current["raw"], receipt["message_id"])
            receipt = service.operations.advance(receipt, token, "dispatch_possible")
            with service._policy(draft):
                # Native send consumes this exact draft container. A 404 can
                # never fall back to messages.send or to recreating the draft.
                dispatched = True
                client.send_draft(identifier, raw)
        return confirm(service, receipt)
    except Exception as error:
        result = service._failure(receipt, token, error, dispatched=dispatched)
        return confirm(service, service.operation(receipt["request_key"])) if dispatched and not getattr(error, "non_dispatch", False) else result


def send_message(service, to, subject, body, *, request_key, cc=None, bcc=None,
                 in_reply_to=None, references=None, thread_id=None, source_id=None,
                 body_format="plain", **kwargs):
    if kwargs.get("attachment_paths"):
        raise MailboxDraftError("draft_attachments_not_supported")
    fields = dict(to=to, subject=subject, body=body, cc=cc, bcc=bcc,
                  in_reply_to=in_reply_to, references=references, thread_id=thread_id,
                  source_id=source_id, body_format=body_format)
    receipt, token = service._reserve(request_key, "send_message", thread_id or "",
                                      in_reply_to or source_id or "", fields)
    if token is None:
        return confirm(service, receipt)
    dispatched = False
    try:
        raw = build(service.owner, message_id=receipt["message_id"], **fields)
        msg = parse(raw)
        from .operator_reply_origin import is_scheduled
        if is_scheduled():
            msg["Auto-Submitted"] = "auto-replied"
        raw = sending_raw(service.owner, msg.as_bytes(), receipt["message_id"])
        with service.provider() as client:
            if in_reply_to:
                existing = service.existing_for_source(in_reply_to, thread_id)
                if existing:
                    result = service._outcome(receipt, state="draft_exists",
                                               cause="existing_draft_preserved",
                                               draft_id=existing[0]["id"])
                    service.operations.advance(receipt, token, "not_dispatched", result=result)
                    return result
            receipt = service.operations.advance(receipt, token, "dispatch_possible")
            with service._policy(fields):
                dispatched = True
                client.send_message(raw)
        return confirm(service, receipt)
    except Exception as error:
        result = service._failure(receipt, token, error, dispatched=dispatched)
        return confirm(service, service.operation(receipt["request_key"])) if dispatched and not getattr(error, "non_dispatch", False) else result


def _date(message):
    try:
        result = parsedate_to_datetime(str(message.get("Date") or ""))
    except (ValueError, TypeError, IndexError, OverflowError):
        raise MailboxDraftError("conversation_date_unavailable") from None
    if result is None:
        raise MailboxDraftError("conversation_date_unavailable")
    return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc)


def answered(service, source):
    """Observe current Sent in the native conversation before composing.

    Company-member answers outside this mailbox still pass through the existing
    assignment projection, which owns trusted member identity and coverage.
    """
    target = source.get("message_id_header") or source.get("in_reply_to")
    if not target:
        raise MailboxDraftError("exact_source_headers_required")
    with service.provider() as client:
        values = client.conversation(target)
    messages = [(value, parse(value["raw"])) for value in values]
    selected = [(value, msg) for value, msg in messages if str(msg.get("Message-ID") or "") == target]
    if len(selected) != 1:
        raise MailboxDraftError("mailbox_source_unavailable")
    source_date = _date(selected[0][1])
    newer_sent = []
    newer_inbound = []
    for value, msg in messages:
        labels = set(value.get("labels") or [])
        if labels & {"DRAFT", "TRASH", "SPAM"}:
            continue
        sender = [address.lower() for _, address in getaddresses([str(msg.get("From") or "")])]
        when = _date(msg)
        if "SENT" in labels and when >= source_date:
            newer_sent.append((when, value))
        elif sender != [service.owner] and when > source_date:
            newer_inbound.append(when)
    if not newer_sent:
        return False
    latest = max(when for when, _ in newer_sent)
    return not any(when > latest for when in newer_inbound)
