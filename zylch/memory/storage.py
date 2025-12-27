"""SQLite storage backend for patterns, memories, and embeddings."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import ZylchMemoryConfig

logger = logging.getLogger(__name__)


class Storage:
    """SQLite storage for patterns, memories, and embeddings with caching."""

    def __init__(self, config: ZylchMemoryConfig):
        """Initialize SQLite storage.

        Args:
            config: Configuration
        """
        self.config = config
        self.db_path = config.db_path

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to database
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return dict-like rows

        # Initialize schema
        self._init_schema()

        logger.info(f"Storage initialized: {self.db_path}")

    def _init_schema(self) -> None:
        """Create database schema if not exists."""
        with self.conn:
            # Patterns table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    context TEXT,
                    action TEXT,
                    outcome TEXT,
                    user_id TEXT,
                    confidence REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    embedding_id INTEGER,
                    UNIQUE(namespace, skill, intent)
                )
            """)

            # Memories table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    category TEXT NOT NULL,
                    context TEXT,
                    pattern TEXT,
                    examples TEXT,
                    confidence REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    embedding_id INTEGER
                )
            """)

            # Embeddings cache table
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    model TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(text, model)
                )
            """)

            # Create indices
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_namespace ON patterns(namespace)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_skill ON patterns(skill)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_user ON patterns(user_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON patterns(confidence)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_text ON embeddings(text)")

        logger.info("Database schema initialized")

    def store_pattern(
        self,
        namespace: str,
        skill: str,
        intent: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: str,
        user_id: Optional[str],
        embedding_id: int,
        confidence: float = 0.5
    ) -> int:
        """Store a pattern.

        Args:
            namespace: Namespace (e.g., "user:mario")
            skill: Skill name
            intent: User intent text
            context: Context metadata
            action: Action taken
            outcome: Outcome ("approved", "rejected", etc.)
            user_id: User identifier
            embedding_id: FK to embeddings table
            confidence: Initial confidence

        Returns:
            Pattern ID
        """
        with self.conn:
            cursor = self.conn.execute("""
                INSERT OR REPLACE INTO patterns
                (namespace, skill, intent, context, action, outcome, user_id, confidence, embedding_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                namespace,
                skill,
                intent,
                json.dumps(context),
                json.dumps(action),
                outcome,
                user_id,
                confidence,
                embedding_id,
                datetime.utcnow()
            ))
            return cursor.lastrowid

    def get_pattern(self, pattern_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve pattern by ID.

        Args:
            pattern_id: Pattern ID

        Returns:
            Pattern dict or None
        """
        cursor = self.conn.execute("SELECT * FROM patterns WHERE id = ?", (pattern_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def get_patterns_by_namespace(
        self, namespace: str, skill: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get patterns by namespace.

        Args:
            namespace: Namespace filter
            skill: Optional skill filter
            limit: Max results

        Returns:
            List of pattern dicts
        """
        if skill:
            cursor = self.conn.execute("""
                SELECT * FROM patterns
                WHERE namespace = ? AND skill = ?
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
            """, (namespace, skill, limit))
        else:
            cursor = self.conn.execute("""
                SELECT * FROM patterns
                WHERE namespace = ?
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
            """, (namespace, limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def update_pattern_confidence(self, pattern_id: int, confidence: float) -> None:
        """Update pattern confidence.

        Args:
            pattern_id: Pattern ID
            confidence: New confidence value
        """
        with self.conn:
            self.conn.execute("""
                UPDATE patterns
                SET confidence = ?, updated_at = ?
                WHERE id = ?
            """, (confidence, datetime.utcnow(), pattern_id))

    def store_memory(
        self,
        namespace: str,
        category: str,
        context: str,
        pattern: str,
        examples: List[str],
        embedding_id: int,
        confidence: float = 0.5
    ) -> int:
        """Store a behavioral memory.

        Args:
            namespace: Namespace
            category: Category ("email", "contacts", etc.)
            context: Context description
            pattern: Pattern description
            examples: List of example IDs
            embedding_id: FK to embeddings
            confidence: Initial confidence

        Returns:
            Memory ID
        """
        with self.conn:
            cursor = self.conn.execute("""
                INSERT INTO memories
                (namespace, category, context, pattern, examples, confidence, embedding_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                namespace,
                category,
                context,
                pattern,
                json.dumps(examples),
                confidence,
                embedding_id
            ))
            return cursor.lastrowid

    def get_memories_by_namespace(
        self, namespace: str, category: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get memories by namespace.

        Args:
            namespace: Namespace filter
            category: Optional category filter
            limit: Max results

        Returns:
            List of memory dicts
        """
        if category:
            cursor = self.conn.execute("""
                SELECT * FROM memories
                WHERE namespace = ? AND category = ?
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
            """, (namespace, category, limit))
        else:
            cursor = self.conn.execute("""
                SELECT * FROM memories
                WHERE namespace = ?
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
            """, (namespace, limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_memory(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve memory by ID.

        Args:
            memory_id: Memory ID

        Returns:
            Memory dict or None
        """
        cursor = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def update_memory(
        self,
        memory_id: int,
        pattern: Optional[str] = None,
        context: Optional[str] = None,
        examples: Optional[List[str]] = None,
        confidence_delta: float = 0.0,
        new_embedding_id: Optional[int] = None
    ) -> None:
        """Update an existing memory (reconsolidation).

        Args:
            memory_id: Memory ID to update
            pattern: New pattern text (if None, keep existing)
            context: New context (if None, keep existing)
            examples: New examples list (if None, keep existing)
            confidence_delta: Amount to add to confidence (clamped to [0, 1])
            new_embedding_id: New embedding ID (if text changed significantly)
        """
        updates = ["updated_at = ?"]
        params: List[Any] = [datetime.utcnow()]

        if pattern is not None:
            updates.append("pattern = ?")
            params.append(pattern)

        if context is not None:
            updates.append("context = ?")
            params.append(context)

        if examples is not None:
            updates.append("examples = ?")
            params.append(json.dumps(examples))

        if confidence_delta != 0:
            updates.append("confidence = MIN(1.0, MAX(0.0, confidence + ?))")
            params.append(confidence_delta)

        if new_embedding_id is not None:
            updates.append("embedding_id = ?")
            params.append(new_embedding_id)

        params.append(memory_id)

        with self.conn:
            self.conn.execute(f"""
                UPDATE memories
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)

        logger.debug(f"Updated memory {memory_id}: {updates}")

    def store_embedding(self, text: str, vector: np.ndarray, model: str) -> int:
        """Store embedding in cache.

        Args:
            text: Original text
            vector: Embedding vector
            model: Model name

        Returns:
            Embedding ID
        """
        vector_bytes = vector.tobytes()

        with self.conn:
            try:
                cursor = self.conn.execute("""
                    INSERT INTO embeddings (text, vector, model)
                    VALUES (?, ?, ?)
                """, (text, vector_bytes, model))
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Already exists, return existing ID
                cursor = self.conn.execute("""
                    SELECT id FROM embeddings WHERE text = ? AND model = ?
                """, (text, model))
                row = cursor.fetchone()
                return row[0] if row else -1

    def get_embedding(self, text: str, model: str) -> Optional[tuple[int, np.ndarray]]:
        """Retrieve cached embedding.

        Args:
            text: Text to lookup
            model: Model name

        Returns:
            (embedding_id, vector) or None
        """
        cursor = self.conn.execute("""
            SELECT id, vector FROM embeddings
            WHERE text = ? AND model = ?
        """, (text, model))

        row = cursor.fetchone()
        if row:
            embedding_id = row[0]
            vector = np.frombuffer(row[1], dtype=np.float32)
            return embedding_id, vector
        return None

    def get_embedding_by_id(self, embedding_id: int) -> Optional[np.ndarray]:
        """Retrieve embedding vector by ID.

        Args:
            embedding_id: Embedding ID

        Returns:
            Vector or None
        """
        cursor = self.conn.execute("""
            SELECT vector FROM embeddings WHERE id = ?
        """, (embedding_id,))

        row = cursor.fetchone()
        if row:
            return np.frombuffer(row[0], dtype=np.float32)
        return None

    def get_all_embeddings_for_namespace(
        self, namespace: str, table: str = "patterns"
    ) -> List[tuple[int, np.ndarray]]:
        """Get all embeddings for a namespace (for index rebuilding).

        Args:
            namespace: Namespace
            table: "patterns" or "memories"

        Returns:
            List of (row_id, embedding_vector) tuples
        """
        query = f"""
            SELECT t.id, e.vector
            FROM {table} t
            JOIN embeddings e ON t.embedding_id = e.id
            WHERE t.namespace = ?
        """

        cursor = self.conn.execute(query, (namespace,))
        results = []

        for row in cursor.fetchall():
            row_id = row[0]
            vector = np.frombuffer(row[1], dtype=np.float32)
            results.append((row_id, vector))

        return results

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert SQLite row to dict with JSON parsing.

        Args:
            row: SQLite row

        Returns:
            Dictionary with parsed JSON fields
        """
        result = dict(row)

        # Parse JSON fields
        for key in ['context', 'action', 'examples']:
            if key in result and result[key]:
                try:
                    result[key] = json.loads(result[key])
                except json.JSONDecodeError:
                    pass

        return result

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
        logger.info("Storage connection closed")
