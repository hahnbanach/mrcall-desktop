"""MrCall Configurator Trainer - Generates feature-specific sub-prompts from MrCall config.

Analyzes MrCall assistant configuration to generate self-contained sub-prompts that:
1. Document available variables and their meaning
2. Describe current behavior in plain language
3. List what can/cannot be changed
4. Include raw prompt value for modification

Each sub-prompt is stored per feature per business in the agent_prompts table.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Meta-prompt for generating welcome message sub-prompts
WELCOME_MESSAGE_META_PROMPT = """You are analyzing the welcome message configuration for a MrCall AI phone assistant.

Your task: Given the current value of OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT, generate a
self-contained sub-prompt that another LLM can use to both UNDERSTAND and MODIFY the configuration.

## UNDERSTANDING THE PROMPT STRUCTURE

The welcome message prompt has two parts:

### Part 1: Variable Declarations
Lines that define what data the assistant has access to. Format:
```
VARIABLE_NAME=%%source.path.to.value=default_value%%
```

Example:
```
FIRST_NAME=%%crm.contact.variables.FIRST_NAME=not known%%
```
This means: "FIRST_NAME comes from the CRM contact record. If not found, use 'not known'."

Common variable sources:
- `%%crm.contact.variables.X%%` - Data from the caller's contact record
- `%%HB_FROM_NUMBER%%` - The caller's phone number
- `%%public:X%%` - Public/shared values (like current time)

### Part 2: Behavioral Instructions
After the `---` separator, the prompt contains instructions for how the assistant should behave.

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these exact sections:

### SECTION 1: AVAILABLE VARIABLES
Create a markdown table listing each %%...%% variable with:
- Variable name
- The full variable reference (MUST be preserved when modifying)
- Human-readable description
- Default value

### SECTION 2: CURRENT BEHAVIOR
Describe what the assistant DOES in plain language:
- "When a new caller phones, the assistant..."
- "When a returning caller phones, the assistant..."
Be specific about greeting style, questions asked, information disclosed.

### SECTION 3: WHAT CAN BE CHANGED
List modifications users can request (with examples):
- Greeting style (formal/informal/personalized)
- Whether to use caller's name
- Recording disclosure (remove, shorten, reword)
- What information to ask for
- How to handle returning callers
- etc.

### SECTION 4: WHAT CANNOT BE CHANGED (via this feature)
- The available variables (from StarChat system)
- Voice or language (separate configuration)
- Call routing/transfer logic (different feature)
- Business hours behavior (different feature)

### SECTION 5: CURRENT PROMPT VALUE
Include the FULL raw prompt text so another LLM can modify it.
Start with: "When modifying, preserve all `%%...%%` variable references and the `---` separator."
Then include the complete prompt in a code block.

---

## CURRENT CONFIGURATION TO ANALYZE:

{current_value}

---

