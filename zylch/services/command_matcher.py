"""Semantic command matching using sentence embeddings.

Matches natural language user messages to slash commands by comparing
embeddings. Enables users to say "sync my emails" instead of "/sync".
"""

import logging
from typing import Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


class SemanticCommandMatcher:
    """Matches natural language to slash commands using embeddings.

    Uses a singleton pattern to ensure embeddings are computed only once.
    The model and embeddings are loaded lazily on first use.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, threshold: float = 0.75):
        """Initialize the matcher.

        Args:
            threshold: Minimum similarity score to consider a match (0-1).
                      Higher values = fewer false positives but may miss valid matches.
        """
        if not SemanticCommandMatcher._initialized:
            self.threshold = threshold
            self.model = None
            self.all_triggers = []
            self._trigger_embeddings = None
            self._initialize_embeddings()
            SemanticCommandMatcher._initialized = True

    def _initialize_embeddings(self):
        """Pre-compute all trigger embeddings at startup."""
        from sentence_transformers import SentenceTransformer

        from zylch.services.command_handlers import COMMAND_TRIGGERS

        logger.info("Initializing semantic command matcher...")

        # Load the same model used by zylch_memory
        self.model = SentenceTransformer('all-MiniLM-L6-v2')

        self.all_triggers = []  # [(command, trigger_text, embedding), ...]

        for command, triggers in COMMAND_TRIGGERS.items():
            embeddings = self.model.encode(triggers, convert_to_numpy=True)
            for trigger, embedding in zip(triggers, embeddings):
                self.all_triggers.append((command, trigger, embedding))

        # Stack all embeddings for vectorized comparison
        self._trigger_embeddings = np.vstack([t[2] for t in self.all_triggers])

        logger.info(f"Loaded {len(self.all_triggers)} command triggers")

    def match(self, user_message: str) -> Optional[str]:
        """Match user message to a command semantically.

        Args:
            user_message: The user's natural language message

        Returns:
            The matched command (e.g., "/sync") or None if no match
        """
        # Skip very short messages - likely not command intent
        # Lowered to 3 to allow "help", "sync", etc.
        if len(user_message.strip()) < 3:
            return None

        # Skip if already a slash command
        if user_message.strip().startswith('/'):
            return None

        # Embed user message
        user_embedding = self.model.encode(user_message, convert_to_numpy=True)

        # Compute cosine similarities against all triggers
        similarities = cosine_similarity([user_embedding], self._trigger_embeddings)[0]

        # Find best match
        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]

        if best_similarity >= self.threshold:
            command, trigger_text, _ = self.all_triggers[best_idx]
            logger.info(
                f"Semantic match: '{user_message}' -> {command} "
                f"via '{trigger_text}' (sim={best_similarity:.3f})"
            )
            return command

        return None

    def get_best_match_info(self, user_message: str) -> dict:
        """Get detailed info about the best match (for debugging/testing).

        Args:
            user_message: The user's natural language message

        Returns:
            Dict with command, trigger, similarity, and threshold
        """
        if len(user_message.strip()) < 5:
            return {"matched": False, "reason": "message_too_short"}

        user_embedding = self.model.encode(user_message, convert_to_numpy=True)
        similarities = cosine_similarity([user_embedding], self._trigger_embeddings)[0]

        best_idx = np.argmax(similarities)
        best_similarity = similarities[best_idx]
        command, trigger_text, _ = self.all_triggers[best_idx]

        return {
            "matched": best_similarity >= self.threshold,
            "command": command,
            "trigger": trigger_text,
            "similarity": float(best_similarity),
            "threshold": self.threshold,
        }
