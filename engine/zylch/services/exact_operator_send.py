"""One exact authenticated request through the ordinary SendDraftTool lifecycle."""

import importlib.util

from .exact_draft_delivery import EvidenceRefusal, addresses, snapshot
from .exact_draft_publication_mime import validate
from .exact_draft_retirement_evidence import sent_proof
from .exact_operator_send_transport import prepare, digest
from zylch.storage.draft_operation_send import finish
from .exact_draft_retirement_imap import RetirementMailbox
from .task_assignment_types import AssignmentError
from . import exact_operator_send_context as context
from zylch.storage.draft_operations import DraftOperations, OperationConflict
from zylch.storage.storage import Storage


def supported():
    return importlib.util.find_spec("zylch.services.task_assignment_email_effect") is not None


def material(draft):
    return snapshot({key: value for key, value in draft.items() if key not in context.BOOKKEEPING})


def inspect(owner, uid, draft_id):
    from .exact_operator_send_admission import resolve

    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        raise EvidenceRefusal("draft_not_found")
    refs = draft.get("references") or []
    root = draft.get("thread_id") or (refs[0] if refs else draft.get("in_reply_to"))
    bound = validate(owner, uid, dict(draft, status="draft"), root)
    source = resolve(owner, draft)
    if source is None or source["root"] != bound["root"] or source["target"] != bound["target"]:
        raise EvidenceRefusal("exact_source_unavailable")
    original = source["source"]
    sender = addresses(original.get("from_email"))
    participants = addresses(original.get("to_email")) + addresses(original.get("cc_email"))
    if (
        not sender
        or owner.lower() in sender
        or owner.lower() not in participants
        or bound["recipients"] != sender
        or not set(bound["cc"]) <= set(participants) - {owner.lower()} - set(sender)
    ):
        raise EvidenceRefusal("exact_recipients_mismatch")
    bound.update(source=source["source"], content_digest=material(draft))
    return {
        "version": 1,
        "ok": True,
        "draft_id": draft_id,
        "owner_id": owner,
        "owner_uid": uid,
        "draft": draft,
        "expected_snapshot": snapshot(draft),
        "binding": bound,
    }


def client_for(owner):
    from zylch.email import mailboxes

    mailbox = mailboxes.primary(owner)
    if mailbox is None or mailbox.address != owner:
        raise EvidenceRefusal("mailbox_unavailable")
    return mailboxes.build_imap_client(mailbox)


def verify(owner, uid, draft, bound, transport):
    mailbox = RetirementMailbox(owner)
    try:
        evidence = sent_proof(
            mailbox, draft, owner, uid, {**bound, "sent_message_id": transport["message_id"]}
        )
        rows, inventory = mailbox.inventory(
            "Sent", search_header="Message-ID", search_value=transport["message_id"]
        )
        if (
            len(rows) != 1
            or digest(rows[0]["message"]) != transport["mime_digest"]
            or inventory != {key: value for key, value in evidence.items() if key != "handle"}
        ):
            raise EvidenceRefusal("sent_transport_unverified")
        return {
            **evidence,
            "message_id": transport["message_id"],
            "mime_digest": transport["mime_digest"],
        }
    finally:
        mailbox.close()


