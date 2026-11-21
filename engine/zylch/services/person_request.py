"""A person's explicit request through the operator MCP.

The marker names the exact source message a person asked to answer. While it
is active, the draft write, the review write and the exact send keep their
binding checks against that message and skip every hold, assignment, conflict
and inbound-coverage refusal: those protect the scheduled operator, and the
person is the authority here. Only the MCP effects set it, around one request,
and a scheduled origin cannot carry it.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .task_assignment_types import AssignmentError, thread

_request = ContextVar("person_request", default=None)


@dataclass(frozen=True)
class PersonRequest:
    mailbox: str
    mailbox_id: str
    root: str
    source_id: str
    target: str
    references: tuple

    def known_identifiers(self) -> set:
        return {self.root, self.target, *self.references}


def from_row(mailbox: str, row) -> PersonRequest:
    """The identity of one ordinary stored source row, or a refusal."""
    from . import task_assignment_mail as mail

    if (
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not row["id"]
        or not isinstance(row.get("mailbox_id"), str)
        or not row["mailbox_id"]
        or row.get("original_message_id")
        or row.get("pec_markers")
    ):
        raise AssignmentError("exact_source_required")
    try:
        root = thread(row.get("thread_id") or "")
        target = thread(row.get("message_id_header") or "")
        references = tuple(mail.references(row.get("references") or ""))
    except AssignmentError:
        raise AssignmentError("exact_source_required") from None
    return PersonRequest(
        mailbox=mailbox.strip().lower(),
        mailbox_id=row["mailbox_id"],
        root=root,
        source_id=row["id"],
        target=target,
        references=references,
    )


def matches_row(request: PersonRequest, row) -> bool:
    """Whether a stored row is still the message the person named."""
    return (
        isinstance(row, dict)
        and row.get("id") == request.source_id
        and row.get("mailbox_id") == request.mailbox_id
        and row.get("thread_id") == request.root
        and row.get("message_id_header") == request.target
        and not row.get("original_message_id")
        and not row.get("pec_markers")
    )


def active():
    return _request.get()


@contextmanager
def scope(request: PersonRequest):
    from .operator_reply_origin import is_scheduled

    if not isinstance(request, PersonRequest):
        raise AssignmentError("person_request_identity_required")
    if is_scheduled() or _request.get() is not None:
        raise AssignmentError("person_request_not_interactive")
    token = _request.set(request)
    try:
        yield request
    finally:
        _request.reset(token)
