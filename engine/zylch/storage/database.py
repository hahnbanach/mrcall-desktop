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
        # 2026-04-17: pinned tasks — pinned=True floats a task to the top of
        # `tasks.list` regardless of urgency. Toggled via `tasks.pin` RPC.
        ("task_items", "pinned", "BOOLEAN DEFAULT 0"),
        # 2026-04-17: persisted attachment metadata on incoming/sent emails so
        # `read_email` and the desktop Email tab can show which files are
        # available without re-fetching the MIME from IMAP. Populated at sync
        # time by IMAPClient._fetch_one and at send time by insert_sent_email.
        ("emails", "has_attachments", "BOOLEAN DEFAULT 0"),
        ("emails", "attachment_filenames", "JSON DEFAULT '[]'"),
        # 2026-04-17: thread-level pin flag + per-row read marker backing
        # the desktop Email tab. `emails.pin` RPC sets pinned_at on all
        # rows sharing a thread_id; `emails.mark_read` sets read_at on
        # every row of a thread when the user opens it in the UI.
        ("emails", "pinned_at", "DATETIME"),
        ("emails", "read_at", "DATETIME"),
        # 2026-04-21: Inbox Archive/Delete actions. `archived_at` is stamped
        # by `emails.archive` (which also IMAP-MOVEs the message to the
        # provider's archive folder). `deleted_at` is a local-only soft
        # delete stamped by `emails.delete` — never touches IMAP.
        ("emails", "archived_at", "DATETIME"),
        ("emails", "deleted_at", "DATETIME"),
        # 2026-05-02: optional free-text note attached when a task is closed
        # by the user (e.g. "already paid via bank transfer"). Display-only:
        # not consumed by the task detector, never sent to any LLM prompt.
        ("task_items", "close_note", "TEXT"),
        # 2026-05-06: epoch-seconds gate consumed by the dedup sweep
        # (zylch.workers.task_dedup_sweep). When the user reopens a
        # task, reopen_task_item sets this to now+7d so the sweep does
        # not immediately re-close it. NULL means "not protected".
        ("task_items", "dedup_skip_until", "BIGINT"),
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

    # 2026-05-06: email_blobs / calendar_blobs association tables (Fase 3.1).
    # Existing installations have populated `blobs.events` strings of
    # the form "Extracted from email <uuid> (<datetime>)" but no
    # entries in the new index. Reconstruct it once on first boot
    # post-3.1; idempotent via INSERT OR IGNORE on the composite PK.
    _backfill_email_blobs_index()


def _backfill_email_blobs_index() -> None:
    """One-shot reconstruction of the email_blobs / calendar_blobs
    index from the legacy blob.events descriptions.

    Runs on every init_db but exits cheaply when the index is already
    populated (or there are no blobs to migrate). Mirrors the logic in
    ``engine/scripts/backfill_email_blobs.py`` so the script remains
    available for explicit reruns / dry-runs.
    """
    import json
    import re

    from zylch.storage.models import Blob, CalendarBlob, CalendarEvent, Email, EmailBlob

    factory = get_session_factory()
    session = factory()
    try:
        existing_links = session.query(EmailBlob.email_id).limit(1).first()
        any_blobs = session.query(Blob.id).limit(1).first()
        if existing_links is not None:
            return  # already populated
        if any_blobs is None:
            return  # nothing to backfill

        email_pattern = re.compile(
            r"^Extracted from email\s+([^\s()]+)(?:\s*\(.*\))?\s*$",
            re.IGNORECASE,
        )
        calendar_pattern = re.compile(
            r"^Extracted from calendar event\s+'(.+?)'\s*\(.*\)\s*$",
            re.IGNORECASE,
        )

        email_ids = {str(r[0]) for r in session.query(Email.id).all() if r[0]}
        summary_to_events: dict[str, list[str]] = {}
        for r in (
            session.query(CalendarEvent.id, CalendarEvent.summary)
            .filter(CalendarEvent.summary.isnot(None))
            .all()
        ):
            eid, summary = str(r[0]), str(r[1] or "")
            summary_to_events.setdefault(summary, []).append(eid)

        n_email = 0
        n_calendar = 0
        for blob in session.query(Blob).all():
            blob_id = str(blob.id)
            owner_id = str(blob.owner_id)
            events = blob.events or []
            if not isinstance(events, list):
                try:
                    events = json.loads(events)
                except (TypeError, ValueError):
                    continue
            for item in events:
                if isinstance(item, dict):
                    desc = item.get("description")
                else:
                    desc = item
                if not isinstance(desc, str):
                    continue
                desc = desc.strip()
                m_email = email_pattern.match(desc)
                if m_email:
                    target_email_id = m_email.group(1).strip()
                    if target_email_id not in email_ids:
                        continue
                    session.merge(
                        EmailBlob(
                            email_id=target_email_id,
                            blob_id=blob_id,
                            owner_id=owner_id,
                        )
                    )
                    n_email += 1
                    continue
                m_cal = calendar_pattern.match(desc)
                if m_cal:
                    summary = m_cal.group(1).strip()
                    for eid in summary_to_events.get(summary, []):
                        session.merge(
                            CalendarBlob(
                                event_id=eid,
                                blob_id=blob_id,
                                owner_id=owner_id,
                            )
                        )
                        n_calendar += 1

        if n_email or n_calendar:
            session.commit()
            logger.info(
                f"[backfill] populated email_blobs index: "
                f"{n_email} email_blobs + {n_calendar} calendar_blobs rows"
            )
        else:
            session.rollback()
    except Exception as e:
        session.rollback()
        logger.warning(f"[backfill] email_blobs index backfill failed: {e}")
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
