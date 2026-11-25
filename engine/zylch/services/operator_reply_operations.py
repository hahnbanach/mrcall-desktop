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


_PRE_DISPATCH_REFUSALS = {
    "structured_draft_required", "structured_reply_decision_required",
    "incomplete_or_tool_generation_refused", "generation_response_too_large",
    "bounded_plain_draft_body_required", "bounded_internal_review_required",
    "reply_generation_provider_error", "reply_generation_budget_or_provider_refusal",
    "authorized_context_changed", "current_instruction_versions_required", "exact_source_required",
    "scheduled_answered", "scheduled_draft_exists", "profile_binding_changed",
    "current_profile_mismatch", "published_identity_and_procedures_required",
    "instructions_changed_before_private_commit", "correspondence_changed_before_private_commit",
    "native_review_profile_mismatch", "native_review_source_scope_held",
    "exact_authorized_mailbox_required", "exact_source_headers_required", "one_external_source_sender_required",
    "exact_authorized_context_required", "generation_context_too_large", "bounded_thread_correspondence_required",
    "exact_ordinary_thread_correspondence_required", "bounded_published_instruction_bundle_required",
    "instruction_content_integrity", "instruction_revision_identity_required", "duplicate_instruction_path",
    "locked_company_instruction_accessor_required", "locked_instruction_company_mismatch",
    "operation_not_claimed_or_already_completed",
}

_PRE_DISPATCH_STAGES = {
    "context": "reply_context_check_failed",
    "generation": "reply_generation_failed",
    "review": "reply_review_recording_failed",
    "addressing": "reply_addressing_failed",
}


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


def _published_locked(session, actor):
    conn = session.get_bind()
    if not conn.exec_driver_sql("PRAGMA main.table_info(project_space)").fetchall():
        raise ReplyRefusal("locked_company_instruction_accessor_required")
    space = conn.exec_driver_sql("SELECT space_id FROM main.project_space WHERE id=1").scalar_one()
    if space != actor.company_space_id:
        raise ReplyRefusal("locked_instruction_company_mismatch")
    paths = ("procedures.md", "mail/" + actor.mailbox_address.lower() + ".md")
    rows = conn.exec_driver_sql(
        "SELECT d.path,d.revision,r.sha256 FROM main.project_documents d "
        "JOIN main.project_revisions r ON r.project=d.project AND r.path=d.path AND r.revision=d.revision "
        "WHERE d.project=? AND d.path IN (?,?)", ("operator-instructions", *paths)).mappings()
    return [dict(row) for row in rows]



def check_mailbox_write(owner, conn):
    """Recheck frozen source/instructions under the company writer, without profile writes."""
    active = _active.get()
    if active is None:
        return
    from types import SimpleNamespace
    from zylch.storage.storage import Storage
    from .operator_reply_context import snapshot
    service, actor = active[:2]
    if actor.mailbox_address != owner:
        raise ReplyRefusal("mailbox_reply_owner_changed")
    service._check(actor)
    current_instructions = service.locked_instruction_reader(SimpleNamespace(get_bind=lambda: conn), actor)
    if _instruction_identity(current_instructions) != _instruction_identity(active[5]):
        raise ReplyRefusal("instructions_changed_before_mailbox_effect")
    source = Storage.get_instance().get_email_by_supabase_id(owner, active[4]["id"])
    keys = ("id", "mailbox_id", "thread_id", "message_id_header", "from_email", "subject", "body_plain", "body_html")
    if source is None or any(source.get(key) != active[4].get(key) for key in keys):
        raise ReplyRefusal("source_changed_before_mailbox_effect")
    if active[6] is not None:
        rows = Storage.get_instance().get_thread_emails(owner, active[4]["thread_id"])
        rows = [row for row in rows if row.get("mailbox_id") == actor.mailbox_id]
        if snapshot(rows, actor, active[4]["thread_id"]) != active[6]:
            raise ReplyRefusal("correspondence_changed_before_mailbox_effect")


