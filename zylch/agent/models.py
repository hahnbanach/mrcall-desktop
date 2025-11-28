"""Model selection logic for cost optimization."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ModelSelector:
    """Selects appropriate Claude model based on task complexity."""

    def __init__(
        self,
        default_model: str = "claude-sonnet-4-20250514",
        classification_model: str = "claude-3-5-haiku-20241022",
        executive_model: str = "claude-opus-4-20250514",
    ):
        """Initialize model selector.

        Args:
            default_model: Default model for general tasks
            classification_model: Fast model for classification
            executive_model: Premium model for executive communications
        """
        self.default_model = default_model
        self.classification_model = classification_model
        self.executive_model = executive_model

    def select_model(
        self,
        message: str,
        context: Optional[dict] = None,
        force_model: Optional[str] = None,
    ) -> str:
        """Select optimal model based on task.

        Args:
            message: User message
            context: Additional context (e.g., contact priority)
            force_model: Force specific model (overrides heuristics)

        Returns:
            Model identifier
        """
        if force_model:
            logger.info(f"Using forced model: {force_model}")
            return force_model

        message_lower = message.lower()

        # Check for executive context
        if context and context.get("is_executive"):
            logger.info(f"Using executive model for high-stakes communication")
            return self.executive_model

        # Heuristics for fast classification model
        # Note: "who is" removed - contact queries need Sonnet for tool calling intelligence
        classification_keywords = [
            "classify", "categorize", "priority score", "relationship type",
            "what priority", "rate this", "score this"
        ]
        if any(keyword in message_lower for keyword in classification_keywords):
            logger.info(f"Using classification model for: {message[:50]}...")
            return self.classification_model

        # Heuristics for quality model (drafting, analysis)
        quality_keywords = [
            "draft", "write", "compose", "enrich", "analyze", "explain",
            "summarize", "research", "find information"
        ]
        if any(keyword in message_lower for keyword in quality_keywords):
            logger.info(f"Using default quality model for: {message[:50]}...")
            return self.default_model

        # Heuristics for executive/premium model
        executive_keywords = [
            "executive", "ceo", "cto", "cfo", "board", "critical",
            "urgent", "important", "strategic"
        ]
        if any(keyword in message_lower for keyword in executive_keywords):
            logger.info(f"Using executive model for: {message[:50]}...")
            return self.executive_model

        # Default to Sonnet for general tasks
        logger.debug(f"Using default model for: {message[:50]}...")
        return self.default_model

    def get_model_info(self, model: str) -> dict:
        """Get information about a model.

        Args:
            model: Model identifier

        Returns:
            Model information
        """
        models = {
            self.classification_model: {
                "name": "Haiku",
                "speed": "fast",
                "cost": "low",
                "use_case": "Classification, priority scoring, simple queries"
            },
            self.default_model: {
                "name": "Sonnet",
                "speed": "medium",
                "cost": "medium",
                "use_case": "Email drafting, enrichment, complex analysis"
            },
            self.executive_model: {
                "name": "Opus",
                "speed": "slower",
                "cost": "high",
                "use_case": "Executive communications, critical decisions"
            }
        }

        return models.get(model, {
            "name": "Unknown",
            "speed": "unknown",
            "cost": "unknown",
            "use_case": "Unknown"
        })
