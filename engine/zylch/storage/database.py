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
# The company memory store's engine (since 2026-09 the six memory tables
# live there, one file per company) and, when memory is unavailable, why.
_memory_engine: Engine | None = None
_memory_reason: str | None = "memory store not attached yet"


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
            # Wait for a concurrent writer instead of failing after pysqlite's
            # 5s default — a second process on the same file is rare today but
            # real (CLI beside the server), and mandatory once memory is shared.
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        logger.info(f"SQLAlchemy engine created for {db_url}")

    return _engine


def current_memory_engine() -> Engine | None:
    """The attached company store's engine, or None while unavailable."""
    return None if _memory_reason else _memory_engine


def memory_unavailable_reason() -> str | None:
    """Why memory is disabled for this profile, or None when it is usable."""
    return _memory_reason


def _bound_memory_engine() -> Engine:
    """What the memory tables are bound to right now.

    A refusing engine while memory is unavailable: every memory statement
    then fails loudly with the reason instead of reading a scratch file as
    if it were the company's knowledge. Mail sync is untouched.
    """
    global _memory_engine
    if _memory_reason:
        from zylch.memory.store import refused_engine

        if _memory_engine is None:
            _memory_engine = refused_engine(_memory_reason)
    return _memory_engine  # type: ignore[return-value]


def set_memory_engine(engine: Engine | None, reason: str | None) -> None:
    """Bind the memory tables to ``engine`` (or mark memory unavailable)."""
    global _memory_engine, _memory_reason, _session_factory
    old = _memory_engine
    _memory_engine = engine
    _memory_reason = reason
    _session_factory = None  # rebuilt with the new binds on next use
    if old is not None and old is not engine:
        try:
            old.dispose()
        except Exception:
            pass


def rebind_memory(engine: Engine) -> None:
    """In-process switch to another company store (the join gesture)."""
    set_memory_engine(engine, None)
    logger.info("[memory] session factory rebound to the joined store")


def attach_memory_store(*, migrating: bool = False) -> Engine | None:
    """Open this profile's company store by provenance; None when refused.

    Existing store: open. Missing store: create only when something the
    host holds vouches for the key — the engine minted it, provisiond
    injected it, or ``migrating`` says this profile's own database is
    pre-split and its rows carry the key. A typed key with no store
    (``MEMORY_KEY_SOURCE=join``, or no source at all) leaves memory
    unavailable and creates nothing.
    """
    from zylch.memory.company_key import current_company_key
    from zylch.memory.store import (
        MemoryUnavailable,
        key_source,
        open_memory_engine,
        prepare_store,
        source_is_vouched,
        store_exists,
    )

    key = current_company_key()
    if not key:
        set_memory_engine(None, "this profile has no MEMORY_KEY")
        return None
    source = key_source()
    may_create = migrating or source_is_vouched(source)
    try:
        engine = open_memory_engine(key, create=(may_create and not store_exists(key)))
    except MemoryUnavailable as e:
        set_memory_engine(None, e.reason)
        logger.warning(f"[memory] unavailable: {e.reason}")
        return None
    prepare_store(engine, key, created_by=("migration" if migrating else source))
    set_memory_engine(engine, None)
    return engine


