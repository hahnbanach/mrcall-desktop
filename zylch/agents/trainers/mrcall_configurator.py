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

import json
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

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

These variables are resolved at runtime during the phone call. Use `%%var%%` or `%%var=fallback%%` syntax in prompts.

{conversation_variables_context}

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

## CONVERSATION VARIABLES AVAILABLE IN PROMPTS

These variables are resolved at runtime during the phone call. Use `%%var%%` or `%%var=fallback%%` syntax in prompts.

{conversation_variables_context}

## CRITICAL: ALL VALUES ARE STRINGS

Every MrCall variable value is a string. There are NO native booleans, numbers, or objects.
- Booleans: "true" or "false" (strings, not true/false primitives)
- Numbers: "30", "60", "24" (strings, not integers)
- JSON, e.g. BOOKING_HOURS=" {{\\""monday\\"":[\\""09:00-08:15\\""],\\""tuesday\\"":[\\""08:00-08:15\\""],\\""wednesday\\"":[\\""08:00-08:15\\""]}}" (valid JSON serialized as string with escaped quotes)

## VARIABLE RELATIONSHIPS

Each variable in the VARIABLE METADATA above may include these annotations:
- **"Depends On: VAR_X"**: This variable is only relevant when VAR_X is enabled/configured. VAR_X is the parent switch.
- **"Modifiable: No (locked by subscription plan)"**: This variable cannot be changed for the current subscription plan. Do NOT attempt to modify it. If the user asks, explain it's locked by their subscription plan.
- **"Visible: No"**: This variable is hidden from end users. Do NOT include it in the generated sub-prompt.
- **"Admin: Yes"**: This variable is for administrators only. Do NOT include it in the generated sub-prompt.

### Rules for generating the sub-prompt
1. **Exclude** variables marked `Visible: No` or `Admin: Yes` from the generated sub-prompt entirely
2. **Include** variables marked `Modifiable: No` in the sub-prompt, but clearly mark them as locked by the subscription plan
3. Show dependency chains from "Depends On" annotations so the configurator agent understands relationships
4. When enabling a parent switch (e.g., setting it to "true"), ASK the user if they also want to configure its dependent variables (they may already have values from a previous configuration)
5. When disabling a parent switch, dependent variables become inactive — no need to modify them
6. If a parent switch is LOCKED, all its dependent variables are effectively locked too

### Value Format Reference
- BOOKING_HOURS format: "{{\\"monday\\": [{{\\"09:00-17:00\\"}}], \\"tuesday\\": [...]}}"
  (Valid JSON embedded in a string with escaped quotes)
- BOOKING_EVENTS_MINUTES determines slot granularity (e.g., "30" for 30-min slots)
- BOOKING_DAYS_TO_GENERATE: how many days ahead to show (e.g., "14")
- BOOKING_SHORTEST_NOTICE: minimum hours notice (e.g., "2")

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

### SECTION 2: VARIABLE RELATIONSHIPS & RESTRICTIONS
Based on the "Depends On" and "LOCKED" annotations in the metadata above:
- Which variables are parent switches (no dependencies)
- Which variables depend on others (from their "Depends On" field)
- Which variables are locked and cannot be modified
- If a parent is locked, note that all its dependents are effectively locked too

