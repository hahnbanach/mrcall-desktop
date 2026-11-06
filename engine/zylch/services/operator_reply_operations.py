from __future__ import annotations

import asyncio
import inspect
import contextvars
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from uuid import uuid4

from sqlalchemy.orm import Session

from sqlalchemy import Column, Float, MetaData, String, Table, Text, UniqueConstraint, select, update


class ReplyRefusal(ValueError):
    pass


@dataclass(frozen=True)
class ReviewRequired:
    reason: str
    missing_facts: list[str]

    def __post_init__(self):
        if (not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason.encode()) > 4096
                or not isinstance(self.missing_facts, list) or not 1 <= len(self.missing_facts) <= 20
                or any(not isinstance(item, str) or not item.strip() or len(item.encode()) > 1024 for item in self.missing_facts)):
            raise ReplyRefusal("bounded_internal_review_required")


@dataclass(frozen=True)
class ActorBinding:
    actor_uid: str
    profile_uid: str
    company_space_id: str
    mailbox_id: str
    mailbox_address: str
    client_id: str
    grant_id: str


_metadata = MetaData()
_operations = Table(
    "operator_reply_operations", _metadata,
    Column("id", String, primary_key=True), Column("owner", String, nullable=False),
    Column("company", String, nullable=False), Column("mailbox", String, nullable=False),
    Column("request_key", String, nullable=False), Column("payload_hash", String, nullable=False),
    Column("payload", Text, nullable=False), Column("attribution", Text, nullable=False),
    Column("state", String, nullable=False), Column("executor", String),
    Column("result", Text), Column("reservation_ids", Text, nullable=False),
    Column("created_at", Float, nullable=False), Column("updated_at", Float, nullable=False),
    UniqueConstraint("owner", "company", "mailbox", "request_key"),
)
_START = str(uuid4())


def _process():
    return f"{os.getpid()}:{_START}"
_active = contextvars.ContextVar("operator_reply_operation", default=None)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def capability():
    try:
        from zylch.services.exact_draft_delivery import snapshot
        from zylch.services import task_assignment_draft_policy
        from zylch.storage.storage import Storage
        if not callable(snapshot) or not callable(task_assignment_draft_policy.scope) or not getattr(Storage.create_draft, "operator_reply_receipts", False):
            raise ImportError
    except ImportError:
        return {"available": False, "version": 1, "reason": "native_causal_draft_unsupported"}
    return {"available": True, "version": 1, "sends": False}


@contextmanager
def _transaction():
    from zylch.storage.database import get_engine
    with get_engine().connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def _owned(actor):
    if not isinstance(actor, ActorBinding) or any(not isinstance(value, str) or not value.strip() for value in asdict(actor).values()):
        raise ReplyRefusal("trusted_actor_binding_required")
    if os.environ.get("OWNER_ID") != actor.profile_uid or os.environ.get("EMAIL_ADDRESS", "").lower() != actor.mailbox_address.lower():
        raise ReplyRefusal("current_profile_mismatch")


def _where(actor):
    return (_operations.c.owner == actor.profile_uid, _operations.c.company == actor.company_space_id,
            _operations.c.mailbox == actor.mailbox_id)


def before_draft_write(owner):
    active = _active.get()
    if active is None:
        return
    service, actor, operation, used = active[:4]
    if used[0] or owner != actor.mailbox_address:
        raise ReplyRefusal("one_exact_draft_effect_required")
    service._check(actor)
    if len(active) > 4:
        from zylch.storage.storage import Storage
        expected = active[4]
        current = Storage.get_instance().get_email_by_supabase_id(owner, expected["id"])
        fields = ("id", "mailbox_id", "message_id_header", "thread_id", "from_email", "subject", "body_plain", "body_html")
        if current is None or any(current.get(key) != expected.get(key) for key in fields):
            raise ReplyRefusal("exact_source_changed_before_private_write")



def _instruction_identity(bundle):
    docs = bundle.get("documents") if isinstance(bundle, dict) else bundle
    if not isinstance(docs, list) or len(docs) > 2:
        raise ReplyRefusal("bounded_published_instruction_bundle_required")
    out = {}
    for doc in docs:
        text = doc.get("text", doc.get("content"))
        digest = doc.get("sha256")
        if isinstance(text, str):
            computed = hashlib.sha256(text.encode()).hexdigest()
            if digest is not None and digest != computed:
                raise ReplyRefusal("instruction_content_integrity")
            digest = computed
        if not isinstance(doc.get("path"), str) or type(doc.get("revision")) is not int or not isinstance(digest, str):
            raise ReplyRefusal("instruction_revision_identity_required")
        if doc["path"] in out:
            raise ReplyRefusal("duplicate_instruction_path")
        out[doc["path"]] = (doc["revision"], digest)
    return out


