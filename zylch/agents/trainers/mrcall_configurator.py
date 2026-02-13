"""MrCall Configurator Trainer - Generates feature-specific sub-prompts from MrCall config.

Analyzes MrCall assistant configuration to generate self-contained sub-prompts that:
1. Document available variables and their meaning
2. Describe current behavior in plain language
3. List what can/cannot be changed
4. Include raw prompt value for modification

Each sub-prompt is stored per feature per business in the agent_prompts table.

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Meta-prompt for generating welcome message sub-prompts
# Uses {variables_context} placeholder for dynamically-fetched StarChat metadata
WELCOME_MESSAGE_META_PROMPT = """You are analyzing the welcome message configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure the welcome message.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

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
- `%%crm.contact.variables.X%%` - Data about the caller (the new / recurrent contact)
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

---

OUTPUT ONLY THE SUB-PROMPT TEXT. No explanations, no additional markdown. Just the sub-prompt itself."""


# Meta-prompt for generating booking sub-prompts
# Uses {variables_context} placeholder for dynamically-fetched StarChat metadata
BOOKING_META_PROMPT = """You are analyzing the booking configuration for a MrCall AI phone assistant.

Your task: Generate a self-contained sub-prompt that teaches another LLM how to configure booking.

## VARIABLE METADATA FROM STARCHAT

{variables_context}

## CRITICAL: ALL VALUES ARE STRINGS

Every MrCall variable value is a string. There are NO native booleans, numbers, or objects.
- Booleans: "true" or "false" (strings, not true/false primitives)
- Numbers: "30", "60", "24" (strings, not integers)
- JSON, e.g. BOOKING_HOURS=" {{\\""monday\\"":[\\""09:00-08:15\\""],\\""tuesday\\"":[\\""08:00-08:15\\""],\\""wednesday\\"":[\\""08:00-08:15\\""]}}" (valid JSON serialized as string with escaped quotes)

## VARIABLE RELATIONSHIPS

The configurator LLM must understand these dependencies:

### Master Switch
- START_BOOKING_PROCESS is the master switch
- When enabling booking (START_BOOKING_PROCESS="true"), MUST also configure:
  - BOOKING_HOURS (JSON string with available slots)
  - BOOKING_EVENTS_MINUTES (appointment duration)
  - ENABLE_GET_CALENDAR_EVENTS "true" / "false" (callers can ask about their appointment)
  - ENABLE_CLEAR_CALENDAR_EVENT "true" / "false" (callers can cancel their appointment)
   - BOOKING_DAYS_TO_GENERATE: How many days in advance can the caller book
  - BOOKING_SHORTEST_NOTICE: Minimum notice in hours for appointments
   - BOOKING_ONLY_WORKING_HOURS: 
   - BOOKING_MULTIPLE_ALLOWED",
    - BOOKING_TITLE",
    - BOOKING_DESCRIPTION",
    - BOOKING_PRE_INSTRUCTION",
    - BOOKING_LAST_INSTRUCTION",
    - COMMUNICATE_BOOKING_MESSAGE",


### Slot Configuration
- BOOKING_HOURS format: "{{\\"monday\\": [{{\\"09:00:"17:00\\"}}], \\"tuesday\\": [...]}}"
  (Valid JSON embedded in a string with escaped quotes)
- BOOKING_EVENTS_MINUTES determines slot granularity (e.g., "30" for 30-min slots)

### Availability Rules
- BOOKING_DAYS_TO_GENERATE: how many days ahead to show (e.g., "14")
- BOOKING_SHORTEST_NOTICE: minimum hours notice (e.g., "2")
- BOOKING_MULTIPLE_ALLOWED: can same caller book multiple times

### Appointment Content
- BOOKING_TITLE: template for calendar event title
- BOOKING_DESCRIPTION: template for event description
- COMMUNICATE_BOOKING_MESSAGE: what assistant says to confirm

### When Booking Disabled
- NO_BOOKING_INSTRUCTIONS: what to say when booking not available
- Only relevant when START_BOOKING_PROCESS="false"

## COMMON USER INTENTS → VARIABLE MAPPINGS

Teach the configurator these patterns:

