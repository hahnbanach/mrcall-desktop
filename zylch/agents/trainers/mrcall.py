"""MrCall Agent Trainer - Trains unified MrCall configuration agent.

Combines all feature sub-prompts (welcome_inbound, welcome_outbound, booking, etc.) into
a single unified agent prompt with tool selection guidance.

The unified agent can then handle any MrCall configuration request by
choosing the appropriate tool based on user intent.

Flusso:

/agent mrcall train
    ↓
MrCallAgentTrainer.build_prompt()
    ↓
Per ogni feature: MrCallConfiguratorTrainer.build_subprompt()
    ↓
Combina tutto → UNIFIED_META_PROMPT + feature_subprompts
    ↓
Salva come "mrcall_{business_id}"

"""

import logging
from typing import Any, Dict, List, Tuple

from zylch.agents.trainers.base import BaseAgentTrainer
from zylch.agents.trainers.mrcall_configurator import MrCallConfiguratorTrainer
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Unified meta-prompt that combines all feature knowledge
UNIFIED_META_PROMPT = """You are the MrCall configuration agent.

You help users configure their MrCall AI phone assistant. You have access to
multiple configuration tools, each for a different feature.

## AVAILABLE TOOLS

1. **configure_welcome_inbound** - Modify how the assistant answers inbound calls
2. **configure_welcome_outbound** - Modify how the assistant starts outbound calls
3. **configure_booking** - Manage appointment booking settings
3. **get_current_config** - Show current configuration for any feature
4. **respond_text** - Answer questions or explain settings

## WHEN TO USE EACH TOOL

- "change the greeting" → configure_welcome_inbound
- "update welcome message" → configure_welcome_inbound
- "change outbound greeting" → configure_welcome_outbound
- "enable booking" → configure_booking
- "set 30 minute appointments" → configure_booking
- "disable booking" → configure_booking
- "what are my current settings?" → get_current_config
- "show booking config" → get_current_config
- "how does booking work?" → respond_text
- "explain the variables" → respond_text
- "is booking enabled?" → respond_text
- "does the assistant answer formally?" → respond_text
- "is the greeting professional?" → respond_text

## CRITICAL RULES

1. ALL values are STRINGS (booleans: "true"/"false", numbers: "30", JSON: escaped)
2. When enabling booking, you MUST set multiple related variables together:
   - START_BOOKING_PROCESS = "true"
   - BOOKING_HOURS (JSON string with schedule)
   - BOOKING_EVENTS_MINUTES (appointment duration)
   - ENABLE_GET_CALENDAR_EVENTS = "true"
3. BOOKING_CALENDAR_ID is auto-set via OAuth - never modify it
4. JSON values must be valid JSON strings with escaped quotes, e.g.:
   "{{\\"monday\\": [{{\\"09:00-17:00\\"}}]}}"

## FEATURE-SPECIFIC KNOWLEDGE

{feature_subprompts}
"""


class MrCallAgentTrainer(BaseAgentTrainer):
    """Trains unified MrCall agent by combining all feature sub-prompts.

    This trainer:
    1. Loads all existing feature sub-prompts (welcome_inbound, welcome_outbound, booking, etc.)
    2. Combines them into a single unified prompt
    3. Adds tool selection guidance so the agent knows which tool to use

    Usage:
        trainer = MrCallAgentTrainer(storage, owner_id, api_key, user_email, provider)
        prompt, metadata = await trainer.build_prompt(business_id)
        storage.store_agent_prompt(owner_id, f"mrcall_{business_id}", prompt, metadata)
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str,
        starchat_client=None,
    ):
        """Initialize MrCallAgentTrainer.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            user_email: User's email address
            provider: LLM provider (anthropic, openai, mistral)
            starchat_client: Optional StarChat client for auto-training features
        """
        super().__init__(storage, owner_id, api_key, user_email, provider)
        self.starchat = starchat_client

    async def build_prompt(self, business_id: str = None) -> Tuple[str, Dict[str, Any]]:
        """Build unified agent prompt from all feature sub-prompts.

        Args:
            business_id: MrCall business ID. If None, will be fetched from storage.

        Returns:
            Tuple of (prompt_content, metadata)

        Raises:
            ValueError: If no MrCall assistant is linked or no features are trained
        """
        # Get business_id if not provided
        if not business_id:
            business_id = self.storage.get_mrcall_link(self.owner_id)
            if not business_id:
                raise ValueError(
                    "No MrCall assistant linked. Run `/mrcall list` then `/mrcall link N` first."
                )

        # Load all feature sub-prompts
        feature_subprompts = []
        features_found = []

        for feature_name in MrCallConfiguratorTrainer.FEATURES.keys():
            agent_type = f"mrcall_{business_id}_{feature_name}"
            subprompt = self.storage.get_agent_prompt(self.owner_id, agent_type)

            if subprompt:
                features_found.append(feature_name)
                # Format with feature name header
                display_name = MrCallConfiguratorTrainer.FEATURES[feature_name].get(
                    "display_name", feature_name
                )
                feature_subprompts.append(
                    f"### {feature_name.upper()}\n**{display_name}**\n\n{subprompt}"
                )
                logger.info(f"Loaded feature sub-prompt: {feature_name}")
            else:
                logger.warning(f"No sub-prompt found for feature: {feature_name}")

        if not feature_subprompts:
            raise ValueError(
                "No feature sub-prompts found. Run `/mrcall train` first to generate them."
            )

        # Combine into unified prompt
        unified_prompt = UNIFIED_META_PROMPT.format(
            feature_subprompts="\n\n".join(feature_subprompts)
        )

        # Build metadata
        metadata = self._build_metadata(
            business_id=business_id,
            features_included=features_found,
            total_features=len(MrCallConfiguratorTrainer.FEATURES),
        )

        logger.info(
            f"Built unified MrCall agent prompt with {len(features_found)} features"
        )

        return unified_prompt, metadata

    async def train_missing_features(self, business_id: str) -> List[str]:
        """Train any missing feature sub-prompts.

        Args:
            business_id: MrCall business ID

        Returns:
            List of feature names that were trained

        Raises:
            ValueError: If no StarChat client available
        """
        if not self.starchat:
            raise ValueError("StarChat client required for training features")

        trained = []
        feature_trainer = MrCallConfiguratorTrainer(
            storage=self.storage,
            starchat_client=self.starchat,
            owner_id=self.owner_id,
            api_key=self.client.api_key if hasattr(self.client, 'api_key') else '',
            provider=self.provider,
        )

        for feature_name in MrCallConfiguratorTrainer.FEATURES.keys():
            agent_type = f"mrcall_{business_id}_{feature_name}"
            existing = self.storage.get_agent_prompt(self.owner_id, agent_type)

            if not existing:
                logger.info(f"Training missing feature: {feature_name}")
                try:
                    await feature_trainer.train_feature(feature_name, business_id)
                    trained.append(feature_name)
                except Exception as e:
                    logger.error(f"Failed to train {feature_name}: {e}")

        return trained