def finish_draft_write(session, draft):
    active = _active.get()
    if active is None:
        return
    from zylch.services.exact_draft_delivery import snapshot
    service, actor, operation, used = active[:4]
    before_draft_write(draft["owner_id"])
    if len(active) < 6:
        raise ReplyRefusal("frozen_instruction_bundle_required")
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
    def __init__(self, *, revalidate, context_reader, generator=None, locked_instruction_reader=None, conflicts=None, mode="draft"):
        if not callable(revalidate) or not callable(context_reader):
            raise TypeError("trusted revalidation and context reader required")
        if conflicts is not None and not callable(conflicts):
            raise TypeError("conflicts must be callable")
        if mode not in {"draft", "send"}:
            raise ValueError("Reply mode must be draft or send")
        self.mode = mode
        self.revalidate, self.context_reader = revalidate, context_reader
        self.generator = generator
        self.locked_instruction_reader = locked_instruction_reader or _published_locked
        # Handles of review copies already on the thread root; a new request
        # refuses before it spends when one exists.
        self.conflicts = conflicts

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

    def admitted_request(self, actor, request_key):
        """Read immutable request input before consulting mutable mailbox/context state."""
        self._check(actor)
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", request_key):
            raise ReplyRefusal("stable_request_key_required")
        self._ensure()
        with _transaction() as conn:
            row = conn.execute(select(_operations.c.id, _operations.c.payload).where(
                *_where(actor), _operations.c.request_key == request_key)).mappings().one_or_none()
        return {"id": row["id"], "payload": json.loads(row["payload"])} if row else None

    async def prepare(self, request_key, exact_source, instruction_versions, request_text, actor_binding):
        actor = actor_binding
        await self._acheck(actor)
        if not capability()["available"]:
            raise ReplyRefusal("native_causal_draft_unsupported")
        if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", request_key):
            raise ReplyRefusal("stable_request_key_required")
        if not isinstance(request_text, str) or not request_text.strip() or len(request_text.encode()) > 16384:
            raise ReplyRefusal("bounded_request_required")
        self._ensure()
        with _transaction() as conn:
            known = conn.execute(select(_operations).where(*_where(actor), _operations.c.request_key == request_key)).mappings().one_or_none()
        if known is not None:
            admitted = json.loads(known["payload"])
            if (admitted["source"] != exact_source or admitted["instructions"] != instruction_versions
                    or admitted["request"] != request_text or admitted.get("mode", "draft") != self.mode):
                raise ReplyRefusal("request_key_payload_conflict")
            return await self.recover(operation_id=known["id"], actor_binding=actor)
        context = await self._context(exact_source, instruction_versions, actor)
        payload = {"source": exact_source, "instructions": instruction_versions, "request": request_text,
                   "profile": actor.profile_uid, "company": actor.company_space_id, "mailbox": actor.mailbox_id,
                   "mailbox_address": actor.mailbox_address, "context": context, "mode": self.mode}
        payload_hash = _hash(payload)
        self._ensure()
        if self.conflicts is not None:
            with _transaction() as conn:
                known = conn.execute(select(_operations.c.id).where(*_where(actor), _operations.c.request_key == request_key)).first()
            if known is None:
                copies = self.conflicts(context["source"]["thread_id"])
                if inspect.isawaitable(copies):
                    copies = await copies
                if copies:
                    named = ",".join(f"{copy['folder']}/{copy['uidvalidity']}/{copy['uid']}" for copy in copies)
                    raise ReplyRefusal("review_copy_exists_on_thread:" + named)
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
        stage = "context"
        try:
            await self._acheck(actor)
            if await self._context(exact_source, instruction_versions, actor) != context:
                raise ReplyRefusal("authorized_context_changed")
            stage = "generation"
            if self.generator is None:
                from .operator_reply_generation import generate
                body = await generate(context, request_text)
            else:
                body = await self.generator(context, request_text)
            if not isinstance(body, ReviewRequired) and (not isinstance(body, str) or not body.strip() or len(body.encode()) > 65536):
                raise ReplyRefusal("bounded_plain_draft_body_required")
            stage = "context"
            await self._acheck(actor)
            if await self._context(exact_source, instruction_versions, actor) != context:
                raise ReplyRefusal("authorized_context_changed")
            if isinstance(body, ReviewRequired):
                stage = "review"
                await asyncio.to_thread(self._finish_review, actor, operation, context, body)
            else:
                from .operator_reply_generation import persist, reply_fields
                stage = "addressing"
                fields = reply_fields(context["source"], actor)
                stage = "mailbox"
                outcome = await asyncio.to_thread(persist, fields, body, actor,
                                                  request_key="prepare:" + operation, mode=self.mode)
                await asyncio.to_thread(self._finish_mailbox, actor, operation, outcome, body)
            if not _active.get()[3][0]:
                raise ReplyRefusal("native_draft_receipt_missing")
        except BaseException as error:
            state, result = "uncertain", None
            if stage in _PRE_DISPATCH_STAGES:
                state = "failed_before_dispatch"
                cause = _PRE_DISPATCH_STAGES[stage]
                if isinstance(error, ReplyRefusal) and str(error) in _PRE_DISPATCH_REFUSALS:
                    cause = str(error)
                elif isinstance(error, asyncio.CancelledError):
                    cause = "reply_operation_cancelled"
                if stage == "context" and cause in {"scheduled_answered", "scheduled_draft_exists"}:
                    state = cause.removeprefix("scheduled_")
                result = _json({"cause": cause, "stage": stage, "effect_certainty": "not-dispatched"})
            with _transaction() as conn:
                conn.execute(update(_operations).where(
                    _operations.c.id == operation, *_where(actor), _operations.c.state.in_(("running", "uncertain")),
                    _operations.c.executor == _process(), _operations.c.result.is_(None),
                ).values(state=state, result=result, updated_at=time.time()))
            if state == "uncertain" or not isinstance(error, Exception):
                raise
        finally:
            _active.reset(token)
        return await self.recover(operation_id=operation, actor_binding=actor)

    def _finish_mailbox(self, actor, operation, outcome, body=None):
        """Record only immutable mailbox identity and hashes, never another draft body."""
        self._check(actor)
        if not isinstance(outcome, dict):
            raise ReplyRefusal("mailbox_operation_receipt_required")
        if self.mode == "draft":
            draft_id = outcome.get("id") or outcome.get("draft_id")
            if not draft_id:
                raise ReplyRefusal("mailbox_draft_receipt_required")
            result = {"draft_id": draft_id, "created": outcome.get("created", True),
                      "mailbox_operation": "prepare:" + operation}
        else:
            result = {key: outcome.get(key) for key in ("ok", "state", "message_id", "operation_id", "effect_certainty", "cause")}
            result["mailbox_operation"] = "prepare:" + operation
        if body is not None:
            result["body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
        with _transaction() as conn:
            changed = conn.execute(update(_operations).where(
                _operations.c.id == operation, *_where(actor),
                _operations.c.state.in_(("running", "uncertain")), _operations.c.result.is_(None),
            ).values(state="completed", result=_json(result), updated_at=time.time())).rowcount
            if changed != 1:
                completed = conn.execute(select(_operations.c.result).where(
                    _operations.c.id == operation, *_where(actor), _operations.c.state == "completed",
                )).scalar_one_or_none()
                if not completed or json.loads(completed).get("mailbox_operation") != result["mailbox_operation"]:
                    raise ReplyRefusal("operation_not_claimed_or_already_completed")
        active = _active.get()
        if active is not None:
            active[3][0] = True

    def _finish_review(self, actor, operation, context, review):
        from .operator_reply_context import check_locked
        from . import project_store, task_assignment_evidence, task_assignment_store
        native_actor, space, _ = task_assignment_evidence.admission()
        if native_actor.uid != actor.profile_uid or native_actor.mailbox != actor.mailbox_address or space != actor.company_space_id:
            raise ReplyRefusal("native_review_profile_mismatch")
        from . import person_request
        with project_store.connection(actor.company_space_id, write=True) as (conn, _):
            task_assignment_store._admit(native_actor, space, conn)
            request = person_request.active()
            if request is None:
                task, _, keys = task_assignment_store.authority(native_actor, space, context["source"]["thread_id"], conn, locked=True)
                if context["source"].get("message_id_header") not in keys or (task or {}).get("state") == "assigned":
                    raise ReplyRefusal("native_review_source_scope_held")
            else:
                # A person's request: the review records on the exact message
                # they named, whatever the thread's assignment state.
                if (context["source"].get("id") != request.source_id
                        or context["source"].get("thread_id") != request.root
                        or context["source"].get("message_id_header") != request.target):
                    raise ReplyRefusal("native_review_source_scope_held")
                task_assignment_store.attach_profile(native_actor, conn)
            with Session(bind=conn.execution_options(schema_translate_map={None: "assignment_profile"}), expire_on_commit=False) as session:
                self._check(actor)
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
        from zylch.services.mailbox_drafts import MailboxDrafts
        mailbox = MailboxDrafts(actor.mailbox_address)
        current = None
        if result is None and row["state"] == "running":
            result = {"cause": "reply_operation_in_progress", "effect_certainty": "unknown"}
        if result is None and row["state"] == "uncertain":
            mailbox_key = "prepare:" + row["id"]
            receipt = await asyncio.to_thread(mailbox.operation, mailbox_key)
            if receipt is None:
                result = {"cause": "reply_operation_without_mailbox_receipt", "effect_certainty": "unknown"}
            elif receipt["stage"] == "reserved":
                result = {"cause": "mailbox_operation_reserved", "effect_certainty": "unknown",
                          "message_id": receipt["message_id"], "mailbox_operation_id": receipt["id"]}
            else:
                recovered = await asyncio.to_thread(mailbox.recover, mailbox_key)
                if recovered.get("ok"):
                    self.mode = payload.get("mode", "draft")
                    outcome = recovered.get("draft") or recovered.get("result") or recovered
                    await asyncio.to_thread(self._finish_mailbox, actor, row["id"], outcome)
                    return await self.recover(actor_binding=actor, operation_id=row["id"])
                result = {key: recovered[key] for key in ("cause", "effect_certainty", "message_id") if key in recovered}
                result["mailbox_operation_id"] = receipt["id"]
        if result is not None and result.get("draft_id"):
            current_row = await asyncio.to_thread(mailbox.get, result["draft_id"])
            current = {"exists": current_row is not None}
        elif result is not None and result.get("mailbox_operation"):
            recovered = await asyncio.to_thread(mailbox.recover, result["mailbox_operation"])
            if isinstance(recovered, dict):
                result = {**result, **{key: recovered[key] for key in
                    ("ok", "state", "message_id", "effect_certainty", "cause") if key in recovered}}
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
