"""One memory store per company: where it lives, who may create it, how it opens.

Under SQLite the company key selects a file — ``<memory dir>/<key>.db`` —
on a host where every profile engine runs as the same system user, so the
wall between two companies' stores is the key's secrecy plus the host's
own isolation (the product brief accepts this; a server that verifies the
key is where the capability becomes complete).

**Creation is a privilege of provenance, not of novelty.** Three paths may
create a store, and each is vouched for by something the host already
holds: the engine minted the key (``MEMORY_KEY_SOURCE=mint``), the
profile's own database is pre-split and its rows carry the key
(migration), or the host's mapping table named the key for this uid
(``provision``). A key a human typed — the onboarding paste, the Settings
join — opens an existing store or nothing: an unknown typed key must never
silently become a fresh empty memory. ``open_memory_engine(create=False)``
is that rule.

The store's own engine owns its transaction boundaries (pysqlite
``isolation_level=None`` plus a ``begin`` listener that emits ``BEGIN`` —
SQLAlchemy's default emits none where one is needed). Transactions are
DEFERRED so N daemons' readers share the file under WAL; the one place
that must serialize — the compare-and-swap in ``BlobStorage.update_blob``
— upgrades to the write lock with a no-op write as its first statement,
so its read, check and write happen under one lock without every search
on the store queueing behind it. ``busy_timeout`` is the retry budget.

Memory can be *unavailable* — no key, an unknown typed key, a missing
file. That is never a unit failure: the daemons also carry mail sync, and
taking mail down to reject a memory key would be a far larger outage than
the fault. Instead the memory tables are bound to :func:`refused_engine`,
whose every connection raises :class:`MemoryUnavailable` with the reason,
and ``memory.status`` reports it over RPC.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from zylch.storage.migrations import run_migrations

logger = logging.getLogger(__name__)

MEMORY_DIRNAME = "memory"
VOUCHED_SOURCES = ("mint", "migration", "provision")
SOURCE_SETTING = "MEMORY_KEY_SOURCE"


class MemoryUnavailable(RuntimeError):
    """Memory is disabled for this profile; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ─── Location ────────────────────────────────────────────────


def memory_dir() -> str:
    """``$MEMORY_DB_DIR`` or ``~/.zylch/memory`` — one directory per host."""
    override = os.environ.get("MEMORY_DB_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~/.zylch"), MEMORY_DIRNAME)


def memory_db_path(company_key: str) -> str:
    return os.path.join(memory_dir(), f"{company_key}.db")


def store_exists(company_key: str) -> bool:
    return os.path.isfile(memory_db_path(company_key))


def key_source() -> Optional[str]:
    """How this profile came by its key: mint | provision | join | None."""
    value = os.environ.get(SOURCE_SETTING, "").strip()
    return value or None


def source_is_vouched(source: Optional[str]) -> bool:
    return source in VOUCHED_SOURCES


# ─── Engines ─────────────────────────────────────────────────


def _install_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn, _record):
        # Let SQLAlchemy own transaction boundaries so the `begin` listener
        # below can open every transaction as IMMEDIATE.
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")


def open_memory_engine(company_key: str, *, create: bool) -> Engine:
    """An engine on the company's store.

    ``create=False`` is the typed-key rule: a missing file raises
    :class:`MemoryUnavailable` and nothing is written to disk.
    """
    path = memory_db_path(company_key)
    if not os.path.isfile(path):
        if not create:
            raise MemoryUnavailable("no company memory store exists for this key on this host")
        os.makedirs(memory_dir(), mode=0o700, exist_ok=True)
        logger.info("[memory] creating a new company store")
    engine = create_engine(f"sqlite:///{path}", echo=False)
    _install_pragmas(engine)
    return engine


def refused_engine(reason: str) -> Engine:
    """An engine that refuses every connection with ``reason``.

    Bound to the memory tables when memory is unavailable, so a memory
    call fails loudly at the first statement instead of reading an empty
    scratch database as if it were the company's knowledge.
    """
    engine = create_engine("sqlite://", echo=False)

    @event.listens_for(engine, "connect")
    def _refuse(_dbapi_conn, _record):
        raise MemoryUnavailable(reason)

    return engine


# ─── Schema on the store ─────────────────────────────────────


def _memory_tables():
    from zylch.storage.database import memory_tables

    return memory_tables()


def _ensure_memory_tables(engine: Engine) -> None:
    from zylch.storage.models import Base

    Base.metadata.create_all(engine, tables=_memory_tables())


def _ensure_memory_columns(engine: Engine) -> None:
    # The same ensure list the profile DB uses; it skips tables absent here.
    from zylch.storage.database import _apply_column_migrations

    _apply_column_migrations(engine)


