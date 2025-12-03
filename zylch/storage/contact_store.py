"""Contact data storage with multi-tenant isolation.

Server-side storage for contacts with owner_id isolation.
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


class ContactStore:
    """Server-side contact storage with multi-tenant isolation."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize contact store.

        Args:
            db_path: Path to SQLite database. Defaults to cache/server_data.db
        """
        if db_path is None:
            db_path = Path(settings.cache_dir) / "server_data.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

        logger.info(f"ContactStore initialized at {self.db_path}")

    def _ensure_tables(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                memory_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                data TEXT NOT NULL,
                last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (memory_id, owner_id)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contact_owner_id ON contacts(owner_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contact_last_modified ON contacts(last_modified)
        """)

        conn.commit()
        conn.close()

    def save_contact(
        self,
        memory_id: str,
        owner_id: str,
        contact_data: Dict[str, Any]
    ) -> bool:
        """Save or update contact.

        Args:
            memory_id: Contact memory identifier
            owner_id: Owner (Firebase UID)
            contact_data: Contact data dict

        Returns:
            True if successful
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO contacts
                (memory_id, owner_id, data, last_modified)
                VALUES (?, ?, ?, ?)
            """, (
                memory_id,
                owner_id,
                json.dumps(contact_data),
                datetime.now(timezone.utc)
            ))

            conn.commit()
            return True

        except Exception as e:
            logger.error(f"Failed to save contact {memory_id}: {e}")
            conn.rollback()
            return False

        finally:
            conn.close()

    def get_contact(
        self,
        memory_id: str,
        owner_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get contact by memory ID.

        Args:
            memory_id: Contact memory identifier
            owner_id: Owner (Firebase UID)

        Returns:
            Contact data dict or None if not found
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT data FROM contacts
                WHERE memory_id = ? AND owner_id = ?
            """, (memory_id, owner_id))

            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

        finally:
            conn.close()

    def list_contacts(
        self,
        owner_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List contacts for owner.

        Args:
            owner_id: Owner (Firebase UID)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of contact data dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT data FROM contacts
                WHERE owner_id = ?
                ORDER BY last_modified DESC
                LIMIT ? OFFSET ?
            """, (owner_id, limit, offset))

            contacts = []
            for row in cursor.fetchall():
                contacts.append(json.loads(row[0]))

            return contacts

        finally:
            conn.close()

    def delete_contact(
        self,
        memory_id: str,
        owner_id: str
    ) -> bool:
        """Delete contact.

        Args:
            memory_id: Contact memory identifier
            owner_id: Owner (Firebase UID)

        Returns:
            True if deleted
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM contacts
                WHERE memory_id = ? AND owner_id = ?
            """, (memory_id, owner_id))

            conn.commit()
            return cursor.rowcount > 0

        finally:
            conn.close()

    def search_contacts(
        self,
        owner_id: str,
        query: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search contacts by query.

        Note: Simple JSON text search. For better search,
        consider adding full-text search or extracting searchable fields.

        Args:
            owner_id: Owner (Firebase UID)
            query: Search query
            limit: Maximum results

        Returns:
            List of matching contact data dicts
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            # Simple LIKE search in JSON data
            # For production, consider FTS5 or dedicated search fields
            cursor.execute("""
                SELECT data FROM contacts
                WHERE owner_id = ? AND data LIKE ?
                ORDER BY last_modified DESC
                LIMIT ?
            """, (owner_id, f'%{query}%', limit))

            contacts = []
            for row in cursor.fetchall():
                contacts.append(json.loads(row[0]))

            return contacts

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
                SELECT COUNT(*) FROM contacts
                WHERE owner_id = ?
            """, (owner_id,))
            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MAX(last_modified) FROM contacts
                WHERE owner_id = ?
            """, (owner_id,))
            last_modified = cursor.fetchone()[0]

            return {
                "total_contacts": total,
                "last_modified": last_modified
            }

        finally:
            conn.close()
