"""Per-folder IMAP sync cursor: UIDVALIDITY + highest confirmed UID.

Why this exists
---------------
Email sync used to derive its floor from *stored content* — the newest
row in the ``emails`` table minus one day, queried at day granularity.
That is a ratchet, not a cursor: one newer message permanently hides
anything older that was never ingested, and the archive can never
notice the hole. A message that arrived on 2026-07-29 was invisible for
three days while the daemon "successfully" synced every five minutes.

A cursor fixes the direction of trust. The floor is no longer "what we
happen to hold" but "what we have *confirmed* we ingested", stored
per (owner, folder) with the folder's UIDVALIDITY so a server-side
renumbering is detected instead of silently mis-read.

Contract
--------
``last_uid`` means: **no message in this folder with UID <= last_uid
needs to be examined again.** It advances only up to the last UID for
which every lower candidate UID was either stored or already present in
the archive. A failed SEARCH, a failed FETCH, or a failed store keeps
the cursor where it is, so the next run re-examines the same range.

``uidvalidity`` is the folder's UIDVALIDITY at the time ``last_uid``
was written. If the server reports a different value, the UID space was
renumbered and every stored UID is meaningless: the row is dropped
(loudly) and the folder falls back to the date-derived floor once, which
re-seeds the cursor.

Seeding: the ``emails`` table has no UID column, so a folder's highest
already-ingested UID is NOT recoverable from the archive. The first run
for a folder therefore falls back ONCE to the date-derived floor (newest
stored email minus the overlap window), and the cursor takes over from
the next run onwards.

Failure policy
--------------
Both directions degrade *conservatively* — towards re-scanning, never
towards skipping — but never silently:

- a read failure logs ERROR and returns ``None`` ("no cursor" -> the
  caller re-seeds from the date floor, i.e. a wider scan);
- a write failure logs ERROR and does not raise. The emails are already
  stored at that point (an irreversible side effect); raising would turn
  a bookkeeping problem into a pipeline abort. The cursor simply stays
  behind and the next run re-examines the same UIDs, which dedup makes
  harmless.

Schema ownership
----------------
This module owns its table end to end via idempotent
``CREATE TABLE IF NOT EXISTS`` against the same SQLite file the rest of
the engine uses. It deliberately does not register an ORM model or an
entry in ``zylch.storage.database``'s migration list.

No LLM anywhere near this module.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

TABLE_NAME = "email_sync_cursor"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    owner_id       TEXT    NOT NULL,
    folder         TEXT    NOT NULL,
    uidvalidity    INTEGER NOT NULL,
    last_uid       INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    PRIMARY KEY (owner_id, folder)
)
"""

# Default overlap window, in days. Deliberately far wider than the
# 1-day window the old date-derived floor used: it is the backstop that
# self-heals a folder whose cursor is behind reality (transition run,
# a server that renumbers, a message that landed with a lower UID than
# one we already passed). Override per profile with
# EMAIL_SYNC_OVERLAP_DAYS in the profile .env (load_dotenv puts profile
# .env values in os.environ at startup). Kept as an env read rather
# than a Settings field so this module owns its own configuration; the
# name matches pydantic-settings conventions if it is ever promoted.
DEFAULT_OVERLAP_DAYS = 7
OVERLAP_DAYS_ENV = "EMAIL_SYNC_OVERLAP_DAYS"


@dataclass(frozen=True)
class FolderCursor:
    """A single (owner, folder) sync position."""

    owner_id: str
    folder: str
    uidvalidity: int
    last_uid: int
    last_synced_at: str
    updated_at: str