### SECTION 3: INTENT → CHANGES MAPPING
List common requests and which variables to change. Only suggest changes to modifiable variables whose parent dependencies are enabled.

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
        business: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build variables context from StarChat metadata.

        Fetches variable schema (type, description, default) and current values,
        then formats them for injection into the meta-prompt.

        Args:
            business_id: MrCall business ID
            variable_names: List of variable names to include
            business: Pre-fetched business config (avoids redundant API call)

        Returns:
            Formatted string with metadata for each variable
        """
        # Get business config for current values and template
        logger.debug(f"[MrCallConfiguratorTrainer] _build_variables_context(business_id={business_id}, vars={variable_names})")
        if business is None:
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

        # Build context for each variable — include ALL variables with full metadata
        # so the sub-prompt-generating LLM has the complete picture
        lines = []
        for var_name in variable_names:
            var_schema = schema.get(var_name, {})

            # Use server-localized flat keys (populated by languageDescriptions param)
            human_name = var_schema.get("humanName", "")
            desc = var_schema.get("description", "")
            default = var_schema.get("defaultValue", "")
            var_type = var_schema.get("type", "unknown")
            current = current_values.get(var_name, "Not set")
            modifiable = var_schema.get("modifiable", True)
            visible = var_schema.get("visible", True)
            admin = var_schema.get("admin", False)

            # Flatten depends_on from [["VAR"]] to ["VAR"]
            depends_on_raw = var_schema.get("depends_on", [])
            depends_on = []
            if isinstance(depends_on_raw, list):
                for dep_item in depends_on_raw:
                    if isinstance(dep_item, list) and dep_item:
                        depends_on.append(dep_item[0])
                    elif isinstance(dep_item, str):
                        depends_on.append(dep_item)

            logger.debug(f"[MrCallConfiguratorTrainer] var={var_name}, type={var_type}, humanName='{human_name}', desc='{desc}', default='{default}', current='{current}', modifiable={modifiable}, visible={visible}, admin={admin}, depends_on={depends_on}")

            if current == "Not set":
                matching_keys = [k for k in current_values.keys() if "BOOKING" in k]
                logger.warning(f"[MrCallConfiguratorTrainer] Variable {var_name} not found in current_values. BusinessID={business_id}")
                logger.warning(f"[MrCallConfiguratorTrainer] Available keys with 'BOOKING': {matching_keys}")

            var_context = f"""
