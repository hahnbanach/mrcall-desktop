"""One authoritative source-bound guard for private writes and provider handoff."""

import contextlib
import contextvars
import functools
import inspect
import os
from sqlalchemy import select
from .task_assignment_types import AssignmentError, thread

_active = contextvars.ContextVar("assignment_email_effect", default=None)


def resolve(owner, values):
    """Resolve from exact owner-scoped original source; never from prose/recipient."""
    # Decorators must load without initializing Storage: IMAP and sync import
    # this module before the storage package has initialized its own guards.
    from zylch.storage import database as db
    from zylch.storage.models import Email
    from . import task_assignment_mail as mail
    from .task_assignment_draft_policy import current

    target, refs, root = values.get("in_reply_to"), values.get("references"), values.get("thread_id")
    bound = current()
    from .contextual_email_policy import validate

    if not any((target, refs, root, bound)):
        validate(owner, None)
        return None
    if not target:
        raise AssignmentError("Contextual email requires its exact original reply source")
    target = thread(target)
    refs = mail.references(refs if isinstance(refs, str) else " ".join(refs or []))
    requested = thread(root) if root else (refs[0] if refs else None)
    with db.get_engine().connect() as conn:
        rows = list(conn.execute(select(Email.__table__).where(
            Email.owner_id == owner, Email.message_id_header == target,
        ).limit(2)).mappings())
    if len(rows) != 1:
        raise AssignmentError("Exact owner-scoped reply source unavailable")
    source = dict(rows[0])
    original_refs = mail.references(source.get("references") or "")
    actual = original_refs[0] if original_refs else thread(source["message_id_header"])
    if source.get("thread_id") and thread(source["thread_id"]) != actual:
        raise AssignmentError("Original reply source has conflicting thread identity")
    if requested and requested != actual or bound and bound != actual:
        raise AssignmentError("Contextual reply identifiers disagree")
    if refs and refs[0] != actual:
        raise AssignmentError("Contextual reply References disagree")
    if refs:
        from types import SimpleNamespace

        known = {actual, target, *original_refs}
        known.update(row["message_id_header"] for row in mail.rows(SimpleNamespace(mailbox=owner), actual))
        if not set(refs) <= known:
            raise AssignmentError("Contextual reply References contain a foreign source")
    binding = {"root": actual, "target": target, "source": mail.row_identity(source)}
    if values.get("reply_binding") is not None and values["reply_binding"] != binding:
        raise AssignmentError("Persisted original reply source changed")
    validate(owner, binding)
    return binding


def _identity(owner):
    from . import task_assignment_identity as identity

    actor = identity.actor()
    if actor.mailbox != owner:
        raise AssignmentError("Contextual email owner mismatch")
    return actor


def _local_recheck(actor):
    from zylch.auth import get_session
    from . import task_assignment_identity as identity
    import time

    session = get_session()
    if (session is None or session.uid != actor.uid or session.id_token != actor.token
        or session.is_expired() or actor.expires_at <= time.time()
        or os.environ.get("OWNER_ID") != actor.uid
        or os.environ.get("EMAIL_ADDRESS", "").strip().lower() != actor.mailbox
        or identity.binding() != actor.binding):
        raise AssignmentError("Contextual email profile changed")


