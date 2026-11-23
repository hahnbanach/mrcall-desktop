"""Opt-in kernel draft scope enforced at the actual private draft write."""

import asyncio
import contextlib
import contextvars
import functools
import inspect
import logging

from sqlalchemy.orm import Session

from zylch.services import project_store
from . import person_request
from . import task_assignment_evidence as evidence
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_projection as projection
from .task_assignment_types import AssignmentError, thread

logger = logging.getLogger(__name__)
VERSION = 1
_scope = contextvars.ContextVar("assignment_draft_thread", default=None)
_write_session = contextvars.ContextVar("assignment_draft_session", default=None)


@contextlib.contextmanager
def mailbox_effect(owner, fields):
    """Keep source/company admission around a provider effect without a profile writer.

    The provider operation commits its dispatch receipt before entering here.
    No attached profile Session is held while the mailbox operation runs.
    """
    from .request_policy import assert_tool_allowed
    from .operator_reply_origin import is_scheduled
    from zylch.storage.storage import Storage

    assert_tool_allowed("create_draft")
    request = person_request.active()
    root = current() or fields.get("thread_id")
    if request is None and current() is None and not is_scheduled():
        yield
        return
    if not root:
        raise AssignmentError("Exact mailbox effect thread required")
    root = thread(root)
    target = thread(fields.get("in_reply_to"))
    refs = fields.get("references") or []
    refs = mail.references(" ".join(refs) if isinstance(refs, list) else refs)
    actor, space, _ = evidence.admission()
    if owner != actor.mailbox or fields.get("thread_id") != root:
        raise AssignmentError("Mailbox effect profile or thread mismatch")
    if request is not None:
        if (owner.strip().lower() != request.mailbox or root != request.root
                or target != request.target or any(ref not in request.known_identifiers() for ref in refs)):
            raise AssignmentError("Person request must retain the exact requested source")
        stored = Storage.get_instance().get_email_by_supabase_id(owner, request.source_id)
        if not person_request.matches_row(request, stored):
            raise AssignmentError("Person request source changed before mailbox effect")
        projected = None
    else:
        projected = projection.project(root)
        if (not projected.get("complete") or projected.get("hold_auto_reply")
                or target not in projected.get("current_message_ids", [])
                or target not in projected.get("component_thread_keys", [])
                or any(ref not in projected.get("component_thread_keys", []) for ref in refs)):
            raise AssignmentError("Assignment scope holds this mailbox effect")
    with project_store.connection(space, write=True) as (conn, _):
        from . import task_assignment_store as store
        store._admit(actor, space, conn)
        identity.recheck(actor, space)
        if request is not None:
            stored = Storage.get_instance().get_email_by_supabase_id(owner, request.source_id)
            if not person_request.matches_row(request, stored):
                raise AssignmentError("Person request source changed before mailbox effect")
        else:
            from .task_assignment_trust import delivery_routes_digest
            task, authoritative, keys = store.authority(actor, space, root, conn, locked=True)
            if (delivery_routes_digest(space) != projected["route_digest"]
                    or authoritative != projected["authoritative_thread_key"]
                    or keys != projected["component_thread_keys"]
                    or task != projected["task"] or task and task["state"] == "assigned"):
                raise AssignmentError("Assignment changed before mailbox effect", -32061)
        from .operator_reply_operations import check_mailbox_write
        check_mailbox_write(owner, conn)
        yield


def current():
    return _scope.get()


@contextlib.contextmanager
def scope(root):
    if root is not None:
        thread(root)
    token = _scope.set(root)
    try:
        yield
    finally:
        _scope.reset(token)


def _person_write(method, args, kwargs, values, root, request):
    """Write the draft a person asked for: bound to the named source, held by nothing.

    The projection, the RFC component and the ancestry proof are not computed:
    a thread the assignment store cannot resolve is still the thread the
    person named. The exact binding to the source row and the company writer
    lock stay.
    """
    from zylch.storage import database as db
    from zylch.storage.models import Email
    from .task_assignment_store import _admit, attach_profile

    actor, space, _ = evidence.admission()
    if (
        values["owner_id"] != actor.mailbox
        or values["owner_id"].strip().lower() != request.mailbox
        or root != request.root
        or values["thread_id"] != root
    ):
        raise AssignmentError("Person request draft must target the requested thread")
    if thread(values["in_reply_to"]) != request.target:
        raise AssignmentError("Person request draft must reply to the requested message")
    refs = values["references"] or []
    if not isinstance(refs, (list, str)):
        raise AssignmentError("Scoped draft references unavailable")
    refs = mail.references(refs if isinstance(refs, str) else " ".join(refs))
    known = request.known_identifiers()
    if any(ref not in known for ref in refs):
        raise AssignmentError("Person request draft must retain the requested message identifiers")
    with db.get_session() as session:
        row = (
            session.query(Email)
            .filter(Email.owner_id == actor.mailbox, Email.id == request.source_id)
            .one_or_none()
        )
        stored = row.to_dict() if row is not None else None
    if not person_request.matches_row(request, stored):
        raise AssignmentError("Person request source changed before draft write")
    with project_store.connection(space, write=True) as (conn, _):
        _admit(actor, space, conn)
        identity.recheck(actor, space)
        attach_profile(actor, conn)
        logger.debug("[tasks.assignment] person request draft admitted before write")
        with Session(bind=conn.execution_options(schema_translate_map={None: "assignment_profile"}), expire_on_commit=False) as session:
            token = _write_session.set(session)
            try:
                result = method(*args, **kwargs)
                session.flush()
                return result
            finally:
                _write_session.reset(token)