OUTPUT ONLY THE SUB-PROMPT TEXT. No explanations, no additional markdown. Just the sub-prompt itself."""


class MrCallConfiguratorTrainer:
    """Generates feature-specific sub-prompts from MrCall configuration.

    Each feature (welcome_message, booking, etc.) has its own sub-prompt that:
    - Documents available variables
    - Describes current behavior
    - Lists what can be changed
    - Includes raw prompt for modification

    Sub-prompts are stored in agent_prompts with agent_type=mrcall_{business_id}_{feature}
    """

    # Feature definitions - maps feature name to variable(s) and meta-prompt
    FEATURES = {
        "welcome_message": {
            "variables": ["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"],
            "description": "How the assistant answers the phone",
            "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
        },
        # Future features:
        # "booking": {
        #     "variables": ["BOOKING_PROMPT", "BOOKING_CONFIRMATION_PROMPT"],
        #     "description": "Appointment booking behavior",
        #     "meta_prompt": BOOKING_META_PROMPT,
        # },
    }

    def __init__(
        self,
        storage: SupabaseStorage,
        starchat_client,
        owner_id: str,
        api_key: str,
        provider: str,
    ):
        """Initialize MrCallConfiguratorTrainer.

        Args:
            storage: SupabaseStorage instance for storing sub-prompts
            starchat_client: StarChatClient for fetching MrCall config
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.starchat = starchat_client
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, PROVIDER_MODELS["anthropic"])
        self.client = LLMClient(api_key=api_key, provider=provider)

    async def train_feature(
        self,
        feature_name: str,
        business_id: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Generate sub-prompt for a specific feature.

        Args:
            feature_name: Feature to train (e.g., "welcome_message")
            business_id: MrCall business ID

        Returns:
            Tuple of (sub_prompt_content, metadata)

        Raises:
            ValueError: If feature not found or business config unavailable
        """
        if feature_name not in self.FEATURES:
            raise ValueError(
                f"Unknown feature: {feature_name}. "
                f"Available: {list(self.FEATURES.keys())}"
            )

        feature = self.FEATURES[feature_name]
        variable_names = feature["variables"]
        meta_prompt_template = feature["meta_prompt"]

        logger.info(
            f"Training MrCall {feature_name} for business {business_id}, "
            f"variables: {variable_names}"
        )

        # 1. Fetch current variable value(s) from StarChat
        business = await self.starchat.get_business_config(business_id)
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        current_values = business.get("variables", {})

        # For now, we only handle single-variable features
        # Multi-variable features will need prompt adjustment
        variable_name = variable_names[0]
        current_value = current_values.get(variable_name)

        if not current_value:
            raise ValueError(
                f"Variable {variable_name} not found in business {business_id}. "
                f"Available: {list(current_values.keys())[:10]}..."
            )

        # 2. Generate sub-prompt using LLM
        meta_prompt = meta_prompt_template.format(current_value=current_value)

        logger.info(
            f"Generating sub-prompt for {feature_name} "
            f"(provider: {self.provider}, model: {self.model})"
        )

        response = await self.client.create_message(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}],
        )

        sub_prompt = response.content[0].text.strip()

        # 3. Store in agent_prompts
        agent_type = f"mrcall_{business_id}_{feature_name}"
        metadata = {
            "business_id": business_id,
            "feature": feature_name,
            "variables": variable_names,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt_length": len(current_value),
        }

        self.storage.store_agent_prompt(
            owner_id=self.owner_id,
            agent_type=agent_type,
            prompt=sub_prompt,
            metadata=metadata,
        )

        logger.info(
            f"Stored sub-prompt for {agent_type} ({len(sub_prompt)} chars)"
        )

        return sub_prompt, metadata

    async def train_all(
        self,
        business_id: str,
    ) -> Dict[str, Tuple[str, Dict[str, Any]]]:
        """Generate sub-prompts for all features.

        Args:
            business_id: MrCall business ID

        Returns:
            Dict mapping feature_name to (sub_prompt, metadata)
        """
        results = {}

        for feature_name in self.FEATURES:
            try:
                sub_prompt, metadata = await self.train_feature(
                    feature_name, business_id
                )
                results[feature_name] = (sub_prompt, metadata)
            except Exception as e:
                logger.error(f"Failed to train {feature_name}: {e}")
                results[feature_name] = (None, {"error": str(e)})

        return results

    def get_feature_context(
        self,
        feature_name: str,
        business_id: str,
    ) -> Optional[str]:
        """Get stored sub-prompt for a feature (if exists).

        Args:
            feature_name: Feature name (e.g., "welcome_message")
            business_id: MrCall business ID

        Returns:
            Sub-prompt content or None if not found
        """
        agent_type = f"mrcall_{business_id}_{feature_name}"
        return self.storage.get_agent_prompt(self.owner_id, agent_type)

    def delete_feature_context(
        self,
        feature_name: str,
        business_id: str,
    ) -> bool:
        """Delete stored sub-prompt for a feature.

        Args:
            feature_name: Feature name
            business_id: MrCall business ID

        Returns:
            True if deleted, False if not found
        """
        agent_type = f"mrcall_{business_id}_{feature_name}"
        return self.storage.delete_agent_prompt(self.owner_id, agent_type)

    @classmethod
    def get_available_features(cls) -> Dict[str, str]:
        """Get list of available features with descriptions.

        Returns:
            Dict mapping feature_name to description
        """
        return {
            name: info["description"]
            for name, info in cls.FEATURES.items()
        }

    @classmethod
    def get_feature_variables(cls, feature_name: str) -> list:
        """Get variables for a feature.

        Args:
            feature_name: Feature name

        Returns:
            List of variable names
        """
        if feature_name not in cls.FEATURES:
            return []
        return cls.FEATURES[feature_name]["variables"]