@contextlib.contextmanager
def effect(owner, values):
    from zylch.services import project_store
    from zylch.storage.assigned_task_models import AssignedTask
    from . import task_assignment_enrollment as enrollment
    from . import task_assignment_projection as projection

    source = resolve(owner, values)
    if source is None:
        if _active.get() is not None:
            raise AssignmentError("Bound contextual email cannot become standalone")
        yield
        return
    existing = _active.get()
    if existing is not None:
        if existing != (owner, source):
            raise AssignmentError("Nested email handoff changed exact reply binding")
        yield
        return
    actor = _identity(owner)
    with project_store.connection() as (conn, space):
        state = enrollment.read(conn, space)["state"]
    projected = projection.project(source["root"]) if state == "managed" else None
    if projected is not None and (not projected["complete"] or projected["hold_auto_reply"]
                                 or source["target"] not in projected["current_message_ids"]
                                 or (projected["state"] == "later-inbound"
                                     and source["target"] in projected["covered_message_ids"])):
        raise AssignmentError("Assignment authority holds this contextual email")
    with project_store.connection(space, write=True) as (conn, _):
        row = enrollment.check_locked(conn, space)
        _local_recheck(actor)
        from zylch.storage.join_fence_model import MemoryJoinFence

        if conn.execute(select(MemoryJoinFence.id).where(
            MemoryJoinFence.phase.in_(("fenced", "accepted")),
        ).limit(1)).first():
            raise AssignmentError("Company join in progress")
        if resolve(owner, values) != source:
            raise AssignmentError("Reply source changed before effect")
        if row["state"] == "managed":
            if projected is None:
                raise AssignmentError("Assignment enrollment changed before effect")
            from .task_assignment_store import _admit

            _admit(actor, space, conn)
            latest = conn.execute(select(AssignedTask.__table__).where(
                AssignedTask.space_id == space, AssignedTask.thread_key == source["root"],
            )).mappings().one_or_none()
            if (dict(latest) if latest else None) != projected["task"]:
                raise AssignmentError("Assignment changed before email effect", -32061)
        token = _active.set((owner, source))
        try:
            yield
        finally:
            _active.reset(token)


def create_guard(method):
    signature = inspect.signature(method)

    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        values = signature.bind(*args, **kwargs)
        values.apply_defaults()
        owner = values.arguments["owner_id"]
        from .request_policy import assert_tool_allowed

        assert_tool_allowed("create_draft")
        from .task_assignment_draft_transaction import create_transaction

        with effect(owner, values.arguments):
            with create_transaction():
                return method(*args, **kwargs)
    return wrapped


def update_guard(method):
    @functools.wraps(method)
    def wrapped(self, owner_id, draft_id, updates):
        from .task_assignment_draft_transaction import locked_row, may_edit_claim, CONTENT

        old = self.get_draft(owner_id, draft_id)
        if not old:
            return None
        if "reply_binding" in updates and updates["reply_binding"] != old.get("reply_binding"):
            raise AssignmentError("Persisted reply binding is immutable")
        if any(key in updates and updates[key] != old.get(key) for key in ("owner_id", "id")):
            raise AssignmentError("Draft owner and identity are immutable")
        binding = ("thread_id", "in_reply_to", "references")
        if any(old.get(key) for key in binding):
            if any(key in updates and updates[key] != old.get(key) for key in binding):
                raise AssignmentError("Existing reply binding is immutable")
        content = bool(set(updates) & CONTENT)
        if content and old.get("status") in {"sending", "sent"}:
            if old["status"] == "sent" or not may_edit_claim(owner_id, draft_id):
                raise AssignmentError("Claimed or delivered draft content cannot change")
        authority = effect(owner_id, {**old, **updates}) if content else contextlib.nullcontext()
        with authority:
            with locked_row(owner_id, draft_id, old):
                if content and old.get("reply_binding") is None and current_binding() is not None:
                    updates = {**updates, "reply_binding": current_binding()}
                return method(self, owner_id, draft_id, updates)
    return wrapped


def transport_guard(method):
    signature = inspect.signature(method)

    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        from .request_policy import assert_tool_allowed

        assert_tool_allowed("send_email")
        values = signature.bind(self, *args, **kwargs)
        values.apply_defaults()
        with effect(self.email_addr, values.arguments):
            return method(self, *args, **kwargs)
    return wrapped


def send(method, *, owner_id, draft=None, **kwargs):
    """Use persisted binding even for a transport which lacks reply parameters."""
    from .request_policy import assert_tool_allowed

    assert_tool_allowed("send_email")
    with effect(owner_id, draft if draft is not None else kwargs):
        if draft is not None:
            from .task_assignment_draft_transaction import locked_row

            with locked_row(owner_id, draft["id"], draft, sending=True):
                return method(**kwargs)
        return method(**kwargs)


def current_binding():
    value = _active.get()
    return value[1] if value is not None else None
