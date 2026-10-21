"""Model selection — single model per provider, no multi-tier routing."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ModelSelector:
    """Returns the configured default model for all tasks.

    Previously did keyword-based routing between Haiku/Sonnet/Opus.
    Now simplified: one model per provider, no premature optimization.
    """

    def __init__(self, default_model: Optional[str] = None):
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
        if self.default_model:
            return self.default_model
        # No configured default: the chat role's model, as the client resolves it.
        from zylch.llm.model_policy import resolve_model

        return resolve_model("MODEL_CHAT")
