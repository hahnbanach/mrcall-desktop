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


def _resolve_db_path() -> str:
    """Resolve DB path: profile-aware or legacy default."""
    env_path = os.environ.get("ZYLCH_DB_PATH")
    if env_path:
        return env_path
    return os.path.join(os.path.expanduser("~/.zylch"), "zylch.db")


DB_DIR = os.path.expanduser("~/.zylch")  # legacy compat


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
        db_path = _resolve_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db_url = f"sqlite:///{db_path}"

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

        logger.info(f"SQLAlchemy engine created for {db_url}")

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

    # Light-touch migrations for columns added after initial schema.
    # `create_all` creates missing tables but does NOT add columns to existing
    # tables. For SQLite, ALTER TABLE ADD COLUMN is cheap and idempotent-ish.
    _apply_column_migrations(engine)

    # Idempotent row-level backfills for data shape changes (not schema).
    _apply_data_backfills()

    logger.info(f"Database initialized at {_resolve_db_path()}")


def _apply_column_migrations(engine: Engine) -> None:
    """Add columns introduced after a table was first created.

    Each entry: (table, column, ddl_type_with_default). We inspect the
    existing column set via PRAGMA table_info and ALTER-ADD if missing.
    """
    migrations = [
        # 2026-04-17: chat attachments — absolute local paths attached to a
        # draft and transported to MIME at send time.
        ("drafts", "attachment_paths", "JSON DEFAULT '[]'"),
        # 2026-04-17: CC/BCC recipients on drafts. Allows "reply-to-all" and
        # adding additional recipients from chat. The columns exist in the
        # ORM model from the start but legacy DBs created before this
        # migration may lack them.
        ("drafts", "cc_addresses", "JSON DEFAULT '[]'"),
        ("drafts", "bcc_addresses", "JSON DEFAULT '[]'"),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            try:
                rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            except Exception as e:
                logger.debug(f"[migrate] PRAGMA failed for {table}: {e}")
                continue
            existing = {r[1] for r in rows}
            if not existing:
                # Table doesn't exist yet -- create_all above would have made
                # it fresh with the column already present.
                continue
            if column in existing:
                continue
            try:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                logger.info(f"[migrate] Added {table}.{column} ({ddl})")
            except Exception as e:
                logger.warning(f"[migrate] Failed to add {table}.{column}: {e}")


def _apply_data_backfills() -> None:
    """Row-level, idempotent data backfills for shape changes.

    Runs inside a single transactional session. Each backfill must be
    idempotent: re-running on an already-migrated DB must be a no-op.
    """
    # 2026-04-17: TaskItem.sources.thread_id — the desktop "Open" button
    # on the Tasks view needs sources.thread_id to activate the Email
    # tab. Tasks created before task_creation.py started storing
    # thread_id in sources have {"emails": [...], "blobs": [...],
    # "calendar_events": [...]} with no thread_id. Derive thread_id
    # from Email rows via sources.emails[0].
    from zylch.storage.models import Email, TaskItem

    factory = get_session_factory()
    session = factory()
    try:
        candidates = session.query(TaskItem).filter(TaskItem.sources.isnot(None)).all()

        # First pass: decide what needs a lookup. Skip rows already populated
        # or rows whose sources has no emails[0] to derive from.
        needs_lookup: dict[str, list] = {}  # first_email_id -> [task, ...]
        for task in candidates:
            sources = task.sources or {}
            if not isinstance(sources, dict):
                continue
            if sources.get("thread_id"):
                continue
            emails = sources.get("emails") or []
            if not emails:
                continue
            first_email_id = emails[0]
            if not first_email_id:
                continue
            needs_lookup.setdefault(first_email_id, []).append(task)

        if not needs_lookup:
            return

        # Batch lookup: single IN(...) query for all required email ids.
        email_ids = list(needs_lookup.keys())
        rows = session.query(Email.id, Email.thread_id).filter(Email.id.in_(email_ids)).all()
        thread_by_email = {eid: tid for eid, tid in rows if tid}

        backfilled = 0
        for email_id, tasks in needs_lookup.items():
            thread_id = thread_by_email.get(email_id)
            if not thread_id:
                logger.debug(
                    f"[backfill] skip task(s) — email {email_id} missing or " f"has no thread_id"
                )
                continue
            for task in tasks:
                sources = dict(task.sources or {})
                sources["thread_id"] = thread_id
                task.sources = sources
                backfilled += 1

        if backfilled:
            session.commit()
            logger.info(f"[backfill] backfilled thread_id on {backfilled} task(s)")
        else:
            session.rollback()
    except Exception as e:
        session.rollback()
        logger.warning(f"[backfill] sources.thread_id backfill failed: {e}")
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose the engine and reset singletons. Used in tests."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
        _engine = None
    _session_factory = None
    logger.info("SQLAlchemy engine disposed")
