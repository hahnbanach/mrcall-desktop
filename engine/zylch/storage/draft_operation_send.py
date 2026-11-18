"""Exact-send terminal transitions spanning native claim and operation journal."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from sqlalchemy import select, update

from .draft_operations import TABLE, _writer, _public, OperationConflict
from .models import Draft, Email


def finish(
    store,
    uid,
    operation_id,
    owner,
    expected_draft,
    *,
    evidence,
    token=None,
    cancelled=False,
    claimed=False,
):
    from zylch.services.exact_operator_send import material

    with _writer(store.engine) as conn:
        operation = (
            conn.execute(
                select(TABLE).where(TABLE.c.owner_uid == uid, TABLE.c.operation_id == operation_id)
            )
            .mappings()
            .one()
        )
        raw = (
            conn.execute(
                select(Draft.__table__).where(
                    Draft.owner_id == owner, Draft.id == operation["draft_id"]
                )
            )
            .mappings()
            .one_or_none()
        )
        actual = Draft(**dict(raw)).to_dict() if raw is not None else None
        if operation["operation_type"] != "send" or actual is None or actual != expected_draft:
            raise OperationConflict("draft_changed")
        if material(actual) != operation["binding"]["content_digest"]:
            raise OperationConflict("draft_changed")
        from zylch.services.task_assignment_mail import row_identity

        source = operation["binding"]["source"]
        stored_source = (
            conn.execute(
                select(Email.__table__).where(Email.owner_id == owner, Email.id == source["id"])
            )
            .mappings()
            .one_or_none()
        )
        if stored_source is None or row_identity(dict(stored_source)) != source:
            raise OperationConflict("source_changed")
        if cancelled:
            if not token or operation["executor_token"] != token or not operation["active"]:
                raise OperationConflict("operation_executor_changed")
            if operation["stage"] not in {"reserved", "inventoried", "dispatch_possible"}:
                raise OperationConflict("invalid_operation_transition")
            if actual["status"] == "sending" and not claimed:
                raise OperationConflict("foreign_send_claim")
            if actual["status"] not in {"draft", "sending", "failed"}:
                raise OperationConflict("native_claim_changed")
            if claimed:
                conn.execute(
                    update(Draft)
                    .where(Draft.id == actual["id"], Draft.owner_id == owner)
                    .values(status="draft", error_message=None)
                )
            stage = "not_dispatched"
        else:
            transport = operation["binding"]["transport"]
            if (
                evidence.get("mime_digest") != transport["mime_digest"]
                or evidence.get("message_id") != transport["message_id"]
            ):
                raise OperationConflict("sent_identity_changed")
            if operation["stage"] == "completed":
                if (
                    actual["status"] != "sent"
                    or actual.get("sent_message_id") != transport["message_id"]
                ):
                    raise OperationConflict("native_sent_changed")
                return _public(operation)
            if operation["stage"] not in {"dispatch_possible", "acknowledged"} or actual[
                "status"
            ] not in {"sending", "sent", "draft", "failed"}:
                raise OperationConflict("native_claim_changed")
            if (
                actual["status"] == "sent"
                and actual.get("sent_message_id") != transport["message_id"]
            ):
                raise OperationConflict("sent_identity_changed")
            if actual["status"] != "sent":
                date = (
                    parsedate_to_datetime(transport["date"])
                    .astimezone(timezone.utc)
                    .replace(tzinfo=None)
                )
                conn.execute(
                    update(Draft)
                    .where(Draft.id == actual["id"], Draft.owner_id == owner)
                    .values(
                        status="sent",
                        sent_message_id=transport["message_id"],
                        sent_at=date,
                        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        error_message=None,
                    )
                )
            stage = "completed"
        values = dict(
            stage=stage,
            version=operation["version"] + 1,
            active=False,
            executor_token="",
            verification=evidence,
        )
        conn.execute(
            update(TABLE)
            .where(TABLE.c.owner_uid == uid, TABLE.c.operation_id == operation_id)
            .values(**values)
        )
        return _public({**operation, **values})