**{var_name}**
- Type: {var_type}
- Human Name: {human_name}
- Description: {desc}
- Default: {default}
- Current Value: {current}"""

            if depends_on:
                var_context += f"\n- Depends On: {', '.join(depends_on)}"
            if not modifiable:
                var_context += "\n- Modifiable: No (locked by subscription plan)"
            if not visible:
                var_context += "\n- Visible: No"
            if admin:
                var_context += "\n- Admin: Yes"

            lines.append(var_context)

        return "\n".join(lines)

    async def _build_conversation_variables_context(
        self,
        business_id: str,
        business: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build conversation variables context for injection into meta-prompts.

        Fetches ASSISTANT_TOOL_VARIABLE_EXTRACTION from the business config
        to discover which caller variables are available, and combines them
        with the static public:* variables and exportable aliases.

        Args:
            business_id: MrCall business ID
            business: Pre-fetched business config (avoids redundant API call)

        Returns:
            Formatted markdown string describing all conversation variables
        """
        if business is None:
            business = await self.starchat.get_business_config(business_id)
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        current_values = business.get("variables", {})

        # --- Dynamic: parse ASSISTANT_TOOL_VARIABLE_EXTRACTION ---
        # Format: [["VAR_NAME", "Description", "required", "forget"], ...]
        extraction_vars = []
        raw_extraction = current_values.get("ASSISTANT_TOOL_VARIABLE_EXTRACTION", "")
        if raw_extraction:
            try:
                parsed = json.loads(raw_extraction)
                for entry in parsed:
                    if isinstance(entry, list) and len(entry) >= 2:
                        var_name = entry[0].strip()
                        description = entry[1]
                        forget = entry[3].lower() == "true" if len(entry) > 3 else False
                        extraction_vars.append((var_name, description, forget))
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning(
                    f"[MrCallConfiguratorTrainer] Failed to parse "
                    f"ASSISTANT_TOOL_VARIABLE_EXTRACTION: {e}"
                )

        logger.debug(
            f"[MrCallConfiguratorTrainer] _build_conversation_variables_context: "
            f"extraction_vars={len(extraction_vars)}"
        )

        lines = []

        # Section 1: Caller-extracted variables
        lines.append("### Caller Information (extracted from conversation)")
        lines.append("")
        lines.append(
            "| Variable | Syntax in prompts | Description | Persists across calls |"
        )
        lines.append("|---|---|---|---|")
        if extraction_vars:
            for var_name, description, forget in extraction_vars:
                syntax = f"%%crm.contact.variables.{var_name}%%"
                persists = "No (fresh each call)" if forget else "Yes"
                lines.append(f"| {var_name} | `{syntax}` | {description} | {persists} |")
        else:
            # Fallback defaults (from sanitizeBusinessVariables.sc)
            lines.append(
                "| FIRST_NAME | `%%crm.contact.variables.FIRST_NAME%%` "
                "| Caller's first name | Yes |"
            )
            lines.append(
                "| FAMILY_NAME | `%%crm.contact.variables.FAMILY_NAME%%` "
                "| Caller's family name | Yes |"
            )
            lines.append(
                "| CALL_REASON | `%%crm.contact.variables.CALL_REASON%%` "
                "| Reason for the call | Yes |"
            )

        # Section 2: Date/time and business status (static, from public:* variables)
        lines.append("")
        lines.append("### Date/Time & Business Status")
        lines.append("")
        lines.append("| Variable | Syntax in prompts | Description |")
        lines.append("|---|---|---|")
        lines.append(
            '| HUMANIZED_TODAY | `%%public:HUMANIZED_TODAY%%` '
            '| Current date in natural language (e.g., "venerdì 20 febbraio 2026") |'
        )
        lines.append(
            '| HUMANIZED_NOW | `%%public:HUMANIZED_NOW%%` '
            '| Current time in natural language (e.g., "Ore 14 e 30 minuti") |'
        )
        lines.append(
            '| HUMANIZED_DAY_OF_WEEK | `%%public:HUMANIZED_DAY_OF_WEEK%%` '
            '| Current day of week name (e.g., "venerdì") |'
        )
        lines.append(
            "| HUMANIZED_TOMORROW_DAY_OF_WEEK "
            "| `%%public:HUMANIZED_TOMORROW_DAY_OF_WEEK%%` "
            "| Tomorrow's day of week name |"
        )
        lines.append(
            '| BUSINESS_OPEN | `%%public:BUSINESS_OPEN%%` '
            '| Whether the business is currently open ("true"/"false") |'
        )
        lines.append(
            '| OPENING_HOURS_TEXT | `%%public:OPENING_HOURS_TEXT%%` '
            '| Human-readable opening hours schedule |'
        )
        lines.append(
            '| HUMANIZED_NEXT_CHANGE_STATUS_DATETIME '
            '| `%%public:HUMANIZED_NEXT_CHANGE_STATUS_DATETIME%%` '
            '| When business will next open/close (e.g., "chiuderemo alle 18:00") |'
        )

        # Section 3: Other caller info (exportable aliases from defineExportableVariables.sc)
        lines.append("")
        lines.append("### Other Caller Info")
        lines.append("")
        lines.append("| Variable | Syntax in prompts | Description |")
        lines.append("|---|---|---|")
        lines.append(
            "| CALLER_NUMBER | `%%CALLER_NUMBER%%` or `%%HB_FROM_NUMBER%%` "
            "| Caller's phone number |"
        )
        lines.append(
            '| RECURRENT_CONTACT | `%%RECURRENT_CONTACT%%` '
            '| Whether this caller has called before ("true"/"false") |'
        )
        lines.append(
            '| OUTBOUND_CALL | `%%OUTBOUND_CALL%%` '
            '| Whether this is an outbound call ("true"/"false") |'
        )

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

        # Fetch business config once — reused by both context builders + metadata
        business = await self.starchat.get_business_config(business_id)
        if not business:
            raise ValueError(f"Business not found: {business_id}")

        # All features use dynamic_context - fetch metadata from StarChat
        variables_context = await self._build_variables_context(
            business_id, variable_names, business=business
        )
        logger.debug(f"[MrCallConfiguratorTrainer] train_feature: variables_context prefix: {variables_context[:500]}...")

        # Build conversation variables context (caller info, public vars, aliases)
        conversation_variables_context = await self._build_conversation_variables_context(
            business_id, business=business
        )
        logger.debug(
            f"[MrCallConfiguratorTrainer] train_feature: "
            f"conversation_variables_context length: {len(conversation_variables_context)}"
        )

        meta_prompt = meta_prompt_template.format(
            variables_context=variables_context,
            conversation_variables_context=conversation_variables_context,
        )
        # For metadata, use total length of all variables
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
