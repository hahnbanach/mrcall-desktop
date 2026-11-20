"""Opt-in kernel draft scope enforced at the actual private draft write."""

import asyncio
import contextlib
import contextvars
import functools
import inspect
import logging

from sqlalchemy.orm import Session

from zylch.services import project_store
from . import task_assignment_evidence as evidence
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_projection as projection
from .task_assignment_types import AssignmentError, thread

logger = logging.getLogger(__name__)
VERSION = 1
_scope = contextvars.ContextVar("assignment_draft_thread", default=None)
_write_session = contextvars.ContextVar("assignment_draft_session", default=None)


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