def reply_headers(source):
    from .task_assignment_mail import references
    target = source.get("message_id_header")
    refs = list(dict.fromkeys([*references(source.get("references") or ""), target]))
    return {"thread_id": source.get("thread_id"), "in_reply_to": target, "references": refs}


def _native_effect_source(session, actor, expected):
    from zylch.storage.models import Email
    from .task_assignment_email_effect import current_binding
    from .task_assignment_mail import row_identity
    binding = current_binding()
    if (not isinstance(binding, dict) or binding.get("root") != expected.get("thread_id")
            or binding.get("target") != expected.get("message_id_header")):
        raise ReplyRefusal("matching_native_email_effect_required")
    fresh = session.execute(select(Email.__table__).where(
        Email.owner_id == actor.mailbox_address, Email.mailbox_id == actor.mailbox_id,
        Email.id == expected.get("id"))).mappings().one_or_none()
    if (fresh is None or row_identity(dict(fresh)) != binding.get("source")
            or row_identity(dict(fresh)) != row_identity(expected)):
        raise ReplyRefusal("native_effect_source_changed")
    fields = ("id", "mailbox_id", "message_id_header", "thread_id", "from_email", "to_email", "cc_email", "references", "subject", "body_plain", "body_html")
    if any(fresh.get(key) != expected.get(key) for key in fields):
        raise ReplyRefusal("exact_source_changed_before_private_commit")
    return dict(fresh)


