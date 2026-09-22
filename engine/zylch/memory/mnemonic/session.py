"""One transaction on the company store, and the failure that is not one.

Both the operation journal and the semantic commit write here, and both need
the same two things: a session bound to the company engine **alone**, and the
store's write lock taken before anything is read that will then be written.

The single bind is what makes "one transaction on one file" true rather than
hopeful. ``database.get_session`` carries per-table binds for the profile file
too, so a statement naming a profile table would open a second transaction and
commit it separately — inside an operation that calls itself atomic. Here a
profile table simply has nowhere to go.

The write lock is not an optimization. Under WAL, SQLite refuses to upgrade a
deferred read transaction whose snapshot has gone stale, and it refuses
*immediately* — ``busy_timeout`` never gets a chance, because there is nothing
to wait for. Two engines on one company store would then both fail and neither
would write.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session, sessionmaker


class JournalError(RuntimeError):
    """The operation journal could not answer; the caller must not proceed."""


def session_factory() -> sessionmaker:
    """A session bound to the COMPANY store and to nothing else.

    Not ``database.get_session``: that one carries per-table binds for both
    files, so a statement naming a profile table would open a second
    transaction and commit it separately. An operation that claims to be
    atomic must not be able to do that by accident, so this factory binds one
    engine and a profile table simply has nowhere to go.
    """
    from zylch.storage.database import current_memory_engine, memory_unavailable_reason

    engine = current_memory_engine()
    if engine is None:
        raise JournalError(memory_unavailable_reason() or "company memory is unavailable")
    return sessionmaker(bind=engine, expire_on_commit=False)


class company_transaction:
    """One transaction on the company store, for the whole commit.

    Used as a context manager: it commits on a clean exit and rolls back on
    any exception, and it is the only transaction a semantic commit opens.

    ``write=True`` takes the store's write lock as the transaction's **first**
    statement — needed by every transaction here that reads a row and then
    updates it, not just by the commit. Under WAL, SQLite refuses to upgrade a
    deferred read transaction whose snapshot has gone stale, and it refuses
    *immediately*: ``busy_timeout`` never gets a chance, because there is
    nothing to wait for. Two engines on one company store would then both fail
    and neither would write.
    """

    def __init__(self, *, write: bool = False) -> None:
        self._session: Optional[Session] = None
        self._write = write

    def __enter__(self) -> Session:
        session = session_factory()()
        self._session = session
        if self._write:
            from zylch.memory.store import take_write_lock

            try:
                take_write_lock(session)
            except BaseException:
                # __exit__ never runs for a failed __enter__, so the session
                # would only go back to the pool when the garbage collector
                # got to it — and a store under contention is exactly where
                # leaking connections hurts.
                session.rollback()
                session.close()
                raise
        return session

    def __exit__(self, exc_type, exc, tb) -> bool:
        session = self._session
        assert session is not None
        try:
            if exc_type is None:
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
        return False


__all__ = ["JournalError", "company_transaction", "session_factory"]
