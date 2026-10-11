"""Authoritative private draft CAS, always after any company effect lock."""

import contextlib
import contextvars
from sqlalchemy import false, update
from sqlalchemy.orm import Session
from zylch.storage import database as db
from zylch.storage.models import Draft
from .task_assignment_types import AssignmentError

_session = contextvars.ContextVar("assignment_private_draft_session", default=None)
_editing = contextvars.ContextVar("assignment_claim_edits", default=None)
CONTENT = frozenset({"id", "owner_id", "thread_id", "in_reply_to", "references", "reply_binding",
                     "to_addresses", "cc_addresses", "bcc_addresses", "subject", "body", "body_format", "original_message_id", "provider", "attachment_paths"})


@contextlib.contextmanager
def session():
    current = _session.get()
    if current is not None:
        yield current
    else:
        with db.get_session() as value:
            yield value


@contextlib.contextmanager
def create_transaction():
    """Serialize insert/reuse before reading any persisted draft candidate."""
    with db.get_engine().begin() as conn:
        conn.execute(update(Draft).where(false()).values(id=Draft.id))
        with Session(bind=conn, expire_on_commit=False) as current:
            token = _session.set(current)
            try:
                yield
                current.flush()
            finally:
                _session.reset(token)


@contextlib.contextmanager
def claim_edits(owner, draft_id):
    """Internal sender scope around approved card edits; no client/API flag."""
    token = _editing.set((owner, draft_id))
    try:
        yield
    finally:
        _editing.reset(token)


def may_edit_claim(owner, draft_id):
    return _editing.get() == (owner, draft_id)


@contextlib.contextmanager
def locked_row(owner, draft_id, expected, *, sending=False):
    """Reserve the private writer, compare authoritative bytes, retain through effect."""
    with db.get_engine().begin() as conn:
        # First statement takes SQLite's writer reservation before reading the row.
        conn.execute(update(Draft).where(false()).values(id=Draft.id))
        with Session(bind=conn, expire_on_commit=False) as current:
            row = current.query(Draft).filter(Draft.owner_id == owner, Draft.id == draft_id).one_or_none()
            actual = row.to_dict() if row is not None else None
            # Claim may stamp provider; transport selection comes from authenticated
            # caller configuration, not this bookkeeping column.
            keys = (CONTENT - {"provider"}) if sending else {column.name for column in Draft.__table__.columns}
            if actual is None or any(actual.get(key) != expected.get(key) for key in keys):
                raise AssignmentError("Persisted draft changed before effect; retry with current draft", -32061)
            if sending and actual["status"] != "sending":
                raise AssignmentError("Current persisted draft send claim required")
            token = _session.set(current)
            try:
                yield actual
                current.flush()
                if sending:
                    # Reservation only: no post-acceptance private commit can
                    # turn a successful transport into a retryable DB failure.
                    conn.rollback()
            finally:
                _session.reset(token)
