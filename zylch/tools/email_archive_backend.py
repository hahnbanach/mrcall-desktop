"""Abstract interface for email archive storage backends."""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class EmailArchiveBackend(ABC):
    """Abstract base class for email archive storage."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database schema/tables."""
        pass

    @abstractmethod
    def store_message(self, message: Dict[str, Any]) -> None:
        """Store a single message."""
        pass

    @abstractmethod
    def store_messages_batch(self, messages: List[Dict[str, Any]]) -> None:
        """Store multiple messages in a batch."""
        pass

    @abstractmethod
    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get message by ID."""
        pass

    @abstractmethod
    def get_thread_messages(self, thread_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all messages in a thread."""
        pass

    @abstractmethod
    def delete_message(self, message_id: str) -> None:
        """Delete a message."""
        pass

    @abstractmethod
    def get_threads_in_window(self, days_back: int) -> List[str]:
        """Get thread IDs with activity in last N days."""
        pass

    @abstractmethod
    def search_messages(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Full-text search messages."""
        pass

    @abstractmethod
    def get_sync_state(self) -> Optional[Dict[str, Any]]:
        """Get current sync state (history_id, last_sync, etc.)."""
        pass

    @abstractmethod
    def update_sync_state(self, history_id: str, last_sync: datetime) -> None:
        """Update sync state."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get archive statistics."""
        pass


class SQLiteArchiveBackend(EmailArchiveBackend):
    """SQLite implementation of email archive."""

    def __init__(self, db_path: str, enable_fts: bool = True):
        """Initialize SQLite backend.

        Args:
            db_path: Path to SQLite database file
            enable_fts: Enable full-text search
        """
        self.db_path = Path(db_path)
        self.enable_fts = enable_fts
        self.conn = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection (creates if not exists)."""
        if self.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row  # Return rows as dicts
        return self.conn

    def initialize(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                from_email TEXT,
                from_name TEXT,
                to_email TEXT,
                cc_email TEXT,
                subject TEXT,
                date TEXT NOT NULL,
                date_timestamp INTEGER,
                snippet TEXT,
                body_plain TEXT,
                body_html TEXT,
                labels TEXT,
                message_id_header TEXT,
                in_reply_to TEXT,
                "references" TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_thread_id ON messages(thread_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date_timestamp ON messages(date_timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_from_email ON messages(from_email)")

        # Threads table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                subject TEXT,
                participants TEXT,
                message_count INTEGER,
                first_message_date TEXT,
                last_message_date TEXT,
                last_message_id TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_message_date ON threads(last_message_date)")

        # Sync state table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                history_id TEXT NOT NULL,
                last_sync TEXT NOT NULL,
                full_sync_completed TEXT
            )
        """)

        # Full-text search
        if self.enable_fts:
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    subject,
                    body_plain,
                    from_email,
                    from_name,
                    content=messages,
                    content_rowid=rowid
                )
            """)

            # Triggers to keep FTS in sync
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, subject, body_plain, from_email, from_name)
                    VALUES (new.rowid, new.subject, new.body_plain, new.from_email, new.from_name);
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    DELETE FROM messages_fts WHERE rowid = old.rowid;
                END
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    UPDATE messages_fts SET subject = new.subject, body_plain = new.body_plain,
                                           from_email = new.from_email, from_name = new.from_name
                    WHERE rowid = new.rowid;
                END
            """)

        conn.commit()
        logger.info(f"Initialized SQLite archive at {self.db_path}")

    def store_message(self, message: Dict[str, Any]) -> None:
        """Store a single message."""
        self.store_messages_batch([message])

    def store_messages_batch(self, messages: List[Dict[str, Any]]) -> None:
        """Store multiple messages in a batch."""
        if not messages:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        for msg in messages:
            cursor.execute("""
                INSERT OR REPLACE INTO messages (
                    id, thread_id, from_email, from_name, to_email, cc_email,
                    subject, date, date_timestamp, snippet, body_plain, body_html,
                    labels, message_id_header, in_reply_to, "references",
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg['id'],
                msg['thread_id'],
                msg.get('from_email'),
                msg.get('from_name'),
                msg.get('to_email'),
                msg.get('cc_email'),
                msg.get('subject'),
                msg['date'],
                msg.get('date_timestamp'),
                msg.get('snippet'),
                msg.get('body_plain'),
                msg.get('body_html'),
                json.dumps(msg.get('labels', [])),
                msg.get('message_id_header'),
                msg.get('in_reply_to'),
                msg.get('references'),
                now,
                now
            ))

        conn.commit()

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get message by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def get_thread_messages(self, thread_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all messages in a thread, sorted by date."""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM messages WHERE thread_id = ? ORDER BY date_timestamp ASC"
        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, (thread_id,))
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def delete_message(self, message_id: str) -> None:
        """Delete a message."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()

    def get_threads_in_window(self, days_back: int) -> List[str]:
        """Get thread IDs with activity in last N days."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Calculate cutoff timestamp (days_back ago)
        from datetime import timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_timestamp = int(cutoff.timestamp())

        cursor.execute("""
            SELECT DISTINCT thread_id
            FROM messages
            WHERE date_timestamp >= ?
            ORDER BY date_timestamp DESC
        """, (cutoff_timestamp,))

        rows = cursor.fetchall()
        return [row['thread_id'] for row in rows]

    def search_messages(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Full-text search messages."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if self.enable_fts:
            # Use FTS5 search
            sql = """
                SELECT messages.*
                FROM messages
                JOIN messages_fts ON messages.rowid = messages_fts.rowid
                WHERE messages_fts MATCH ?
            """
            params = [query]
        else:
            # Fallback to LIKE search
            sql = """
                SELECT * FROM messages
                WHERE subject LIKE ? OR body_plain LIKE ? OR from_email LIKE ?
            """
            query_pattern = f"%{query}%"
            params = [query_pattern, query_pattern, query_pattern]

        # Add date filters
        if from_date:
            sql += " AND date_timestamp >= ?"
            params.append(int(from_date.timestamp()))
        if to_date:
            sql += " AND date_timestamp <= ?"
            params.append(int(to_date.timestamp()))

        sql += f" ORDER BY date_timestamp DESC LIMIT {limit}"

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def get_sync_state(self) -> Optional[Dict[str, Any]]:
        """Get current sync state."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sync_state WHERE id = 1")
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def update_sync_state(self, history_id: str, last_sync: datetime) -> None:
        """Update sync state."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO sync_state (id, history_id, last_sync)
            VALUES (1, ?, ?)
        """, (history_id, last_sync.isoformat()))

        conn.commit()

    def mark_full_sync_completed(self) -> None:
        """Mark initial full sync as completed."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sync_state
            SET full_sync_completed = ?
            WHERE id = 1
        """, (datetime.now().isoformat(),))

        conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Get archive statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Total messages
        cursor.execute("SELECT COUNT(*) as count FROM messages")
        total_messages = cursor.fetchone()['count']

        # Total threads
        cursor.execute("SELECT COUNT(DISTINCT thread_id) as count FROM messages")
        total_threads = cursor.fetchone()['count']

        # Date range
        cursor.execute("""
            SELECT MIN(date_timestamp) as earliest, MAX(date_timestamp) as latest
            FROM messages
        """)
        date_range = cursor.fetchone()

        earliest = None
        latest = None
        if date_range['earliest']:
            earliest = datetime.fromtimestamp(date_range['earliest']).isoformat()
        if date_range['latest']:
            latest = datetime.fromtimestamp(date_range['latest']).isoformat()

        # Sync state
        sync_state = self.get_sync_state()

        # Database size
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        db_size_mb = db_size / (1024 * 1024)

        return {
            'backend': 'sqlite',
            'db_path': str(self.db_path),
            'total_messages': total_messages,
            'total_threads': total_threads,
            'earliest_message': earliest,
            'latest_message': latest,
            'last_sync': sync_state['last_sync'] if sync_state else None,
            'full_sync_completed': sync_state.get('full_sync_completed') if sync_state else None,
            'db_size_mb': round(db_size_mb, 2)
        }

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