def get_session_factory() -> sessionmaker:
    """Get or create the singleton session factory.

    Per-table binds route every memory-table statement to the company
    store and everything else to the profile file. No ORM join crosses
    the boundary (every access is single-table), so one session serves
    both; a session that touches both files commits two transactions,
    not one — `_reset_all_data` and `migrate_blob_references` are the two
    such places and each defines its own partial-failure outcome.
    """
    global _session_factory
    if _session_factory is None:
        memory_engine = _bound_memory_engine()
        binds = {tbl: memory_engine for tbl in memory_tables()}
        _session_factory = sessionmaker(
            bind=get_engine(),
            binds=binds,
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


# The six memory tables are the ones a company shares; everything else is
# per-profile (mail, tasks, tokens, cursors — never shareable). Named here so
# `create_all` is always called with an explicit table list: a shared
# MetaData would otherwise create every table in every file, and the
# mis-binding would be silent instead of an error.
MEMORY_TABLE_NAMES = (
    "blobs",
    "blob_sentences",
    "email_blobs",
    "calendar_blobs",
    "whatsapp_blobs",
    "person_identifiers",
    # the store's own tables (M2): its meta row, merge history, blob aliases
    "memory_meta",
    "fact_history",
    "blob_aliases",
)


def _tables(names: tuple[str, ...] | None, *, exclude: bool = False):
    from zylch.storage.models import Base as _Base

    if names is None:
        return list(_Base.metadata.sorted_tables)
    wanted = set(names)
    return [tbl for tbl in _Base.metadata.sorted_tables if (tbl.name in wanted) != exclude]


def profile_tables():
    """Tables that live in the per-profile ``zylch.db``."""
    return _tables(MEMORY_TABLE_NAMES, exclude=True)


def memory_tables():
    """Tables that live in the company memory store (in ``zylch.db`` until M2)."""
    return _tables(MEMORY_TABLE_NAMES)


# Versioned, run-once steps for the profile database, in order. Milestones
# append here; the ensure passes below are not steps because they are
# idempotent and cheap enough to run on every boot.
PROFILE_STEPS: list = []


def _register_profile_steps() -> None:
    from zylch.storage.step_company_key import STEP as company_key_step
    from zylch.storage.step_memory_split import STEP as memory_split_step

    for step in (company_key_step, memory_split_step):
        if step not in PROFILE_STEPS:
            PROFILE_STEPS.append(step)


def _ensure_all_tables(engine: Engine) -> None:
    """``create_all`` for the tables the PROFILE file owns — under the lock.

    The memory tables are created on the company store by
    ``memory.store.prepare_store``; an explicit ``tables=`` list here is
    what keeps a shared MetaData from silently creating them in both files.
    """
    from zylch.storage.models import Base as _Base

    _Base.metadata.create_all(engine, tables=profile_tables())


def init_db():
    """Bring the database to the current schema as its single owner.

    Delegates to :mod:`zylch.storage.migrations`: takes the file's migration
    lock (blocking, bounded), runs the ensure passes (``create_all`` with an
    explicit table list, the column list, indexes), applies any pending
    versioned step exactly once, then the idempotent data backfills. A
    process that returns from here never serves against a half-migrated
    file, because it could not get past the lock while another was writing.
    """
    from zylch.storage.migrations import run_migrations

    _register_profile_steps()
    engine = get_engine()
    applied = run_migrations(
        engine,
        _resolve_db_path(),
        ensure=(_ensure_all_tables, _apply_column_migrations),
        steps=PROFILE_STEPS,
        backfills=(_apply_data_backfills,),
    )
    if applied:
        logger.info(f"Database migrated ({', '.join(applied)}) at {_resolve_db_path()}")
    # The split step attaches the store while it runs; every other boot
    # attaches it here, after the profile lock is released (profile lock
    # first, then the store's — never the other way round).
    if current_memory_engine() is None:
        attach_memory_store(migrating=False)
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
        # 2026-05-06 (Fase 3.2): semantic channel ('email', 'phone',
        # 'calendar', 'whatsapp'). NULL means "unknown" and is
        # treated as 'email' by the UI filter for backward compat.
        ("task_items", "channel", "TEXT"),
        # 2026-05-13 (whatsapp-pipeline-parity Fase 3a): phone identifier
        # for WhatsApp-trigger tasks. F8 dedup clusters on
        # contact_email OR contact_phone; F4 reanalyze uses it as
        # contact key when contact_email is empty. NULL on existing
        # email/phone/calendar tasks; populated by task_creation when
        # event_type == 'whatsapp'.
        ("task_items", "contact_phone", "TEXT"),
        # 2026-05-20: short LLM-generated task title (TASK_DECISION_TOOL).
        # NULL on tasks created before this column; renderer falls back to
        # contact_name / contact_email.
        ("task_items", "title", "TEXT"),
        # 2026-05-20: WhatsApp voice-note transcription. `media_path` is
        # stamped at event time when audio bytes are downloaded;
        # `transcription` is filled later in batch by the update pipeline.
        # (`media_type` already exists in the model/schema.)
        ("whatsapp_messages", "transcription", "TEXT"),
        ("whatsapp_messages", "media_path", "TEXT"),
        # 2026-08-01: audit column naming WHO closed a task — a stable
        # machine token ('human', 'f4.reanalyze', 'dedup.topic', …).
        # Every `complete_task_item` call site must declare one; NULL
        # only on rows closed before this column existed.
        ("task_items", "close_actor", "TEXT"),
        # 2026-08-01: act-at timestamp (epoch seconds, UTC) — the
        # "call me back in N days" primitive written by `tasks.snooze`.
        # NULL means "actionable now", so an ALTER on an existing table
        # leaves every current task exactly where it was.
        ("task_items", "due_at", "REAL"),
        # 2026-09-08 (shared company memory, M1): the company key on every
        # memory row. Nullable so reverted code can still insert; stamped on
        # existing rows by migration step 0001_company_key.
        ("blobs", "company_key", "TEXT"),
        ("blob_sentences", "company_key", "TEXT"),
        ("email_blobs", "company_key", "TEXT"),
        ("calendar_blobs", "company_key", "TEXT"),
        ("whatsapp_blobs", "company_key", "TEXT"),
        ("person_identifiers", "company_key", "TEXT"),
    ]
    # Indexes the SQLAlchemy `index=True` declaration creates on FRESH
    # tables but never gets back-applied to tables that pre-date the
    # column add. `create_all` runs BEFORE this migration and does not
    # touch existing tables, so post-migration we CREATE INDEX IF NOT
    # EXISTS to make `index=True` truthful on legacy DBs. (Same name
    # convention SQLAlchemy uses: `ix_<table>_<column>`.)
    indexes = [
        ("task_items", "channel"),
        ("task_items", "contact_phone"),
        ("blobs", "company_key"),
        ("blob_sentences", "company_key"),
        ("email_blobs", "company_key"),
        ("calendar_blobs", "company_key"),
        ("whatsapp_blobs", "company_key"),
        ("person_identifiers", "company_key"),
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
        # This ensure pass runs on BOTH files (profile and company store),
        # each holding its own subset of tables; an index on a table that
        # lives in the other file is not a failure, it is the other file's.
        present = {
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, column in indexes:
            if table not in present:
                continue
            idx_name = f"ix_{table}_{column}"
            try:
                conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})")
            except Exception as e:
                logger.warning(f"[migrate] Failed to ensure index {idx_name}: {e}")


