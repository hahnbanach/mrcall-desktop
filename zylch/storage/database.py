"""SQLAlchemy engine and session management for SQLite.

Provides a singleton engine, session factory, and context manager for
transactional session management. All storage methods use get_session()
to obtain a session that auto-commits on exit and rolls back on
exception.

Database file: ~/.zylch/zylch.db (created automatically).
"""

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

logger = logging.getLogger(__name__)

DB_DIR = os.path.expanduser("~/.zylch")
DB_PATH = os.path.join(DB_DIR, "zylch.db")


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# Module-level singletons
_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    """Get or create the singleton SQLAlchemy engine.

    Creates ~/.zylch/ directory if it doesn't exist.
    Configures WAL journal mode and foreign keys for SQLite.
    """
    global _engine
    if _engine is None:
        os.makedirs(DB_DIR, exist_ok=True)
        db_url = f"sqlite:///{DB_PATH}"

        _engine = create_engine(
            db_url,
            echo=False,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        logger.info(f"SQLAlchemy engine created for sqlite:///{DB_PATH}")

    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
        )
    return _session_factory


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager providing a transactional database session.

    Auto-commits on clean exit, rolls back on exception.

    Usage:
        with get_session() as session:
            user = session.query(User).filter_by(id=uid).one()
            user.name = "new"
            # commits automatically
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables if they don't exist."""
    from zylch.storage.models import Base as _Base  # noqa: F811
    engine = get_engine()
    _Base.metadata.create_all(engine)
    logger.info(f"Database initialized at {DB_PATH}")


def dispose_engine() -> None:
    """Dispose the engine and reset singletons. Used in tests."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _session_factory = None
    logger.info("SQLAlchemy engine disposed")