**"Enable booking"** →
  START_BOOKING_PROCESS = "true"
  BOOKING_HOURS = "{{\\"monday\\": [{{\\"09:00-17:00\\"}}], \\"tuesday\\": [{{\\"09:00-17:00\\"}}], \\"wednesday\\": [{{\\"09:00-17:00\\"}}], \\"thursday\\": [{{\\"09:00-17:00\\"}}], \\"friday\\": [{{\\"09:00-17:00\\"}}]}}"
  BOOKING_EVENTS_MINUTES = "30"
  ENABLE_GET_CALENDAR_EVENTS = "true"

**"Disable booking"** →
  START_BOOKING_PROCESS = "false"

**"30-minute appointments"** →
  BOOKING_EVENTS_MINUTES = "30"

**"1-hour appointments"** →
  BOOKING_EVENTS_MINUTES = "60"

**"Only mornings"** →
  BOOKING_HOURS = "{{\\"monday\\": [{{\\"09:00-12:00\\"}}], \\"tuesday\\": [{{\\"09:00-12:00\\"}}], \\"wednesday\\": [{{\\"09:00-12:00\\"}}], \\"thursday\\": [{{\\"09:00-12:00\\"}}], \\"friday\\": [{{\\"09:00-12:00\\"}}]}}"

**"Require 24 hours notice"** →
  BOOKING_SHORTEST_NOTICE = "24"

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these sections:

### SECTION 1: CURRENT BOOKING STATUS
Is booking enabled? What are the current hours/duration?

### SECTION 2: VARIABLE RELATIONSHIPS
Explain which variables must be set together.

### SECTION 3: INTENT → CHANGES MAPPING
List common requests and which variables to change.

### SECTION 4: VARIABLE TYPES & VALIDATION
- Booleans: "true"/"false" (string, not primitive)
- Integers: "30" (string)
- JSON: Valid JSON string for BOOKING_HOURS

### SECTION 5: ALL CURRENT VALUES
You MUST explicitly list the current value of EVERY variable provided in the VARIABLE METADATA.
The configurator agent relies on this section to know the current state.
Format:
- VARIABLE_NAME: "exact_current_value"

---

