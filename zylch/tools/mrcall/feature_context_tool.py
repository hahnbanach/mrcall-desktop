"""MrCall Feature Context Tool - Loads sub-prompts for MrCall configuration.

Provides context about MrCall features so the LLM can understand and modify
the assistant's configuration. Supports lazy generation - if a sub-prompt
doesn't exist, it will be generated on first request.
"""

import logging
from typing import Any, Dict

from ..base import Tool, ToolResult, ToolStatus
from ..factory import SessionState
from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer

logger = logging.getLogger(__name__)


class GetMrCallFeatureContextTool(Tool):
    """Tool to load context about a MrCall feature configuration.

    If the sub-prompt doesn't exist, generates it first (lazy loading).
    Returns the context along with a flag indicating if it was just generated,
    so the LLM can craft an appropriate response.
    """

    def __init__(
        self,
        trainer: MrCallConfiguratorTrainer,
        session_state: SessionState,
    ):
        super().__init__(
            name="get_mrcall_feature_context",
            description=(
                "Get context about a MrCall assistant feature configuration. "
                "Use this BEFORE attempting to modify MrCall settings. "
                "Returns detailed information about the current configuration, "
                "what can be changed, and what cannot. "
                "Available features: welcome_message (how the assistant answers the phone). "
                "If the context hasn't been analyzed yet, this will analyze it first."
            ),
        )
        self.trainer = trainer
        self.session_state = session_state

    async def execute(
        self,
        feature: str = "welcome_message",
    ) -> ToolResult:
        """Load context for a MrCall feature.

        Args:
            feature: Feature name. Currently supported: "welcome_message"

        Returns:
            ToolResult with context, was_generated flag, and feature name
        """
        business_id = self.session_state.get_business_id()
        if not business_id:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    "No MrCall assistant selected. "
                    "Use /mrcall <id> to select one first."
                ),
            )

        # Validate feature name
        available_features = MrCallConfiguratorTrainer.get_available_features()
        if feature not in available_features:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=(
                    f"Unknown feature: {feature}. "
                    f"Available features: {', '.join(available_features.keys())}"
                ),
            )

        try:
            # Try to load existing sub-prompt
            context = self.trainer.get_feature_context(feature, business_id)
            was_generated = False

            if not context:
                # Lazy generation - this takes 3-5 seconds
                logger.info(
                    f"No cached context for {feature}, generating..."
                )
                context, metadata = await self.trainer.train_feature(
                    feature, business_id
                )
                was_generated = True
                logger.info(
                    f"Generated context for {feature} "
                    f"({len(context)} chars, took lazy generation)"
                )

            return ToolResult(
                status=ToolStatus.SUCCESS,
                data={
                    "context": context,
                    "was_generated": was_generated,
                    "feature": feature,
                    "business_id": business_id,
                },
                message=(
                    f"{'Analyzed' if was_generated else 'Loaded'} "
                    f"{feature} configuration for business {business_id}"
                ),
            )

        except Exception as e:
            logger.error(f"Failed to get feature context: {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e),
            )

    def get_schema(self) -> Dict[str, Any]:
        available_features = list(
            MrCallConfiguratorTrainer.get_available_features().keys()
        )

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "description": (
                            "The MrCall feature to get context for. "
                            "Use 'welcome_message' for how the assistant answers calls."
                        ),
                        "enum": available_features,
                        "default": "welcome_message",
                    },
                },
                "required": [],
            },
        }
