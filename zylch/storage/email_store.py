"""Email data storage with multi-tenant isolation.

Server-side storage for email threads with owner_id isolation.
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


class EmailStore:
    """Server-side email thread storage with multi-tenant isolation."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize email store.

        Args:
            db_path: Path to SQLite database. Defaults to cache/server_data.db
        """
        if db_path is None:
            db_path = Path(settings.cache_dir) / "server_data.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

        logger.info(f"EmailStore initialized at {self.db_path}")

    def _ensure_tables(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_threads (
                thread_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                data TEXT NOT NULL,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, owner_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_owner_id ON email_threads(owner_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_modified ON email_threads(last_modified)
        """)

        conn.commit()
        conn.close()

    def save_thread(
        self,
        thread_id: str,
        owner_id: str,
        thread_data: Dict[str, Any]
    ) -> bool:
        """Save or update email thread.

        Args:
            thread_id: Thread identifier
            owner_id: Owner (Firebase UID)
            thread_data: Thread data dict

        Returns:
            True if successful
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO email_threads
                (thread_id, owner_id, data, last_modified)
                VALUES (?, ?, ?, ?)
            """, (
                thread_id,
                owner_id,
                json.dumps(thread_data),
                datetime.now(timezone.utc)
            ))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Failed to save thread {thread_id}: {e}")
            conn.rollback()
            return False

        finally:
            conn.close()

    def get_thread(
        self,
        thread_id: str,
        owner_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get email thread by ID.

        Args:
            thread_id: Thread identifier
            owner_id: Owner (Firebase UID)

        Returns:
            Thread data dict or None if not found
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT data FROM email_threads
                WHERE thread_id = ? AND owner_id = ?
            """, (thread_id, owner_id))

            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

        finally:
            conn.close()

    def list_threads(
        self,
        owner_id: str,
        limit: int = 100,
        offset: int = 0,
        days_back: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """List email threads for owner.

        Args:
            owner_id: Owner (Firebase UID)
            limit: Maximum results
            offset: Pagination offset
            days_back: Optional filter for recent threads

        Returns:
            List of thread data dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            query = """
                SELECT data FROM email_threads
                WHERE owner_id = ?
            """
            params = [owner_id]

            if days_back:
                from datetime import timedelta
                cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
                query += " AND last_modified >= ?"
                params.append(cutoff)

            query += " ORDER BY last_modified DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            threads = []
            for row in cursor.fetchall():
                threads.append(json.loads(row[0]))

            return threads

        finally:
            conn.close()

    def delete_thread(
        self,
        thread_id: str,
        owner_id: str
    ) -> bool:
        """Delete email thread.

        Args:
            thread_id: Thread identifier
            owner_id: Owner (Firebase UID)

        Returns:
            True if deleted
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM email_threads
                WHERE thread_id = ? AND owner_id = ?
            """, (thread_id, owner_id))

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
                SELECT COUNT(*) FROM email_threads
                WHERE owner_id = ?
            """, (owner_id,))
            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MAX(last_modified) FROM email_threads
                WHERE owner_id = ?
            """, (owner_id,))
            last_modified = cursor.fetchone()[0]

            return {
                "total_threads": total,
                "last_modified": last_modified
            }

        finally:
            conn.close()
