"""Internal exact operator scope; no scheduled-origin or global hold override."""

from contextlib import contextmanager
from contextvars import ContextVar
import os

from .exact_draft_delivery import snapshot
from .task_assignment_types import AssignmentError

_request = ContextVar("exact_operator_send", default=None)
BOOKKEEPING = {"status", "updated_at", "sent_at", "sent_message_id", "error_message", "provider"}


def manual_hold(value, uid, root, target):
    evidence = value.get("reply_evidence") or []
    return (
        value.get("actor_uid") == uid
        and value.get("source_owner_uid") == uid
        and value.get("thread_key") == root
        and value.get("task") is None
        and value.get("state") == "needs-assignment"
        and value.get("reason") == "NEEDS_HUMAN_VERIFICATION"
        and value.get("hold_auto_reply") is True
        and value.get("authority_complete") is not False
        and target in value.get("current_message_ids", [])
        and bool(evidence)
        and all(isinstance(item, dict) and item.get("complete") is True for item in evidence)
        and any(
            item.get("judgement")
            in {
                "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE",
                "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION",
            }
            for item in evidence
        )
    )


@contextmanager
def scope(owner, uid, operation_id, draft, bound, transport=None):
    from .operator_reply_origin import is_scheduled

    if is_scheduled() or _request.get() is not None:
        raise AssignmentError("operator_request_not_interactive")
    request = dict(
        owner=owner,
        uid=uid,
        operation_id=operation_id,
        draft=draft,
        binding=bound,
        claim_used=False,
        claim_acquired=False,
        wire_started=False,
        transport=transport,
    )
    token = _request.set(request)
    try:
        yield request
    finally:
        _request.reset(token)


def preflight(owner, draft):
    request = _request.get()
    if request is not None and (
        owner != request["owner"] or snapshot(draft) != snapshot(request["draft"])
    ):
        raise AssignmentError("exact_send_snapshot_changed")


def permits(owner, draft, source, projected):
    request = _request.get()
    if request is None:
        return False
    expected = request["draft"]
    if (
        owner != request["owner"]
        or source != request["binding"]
        or any(draft.get(key) != value for key, value in expected.items() if key not in BOOKKEEPING)
    ):
        raise AssignmentError("exact_send_binding_changed")
    return projected is not None and manual_hold(
        projected, request["uid"], source["root"], source["target"]
    )


def claim_allowed(session, owner, draft_id):
    from sqlalchemy import text

    exists = session.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='draft_provider_operations'")
    ).first()
    if not exists:
        return True
    rows = session.execute(
        text(
            "SELECT operation_id, stage FROM draft_provider_operations WHERE owner_uid=:uid AND draft_id=:draft AND operation_type='send' AND active=1"
        ),
        {"uid": os.environ.get("OWNER_ID", ""), "draft": draft_id},
    ).all()
    if not rows:
        return _request.get() is None
    request = _request.get()
    if (
        len(rows) != 1
        or request is None
        or request["owner"] != owner
        or request["draft"]["id"] != draft_id
        or request["operation_id"] != rows[0][0]
        or rows[0][1] != "dispatch_possible"
        or request["claim_used"]
    ):
        return False
    request["claim_used"] = True
    return True


def claimed(acquired):
    request = _request.get()
    if request is not None:
        request["claim_acquired"] = acquired


def transport_message(message, owner, recipients):
    from .exact_operator_send_transport import digest

    request = _request.get()
    if request is None:
        return message
    expected = request["transport"]
    if expected is None or owner != request["owner"]:
        raise AssignmentError("exact_transport_unavailable")
    for header, key in (("Message-ID", "message_id"), ("Date", "date")):
        message.replace_header(header, expected[key])
    if digest(message) != expected["mime_digest"] or sorted(recipients) != expected["recipients"]:
        raise AssignmentError("exact_transport_changed")
    return message


def wire_started():
    request = _request.get()
    if request is not None:
        request["wire_started"] = True
