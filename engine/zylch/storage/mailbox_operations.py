"""Durable mailbox effect receipts; these records never contain editable mail."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import secrets
import time
from uuid import uuid4

from sqlalchemy import Column, Float, MetaData, String, Table, Text, UniqueConstraint, select

logger = logging.getLogger(__name__)
_metadata = MetaData()
RECEIPTS = Table(
    "mailbox_operation_receipts", _metadata,
    Column("id", String, primary_key=True),
    Column("owner", String, nullable=False),
    Column("request_key", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("target", String, nullable=False),
    Column("source", String, nullable=False),
    Column("payload_digest", String, nullable=False),
    Column("message_id", String, nullable=False),
    Column("draft_id", String),
    Column("stage", String, nullable=False),
    Column("executor", String, nullable=False),
    Column("result", Text),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("owner", "request_key"),
)


class ReceiptConflict(ValueError):
    """The requested effect conflicts with an existing durable identity."""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _public(row):
    if row is None:
        return None
    result = dict(row)
    result.pop("executor", None)
    result["result"] = json.loads(result["result"]) if result["result"] else None
    return result


class MailboxOperations:
    def __init__(self, engine=None):
        if engine is None:
            from .database import get_engine
            engine = get_engine()
        self.engine = engine
        _metadata.create_all(engine)

    @contextmanager
    def writer(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA synchronous=FULL")
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def read(self, owner, request_key):
        with self.engine.connect() as conn:
            row = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.request_key == request_key,
            )).mappings().one_or_none()
        return _public(row)

    def for_draft(self, owner, draft_id, kind="send", *, active_only=False):
        with self.engine.connect() as conn:
            query = select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.target == draft_id,
                RECEIPTS.c.kind == kind,
                RECEIPTS.c.stage != "not_dispatched",
            )
            if active_only:
                query = query.where(RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]))
            rows = conn.execute(query.order_by(RECEIPTS.c.created_at)).mappings().all()
        return _public(rows[0]) if rows else None

    def reserve(self, *, owner, request_key, kind, target, source="", payload_digest,
                message_id=""):
        if kind not in {"create", "send", "send_message", "trash", "update"}:
            raise ReceiptConflict("invalid_mailbox_operation")
        if not isinstance(request_key, str) or not 16 <= len(request_key) <= 256:
            raise ReceiptConflict("stable_request_key_required")
        if any(not isinstance(v, str) for v in (owner, target, source, payload_digest)):
            raise ReceiptConflict("invalid_mailbox_binding")
        with self.writer() as conn:
            old = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.request_key == request_key,
            )).mappings().one_or_none()
            if old is not None:
                if any(old[k] != v for k, v in {
                    "kind": kind, "target": target, "source": source,
                    "payload_digest": payload_digest,
                }.items()):
                    raise ReceiptConflict("request_key_payload_conflict")
                return _public(old), None
            if kind == "send":
                prior_send = conn.execute(select(RECEIPTS).where(
                    RECEIPTS.c.owner == owner, RECEIPTS.c.target == target,
                    RECEIPTS.c.kind == "send", RECEIPTS.c.stage != "not_dispatched",
                ).order_by(RECEIPTS.c.created_at)).mappings().first()
                if prior_send is not None:
                    return _public(prior_send), None
            if kind == "trash":
                prior_trash = conn.execute(select(RECEIPTS).where(
                    RECEIPTS.c.owner == owner, RECEIPTS.c.target == target,
                    RECEIPTS.c.kind == "trash",
                    RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]),
                ).order_by(RECEIPTS.c.created_at)).mappings().first()
                if prior_trash is not None:
                    return _public(prior_trash), None
            if kind in {"send", "update"}:
                conflicting_kinds = ["update"] if kind == "send" else ["send", "update"]
                active_target = conn.execute(select(RECEIPTS.c.kind).where(
                    RECEIPTS.c.owner == owner, RECEIPTS.c.target == target,
                    RECEIPTS.c.kind.in_(conflicting_kinds),
                    RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]),
                ).order_by(RECEIPTS.c.created_at)).first()
                if active_target is not None:
                    raise ReceiptConflict(f"draft_{active_target.kind}_operation_unconfirmed")
            if source and kind in {"create", "send", "send_message"}:
                active = conn.execute(select(RECEIPTS.c.id).where(
                    RECEIPTS.c.owner == owner, RECEIPTS.c.source == source,
                    RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]),
                )).first()
                if active:
                    raise ReceiptConflict("source_operation_unconfirmed")
            now, token = time.time(), secrets.token_hex(32)
            row = dict(id=str(uuid4()), owner=owner, request_key=request_key, kind=kind,
                       target=target, source=source, payload_digest=payload_digest,
                       message_id=message_id, draft_id=None, stage="reserved",
                       executor=token, result=None, created_at=now, updated_at=now)
            conn.execute(RECEIPTS.insert().values(**row))
        logger.debug("[mailbox-receipt] reserve kind=%s", kind)
        return _public(row), token

    def advance(self, receipt, token, stage, *, result=None, draft_id=None):
        transitions = {
            "reserved": {"dispatch_possible", "not_dispatched", "completed"},
            "dispatch_possible": {"unconfirmed", "completed", "not_dispatched"},
            "unconfirmed": {"unconfirmed", "completed"},
            "completed": {"completed"},
        }
        with self.writer() as conn:
            row = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.id == receipt["id"], RECEIPTS.c.owner == receipt["owner"],
            )).mappings().one()
            if token is not None and row["executor"] != token:
                raise ReceiptConflict("mailbox_executor_changed")
            if token is None and stage not in {"completed", "unconfirmed"}:
                raise ReceiptConflict("recovery_cannot_dispatch")
            if stage not in transitions.get(row["stage"], set()):
                raise ReceiptConflict("invalid_mailbox_transition")
            values = {"stage": stage, "updated_at": time.time()}
            if result is not None:
                values["result"] = json.dumps(result, sort_keys=True, allow_nan=False)
            if draft_id is not None:
                values["draft_id"] = draft_id
            conn.execute(RECEIPTS.update().where(RECEIPTS.c.id == row["id"]).values(**values))
            updated = _public({**row, **values})
        logger.debug("[mailbox-receipt] advance kind=%s stage=%s", row["kind"], stage)
        return updated

    def provenance(self, owner, draft_id):
        with self.engine.connect() as conn:
            rows = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.draft_id == draft_id,
                RECEIPTS.c.kind == "create",
            )).mappings().all()
        return _public(rows[0]) if rows else None

    def pending_legacy(self, owner, source):
        if not source:
            return None
        with self.engine.connect() as conn:
            rows = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.source == source,
                RECEIPTS.c.request_key.like("legacy-send:%"),
                RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]),
            )).mappings().all()
        return _public(rows[0]) if rows else None

    def pending_send(self, owner, source):
        if not source:
            return None
        with self.engine.connect() as conn:
            rows = conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == owner, RECEIPTS.c.source == source,
                RECEIPTS.c.kind.in_(["send", "send_message"]),
                RECEIPTS.c.stage.in_(["reserved", "dispatch_possible", "unconfirmed"]),
            )).mappings().all()
        return _public(rows[0]) if rows else None


def confirmed_message_ids(owner, ids, *, session=None) -> set[str]:
    def read(conn):
        present = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (RECEIPTS.name,),
        ).first()
        if present is None:
            return set()
        return set(conn.execute(select(RECEIPTS.c.message_id).where(
            RECEIPTS.c.owner == owner, RECEIPTS.c.message_id.in_(list(ids)),
            RECEIPTS.c.kind.in_(["send", "send_message"]),
            RECEIPTS.c.stage == "completed",
        )).scalars())
    if session is not None:
        return read(session.connection())
    from .database import get_engine
    with get_engine().connect() as conn:
        return read(conn)
