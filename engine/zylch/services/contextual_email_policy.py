"""Restrictive known reply context retained across chat, tools and worker threads.

This is source binding, never a caller grant or an assignment bypass. Dependency
imports stay inside execution so transport decorators remain independently loadable.
"""

import contextlib
import contextvars
import functools
from dataclasses import dataclass

from .task_assignment_types import AssignmentError, thread

VERSION = 1


@dataclass(frozen=True)
class Binding:
    owner: str
    root: str | None = None
    target: str | None = None
    source: dict | None = None
    unavailable: str | None = None
    sources: tuple = ()


_binding = contextvars.ContextVar("known_contextual_email", default=None)


def current():
    return _binding.get()


def intersect(left, right):
    if left is None:
        return right
    if right is None:
        return left
    if left.owner != right.owner or left.unavailable or right.unavailable:
        if left == right:
            return left
        raise AssignmentError("Known task/context email authority unavailable or conflicting")
    if any(a is not None and b is not None and a != b for a, b in (
        (left.root, right.root), (left.target, right.target), (left.source, right.source),
    )):
        raise AssignmentError("Known contextual email binding cannot change")
    allowed = left.sources or right.sources
    if left.sources and right.sources:
        allowed = tuple(value for value in left.sources if value in right.sources)
        if not allowed:
            raise AssignmentError("Known task source sets disagree")
    source = left.source or right.source
    if allowed and source is not None and source not in allowed:
        raise AssignmentError("Selected email is not an authoritative task source")
    return Binding(left.owner, left.root or right.root, left.target or right.target,
                   source, sources=allowed)



@contextlib.contextmanager
def scope(value):
    token = _binding.set(intersect(current(), value))
    try:
        yield
    finally:
        _binding.reset(token)


def source_binding(owner, values):
    """Resolve all supplied identifiers against owner-scoped private records."""
    from zylch.storage.storage import Storage
    from .task_assignment_email_effect import resolve

    if not isinstance(values, dict) or not values or set(values) - {
        "thread_key", "source_email_id", "target_message_id", "draft_id",
    }:
        raise AssignmentError("Explicit contextual email source required", -32602)
    if any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise AssignmentError("Invalid contextual email source", -32602)
    store = Storage.get_instance()
    sources = []
    draft = None
    if values.get("draft_id"):
        draft = store.get_draft(owner, values["draft_id"])
        if draft is None:
            raise AssignmentError("Exact contextual draft unavailable")
        if any(draft.get(k) for k in ("in_reply_to", "references", "thread_id", "reply_binding")):
            sources.append(resolve(owner, draft))
        elif len(values) != 1:
            raise AssignmentError("Standalone draft disagrees with contextual original source")
    if values.get("source_email_id"):
        email = (store.get_email_by_supabase_id(owner, values["source_email_id"])
                 or store.get_email_by_id(owner, values["source_email_id"]))
        if email is None or not email.get("message_id_header"):
            raise AssignmentError("Exact contextual email source unavailable")
        sources.append(resolve(owner, {"in_reply_to": email["message_id_header"]}))
    if values.get("target_message_id"):
        sources.append(resolve(owner, {"in_reply_to": values["target_message_id"]}))
    if sources and any(item != sources[0] for item in sources):
        raise AssignmentError("Supplied contextual source identities disagree")
    root = thread(values["thread_key"]) if values.get("thread_key") else None
    if sources:
        source = sources[0]
        if root is not None and root != source["root"]:
            raise AssignmentError("Supplied contextual thread identities disagree")
        return Binding(owner, source["root"], source["target"], source["source"])
    if root:
        if draft is not None:
            raise AssignmentError("Standalone draft disagrees with contextual thread")
        # A caller which only knows the RFC root restricts the whole turn to
        # that root; the actual tool must still supply an exact stored target.
        return Binding(owner, root)
    if draft is not None and len(values) == 1:
        return None  # Independently source-free persisted composition.
    raise AssignmentError("Contextual email identity unavailable")


def from_task(owner, task):
    """Use ordinary task authority, never a model-written tool argument."""
    if not isinstance(task, dict) or not task:
        return Binding(owner, unavailable="Known task source unavailable")
    sources = task.get("sources") or {}
    if not isinstance(sources, dict):
        return Binding(owner, unavailable="Known task source metadata malformed")
    ids = sources.get("emails") or []
    if not isinstance(ids, list):
        return Binding(owner, unavailable="Known task email sources malformed")
    event = task.get("event_id")
    email_kind = task.get("event_type") == "email" or task.get("trigger_channel") == "email"
    if email_kind and event:
        ids = [event, *ids]
    if not ids:
        return Binding(owner, unavailable="Known email task has no source") if email_kind else None
    try:
        bindings = [source_binding(owner, {"source_email_id": value}) for value in dict.fromkeys(ids)]
        if not bindings or any(value.root != bindings[0].root for value in bindings):
            return Binding(owner, unavailable="Known task has conflicting email threads")
        if any(value != bindings[0] for value in bindings):
            return Binding(owner, bindings[0].root, sources=tuple(value.source for value in bindings))
        return bindings[0]
    except (AssignmentError, TypeError, ValueError):
        return Binding(owner, unavailable="Known task original email source unavailable")


def from_context(owner, context, *, task_id=None):
    from zylch.storage.storage import Storage

    context = context or {}
    explicit = context.get("email_context")
    provided = []
    if explicit is not None:
        provided.append(source_binding(owner, explicit))
    if context.get("email_id"):
        provided.append(source_binding(owner, {"source_email_id": context["email_id"]}))
    legacy = {field: context[key] for field, key in (
        ("thread_key", "thread_id"), ("source_email_id", "source_email_id"),
        ("target_message_id", "in_reply_to"),
    ) if context.get(key)}
    if legacy:
        provided.append(source_binding(owner, legacy))
    task_id = context.get("task_id") or task_id
    if task_id:
        task = Storage.get_instance().get_task_by_id(owner, task_id)
        task_binding = from_task(owner, task)
        if task_binding is not None:
            provided.append(task_binding)
    if not provided:
        return current()
    known = [value for value in provided if value is not None]
    if not known:
        return current()
    binding = current()
    for value in known:
        binding = intersect(binding, value)
    return binding


def chat_scope(method):
    @functools.wraps(method)
    async def wrapped(self, user_message, user_id, conversation_history=None, session_id=None,
                      context=None, approval_callback=None):
        from zylch.tools.factory import ToolFactory

        state = ToolFactory._session_state
        task_id = state.get_task_id() if state and state.is_task_mode() else None
        binding = from_context(user_id, context, task_id=task_id)
        with scope(binding):
            return await method(self, user_message, user_id, conversation_history,
                                session_id, context, approval_callback)
    return wrapped


def validate(owner, source):
    bound = current()
    if bound is None:
        return
    if bound.owner != owner or bound.unavailable:
        raise AssignmentError(bound.unavailable or "Contextual email owner mismatch")
    if source is None:
        raise AssignmentError("Known contextual email cannot become standalone by dropping reply metadata")
    if bound.sources and source["source"] not in bound.sources:
        raise AssignmentError("Email effect is not an authoritative original task source")
    if source["root"] != bound.root or (bound.target is not None and source["target"] != bound.target) or (
        bound.source is not None and source["source"] != bound.source
    ):
        raise AssignmentError("Email effect disagrees with known original reply source")