def prepare_store(engine: Engine, company_key: str, *, created_by: Optional[str]) -> None:
    """Bring a store to the current schema as its single owner.

    Runs the memory-side runner under ``<store>.migrate.lock`` — taken
    AFTER the profile lock whenever both are held, never before, which is
    what keeps two engines migrating both files from deadlocking.
    """
    path = memory_db_path(company_key)

    def _meta(_engine: Engine) -> None:
        ensure_meta_row(_engine, company_key, created_by=created_by)

    from zylch.storage.step_identifiers_company_unique import STEP as identifiers_step

    run_migrations(
        engine,
        path,
        ensure=(_ensure_memory_tables, _ensure_memory_columns, _meta),
        steps=(identifiers_step,),
    )


# ─── memory_meta: the store's own row ────────────────────────


def ensure_meta_row(engine: Engine, company_key: str, *, created_by: Optional[str]) -> None:
    seed = (os.environ.get("USER_COMPANY") or "").strip() or None
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM memory_meta LIMIT 1")).first()
        if exists:
            return
        conn.execute(
            text(
                "INSERT INTO memory_meta (id, company_key, self_notion, mutation_seq, "
                "last_sweep_seq, created_by_source) VALUES (1, :key, :notion, 0, 0, :src)"
            ),
            {"key": company_key, "notion": seed, "src": created_by},
        )
    logger.info(f"[memory] store meta row created (self_notion={'set' if seed else 'unset'})")


def get_meta(engine: Engine) -> Dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT company_key, self_notion, mutation_seq, created_by_source, created_at, "
                "last_sweep_seq FROM memory_meta WHERE id = 1"
            )
        ).first()
    if row is None:
        return {
            "self_notion": None,
            "mutation_seq": 0,
            "created_by_source": None,
            "last_sweep_seq": 0,
        }
    return {
        "company_key": row[0],
        "self_notion": row[1],
        "mutation_seq": int(row[2] or 0),
        "created_by_source": row[3],
        "created_at": row[4],
        "last_sweep_seq": int(row[5] or 0),
    }


def set_self_notion(engine: Engine, notion: Optional[str]) -> None:
    value = (notion or "").strip() or None  # NULL, never the empty string
    with engine.begin() as conn:
        conn.execute(text("UPDATE memory_meta SET self_notion = :n WHERE id = 1"), {"n": value})


def bump_mutation_seq(session: Session) -> None:
    """Inside a session: tell every process on this store the index is stale.

    An ORM-enabled UPDATE, not a bare ``text()``: with per-table binds a
    statement is routed by the table it names, and a raw string names
    none — it would run against the profile file and miss.
    """
    from sqlalchemy import update

    from zylch.storage.models import MemoryMeta

    session.execute(
        update(MemoryMeta)
        .where(MemoryMeta.id == 1)
        .values(mutation_seq=MemoryMeta.mutation_seq + 1)
    )


def take_write_lock(session: Session) -> None:
    """Upgrade this transaction to the store's write lock NOW.

    A no-op UPDATE on the meta row: SQLite grants the RESERVED lock at the
    first write, so everything after it in the transaction — the read, the
    compare, the write — runs with no other writer able to interleave.
    ORM-routed so it reaches the store, not the profile file.
    """
    from sqlalchemy import update

    from zylch.storage.models import MemoryMeta

    session.execute(
        update(MemoryMeta).where(MemoryMeta.id == 1).values(mutation_seq=MemoryMeta.mutation_seq)
    )


def sweep_due(engine: Engine) -> bool:
    """Has the store changed since the last reconsolidation sweep started?"""
    meta = get_meta(engine)
    return int(meta.get("mutation_seq") or 0) != int(meta.get("last_sweep_seq") or 0)


def record_sweep_started(engine: Engine) -> None:
    """Remember the sequence this sweep starts from; its own merges bump the
    sequence, so the next tick runs one more (cheap, clusterless) pass and
    then rests."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE memory_meta SET last_sweep_seq = mutation_seq WHERE id = 1"))


def read_mutation_seq(session: Session) -> int:
    from zylch.storage.models import MemoryMeta

    value = session.query(MemoryMeta.mutation_seq).filter(MemoryMeta.id == 1).scalar()
    return int(value or 0)


def store_summary(engine: Engine) -> Dict[str, Any]:
    """What a joiner is shown before committing: size and who is in it. No paths."""
    from zylch.memory.company_key import COMPANY_FAMILIES

    with engine.begin() as conn:
        blobs = conn.execute(text("SELECT COUNT(*) FROM blobs")).scalar_one()
        facts = conn.execute(
            text("SELECT COUNT(*) FROM blobs WHERE namespace LIKE 'facts:%'")
        ).scalar_one()
        contributors = [
            r[0]
            for r in conn.execute(
                text("SELECT DISTINCT owner_id FROM blobs ORDER BY owner_id")
            ).fetchall()
        ]
    meta = get_meta(engine)
    return {
        "self_notion": meta.get("self_notion"),
        "blob_count": int(blobs),
        "fact_count": int(facts),
        "contributors": contributors,
        "families": list(COMPANY_FAMILIES),
    }
