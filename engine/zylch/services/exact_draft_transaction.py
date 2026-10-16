"""Exact delivery CAS across the released and assignment-aware engines.

The released engine has no assignment effect module. Its existing request
policy and send-claim lifecycle remain authoritative; a private SQLite writer
reservation serializes exact effects with that lifecycle. Newer engines retain
their company effect lock and existing private transaction implementation.
"""

import contextlib
import contextvars
import importlib.util
from typing import Any, Iterator
from sqlalchemy import false, update
from sqlalchemy.orm import Session
from zylch.storage import database as db
from zylch.storage.models import Draft
from zylch.services.task_assignment_types import AssignmentError

_current = contextvars.ContextVar("exact_delivery_session", default=None)
_ASSIGNMENT = (
    importlib.util.find_spec("zylch.services.task_assignment_draft_transaction") is not None
)


@contextlib.contextmanager
def effect(owner: str, draft: dict[str, Any]) -> Iterator[None]:
    """Retain newer company authority; released engines have no such surface."""
    if _ASSIGNMENT:
        from zylch.services.task_assignment_email_effect import effect as assignment_effect

        with assignment_effect(owner, draft):
            yield
    else:
        yield


@contextlib.contextmanager
def session() -> Iterator[Session]:
    """Yield the session held by the current exact row reservation."""
    if _ASSIGNMENT:
        from zylch.services.task_assignment_draft_transaction import session as assignment_session

        with assignment_session() as current:
            yield current
    else:
        current = _current.get()
        if current is None:
            raise RuntimeError("Exact draft session requires a locked row")
        yield current


@contextlib.contextmanager
def locked_row(owner: str, draft_id: str, expected: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Reserve the writer and hold a verified full-row snapshot through effect."""
    if _ASSIGNMENT:
        from zylch.services.task_assignment_draft_transaction import (
            locked_row as assignment_locked_row,
        )

        with assignment_locked_row(owner, draft_id, expected) as actual:
            yield actual
        return
    with db.get_engine().begin() as conn:
        conn.execute(update(Draft).where(false()).values(id=Draft.id))
        with Session(bind=conn, expire_on_commit=False) as current:
            row = (
                current.query(Draft)
                .filter(Draft.owner_id == owner, Draft.id == draft_id)
                .one_or_none()
            )
            actual = row.to_dict() if row is not None else None
            keys = {column.name for column in Draft.__table__.columns}
            if actual is None or any(actual.get(key) != expected.get(key) for key in keys):
                raise AssignmentError("Persisted draft changed before exact effect", -32061)
            token = _current.set(current)
            try:
                yield actual
                current.flush()
            finally:
                _current.reset(token)
