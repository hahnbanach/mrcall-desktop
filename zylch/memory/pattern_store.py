"""SQLite-based pattern storage for learned interaction patterns."""

import sqlite3
import json
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from zylch.config import settings
import logging

logger = logging.getLogger(__name__)


class PatternStore:
    """Store and retrieve successful interaction patterns."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.pattern_store_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"Initialized PatternStore at {self.db_path}")

    def _init_db(self):
        """Initialize SQLite database with schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Patterns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                skill TEXT NOT NULL,
                intent_hash TEXT NOT NULL,
                context TEXT NOT NULL,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                usage_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_used TEXT,
                user_id TEXT NOT NULL
            )
        """)

        # Embeddings table (hash-based initially, can add vector embeddings later)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_embeddings (
                pattern_id TEXT PRIMARY KEY,
                embedding_hash TEXT NOT NULL,
                FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
            )
        """)

        # Trajectories table (skill execution sequences)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                id TEXT PRIMARY KEY,
                pattern_id TEXT NOT NULL,
                skill_sequence TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                success BOOLEAN NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_intent_hash ON patterns(intent_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_skill ON patterns(skill)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_confidence ON patterns(confidence)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_embedding_hash ON pattern_embeddings(embedding_hash)")

        conn.commit()
        conn.close()

    def store_pattern(
        self,
        skill: str,
        intent: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: str,
        user_id: str
    ) -> str:
        """Store a successful pattern."""

        # Generate intent hash for similarity matching
        intent_hash = self._hash_intent(intent)

        # Generate pattern ID
        pattern_id = hashlib.sha256(
            f"{skill}:{intent_hash}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO patterns (
                id, skill, intent_hash, context, action, outcome,
                confidence, usage_count, success_count, created_at, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern_id,
            skill,
            intent_hash,
            json.dumps(context),
            json.dumps(action),
            outcome,
            0.5,  # Initial confidence
            1,
            1,
            datetime.now().isoformat(),
            user_id
        ))

        # Store embedding hash
        cursor.execute("""
            INSERT INTO pattern_embeddings (pattern_id, embedding_hash)
            VALUES (?, ?)
        """, (pattern_id, intent_hash))

        conn.commit()
        conn.close()

        logger.info(f"Stored pattern {pattern_id} for skill {skill}")
        return pattern_id

    def retrieve_similar(
        self,
        intent: str,
        skill: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Retrieve similar successful patterns."""

        intent_hash = self._hash_intent(intent)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT p.*, pe.embedding_hash
            FROM patterns p
            JOIN pattern_embeddings pe ON p.id = pe.pattern_id
            WHERE p.confidence >= ?
        """
        params = [settings.pattern_confidence_threshold]

        if skill:
            query += " AND p.skill = ?"
            params.append(skill)

        # Simple hash matching (can be enhanced with vector similarity)
        query += " AND pe.embedding_hash = ?"
        params.append(intent_hash)

        query += " ORDER BY p.confidence DESC, p.usage_count DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        patterns = []
        for row in rows:
            patterns.append({
                "id": row["id"],
                "skill": row["skill"],
                "context": json.loads(row["context"]),
                "action": json.loads(row["action"]),
                "outcome": row["outcome"],
                "confidence": row["confidence"],
                "usage_count": row["usage_count"],
                "summary": self._summarize_pattern(row)
            })

        conn.close()
        logger.info(f"Retrieved {len(patterns)} similar patterns for intent hash {intent_hash}")
        return patterns

    def update_confidence(self, pattern_id: str, success: bool):
        """Update pattern confidence based on outcome (Bayesian update)."""

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get current confidence
        cursor.execute("SELECT confidence, usage_count, success_count FROM patterns WHERE id = ?", (pattern_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            logger.warning(f"Pattern {pattern_id} not found")
            return

        confidence, usage_count, success_count = row

        # Bayesian update (same as ReasoningBank)
        if success:
            new_confidence = confidence + 0.15 * (1 - confidence)
            new_success = success_count + 1
        else:
            new_confidence = confidence - 0.10 * confidence
            new_success = success_count

        new_usage = usage_count + 1

        cursor.execute("""
            UPDATE patterns
            SET confidence = ?, usage_count = ?, success_count = ?, last_used = ?
            WHERE id = ?
        """, (new_confidence, new_usage, new_success, datetime.now().isoformat(), pattern_id))

        conn.commit()
        conn.close()

        logger.info(f"Updated pattern {pattern_id} confidence: {confidence:.2f} → {new_confidence:.2f}")

    def _hash_intent(self, intent: str) -> str:
        """Generate hash for intent similarity matching."""
        # Normalize: lowercase, remove punctuation, sort words
        words = sorted(intent.lower().replace("?", "").replace("!", "").replace(",", "").split())
        normalized = " ".join(words)
        return hashlib.md5(normalized.encode()).hexdigest()[:8]

    def _summarize_pattern(self, row) -> str:
        """Create human-readable pattern summary."""
        return f"{row['skill']}: {row['outcome']} (used {row['usage_count']}x, confidence {row['confidence']:.0%})"
