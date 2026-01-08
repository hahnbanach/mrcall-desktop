"""MrCall Agent - Unified multi-tool agent for MrCall configuration.

This is a TRUE AGENT with multiple tools that can:
- Configure welcome message (configure_welcome_message)
- Configure booking settings (configure_booking)
- Show current configuration (get_current_config)
- Answer questions (respond_text)

The trained prompt instructs the agent when to use each tool based on
the user's request.

Inherits from BaseAgent for common functionality (init, prompt loading, etc.)
"""

import logging
from typing import Any, Dict, Optional

from zylch.agents.base_agent import BaseAgent
from zylch.storage.supabase_client import SupabaseStorage
from zylch.agents.mrcall_configurator_trainer import MrCallConfiguratorTrainer

logger = logging.getLogger(__name__)


# Multi-tool schema for the MrCall agent
MRCALL_AGENT_TOOLS = [
    {
        "name": "configure_welcome_message",
        "description": "Modify the welcome message / greeting settings. Use when the user wants to change how the assistant answers the phone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "description": "Map of variable_name -> new_value. All values must be strings.",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_booking",
        "description": "Modify booking/appointment settings. When enabling booking, you MUST set START_BOOKING_PROCESS, BOOKING_HOURS, BOOKING_EVENTS_MINUTES, and ENABLE_GET_CALENDAR_EVENTS together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "object",
                    "description": "Map of variable_name -> new_value. All values must be strings. JSON values must be escaped strings.",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["changes"]
        }
    },
    {
        "name": "get_current_config",
        "description": "Show current configuration for a feature. Use when the user wants to see their settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "enum": ["welcome_message", "booking", "all"],
                    "description": "Which feature to show config for"
                }
            },
            "required": ["feature"]
        }
    },
    {
        "name": "respond_text",
        "description": "Answer questions or explain settings without making changes. Use for informational requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "Your response text"
                }
            },
            "required": ["response"]
        }
    }
]