async def send(owner, uid, draft_id, expected, operation_id, bound, recheck):
    from .request_policy import assert_tool_allowed
    from .operator_reply_origin import is_scheduled
    from .exact_operator_send_admission import effect
    from zylch.tools.gmail_tools import SendDraftTool

    assert_tool_allowed("send_draft")
    store = DraftOperations()
    reservation = None
    client = None
    request = None

    def outcome(cause, *, sent=False, uncertain=False, **extra):
        return {
            "version": 1,
            "ok": sent,
            "draft_id": draft_id,
            "operation_id": operation_id,
            "owner_id": owner,
            "owner_uid": uid,
            "root": bound.get("root"),
            "expected_snapshot": expected,
            "state": (
                "sent-with-cleanup-pending"
                if sent
                else "delivery-unknown" if uncertain else "send-held"
            ),
            "achieved_stages": ["engine-saved"] + (["sent"] if sent else []),
            "effect_certainty": (
                "verified" if sent else "unknown" if uncertain else "not-dispatched"
            ),
            "cleanup_certainty": "not-dispatched",
            "cause": cause,
            "next_action": (
                "retire-sent-mirror"
                if sent
                else "inspect-operation" if uncertain else "inspect-draft"
            ),
            "audit_reason": "explicit_operator_request",
            **extra,
        }

    try:
        if is_scheduled():
            raise EvidenceRefusal("operator_request_not_interactive")
        current = inspect(owner, uid, draft_id)
        draft = current["draft"]
        if current["binding"] != bound:
            raise EvidenceRefusal("exact_send_binding_changed")
        previous = store.read(uid, operation_id)
        if previous is not None:
            stored_binding = {
                key: value for key, value in previous["binding"].items() if key != "transport"
            }
            if (
                previous["draft_id"] != draft_id
                or previous["expected_snapshot"] != expected
                or stored_binding != bound
                or previous["operation_type"] != "send"
            ):
                raise EvidenceRefusal("operation_binding_changed")
            if previous["stage"] == "not_dispatched":
                return outcome("exact_send_not_dispatched", next_action="new-explicit-operation")
            if previous["stage"] not in {"dispatch_possible", "acknowledged", "completed"}:
                return outcome("exact_send_operation_held", uncertain=previous["active"])
            try:
                evidence = verify(owner, uid, draft, bound, previous["binding"]["transport"])
                if recheck() != (owner, uid) or inspect(owner, uid, draft_id)["binding"] != bound:
                    raise EvidenceRefusal("exact_send_binding_changed")
                finish(store, uid, operation_id, owner, draft, evidence=evidence)
                return outcome("exact_sent_verified", sent=True, provider_handles=evidence)
            except Exception:
                return outcome("exact_send_operation_held", uncertain=True)
        active = store.active(uid, bound["root"])
        if active and active["operation_id"] != operation_id:
            return outcome(
                "thread_operation_held",
                uncertain=True,
                blocking_operation_id=active["operation_id"],
            )
        if previous is None and (
            draft["status"] != "draft" or current["expected_snapshot"] != expected
        ):
            raise EvidenceRefusal("stale_snapshot")
        source = {key: bound[key] for key in ("root", "target", "source")}
        if previous is None:
            with context.scope(owner, uid, operation_id, draft, source):
                with effect(owner, draft):
                    if recheck() != (owner, uid):
                        raise EvidenceRefusal("owner_profile_mismatch")
        from zylch.email.imap_client import IMAPClient

        preparer = object.__new__(IMAPClient)
        preparer.email_addr = owner
        transport = prepare(preparer, draft)
        reservation = store.reserve(
            owner_uid=uid,
            operation_id=operation_id,
            canonical_root=bound["root"],
            operation_type="send",
            draft_id=draft_id,
            expected_snapshot=expected,
            binding={**bound, "transport": transport},
            output_mime_digest=transport["mime_digest"],
        )
        operation = reservation.operation
        if operation["operation_id"] != operation_id:
            return outcome(
                "thread_operation_held",
                uncertain=True,
                blocking_operation_id=operation["operation_id"],
            )
        if not reservation.acquired:
            return outcome("exact_send_operation_held", uncertain=operation["active"])
        token = reservation.executor_token
        store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=0,
            stage="inventoried",
            evidence={"source": source, "audit_reason": "explicit_operator_request"},
        )
        client = client_for(owner)
        store.advance(
            uid, operation_id, executor_token=token, expected_version=1, stage="dispatch_possible"
        )
        with context.scope(owner, uid, operation_id, draft, source, transport) as request:
            await SendDraftTool(client, Storage.get_instance(), owner).execute(draft_id=draft_id)
        after = Storage.get_instance().get_draft(owner, draft_id)
        if not after or after.get("status") != "sent" or material(after) != bound["content_digest"]:
            if request is not None and not request["wire_started"]:
                finish(
                    store,
                    uid,
                    operation_id,
                    owner,
                    after,
                    token=token,
                    cancelled=True,
                    claimed=request["claim_acquired"],
                    evidence={"not_dispatched": True},
                )
                return outcome("exact_send_not_dispatched", next_action="new-explicit-operation")
            return outcome("exact_send_unconfirmed", uncertain=True)
        store.advance(
            uid,
            operation_id,
            executor_token=token,
            expected_version=2,
            stage="acknowledged",
            evidence={"sent_message_id": after.get("sent_message_id")},
        )
        evidence = verify(owner, uid, after, bound, transport)
        if recheck() != (owner, uid):
            raise EvidenceRefusal("owner_profile_mismatch")
        finish(store, uid, operation_id, owner, after, evidence=evidence)
        return outcome("exact_sent_verified", sent=True, provider_handles=evidence)
    except Exception as error:
        retained = store.read(uid, operation_id)
        uncertain = reservation is not None or bool(
            retained and retained["stage"] in {"dispatch_possible", "acknowledged", "completed"}
        )
        if (
            reservation is not None
            and reservation.acquired
            and (request is None or not request["wire_started"])
        ):
            try:
                finish(
                    store,
                    uid,
                    operation_id,
                    owner,
                    Storage.get_instance().get_draft(owner, draft_id),
                    token=reservation.executor_token,
                    cancelled=True,
                    claimed=bool(request and request["claim_acquired"]),
                    evidence={"not_dispatched": True},
                )
                uncertain = False
            except Exception:
                pass
        cause = (
            str(error)
            if isinstance(error, (EvidenceRefusal, OperationConflict, AssignmentError))
            else "exact_send_unavailable"
        )
        return outcome(cause, uncertain=uncertain)
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
