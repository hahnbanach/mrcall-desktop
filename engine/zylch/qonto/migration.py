"""Additive profile schema with a protected SQLite backup before first installation."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import inspect

from zylch.qonto.models import TABLE_NAMES
from zylch.qonto.private_files import exclusive_write, private_directory
from zylch.storage.database import Base
from zylch.storage.migrations import MigrationStep, backup_sqlite


def backup_before_install(engine) -> None:
    names = set(inspect(engine).get_table_names())
    if "qonto_connections" in names or not names - {"schema_version"}:
        return
    directory = Path(engine.url.database).absolute().parent
    backup_dir = directory / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    private_directory(backup_dir)
    backup = Path(
        backup_sqlite(str(directory / Path(engine.url.database).name), "qonto-private-v1")
    )
    os.chmod(backup, 0o600)
    for name in (".env", "qonto.key"):
        source = directory / name
        if source.exists() and not source.is_symlink():
            exclusive_write(Path(str(backup) + "." + name.lstrip(".")), source.read_bytes())


def apply(conn) -> None:
    Base.metadata.create_all(
        conn, tables=[table for table in Base.metadata.sorted_tables if table.name in TABLE_NAMES]
    )


STEP = MigrationStep(
    id="0003_qonto_private",
    apply=apply,
    description="private profile-only Qonto connection and source tables",
)


def sync_columns(conn) -> None:
    additions = {
        "qonto_connections": {
            "sync_token": "TEXT",
            "sync_expires_at": "FLOAT",
            "last_sync_at": "FLOAT",
            "provider_retry_at": "FLOAT",
        },
        "qonto_accounts": {
            "balance_provider_at": "TEXT",
            "authorized_balance_minor": "BIGINT",
            "authorized_balance_scale": "INTEGER",
            "authorized_balance_decimal": "TEXT",
            "initial_from": "TEXT",
            "initial_to": "TEXT",
            "emitted_watermark": "TEXT",
            "updated_watermark": "TEXT",
            "pending_repair_cursor": "TEXT",
        },
        "qonto_sync_windows": {
            "observed_count": "INTEGER NOT NULL DEFAULT 0",
            "total_count": "INTEGER",
            "total_pages": "INTEGER",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "retry_at": "FLOAT",
            "purpose": "TEXT NOT NULL DEFAULT 'initial'",
        },
    }
    for table, columns in additions.items():
        present = {column["name"] for column in inspect(conn).get_columns(table)}
        for name, kind in columns.items():
            if name not in present:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


SYNC_STEP = MigrationStep(
    id="0004_qonto_source_sync",
    apply=sync_columns,
    description="bounded private Qonto source window state",
)


HISTORY_STEP = MigrationStep(
    id="0005_qonto_managed_history",
    apply=apply,
    description="private canonical finance conversations and retained evidence receipts",
)
