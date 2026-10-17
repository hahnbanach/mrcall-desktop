from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

from zylch.services.task_assignment_types import AssignmentError

_request = ContextVar("operator_reply_request", default=None)
_send = ContextVar("operator_reply_handoff", default=None)


def validate(params):
    keys = ("operator_origin", "operator_origin_version")
    if not any(key in params for key in keys):
        return False
    if (
        type(params.get(keys[0])) is not str
        or params[keys[0]] != "scheduled_operator"
        or type(params.get(keys[1])) is not int
        or params[keys[1]] != 1
    ):
        raise AssignmentError("Invalid scheduled operator origin", -32602)
    return True


@contextmanager
def scope(callback):
    request = {"callback": callback, "active": True} if callback is not None else None
    token = _request.set(request)
    try:
        yield
    finally:
        if request is not None:
            request["active"] = False
        _request.reset(token)


def snapshot(owner, draft):
    refs = draft.get("references") or []
    return {
        "owner": owner,
        "thread_id": draft.get("thread_id"),
        "in_reply_to": draft.get("in_reply_to"),
        "references": " ".join(refs) if isinstance(refs, list) else refs,
    }


async def admit(owner, draft):
    request = _request.get()
    if request is None or not draft.get("in_reply_to"):
        return None
    if not request["active"]:
        raise AssignmentError("Scheduled operator request has ended")
    binding = await request["callback"](owner, draft)
    if not request["active"]:
        raise AssignmentError("Scheduled operator request has ended")
    return binding


@contextmanager
def handoff(binding, owner, draft):
    admission = None
    if binding is not None:
        request = _request.get()
        if (
            request is None
            or not request["active"]
            or {key: value for key, value in binding.items() if key != "_assignment"}
            != snapshot(owner, draft)
        ):
            raise AssignmentError("Scheduled reply identity changed before transport")
        admission = binding.get("_assignment")
        if not isinstance(admission, dict):
            raise AssignmentError("Scheduled reply assignment admission unavailable")
    from .task_assignment_email_effect import effect

    authority = (
        effect(owner, draft, sending=True, scheduled=admission)
        if binding is not None
        else nullcontext()
    )
    with authority:
        token = _send.set(binding)
        try:
            yield
        finally:
            _send.reset(token)


def automatic(sender, target, references):
    binding = _send.get()
    if binding is None:
        return False
    request = _request.get()
    if (
        request is None
        or not request["active"]
        or sender.strip().lower() != binding["owner"]
        or target != binding["in_reply_to"]
        or references != binding["references"]
    ):
        raise AssignmentError("Scheduled reply transport identity changed")
    return True
