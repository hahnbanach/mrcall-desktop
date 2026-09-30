"""Profile-store step ``0003_emails_mailbox``: every mail row names its mailbox.

Before this step a profile had one mailbox and ``emails`` was unique on
``(owner_id, gmail_id)``; on the IMAP path ``gmail_id`` is the RFC 5322
Message-ID, so a second mailbox receiving the same message could not be
stored. After it:

1. ``mailboxes`` exists, with one row per distinct ``emails.owner_id`` plus
   the profile's current ``EMAIL_ADDRESS``. The row of the current address
   is primary and active (its password stays in ``.env``, ``secret`` NULL).
   Every other owner (a former address, or ``local-user`` for a profile
   that once had no address) gets a hidden row, ``removed_at`` set, so its
   rows stay invisible as they were; a profile whose current owner IS
   ``local-user`` keeps that row active, so its rows stay visible. With no
   ``EMAIL_ADDRESS`` there is no primary row.
2. ``emails`` is rebuilt in the current model shape — ``mailbox_id`` NOT
   NULL, ``original_message_id``, ``pec_markers``, unique on
   ``(owner_id, mailbox_id, gmail_id)`` — every row keeping its ``id`` and
   stamped with the mailbox row of its ``owner_id``; its indexes are
   recreated.
3. The sync cursor table moves to ``email_sync_cursor_v2`` keyed
   ``(owner_id, mailbox_id, folder)``; a cursor whose owner has a mailbox
   row follows it, any other is dropped (the folder re-seeds from the
   date floor, the conservative direction).

SQLite cannot alter a constraint in place, hence the rebuild (create the
new shape, copy, drop, rename, recreate indexes) inside the step's
transaction, on the ``step_identifiers_company_unique`` template.
Idempotent: a file already in the new shape is left alone, and existing
mailbox rows are reused, never duplicated.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import Connection

from zylch.email.mailboxes import env_hosts, env_primary_address, runtime_owner_id
from zylch.email.sync_cursor import CREATE_TABLE_SQL as CURSOR_V2_DDL
from zylch.email.sync_cursor import LEGACY_TABLE_NAME as CURSOR_V1
from zylch.email.sync_cursor import TABLE_NAME as CURSOR_V2
from zylch.storage.migrations import MigrationStep

logger = logging.getLogger(__name__)

STEP_ID = "0003_emails_mailbox"
NEW_CONSTRAINT = "emails_owner_mailbox_gmail_unique"

# Frozen copy of the model's DDL at the time of this step (generated from
# ``CreateTable(Email.__table__)`` on the SQLite dialect). Later column adds
# go through the column ensure pass, not here.
EMAILS_NEW_DDL = f"""
CREATE TABLE emails_new (
    id VARCHAR(36) NOT NULL,
    owner_id TEXT NOT NULL,
    mailbox_id VARCHAR(36) NOT NULL,
    gmail_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    from_email TEXT,
    from_name TEXT,
    to_email TEXT,
    cc_email TEXT,
    subject TEXT,
    date DATETIME NOT NULL,
    date_timestamp INTEGER,
    snippet TEXT,
    body_plain TEXT,
    body_html TEXT,
    labels TEXT,
    message_id_header TEXT,
    in_reply_to TEXT,
    "references" TEXT,
    created_at DATETIME,
    updated_at DATETIME,
    read_events JSON,
    memory_processed_at DATETIME,
    embedding BLOB,
    task_processed_at DATETIME,
    is_auto_reply BOOLEAN,
    has_attachments BOOLEAN NOT NULL,
    attachment_filenames JSON,
    pinned_at DATETIME,
    read_at DATETIME,
    archived_at DATETIME,
    deleted_at DATETIME,
    original_message_id TEXT,
    pec_markers JSON,
    PRIMARY KEY (id),
    CONSTRAINT {NEW_CONSTRAINT} UNIQUE (owner_id, mailbox_id, gmail_id)
)
"""

EMAILS_COLUMNS = (
    "id",
    "owner_id",
    "mailbox_id",
    "gmail_id",
    "thread_id",
    "from_email",
    "from_name",
    "to_email",
    "cc_email",
    "subject",
    "date",
    "date_timestamp",
    "snippet",
    "body_plain",
    "body_html",
    "labels",
    "message_id_header",
    "in_reply_to",
    "references",
    "created_at",
    "updated_at",
    "read_events",
    "memory_processed_at",
    "embedding",
    "task_processed_at",
    "is_auto_reply",
    "has_attachments",
    "attachment_filenames",
    "pinned_at",
    "read_at",
    "archived_at",
    "deleted_at",
    "original_message_id",
    "pec_markers",
)

EMAILS_INDEXES = (
    "owner_id",
    "mailbox_id",
    "has_attachments",
    "pinned_at",
    "read_at",
    "archived_at",
    "deleted_at",
)

MAILBOXES_DDL = """
CREATE TABLE IF NOT EXISTS mailboxes (
    id VARCHAR(36) NOT NULL,
    owner_id TEXT NOT NULL,
    address TEXT NOT NULL,
    imap_host TEXT,
    imap_port INTEGER,
    smtp_host TEXT,
    smtp_port INTEGER,
    preset TEXT,
    is_primary BOOLEAN NOT NULL,
    secret TEXT,
    created_at DATETIME,
    last_sync_at DATETIME,
    last_error TEXT,
    removed_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT mailboxes_owner_address_unique UNIQUE (owner_id, address)
)
"""


def _tables(conn: Connection) -> set[str]:
    return {
        r[0]
        for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _columns(conn: Connection, table: str) -> list[str]:
    return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]


def _has_new_shape(conn: Connection) -> bool:
    rows = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='emails'"
    ).fetchall()
    return (
        bool(rows)
        and NEW_CONSTRAINT in (rows[0][0] or "")
        and "mailbox_id" in _columns(conn, "emails")
    )


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")


def _ensure_owner_row(conn: Connection, owner: str, *, primary: bool, active: bool) -> str:
    """The mailbox row of ``owner`` (address == owner), created when missing.

    An existing row is reused; only the primary flag is enforced on it, so
    a re-run never hides a row the first run left active.
    """
    row = conn.exec_driver_sql(
        "SELECT id FROM mailboxes WHERE owner_id = ? AND address = ? LIMIT 1", (owner, owner)
    ).fetchone()
    if row:
        if primary:
            conn.exec_driver_sql(
                "UPDATE mailboxes SET is_primary = 1, removed_at = NULL WHERE id = ?", (row[0],)
            )
        return row[0]
    hosts = env_hosts() if primary else {}
    mailbox_id = str(uuid.uuid4())
    now = _now()
    conn.exec_driver_sql(
        "INSERT INTO mailboxes (id, owner_id, address, imap_host, imap_port, smtp_host, "
        "smtp_port, preset, is_primary, secret, created_at, last_sync_at, last_error, removed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, NULL, NULL, ?)",
        (
            mailbox_id,
            owner,
            owner,
            hosts.get("imap_host"),
            hosts.get("imap_port"),
            hosts.get("smtp_host"),
            hosts.get("smtp_port"),
            1 if primary else 0,
            now,
            None if active else now,
        ),
    )
    return mailbox_id


def _rebuild_emails(conn: Connection) -> tuple[int, int]:
    old_cols = set(_columns(conn, "emails"))
    copy_cols = [c for c in EMAILS_COLUMNS if c in old_cols and c != "mailbox_id"]
    targets = ", ".join(f'"{c}"' for c in copy_cols)
    sources = ", ".join(
        'COALESCE("has_attachments", 0)' if c == "has_attachments" else f'e."{c}"'
        for c in copy_cols
    )
    conn.exec_driver_sql("DROP TABLE IF EXISTS emails_new")
    conn.exec_driver_sql(EMAILS_NEW_DDL)
    before = conn.exec_driver_sql("SELECT COUNT(*) FROM emails").scalar_one()
    # A NULL here (an owner with no mailbox row) violates NOT NULL and rolls
    # the whole step back — loud, never a half-stamped table.
    res = conn.exec_driver_sql(
        f"INSERT INTO emails_new ({targets}, mailbox_id) SELECT {sources}, "
        "(SELECT m.id FROM mailboxes m WHERE m.owner_id = e.owner_id AND m.address = e.owner_id "
        "ORDER BY m.is_primary DESC, m.created_at LIMIT 1) FROM emails e"
    )
    conn.exec_driver_sql("DROP TABLE emails")
    conn.exec_driver_sql("ALTER TABLE emails_new RENAME TO emails")
    for col in EMAILS_INDEXES:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS ix_emails_{col} ON emails ({col})")
    return before, res.rowcount


def _migrate_cursors(conn: Connection) -> tuple[int, int]:
    # The cursor module creates its table lazily on first use; a fresh file
    # keeps that (no v2 table until a sync runs) — only legacy rows force it.
    if CURSOR_V1 not in _tables(conn):
        return 0, 0
    conn.exec_driver_sql(CURSOR_V2_DDL)
    before = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {CURSOR_V1}").scalar_one()
    res = conn.exec_driver_sql(
        f"INSERT OR IGNORE INTO {CURSOR_V2} "
        "(owner_id, mailbox_id, folder, uidvalidity, last_uid, last_synced_at, updated_at) "
        "SELECT c.owner_id, m.id, c.folder, c.uidvalidity, c.last_uid, c.last_synced_at, "
        f"c.updated_at FROM {CURSOR_V1} c JOIN mailboxes m "
        "ON m.owner_id = c.owner_id AND m.address = c.owner_id"
    )
    conn.exec_driver_sql(f"DROP TABLE {CURSOR_V1}")
    return before, res.rowcount


def apply(conn: Connection) -> None:
    conn.exec_driver_sql(MAILBOXES_DDL)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_mailboxes_owner_id ON mailboxes (owner_id)")
    present = _tables(conn)

    # Exactly the runtime's notion of owner (``get_owner_id``): the raw
    # EMAIL_ADDRESS when the key is present — whitespace and an empty string
    # included — and ``local-user`` when it is absent. Only a NULL owner_id
    # is skipped; an empty one is a real owner the runtime once wrote.
    current = env_primary_address()
    current_owner = runtime_owner_id()
    owners: set[str] = set()
    if "emails" in present:
        owners = {
            r[0]
            for r in conn.exec_driver_sql("SELECT DISTINCT owner_id FROM emails").fetchall()
            if r[0] is not None
        }
    if current is not None:
        owners.add(current)
    for owner in sorted(owners):
        _ensure_owner_row(conn, owner, primary=(owner == current), active=(owner == current_owner))

    if "emails" in present and not _has_new_shape(conn):
        before, after = _rebuild_emails(conn)
        logger.info(f"[migrate] {STEP_ID}: rebuilt emails per mailbox ({before} rows -> {after})")
    else:
        logger.info(f"[migrate] {STEP_ID}: emails already per mailbox, nothing to rebuild")

    before, after = _migrate_cursors(conn)
    if before:
        logger.info(f"[migrate] {STEP_ID}: sync cursors -> v2 ({before} rows -> {after})")
    logger.info(
        f"[migrate] {STEP_ID}: mailbox rows for {len(owners)} owner(s), "
        f"primary={'present' if current else 'none'}"
    )


STEP = MigrationStep(
    id=STEP_ID,
    apply=apply,
    destructive=True,
    description="emails per mailbox: mailboxes table, mailbox_id stamped, cursors keyed by mailbox",
)
