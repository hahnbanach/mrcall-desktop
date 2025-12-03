"""Calendar data storage with multi-tenant isolation.

Server-side storage for calendar events with owner_id isolation.
Uses SQLite for now, can migrate to PostgreSQL later.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)


class CalendarStore:
    """Server-side calendar event storage with multi-tenant isolation."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize calendar store.

        Args:
            db_path: Path to SQLite database. Defaults to cache/server_data.db
        """
        if db_path is None:
            db_path = Path(settings.cache_dir) / "server_data.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

        logger.info(f"CalendarStore initialized at {self.db_path}")

    def _ensure_tables(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                event_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                data TEXT NOT NULL,
                start_time TIMESTAMP,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, owner_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cal_owner_id ON calendar_events(owner_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cal_start_time ON calendar_events(start_time)
        """)

        conn.commit()
        conn.close()

    def save_event(
        self,
        event_id: str,
        owner_id: str,
        event_data: Dict[str, Any]
    ) -> bool:
        """Save or update calendar event.

        Args:
            event_id: Event identifier
            owner_id: Owner (Firebase UID)
            event_data: Event data dict

        Returns:
            True if successful
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            # Extract start_time for indexing
            start_time = event_data.get('start')
            if start_time and isinstance(start_time, str):
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                except:
                    start_dt = None
            else:
                start_dt = None

            cursor.execute("""
                INSERT OR REPLACE INTO calendar_events
                (event_id, owner_id, data, start_time, last_modified)
                VALUES (?, ?, ?, ?, ?)
            """, (
                event_id,
                owner_id,
                json.dumps(event_data),
                start_dt,
                datetime.now(timezone.utc)
            ))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Failed to save event {event_id}: {e}")
            conn.rollback()
            return False

        finally:
            conn.close()

    def get_event(
        self,
        event_id: str,
        owner_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get calendar event by ID.

        Args:
            event_id: Event identifier
            owner_id: Owner (Firebase UID)

        Returns:
            Event data dict or None if not found
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT data FROM calendar_events
                WHERE event_id = ? AND owner_id = ?
            """, (event_id, owner_id))

            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

        finally:
            conn.close()

    def list_events(
        self,
        owner_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List calendar events for owner.

        Args:
            owner_id: Owner (Firebase UID)
            start_date: Filter events starting after this date
            end_date: Filter events starting before this date
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of event data dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            query = """
                SELECT data FROM calendar_events
                WHERE owner_id = ?
            """
            params = [owner_id]

            if start_date:
                query += " AND start_time >= ?"
                params.append(start_date)

            if end_date:
                query += " AND start_time <= ?"
                params.append(end_date)

            query += " ORDER BY start_time ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            events = []
            for row in cursor.fetchall():
                events.append(json.loads(row[0]))

            return events

        finally:
            conn.close()

    def delete_event(
        self,
        event_id: str,
        owner_id: str
    ) -> bool:
        """Delete calendar event.

        Args:
            event_id: Event identifier
            owner_id: Owner (Firebase UID)

        Returns:
            True if deleted
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM calendar_events
                WHERE event_id = ? AND owner_id = ?
            """, (event_id, owner_id))

            conn.commit()
            return cursor.rowcount > 0

        finally:
            conn.close()

    def get_stats(self, owner_id: str) -> Dict[str, Any]:
        """Get storage statistics for owner.

        Args:
            owner_id: Owner (Firebase UID)

        Returns:
            Stats dict
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*) FROM calendar_events
                WHERE owner_id = ?
            """, (owner_id,))
            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MAX(last_modified) FROM calendar_events
                WHERE owner_id = ?
            """, (owner_id,))
            last_modified = cursor.fetchone()[0]

            return {
                "total_events": total,
                "last_modified": last_modified
            }

        finally:
            conn.close()
