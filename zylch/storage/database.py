"""SQLAlchemy engine and session management for direct PostgreSQL access.

Provides a singleton engine, session factory, and context manager for
transactional session management. All storage methods use get_session()
to obtain a session that auto-commits on exit and rolls back on exception.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from zylch.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


# Module-level singletons
_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def get_engine() -> Engine:
    """Get or create the singleton SQLAlchemy engine.

    Uses settings.database_url with connection pooling optimized for
    a FastAPI backend running in threadpool mode.
    """
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise ValueError(
                "DATABASE_URL not configured. "
                "Set DATABASE_URL=postgresql://user:pass@host:5432/zylch"
            )

        _engine = create_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,     # detect stale connections (Railway/Docker)
            pool_recycle=1800,      # recycle connections every 30 min
            echo=(settings.log_level.upper() == "DEBUG"),
        )
        logger.info(f"SQLAlchemy engine created for {_mask_url(settings.database_url)}")

    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the singleton session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,  # allow to_dict() on detached objects
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


def _mask_url(url: str) -> str:
    """Mask password in database URL for logging."""
    try:
        # postgresql://user:PASSWORD@host:port/db → postgresql://user:***@host:port/db
        if "@" in url and ":" in url.split("@")[0]:
            prefix, rest = url.split("@", 1)
            scheme_user, _ = prefix.rsplit(":", 1)
            return f"{scheme_user}:***@{rest}"
    except Exception:
        pass
    return "***"


def dispose_engine() -> None:
    """Dispose the engine and reset singletons. Used in tests."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _session_factory = None
    logger.info("SQLAlchemy engine disposed")