def _apply_data_backfills() -> None:
    """Row-level, idempotent data backfills for shape changes.

    Runs inside a single transactional session. Each backfill must be
    idempotent: re-running on an already-migrated DB must be a no-op.
    """
    _backfill_task_thread_id()

    # 2026-05-06: email_blobs / calendar_blobs association tables (Fase 3.1).
    # Existing installations have populated `blobs.events` strings of
    # the form "Extracted from email <uuid> (<datetime>)" but no
    # entries in the new index. Reconstruct it once on first boot
    # post-3.1; idempotent via INSERT OR IGNORE on the composite PK.
    _backfill_email_blobs_index()

    # 2026-05-06 (Fase 3.2): backfill task_items.channel for tasks
    # created before the column existed. Idempotent — only tasks with
    # NULL channel are touched.
    _backfill_task_channels()


def _backfill_task_thread_id() -> None:
    """2026-04-17: TaskItem.sources.thread_id — the desktop "Open" button
    on the Tasks view needs sources.thread_id to activate the Email
    tab. Tasks created before task_creation.py started storing
    thread_id in sources have {"emails": [...], "blobs": [...],
    "calendar_events": [...]} with no thread_id. Derive thread_id
    from Email rows via sources.emails[0].
    """
    # NOTE: this used to live inline in _apply_data_backfills with an
    # `if not needs_lookup: return` early-out. That `return` short-circuited
    # the whole `_apply_data_backfills` body — the new Fase 3.1 / 3.2
    # backfills appended below were silently skipped on every install
    # whose tasks already had thread_id (i.e. all current installs).
    # Lifting it into its own function makes the early-out local.
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

    from zylch.cli.utils import get_owner_id
    from zylch.memory.company_key import current_company_key
    from zylch.storage.models import Blob, CalendarBlob, CalendarEvent, Email, EmailBlob

    owner_id = get_owner_id()
    company_key = current_company_key()
    factory = get_session_factory()
    session = factory()
    try:
        # Per-profile guard: under a shared store "the index is populated"
        # must mean populated FOR THIS PROFILE'S MAIL, or only whichever
        # profile boots first is ever backfilled. Provenance says who wrote
        # a link, so the guard is on the writer, not on the table.
        existing_links = (
            session.query(EmailBlob.email_id)
            .filter(EmailBlob.owner_id == owner_id)
            .limit(1)
            .first()
        )
        blob_scan = session.query(Blob)
        if company_key:
            blob_scan = blob_scan.filter(Blob.company_key == company_key)
        any_blobs = blob_scan.with_entities(Blob.id).limit(1).first()
        if existing_links is not None:
            return  # already populated for this profile
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
        # The company's blobs, joined against THIS profile's mail (the
        # `email_ids` set above is per-profile); the link rows carry the
        # indexing profile as provenance, not the blob's contributor.
        for blob in blob_scan.all():
            blob_id = str(blob.id)
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


def _backfill_task_channels() -> None:
    """Stamp ``task_items.channel`` for legacy tasks (Fase 3.2).

    Walks rows where channel IS NULL, computes the value via
    ``Storage._infer_task_channel`` (same rule used by new inserts),
    and updates in place. Touches only tasks that need it, so it's
    cheap on already-migrated DBs.
    """
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import _infer_task_channel

    factory = get_session_factory()
    session = factory()
    try:
        rows = session.query(TaskItem).filter(TaskItem.channel.is_(None)).all()
        if not rows:
            return
        n = 0
        for t in rows:
            ch = _infer_task_channel(contact_email=t.contact_email or "", event_type=t.event_type)
            if ch:
                t.channel = ch
                n += 1
        if n:
            session.commit()
            logger.info(f"[backfill] stamped channel on {n} task(s)")
        else:
            session.rollback()
    except Exception as e:
        session.rollback()
        logger.warning(f"[backfill] task_items.channel backfill failed: {e}")
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose both engines and reset singletons. Used in tests."""
    global _engine, _session_factory, _memory_engine, _memory_reason
    if _engine is not None:
        _engine.dispose()
        _engine = None
    if _memory_engine is not None:
        try:
            _memory_engine.dispose()
        except Exception:
            pass
        _memory_engine = None
    _memory_reason = "memory store not attached yet"
    _session_factory = None
    logger.info("SQLAlchemy engine disposed")