def _published_locked(session, actor):
    import sqlite3
    from contextlib import closing
    from urllib.parse import quote
    from zylch.storage.database import current_memory_engine
    active = _active.get()
    if active is None or len(active) < 6 or active[1] != actor:
        raise ReplyRefusal("matching_native_email_effect_required")
    _native_effect_source(session, actor, active[4])
    engine = current_memory_engine()
    if engine is None or not engine.url.database:
        raise ReplyRefusal("locked_company_instruction_accessor_required")
    paths = ("procedures.md", "mail/" + actor.mailbox_address.lower() + ".md")
    with closing(sqlite3.connect("file:" + quote(engine.url.database, safe="/") + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        space = conn.execute("SELECT space_id FROM project_space WHERE id=1").fetchone()
        if space is None or space[0] != actor.company_space_id:
            raise ReplyRefusal("locked_instruction_company_mismatch")
        rows = conn.execute(
            "SELECT d.path,d.revision,r.sha256 FROM project_documents d "
            "JOIN project_revisions r ON r.project=d.project AND r.path=d.path AND r.revision=d.revision "
            "WHERE d.project=? AND d.path IN (?,?)", ("operator-instructions", *paths))
        return [dict(row) for row in rows]


def finish_draft_write(session, draft):
    active = _active.get()
    if active is None:
        return
    from zylch.services.exact_draft_delivery import snapshot
    service, actor, operation, used = active[:4]
    before_draft_write(draft["owner_id"])
    if len(active) < 6:
        raise ReplyRefusal("frozen_instruction_bundle_required")
    source = _native_effect_source(session, actor, active[4])
    from email.utils import getaddresses
    recipients = getaddresses([source.get("from_email") or ""])
    if (len(recipients) != 1 or [value.lower() for value in draft.get("to_addresses", [])] != [recipients[0][1].lower()]
            or draft.get("cc_addresses") or draft.get("bcc_addresses")):
        raise ReplyRefusal("exact_source_recipient_required")
    current_instructions = service.locked_instruction_reader(session, actor)
    if _instruction_identity(current_instructions) != _instruction_identity(active[5]):
        raise ReplyRefusal("instructions_changed_before_private_commit")
    from .operator_reply_context import check_locked
    check_locked(session, actor, active[4], active[6] if len(active) > 6 else None)
    persisted = {key: value for key, value in draft.items() if key != "created"}
    result = {"draft_id": persisted["id"], "snapshot": persisted, "snapshot_hash": snapshot(persisted),
              "body_sha256": hashlib.sha256((persisted.get("body") or "").encode()).hexdigest(),
              "created": bool(draft.get("created"))}
    changed = session.execute(update(_operations).where(
        _operations.c.id == operation, *_where(actor), _operations.c.state == "running",
        _operations.c.executor == _process(), _operations.c.result.is_(None),
    ).values(state="completed", result=_json(result), updated_at=time.time())).rowcount
    if changed != 1:
        raise ReplyRefusal("operation_not_claimed_or_already_completed")
    used[0] = True


def link_reservation(conn, reservation, request_kwargs):
    active = _active.get()
    if active is None:
        return
    service, actor, operation, used = active[:4]
    service._check(actor)
    if used[0] or request_kwargs.get("tools") or request_kwargs.get("tool_choice"):
        raise ReplyRefusal("reply_generation_has_no_external_tools")
    row = conn.execute(select(_operations).where(_operations.c.id == operation, *_where(actor))).mappings().one()
    if row["state"] != "running" or row["executor"] != _process() or reservation.owner_id != actor.profile_uid:
        raise ReplyRefusal("reservation_operation_mismatch")
    reservations = json.loads(row["reservation_ids"])
    if reservations:
        raise ReplyRefusal("one_paid_dispatch_per_operation")
    conn.execute(update(_operations).where(_operations.c.id == operation).values(
        reservation_ids=_json([reservation.id]), updated_at=time.time()))


class ReplyOperations:
    def __init__(self, *, revalidate, context_reader, generator=None, locked_instruction_reader=None):
        if not callable(revalidate) or not callable(context_reader):
            raise TypeError("trusted revalidation and context reader required")
        self.revalidate, self.context_reader = revalidate, context_reader
        self.generator = generator
        self.locked_instruction_reader = locked_instruction_reader or _published_locked

    capability = staticmethod(capability)

    def _check(self, actor):
        _owned(actor)
        result = self.revalidate(actor)
        if inspect.isawaitable(result):
            asyncio.run(result)

    async def _acheck(self, actor):
        _owned(actor)
        result = self.revalidate(actor)
        if inspect.isawaitable(result):
            await result

    def _ensure(self):
        from zylch.storage.database import get_engine
        _metadata.create_all(get_engine())

    async def _context(self, source, versions, actor):
        value = self.context_reader(source, versions, actor)
        if inspect.isawaitable(value):
            value = await value
        if not isinstance(value, dict) or set(value) not in ({"source", "instructions"}, {"source", "instructions", "correspondence"}):
            raise ReplyRefusal("exact_authorized_context_required")
        if len(_json(value).encode()) > 196608:
            raise ReplyRefusal("generation_context_too_large")
        return json.loads(_json(value))

    async def prepare(self, request_key, exact_source, instruction_versions, request_text, actor_binding):
        actor = actor_binding
        await self._acheck(actor)
        if not capability()["available"]:
            raise ReplyRefusal("native_causal_draft_unsupported")
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", request_key):
            raise ReplyRefusal("stable_request_key_required")
        if not isinstance(request_text, str) or not request_text.strip() or len(request_text.encode()) > 16384:
            raise ReplyRefusal("bounded_request_required")
        context = await self._context(exact_source, instruction_versions, actor)
        payload = {"source": exact_source, "instructions": instruction_versions, "request": request_text,
                   "profile": actor.profile_uid, "company": actor.company_space_id, "mailbox": actor.mailbox_id,
                   "mailbox_address": actor.mailbox_address, "context": context}
        payload_hash = _hash(payload)
        self._ensure()
        with _transaction() as conn:
            existing = conn.execute(select(_operations).where(*_where(actor), _operations.c.request_key == request_key)).mappings().one_or_none()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise ReplyRefusal("request_key_payload_conflict")
                operation = existing["id"]
            else:
                operation, now = str(uuid4()), time.time()
                conn.execute(_operations.insert().values(
                    id=operation, owner=actor.profile_uid, company=actor.company_space_id, mailbox=actor.mailbox_id,
                    request_key=request_key, payload_hash=payload_hash, payload=_json(payload), attribution=_json(asdict(actor)),
                    state="admitted", executor=None, result=None, reservation_ids="[]", created_at=now, updated_at=now))
            claimed = conn.execute(update(_operations).where(_operations.c.id == operation,
                _operations.c.state == "admitted").values(state="running", executor=_process(), updated_at=time.time())).rowcount
        if not claimed:
            return await self.recover(operation_id=operation, actor_binding=actor)
        token = _active.set((self, actor, operation, [False], context["source"], context["instructions"], context.get("correspondence")))
        try:
            await self._acheck(actor)
            if await self._context(exact_source, instruction_versions, actor) != context:
                raise ReplyRefusal("authorized_context_changed")
            if self.generator is None:
                from .operator_reply_generation import generate
                body = await generate(context, request_text)
            else:
                body = await self.generator(context, request_text)
            if not isinstance(body, ReviewRequired) and (not isinstance(body, str) or not body.strip() or len(body.encode()) > 65536):
                raise ReplyRefusal("bounded_plain_draft_body_required")
            await self._acheck(actor)
            if await self._context(exact_source, instruction_versions, actor) != context:
                raise ReplyRefusal("authorized_context_changed")
            if isinstance(body, ReviewRequired):
                await asyncio.to_thread(self._finish_review, actor, operation, context, body)
            else:
                from .operator_reply_generation import persist
                await asyncio.to_thread(persist, context["source"], body, actor)
            if not _active.get()[3][0]:
                raise ReplyRefusal("native_draft_receipt_missing")
        except BaseException:
            with _transaction() as conn:
                row = conn.execute(select(_operations).where(_operations.c.id == operation)).mappings().one()
                if row["state"] == "running":
                    conn.execute(update(_operations).where(_operations.c.id == operation).values(
                        state="uncertain" if json.loads(row["reservation_ids"]) else "failed_before_dispatch", updated_at=time.time()))
            raise
        finally:
            _active.reset(token)
        return await self.recover(operation_id=operation, actor_binding=actor)

    def _finish_review(self, actor, operation, context, review):
        from .operator_reply_context import check_locked
        from .task_assignment_email_effect import effect
        from .task_assignment_draft_transaction import create_transaction, session as draft_session
        with effect(actor.mailbox_address, reply_headers(context["source"])):
            with create_transaction():
                with draft_session() as session:
                    self._check(actor)
                    _native_effect_source(session, actor, context["source"])
                    if _instruction_identity(self.locked_instruction_reader(session, actor)) != _instruction_identity(context["instructions"]):
                        raise ReplyRefusal("instructions_changed_before_private_commit")
                    check_locked(session, actor, context["source"], context.get("correspondence"))
                    changed = session.execute(update(_operations).where(
                        _operations.c.id == operation, *_where(actor), _operations.c.state == "running",
                        _operations.c.executor == _process(), _operations.c.result.is_(None),
                    ).values(state="needs_review", result=_json(asdict(review)), updated_at=time.time())).rowcount
                    if changed != 1:
                        raise ReplyRefusal("operation_not_claimed_or_already_completed")
                    session.flush()
                    _active.get()[3][0] = True

    async def recover(self, *, actor_binding, operation_id=None, request_key=None):
        actor = actor_binding
        await self._acheck(actor)
        if bool(operation_id) == bool(request_key):
            raise ReplyRefusal("one_operation_lookup_key_required")
        self._ensure()
        with _transaction() as conn:
            selector = _operations.c.id == operation_id if operation_id else _operations.c.request_key == request_key
            row = conn.execute(select(_operations).where(*_where(actor), selector)).mappings().one_or_none()
            if row is None:
                raise ReplyRefusal("operation_not_found")
            row = dict(row)
            if row["state"] == "running" and row["executor"] != _process():
                conn.execute(update(_operations).where(_operations.c.id == row["id"]).values(state="uncertain", updated_at=time.time()))
                row["state"] = "uncertain"
        payload = json.loads(row["payload"])
        historical = payload["context"]
        from zylch.storage.storage import Storage
        selected = Storage.get_instance().get_email_by_supabase_id(actor.mailbox_address, historical["source"]["id"])
        if selected is not None and selected.get("mailbox_id") != actor.mailbox_id:
            raise ReplyRefusal("current_source_provenance_changed")
        source_fields = ("id", "mailbox_id", "message_id_header", "thread_id", "from_email", "subject", "body_plain", "body_html")
        source_changed = selected is None or any(selected.get(key) != historical["source"].get(key) for key in source_fields)
        from zylch.services.operator_instructions import documents
        published = await asyncio.to_thread(documents, actor.mailbox_address)
        if any(doc.get("space_id", actor.company_space_id) != actor.company_space_id for doc in published):
            raise ReplyRefusal("current_instruction_provenance_changed")
        instruction_changed = _instruction_identity(published) != _instruction_identity(historical["instructions"])
        result = json.loads(row["result"]) if row["result"] else None
        review = result if row["state"] == "needs_review" else None
        if review is not None:
            ReviewRequired(**review)
            result = None
        current = None
        if result is not None:
            from zylch.storage.storage import Storage
            from zylch.services.exact_draft_delivery import snapshot
            current_row = Storage.get_instance().get_draft(actor.mailbox_address, result["draft_id"])
            current = {"exists": current_row is not None, "snapshot_hash": snapshot(current_row) if current_row else None,
                       "matches_original": current_row is not None and snapshot(current_row) == result["snapshot_hash"]}
        await self._acheck(actor)
        return {"operation_id": row["id"], "request_key": row["request_key"], "state": row["state"],
                "source": {key: historical["source"].get(key) for key in
                           ("id", "thread_id", "from_email", "subject")},
                "result": result, "review": review, "current_draft": current,
                "correspondence": historical.get("correspondence"),
                "context_changed": source_changed or instruction_changed is not False,
                "context_status": {"source_changed": source_changed, "source_exists": selected is not None,
                                   "instructions_changed": instruction_changed},
                "reservation_ids": json.loads(row["reservation_ids"])}

    def list_recoverable(self, actor_binding):
        actor = actor_binding
        self._check(actor)
        self._ensure()
        from zylch.storage.database import get_engine
        with get_engine().connect() as conn:
            rows = conn.execute(select(_operations.c.id, _operations.c.request_key, _operations.c.state,
                _operations.c.created_at).where(*_where(actor)).order_by(_operations.c.created_at.desc()).limit(100)).mappings().all()
        self._check(actor)
        return [dict(row) for row in rows]