class MrCallAgent(BaseAgent):
    """Unified MrCall configuration agent with multiple tools.

    Inherits from BaseAgent for common functionality.

    This agent:
    1. Has a trained prompt that combines all feature knowledge
    2. Has multiple tools for different configuration actions
    3. Lets the LLM choose which tool to use based on user intent

    Tools available:
    - configure_welcome_message: Update greeting settings
    - configure_booking: Update booking settings
    - get_current_config: Show current settings
    - respond_text: Answer questions

    Usage:
        agent = MrCallAgent(storage, owner_id, api_key, provider, starchat)
        result = await agent.run("enable booking with 30 minute appointments")
    """

    PROMPT_KEY = 'mrcall'  # Base key - actual key is mrcall_{business_id}
    TOOLS = MRCALL_AGENT_TOOLS

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        provider: str = "anthropic",
        starchat_client=None,
    ):
        """Initialize MrCallAgent.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
            starchat_client: StarChat client for API calls
        """
        super().__init__(storage, owner_id, api_key, provider)
        self.starchat = starchat_client

        # Get business_id for dynamic prompt key
        self.business_id = storage.get_mrcall_link(owner_id)

        logger.info(f"MrCallAgent initialized for owner={owner_id}, business={self.business_id}")

    def _get_trained_prompt(self) -> Optional[str]:
        """Override to use dynamic prompt key based on business_id.

        Returns:
            The trained unified prompt, or None if not trained
        """
        if not self._prompt_loaded:
            if not self.business_id:
                logger.warning("No MrCall assistant linked")
                self._trained_prompt = None
            else:
                # Dynamic key: mrcall_{business_id}
                self._trained_prompt = self.storage.get_agent_prompt(
                    self.owner_id,
                    f"mrcall_{self.business_id}"
                )

            self._prompt_loaded = True

            if self._trained_prompt:
                logger.info("Loaded trained MrCall agent prompt")
            else:
                logger.debug("No trained MrCall agent prompt found")

        return self._trained_prompt

    async def _gather_context(self, instructions: str, **kwargs) -> str:
        """Override - MrCall doesn't need hybrid search context.

        The trained prompt contains all the feature knowledge.
        """
        return ""

    async def run(self, instructions: str, **kwargs) -> Dict[str, Any]:
        """Execute agent with given instructions.

        Overrides BaseAgent.run() to add MrCall-specific checks and prompt format.

        Args:
            instructions: What the user wants to do

        Returns:
            Dict with:
            - tool_used: Name of the tool the agent chose
            - tool_input: Input the agent provided to the tool
            - result: Processed result
            - error: Error message if something went wrong
        """
        # MrCall-specific: Check for linked assistant
        if not self.business_id:
            return {
                'error': 'No MrCall assistant linked. Run `/mrcall list` then `/mrcall link N` first.'
            }

        # Load trained prompt (uses overridden _get_trained_prompt)
        trained_prompt = self._get_trained_prompt()
        if not trained_prompt:
            return {
                'error': 'Agent not trained. Run `/agent mrcall train` first.'
            }

        # Build full prompt with MrCall-specific instructions
        prompt = f"""{trained_prompt}

---

INSTRUCTIONS: {instructions}

Choose the appropriate tool based on what the user wants. Remember:
- ALL values must be strings
- JSON values must be escaped strings like "{{\\"key\\": \\"value\\"}}"
- When enabling booking, set multiple variables together
"""

        logger.debug(f"[MrCallAgent] Sending prompt ({len(prompt)} chars)")

        # Call LLM with tools (uses inherited self.llm from BaseAgent)
        response = await self.llm.create_message(
            messages=[{"role": "user", "content": prompt}],
            tools=self.TOOLS,
            max_tokens=2000
        )

        # Handle tool response (MrCall-specific processing)
        return await self._handle_tool_response(response)

    async def _handle_tool_response(self, response) -> Dict[str, Any]:
        """Handle the LLM's tool response.

        Args:
            response: LLMResponse from create_message

        Returns:
            Dict with tool_used, tool_input, and processed result
        """
        result = {
            'tool_used': None,
            'tool_input': {},
            'result': None,
            'error': None
        }

        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):  # ToolUseBlock
                    result['tool_used'] = block.name
                    result['tool_input'] = block.input

                    # Process based on tool
                    if block.name == 'configure_welcome_message':
                        result['result'] = await self._process_configure(
                            block.input, 'welcome_message'
                        )
                    elif block.name == 'configure_booking':
                        result['result'] = await self._process_configure(
                            block.input, 'booking'
                        )
                    elif block.name == 'get_current_config':
                        result['result'] = await self._process_get_config(block.input)
                    elif block.name == 'respond_text':
                        result['result'] = {
                            'response': block.input.get('response', '')
                        }
                    break
        else:
            # No tool called - extract text response as fallback
            for block in response.content:
                if hasattr(block, 'text'):
                    result['tool_used'] = 'respond_text'
                    result['result'] = {'response': block.text}
                    break

        return result

    async def _process_configure(
        self,
        tool_input: Dict[str, Any],
        feature: str
    ) -> Dict[str, Any]:
        """Process configure_* tool by updating variables via StarChat.

        Args:
            tool_input: Tool input with 'changes' dict
            feature: Feature name for validation

        Returns:
            Dict with success status and updated variables
        """
        changes = tool_input.get('changes', {})

        if not changes:
            return {'success': False, 'error': 'No changes specified'}

        if not self.starchat:
            return {'success': False, 'error': 'StarChat client not available'}

        # Validate variables belong to this feature
        valid_vars = set(MrCallConfiguratorTrainer.FEATURES.get(feature, {}).get('variables', []))

        invalid_vars = [v for v in changes.keys() if v not in valid_vars]
        if invalid_vars:
            return {
                'success': False,
                'error': f'Invalid variables for {feature}: {invalid_vars}'
            }

        # Update each variable via StarChat
        updated = []
        errors = []

        for var_name, new_value in changes.items():
            try:
                result = await self.starchat.update_business_variable(
                    self.business_id,
                    var_name,
                    new_value
                )
                if result is not None:
                    updated.append(f"{var_name}={new_value[:50]}..." if len(new_value) > 50 else f"{var_name}={new_value}")
                else:
                    errors.append(f"Failed to update {var_name}")
            except Exception as e:
                errors.append(f"{var_name}: {str(e)}")
                logger.error(f"Error updating {var_name}: {e}", exc_info=True)

        return {
            'success': len(errors) == 0,
            'updated': updated,
            'errors': errors if errors else None,
            'feature': feature
        }

    async def _process_get_config(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process get_current_config tool by fetching current values.

        Args:
            tool_input: Tool input with 'feature' selection

        Returns:
            Dict with current configuration values
        """
        feature = tool_input.get('feature', 'all')

        if not self.starchat:
            return {'error': 'StarChat client not available'}

        try:
            # Get business config
            business = await self.starchat.get_business_config(self.business_id)
            current_values = business.get('variables', {})

            if feature == 'all':
                # Return all feature variables
                config = {}
                for feat_name, feat_data in MrCallConfiguratorTrainer.FEATURES.items():
                    config[feat_name] = {}
                    for var in feat_data['variables']:
                        if var in current_values:
                            config[feat_name][var] = current_values[var]
                return {'config': config}
            else:
                # Return single feature variables
                feat_data = MrCallConfiguratorTrainer.FEATURES.get(feature)
                if not feat_data:
                    return {'error': f'Unknown feature: {feature}'}

                config = {}
                for var in feat_data['variables']:
                    if var in current_values:
                        config[var] = current_values[var]

                return {'feature': feature, 'config': config}

        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return {'error': str(e)}
