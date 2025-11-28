"""Pattern learning service - business logic layer."""

from typing import Dict, Any, Optional, List
import logging
from pathlib import Path

from zylch.memory import ZylchMemory, ZylchMemoryConfig
from zylch.config import settings

logger = logging.getLogger(__name__)


class PatternService:
    """Service for pattern learning and retrieval using ZylchMemory."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize pattern service.

        Args:
            db_path: Optional custom database path
        """
        if settings.pattern_store_enabled:
            config = ZylchMemoryConfig(
                db_path=Path(db_path) if db_path else Path(settings.cache_dir) / "zylch_memory.db",
                index_dir=Path(settings.cache_dir) / "indices"
            )
            self.memory = ZylchMemory(config=config)
        else:
            self.memory = None

    def store_pattern(
        self,
        skill: str,
        intent: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        outcome: str,
        user_id: str
    ) -> Optional[str]:
        """Store a successful interaction pattern.

        Args:
            skill: Skill that was used
            intent: User intent (natural language)
            context: Context dict
            action: Action taken
            outcome: Outcome description
            user_id: User identifier

        Returns:
            Pattern ID if stored, None if memory disabled
        """
        if not self.memory:
            logger.warning("Memory system not enabled")
            return None

        pattern_id = self.memory.store_pattern(
            namespace=f"user:{user_id}",
            skill=skill,
            intent=intent,
            context=context,
            action=action,
            outcome=outcome,
            user_id=user_id
        )

        logger.info(f"Stored pattern {pattern_id} for skill {skill}")
        return pattern_id

    def retrieve_similar_patterns(
        self,
        intent: str,
        skill: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Retrieve similar successful patterns using semantic search.

        Args:
            intent: User intent to match against
            skill: Optional skill filter
            user_id: User ID for personalized patterns
            limit: Maximum number of patterns to return

        Returns:
            List of similar patterns
        """
        if not self.memory:
            logger.warning("Memory system not enabled")
            return []

        if not skill:
            logger.warning("Skill parameter required for pattern retrieval")
            return []

        patterns = self.memory.retrieve_similar_patterns(
            intent=intent,
            skill=skill,
            user_id=user_id,
            limit=limit
        )

        logger.info(f"Retrieved {len(patterns)} patterns for intent '{intent}' (semantic search)")
        return patterns

    def update_pattern_confidence(self, pattern_id: str, success: bool) -> bool:
        """Update pattern confidence based on outcome using Bayesian learning.

        Args:
            pattern_id: Pattern identifier
            success: Whether the pattern was successful

        Returns:
            True if updated, False if memory disabled
        """
        if not self.memory:
            logger.warning("Memory system not enabled")
            return False

        self.memory.update_confidence(pattern_id, success)
        logger.info(f"Updated pattern {pattern_id} confidence (success={success}) [Bayesian]")
        return True

    def get_pattern_stats(self) -> Dict[str, Any]:
        """Get statistics about stored patterns.

        Returns:
            Pattern statistics
        """
        if not self.memory:
            return {
                "enabled": False,
                "message": "Memory system not enabled"
            }

        # Query ZylchMemory database for stats
        import sqlite3

        conn = sqlite3.connect(str(self.memory.config.db_path))
        cursor = conn.cursor()

        # Total patterns
        cursor.execute("SELECT COUNT(*) FROM patterns")
        total_patterns = cursor.fetchone()[0]

        # By skill
        cursor.execute("SELECT skill, COUNT(*) FROM patterns GROUP BY skill")
        by_skill = dict(cursor.fetchall())

        # By namespace
        cursor.execute("SELECT namespace, COUNT(*) FROM patterns GROUP BY namespace")
        by_namespace = dict(cursor.fetchall())

        # Average confidence
        cursor.execute("SELECT AVG(confidence) FROM patterns")
        avg_confidence = cursor.fetchone()[0] or 0.0

        # High confidence patterns (>0.7)
        cursor.execute("SELECT COUNT(*) FROM patterns WHERE confidence > 0.7")
        high_confidence = cursor.fetchone()[0]

        conn.close()

        return {
            "enabled": True,
            "system": "ZylchMemory (semantic search)",
            "total_patterns": total_patterns,
            "by_skill": by_skill,
            "by_namespace": by_namespace,
            "average_confidence": round(avg_confidence, 2),
            "high_confidence_patterns": high_confidence,
            "db_path": str(self.memory.config.db_path)
        }
