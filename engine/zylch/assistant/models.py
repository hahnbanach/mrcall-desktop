"""Model selection — single model per provider, no multi-tier routing."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ModelSelector:
    """Returns the configured default model for all tasks.

    Previously did keyword-based routing between Haiku/Sonnet/Opus.
    Now simplified: one model per provider, no premature optimization.
    """

    def __init__(self, default_model: str = "claude-opus-4-6-20260205"):
        self.default_model = default_model

    def select_model(
        self,
        message: str,
        context: Optional[dict] = None,
        force_model: Optional[str] = None,
    ) -> str:
        if force_model:
            logger.info(f"Using forced model: {force_model}")
            return force_model
        return self.default_model