OUTPUT ONLY THE SUB-PROMPT TEXT."""


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
            "description": "How the assistant answers the phone",  # for devs
            "display_name": "How the assistant answers the phone",  # for users
            "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
            "dynamic_context": True,  # Uses _build_variables_context for metadata
        },
        "booking": {
            "variables": [
                "START_BOOKING_PROCESS",
                "BOOKING_TRIGGER",
                "NO_BOOKING_INSTRUCTIONS",
                "ENABLE_GET_CALENDAR_EVENTS",
                "ENABLE_CLEAR_CALENDAR_EVENTS",
                "BOOKING_HOURS",
                "BOOKING_EVENTS_MINUTES",
                "BOOKING_DAYS_TO_GENERATE",
                "BOOKING_SHORTEST_NOTICE",
                "BOOKING_ONLY_WORKING_HOURS",
                "BOOKING_MULTIPLE_ALLOWED",
                # BOOKING_CALENDAR_ID is auto-set via OAuth, not user-configurable
                "BOOKING_TITLE",
                "BOOKING_DESCRIPTION",
                "BOOKING_PRE_INSTRUCTION",
                "BOOKING_LAST_INSTRUCTION",
                "COMMUNICATE_BOOKING_MESSAGE",
            ],
            "display_name": "How your MrCall assistant manages booking requests",
            "meta_prompt": BOOKING_META_PROMPT,
            "dynamic_context": True,  # Uses _build_variables_context for metadata
        }
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

    async def _build_variables_context(
        self,
        business_id: str,
        variable_names: List[str],
    ) -> str:
        """Build variables context from StarChat metadata.

        Fetches variable schema (type, description, default) and current values,
        then formats them for injection into the meta-prompt.

        Args:
            business_id: MrCall business ID
            variable_names: List of variable names to include

        Returns:
            Formatted string with metadata for each variable
        """
        # Get business config for current values and template
        logger.debug(f"[MrCallConfiguratorTrainer] _build_variables_context(business_id={business_id}, vars={variable_names})")
        business = await self.starchat.get_business_config(business_id)
        logger.debug(f"[MrCallConfiguratorTrainer] get_business_config -> found={business is not None}")
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        current_values = business.get("variables", {})
        template = business.get("template", "businesspro")
        # languageCountry for default value fallback (e.g. "it_IT" -> "it-IT")
        raw_lang = business.get("languageCountry", "")
        biz_lang = raw_lang.replace("_", "-") if raw_lang else ""
        biz_lang_short = biz_lang[:2] if biz_lang else ""
        logger.debug(f"[MrCallConfiguratorTrainer] template={template}, current_values_count={len(current_values)}, languageCountry={raw_lang} -> biz_lang={biz_lang}")

        # Get schema for metadata (type, description, default)
        # nested=True with languageDescriptions returns localized flat fields
        # Response is an array of collections: [{variables: [{name, type, description, defaultValue, ...}]}]
        raw_schema = await self.starchat.get_variable_schema(
            template_name=template,
            language=biz_lang or "en-US",
            nested=True,
            language_descriptions=biz_lang_short or "en",
        )
        logger.debug(f"[MrCallConfiguratorTrainer] get_variable_schema(template={template}, nested=True, langDesc={biz_lang_short or 'en'}) -> type={type(raw_schema).__name__}, len={len(raw_schema) if raw_schema else 0}")

        # Flatten collections array into {var_name: var_data}
        # variables arrays may contain nested lists (dashboard uses .flat())
        schema: Dict[str, Any] = {}
        if isinstance(raw_schema, list):
            for collection in raw_schema:
                if not isinstance(collection, dict):
                    continue
                for item in collection.get("variables", []):
                    # Handle nested lists: [[{var}, {var}], [{var}]]
                    vars_to_process = item if isinstance(item, list) else [item]
                    for var in vars_to_process:
                        if isinstance(var, dict):
                            name = var.get("name")
                            if name:
                                schema[name] = var
        elif isinstance(raw_schema, dict):
            schema = raw_schema
        logger.debug(f"[MrCallConfiguratorTrainer] flattened schema: {len(schema)} variables")

        # Build context for each variable
        lines = []
        for var_name in variable_names:
            var_schema = schema.get(var_name, {})

            logger.debug(
                f"[MrCallConfiguratorTrainer] _build_variables_context: var={var_name}, "
                f"schema_keys={list(var_schema.keys())}, "
                f"description='{var_schema.get('description', '')}', "
                f"defaultValue='{var_schema.get('defaultValue', '')}'"
            )

            # Use server-localized flat keys (populated by languageDescriptions param)
            desc = var_schema.get("description", "")
            default = var_schema.get("defaultValue", "")
            var_type = var_schema.get("type", "unknown")
            current = current_values.get(var_name, "Not set")

            logger.debug(f"[MrCallConfiguratorTrainer] _build_variables_context: var={var_name}, desc='{desc}', default='{default}', current='{current}'")

            if current == "Not set":
                # Diagnostic logging for missing variable
                matching_keys = [k for k in current_values.keys() if "BOOKING" in k]
                logger.warning(f"[MrCallConfiguratorTrainer] Variable {var_name} not found in current_values. BusinessID={business_id}")
                logger.warning(f"[MrCallConfiguratorTrainer] Available keys with 'BOOKING': {matching_keys}")
                logger.debug(f"[MrCallConfiguratorTrainer] All available keys: {list(current_values.keys())[:50]}...")

            lines.append(f"""
**{var_name}**
- Type: {var_type}
- Description: {desc}
- Default: {default}
- Current Value: {current}
""")

        return "\n".join(lines)

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

        # All features use dynamic_context - fetch metadata from StarChat
        variables_context = await self._build_variables_context(
            business_id, variable_names
        )
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: variables_context prefix: {variables_context[:500]}...")
        meta_prompt = meta_prompt_template.format(
            variables_context=variables_context
        )
        # For metadata, use total length of all variables
        business = await self.starchat.get_business_config(business_id)
        current_values = business.get("variables", {})
        total_length = sum(
            len(str(current_values.get(v, ""))) for v in variable_names
        )

        logger.info(
            f"Generating sub-prompt for {feature_name} "
            f"(provider: {self.provider}, model: {self.model})"
        )
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: calling LLM for {feature_name}, meta_prompt_len={len(meta_prompt)}")

        response = await self.client.create_message(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}],
        )

        sub_prompt = response.content[0].text.strip()
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt generated, len={len(sub_prompt)}")
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt content start: {sub_prompt[:500]}...")
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: sub-prompt content end: ...{sub_prompt[-500:]}")

        # 3. Store in agent_prompts
        agent_type = f"mrcall_{business_id}_{feature_name}"
        metadata = {
            "business_id": business_id,
            "feature": feature_name,
            "variables": variable_names,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prompt_length": total_length,
        }

        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: storing agent_prompt for {agent_type}")
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
