"""Persisted generation fencing. Commit order: guard, company, profile.

Network and model waits must stay outside this guard. A company transaction,
when needed, precedes the profile transaction; they do not commit atomically.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

from zylch.qonto.errors import QontoError
from zylch.qonto.identity import Authority, current_authority, profile_identity, require_same
from zylch.qonto.models import QontoConversation, QontoPublicationIntent
from zylch.qonto.private_files import private_lock
from zylch.qonto.repository import Binding, connection, profile_transaction, snapshot


@contextmanager
def state_guard(profile_dir):
    with private_lock(profile_dir / "qonto-state.lock"):
        yield


def revoke(row, *, status: str, reason: str, erase: bool = False) -> None:
    row.generation += 1
    row.status = status
    row.last_error = reason
    row.changed_at = time.time()
    row.sync_token = None
    row.sync_expires_at = None
    if erase:
        row.encrypted_credentials = None


def cancel_intents(session, uid: str) -> None:
    session.query(QontoConversation).filter_by(uid=uid).update(
        {"tombstoned": True, "turn_token": None, "turn_expires_at": None},
        synchronize_session=False,
    )
    session.query(QontoPublicationIntent).filter(
        QontoPublicationIntent.uid == uid,
        QontoPublicationIntent.state.in_(("pending", "confirmed", "running")),
    ).update({"state": "cancelled"}, synchronize_session=False)


def suspend_for_join() -> None:
    from sqlalchemy import inspect
    from zylch.storage.database import get_engine
    from zylch.qonto.models import QontoConnection

    if not inspect(get_engine()).has_table(QontoConnection.__tablename__):
        return
    with profile_transaction() as session:
        if session.query(QontoConnection.uid).first() is None:
            return
    with state_guard_path():
        with profile_transaction() as session:
            rows = session.query(QontoConnection).all()
            for row in rows:
                if row.status != "suspended" or row.last_error != "company_joining":
                    revoke(row, status="suspended", reason="company_joining")
                cancel_intents(session, row.uid)


@contextmanager
def state_guard_path():
    from pathlib import Path
    from zylch.storage.database import _resolve_db_path

    with state_guard(Path(_resolve_db_path()).absolute().parent):
        yield


def recover() -> None:
    from zylch.qonto.models import QontoConnection

    with profile_transaction() as session:
        connected = (
            session.query(QontoConnection.uid).filter(QontoConnection.status == "connected").all()
        )
    if not connected:
        return
    try:
        authority = current_authority(session_required=False, create_host=False)
    except QontoError:
        authority = None
    with state_guard_path():
        with profile_transaction() as session:
            for (uid,) in connected:
                row = connection(session, uid)
                if row.status == "connected" and (
                    authority is None or not snapshot(row).matches(authority)
                ):
                    revoke(row, status="suspended", reason="binding_changed")
                    cancel_intents(session, uid)


def state(authority: Authority) -> Binding:
    with state_guard(authority.profile_dir):
        require_same(authority)
        with profile_transaction() as session:
            row = connection(session, authority.uid, create=True)
            if row.status == "connected" and not snapshot(row).matches(authority):
                revoke(row, status="suspended", reason="binding_changed")
                cancel_intents(session, authority.uid)
            return snapshot(row)


@contextmanager
def commit_guard(authority: Authority, binding: Binding):
    with state_guard(authority.profile_dir):
        require_same(authority)
        with profile_transaction() as session:
            row = connection(session, authority.uid)
            if row is None or row.generation != binding.generation:
                raise QontoError("generation_changed")
            if row.status != "connected":
                raise QontoError("not_connected")
            current = snapshot(row)
            if current != binding or not current.matches(authority):
                raise QontoError("binding_changed")
            yield session
            require_same(authority)


def auth_failed(authority: Authority, binding: Binding) -> None:
    with state_guard(authority.profile_dir):
        with profile_transaction() as session:
            row = connection(session, authority.uid)
            if row is not None and row.generation == binding.generation:
                revoke(row, status="auth_failed", reason="auth", erase=True)
                cancel_intents(session, authority.uid)


def active_binding() -> tuple[Authority, Binding]:
    authority = current_authority()
    binding = state(authority)
    if binding.status != "connected":
        raise QontoError("not_connected")
    if not binding.matches(authority):
        raise QontoError("binding_changed")
    return authority, binding


def suspend_on_signout() -> None:
    try:
        uid, directory = profile_identity()
    except QontoError:
        return
    with state_guard(directory):
        with profile_transaction() as session:
            row = connection(session, uid)
            if row is not None and row.status == "connected":
                revoke(row, status="suspended", reason="identity_required")
                cancel_intents(session, uid)
