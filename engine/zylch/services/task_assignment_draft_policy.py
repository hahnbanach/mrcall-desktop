"""Opt-in kernel draft scope enforced at the actual private draft write."""

import asyncio
import contextlib
import contextvars
import functools
import inspect
import logging

from sqlalchemy import select

from zylch.services import project_store
from zylch.storage.assigned_task_models import AssignedTask
from . import task_assignment_evidence as evidence
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_projection as projection
from .task_assignment_types import AssignmentError, thread

logger = logging.getLogger(__name__)
VERSION = 1
_scope = contextvars.ContextVar("assignment_draft_thread", default=None)


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
        if (refs and refs[0] != root) or (not refs and target != root):
            raise AssignmentError("Scoped draft must retain the exact RFC thread root")
        # The shared effect guard covers scoped and ordinary contextual writes.
        # It owns the sole company transaction; do not nest another write lock.
        return method(*args, **kwargs)

    return wrapped


async def process_chat(service, message, owner, history, session_id, approval_callback):
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
    )
    return {
        "response": response,
        "tool_calls": [],
        "metadata": {"assignment_draft_policy": VERSION},
        "session_id": session_id,
    }