def guard(method):
    signature = inspect.signature(method)

    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        root = current()
        if root is None:
            return method(*args, **kwargs)
        from .request_policy import assert_tool_allowed

        assert_tool_allowed("create_draft")
        params = signature.bind(*args, **kwargs)
        params.apply_defaults()
        values = params.arguments
        request = person_request.active()
        if request is not None:
            return _person_write(method, args, kwargs, values, root, request)
        actor, space, _ = evidence.admission()
        if values["owner_id"] != actor.mailbox or values["thread_id"] != root:
            raise AssignmentError("Scoped draft must target the exact authorized thread")
        target = thread(values["in_reply_to"])
        refs = values["references"] or []
        if not isinstance(refs, (list, str)):
            raise AssignmentError("Scoped draft references unavailable")
        refs = mail.references(refs if isinstance(refs, str) else " ".join(refs))
        source = projection.project(root)
        if (
            not source["complete"]
            or source["hold_auto_reply"]
            or target not in source["current_message_ids"]
        ):
            raise AssignmentError("Assignment scope holds this draft before writing")
        keys = source["component_thread_keys"]
        if target not in keys or any(ref not in keys for ref in refs):
            raise AssignmentError("Scoped draft must retain the proven RFC component")
        prior = source["task"]
        with project_store.connection(space, write=True) as (conn, _):
            from .task_assignment_store import _admit

            _admit(actor, space, conn)
            from .task_assignment_trust import delivery_routes_digest

            if delivery_routes_digest(space) != source["route_digest"]:
                raise AssignmentError("Delivery routes changed before draft write", -32061)
            from .task_assignment_store import authority

            now, authoritative, keys = authority(actor, space, root, conn, locked=True)
            if (authoritative != source["authoritative_thread_key"]
                    or keys != source["component_thread_keys"]):
                raise AssignmentError("Assignment component changed before draft write", -32061)
            if now != prior or (now and now["state"] == "assigned"):
                raise AssignmentError("Assignment changed before draft write", -32061)
            identity.recheck(actor, space)
            logger.debug("[tasks.assignment] scoped draft admitted before write")
            with Session(bind=conn.execution_options(schema_translate_map={None: "assignment_profile"}), expire_on_commit=False) as session:
                token = _write_session.set(session)
                try:
                    result = method(*args, **kwargs)
                    session.flush()
                    return result
                finally:
                    _write_session.reset(token)

    return wrapped


@contextlib.contextmanager
def draft_session():
    active = _write_session.get()
    if active is not None:
        yield active
    else:
        from zylch.storage.database import get_session

        with get_session() as session:
            yield session


async def process_chat(service, message, owner, history, session_id, approval_callback, *, action_failures=None):
    """Run the existing agent without command/task routing or background writes."""
    from zylch.qonto import history as finance_history
    from zylch.assistant.turn_context import set_turn_observation

    if finance_history.is_managed() or message.strip().startswith("/"):
        raise AssignmentError("Scoped assignment draft does not admit command or finance routing")
    root = current()
    source = await asyncio.to_thread(projection.project, root)
    if not source["complete"] or source["hold_auto_reply"]:
        raise AssignmentError("Assignment scope holds this draft before routing")
    actor, _, _ = evidence.admission()
    if owner != actor.mailbox:
        raise AssignmentError("Scoped draft profile owner mismatch")
    set_turn_observation(message)
    await service._initialize_agent(owner_id=owner)
    if history:
        service.agent.set_history(history)
    else:
        service.agent.clear_history()
    response = await service.agent.process_message(
        user_message=f"Draft only for exact RFC thread {root}. Retain that thread_id and exact reply headers.\n\n{message}",
        context={"user_id": owner, "thread_id": root},
        approval_callback=approval_callback,
        action_failures=action_failures,
    )
    return {
        "response": response,
        "tool_calls": [],
        "metadata": {"assignment_draft_policy": VERSION},
        "session_id": session_id,
    }