def overlap_days() -> int:
    """Overlap window in days, from env with a safe default.

    A non-numeric or non-positive value is a configuration mistake, not
    a reason to disable the backstop: log a warning and use the default.
    """
    raw = os.environ.get(OVERLAP_DAYS_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_OVERLAP_DAYS
    try:
        value = int(str(raw).strip())
    except ValueError:
        logger.warning(
            f"[sync-cursor] {OVERLAP_DAYS_ENV}={raw!r} is not an integer; "
            f"using default {DEFAULT_OVERLAP_DAYS}"
        )
        return DEFAULT_OVERLAP_DAYS
    if value <= 0:
        logger.warning(
            f"[sync-cursor] {OVERLAP_DAYS_ENV}={value} must be > 0; "
            f"using default {DEFAULT_OVERLAP_DAYS}"
        )
        return DEFAULT_OVERLAP_DAYS
    return value


def normalize_folder(folder: str) -> str:
    """Canonical storage key for an IMAP folder name.

    IMAP folder names reach us quoted (``'"[Gmail]/All Mail"'``) because
    that is what SELECT needs. The cursor must key on the same folder
    whether or not the discovery path quoted it, so the stored key is
    always the unquoted name.
    """
    name = (folder or "").strip()
    if len(name) >= 2 and name.startswith('"') and name.endswith('"'):
        name = name[1:-1]
    return name


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(conn) -> None:
    """Create the cursor table if missing. Idempotent, cheap."""
    conn.exec_driver_sql(_CREATE_TABLE_SQL)


def get_cursor(owner_id: str, folder: str) -> Optional[FolderCursor]:
    """Return the stored cursor for ``(owner_id, folder)``, or ``None``.

    ``None`` means "no confirmed position" and the caller must fall back
    to the date-derived floor. A read failure returns ``None`` too — the
    conservative direction — but logs ERROR rather than passing silently.
    """
    key = normalize_folder(folder)
    try:
        from zylch.storage.database import get_engine

        with get_engine().begin() as conn:
            _ensure_schema(conn)
            row = conn.exec_driver_sql(
                f"SELECT owner_id, folder, uidvalidity, last_uid, last_synced_at, updated_at "
                f"FROM {TABLE_NAME} WHERE owner_id = ? AND folder = ?",
                (owner_id, key),
            ).fetchone()
    except Exception as e:
        logger.error(
            f"[sync-cursor] get_cursor(owner_id={owner_id}, folder={key}) failed: {e} "
            f"-> treating as NO CURSOR (folder will re-seed from the date floor)",
            exc_info=True,
        )
        return None

    if row is None:
        logger.debug(f"[sync-cursor] get_cursor(owner_id={owner_id}, folder={key}) -> None")
        return None

    cursor = FolderCursor(
        owner_id=row[0],
        folder=row[1],
        uidvalidity=int(row[2]),
        last_uid=int(row[3]),
        last_synced_at=row[4],
        updated_at=row[5],
    )
    logger.debug(
        f"[sync-cursor] get_cursor(owner_id={owner_id}, folder={key}) -> "
        f"uidvalidity={cursor.uidvalidity} last_uid={cursor.last_uid}"
    )
    return cursor


def set_cursor(owner_id: str, folder: str, uidvalidity: int, last_uid: int) -> bool:
    """Upsert the confirmed position for ``(owner_id, folder)``.

    Returns True when the row was written. A failure logs ERROR and
    returns False without raising: callers reach this point *after*
    storing emails, and a bookkeeping failure must not undo or abort
    work that already succeeded. The cost of a failed write is a
    repeated (deduplicated) scan on the next run.
    """
    key = normalize_folder(folder)
    now = _now_iso()
    try:
        from zylch.storage.database import get_engine

        with get_engine().begin() as conn:
            _ensure_schema(conn)
            conn.exec_driver_sql(
                f"INSERT INTO {TABLE_NAME} "
                f"(owner_id, folder, uidvalidity, last_uid, last_synced_at, updated_at) "
                f"VALUES (?, ?, ?, ?, ?, ?) "
                f"ON CONFLICT(owner_id, folder) DO UPDATE SET "
                f"uidvalidity = excluded.uidvalidity, "
                f"last_uid = excluded.last_uid, "
                f"last_synced_at = excluded.last_synced_at, "
                f"updated_at = excluded.updated_at",
                (owner_id, key, int(uidvalidity), int(last_uid), now, now),
            )
    except Exception as e:
        logger.error(
            f"[sync-cursor] set_cursor(owner_id={owner_id}, folder={key}, "
            f"uidvalidity={uidvalidity}, last_uid={last_uid}) FAILED: {e} "
            f"-> cursor stays behind; next run re-examines the same UIDs",
            exc_info=True,
        )
        return False

    logger.debug(
        f"[sync-cursor] set_cursor(owner_id={owner_id}, folder={key}) -> "
        f"uidvalidity={uidvalidity} last_uid={last_uid}"
    )
    return True


def drop_cursor(owner_id: str, folder: str) -> bool:
    """Delete the cursor for ``(owner_id, folder)``.

    Used when UIDVALIDITY changes: every stored UID for that folder is
    meaningless and keeping it would silently skip mail. Returns True on
    success; a failure logs ERROR and returns False.
    """
    key = normalize_folder(folder)
    try:
        from zylch.storage.database import get_engine

        with get_engine().begin() as conn:
            _ensure_schema(conn)
            conn.exec_driver_sql(
                f"DELETE FROM {TABLE_NAME} WHERE owner_id = ? AND folder = ?",
                (owner_id, key),
            )
    except Exception as e:
        logger.error(
            f"[sync-cursor] drop_cursor(owner_id={owner_id}, folder={key}) FAILED: {e}",
            exc_info=True,
        )
        return False

    logger.info(f"[sync-cursor] drop_cursor(owner_id={owner_id}, folder={key}) -> deleted")
    return True


def list_cursors(owner_id: str) -> list:
    """All cursors for an owner, newest-written first. Diagnostics only."""
    try:
        from zylch.storage.database import get_engine

        with get_engine().begin() as conn:
            _ensure_schema(conn)
            rows = conn.exec_driver_sql(
                f"SELECT owner_id, folder, uidvalidity, last_uid, last_synced_at, updated_at "
                f"FROM {TABLE_NAME} WHERE owner_id = ? ORDER BY updated_at DESC",
                (owner_id,),
            ).fetchall()
    except Exception as e:
        logger.error(f"[sync-cursor] list_cursors(owner_id={owner_id}) failed: {e}")
        return []

    return [
        FolderCursor(
            owner_id=r[0],
            folder=r[1],
            uidvalidity=int(r[2]),
            last_uid=int(r[3]),
            last_synced_at=r[4],
            updated_at=r[5],
        )
        for r in rows
    ]
