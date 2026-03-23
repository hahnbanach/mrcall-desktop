"""MrCall Agent - Unified multi-tool agent for MrCall configuration.

This is a TRUE AGENT with multiple tools that can:
- Configure inbound welcome message (configure_welcome_inbound)
- Configure outbound welcome message (configure_welcome_outbound)
- Configure booking settings (configure_booking)
- Show current configuration (get_current_config)
- Answer questions (respond_text)

The trained prompt instructs the agent when to use each tool based on
the user's request.

Inherits from SpecializedAgent for common functionality (init, prompt loading, etc.)
"""

import logging
from typing import Any, Dict, Optional

from zylch.agents.base_agent import SpecializedAgent
from zylch.storage.supabase_client import SupabaseStorage
from zylch.agents.trainers import MrCallConfiguratorTrainer


def _build_changes_schema(feature_name: str) -> dict:
    """Build schema for 'changes' property with only valid variable names.

    Uses MrCallConfiguratorTrainer.FEATURES as the single source of truth.

    Args:
        feature_name: Feature key (e.g., 'welcome_inbound', 'booking')

    Returns:
        JSON schema dict with properties for each valid variable
    """
    variables = MrCallConfiguratorTrainer.FEATURES[feature_name]["variables"]
    return {
        "type": "object",
        "properties": {
            var: {"type": "string", "description": f"New value for {var}"}
            for var in variables
        },
        "additionalProperties": False  # Reject unknown variable names
    }

logger = logging.getLogger(__name__)


# Multi-tool schema for the MrCall agent
# Uses _build_changes_schema to constrain variable names to valid options
MRCALL_AGENT_TOOLS = [
    {
        "name": "configure_welcome_inbound",
        "description": "Modify the inbound welcome message / greeting. Use this when user wants to CHANGE, UPDATE, or MODIFY how the assistant answers incoming calls — including making it more formal, informal, adding/removing greetings, etc. You must provide the COMPLETE new prompt text with your modifications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("welcome_inbound")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_welcome_outbound",
        "description": "Modify the outbound welcome message. Use this when user wants to CHANGE, UPDATE, or MODIFY how the assistant starts outgoing calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("welcome_outbound")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_booking",
        "description": "Modify booking/appointment settings. Use this when user wants to CHANGE, UPDATE, or MODIFY booking behavior. When enabling booking, you MUST set START_BOOKING_PROCESS, BOOKING_HOURS, BOOKING_EVENTS_MINUTES, and ENABLE_GET_CALENDAR_EVENTS together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("booking")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_caller_followup",
        "description": "Modify post-call WhatsApp/SMS messages sent to the caller. Use this when user wants to CHANGE, UPDATE, or MODIFY what message callers receive after the call — including enabling/disabling WhatsApp (MrZappa, WATI, Callbell) or SMS channels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("caller_followup")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_conversation",
        "description": "Modify the conversation flow — what the assistant asks or does after the greeting. Use this when user wants to CHANGE, UPDATE, or MODIFY the questions asked, information collected, or steps followed during the call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("conversation")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_knowledge_base",
        "description": "Modify the knowledge base Q&A pairs and general behavior instructions. Use this when user wants to ADD, REMOVE, or CHANGE how the assistant answers specific caller questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("knowledge_base")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_notifications_business",
        "description": "Modify notification settings that inform the business owner about calls — email, WhatsApp, SMS, Firebase push. Use this when user wants to CHANGE, UPDATE, or MODIFY how/where call notifications are sent to the business.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("notifications_business")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_runtime_data",
        "description": "Modify external API integrations (PREFETCH/RUNNINGLOOP/FINAL stages). Use this when user wants to CONNECT external systems — CRM lookups before calls, real-time data queries during calls, or webhook/CRM pushes after calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("runtime_data")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_call_transfer",
        "description": "Modify call forwarding/transfer rules. Use this when user wants to CHANGE, UPDATE, ADD, or REMOVE rules for transferring calls to specific phone numbers based on caller intent or business hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("call_transfer")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "get_current_config",
        "description": "Show current configuration for a feature. ONLY use when the user explicitly asks to SEE, VIEW, or DISPLAY their current settings WITHOUT making changes. Do NOT use this for modification requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "feature": {
                    "type": "string",
                    "enum": ["welcome_inbound", "welcome_outbound", "booking", "caller_followup", "conversation", "knowledge_base", "notifications_business", "runtime_data", "call_transfer", "all"],
                    "description": "Which feature to show config for"
                }
            },
            "required": ["feature"]
        }
    },
    {
        "name": "respond_text",
        "description": "Answer questions, explain settings, or interpret current configuration. Use for: YES/NO questions ('is booking enabled?', 'does it answer formally?'), behavioral questions ('how does it greet callers?'), and any request to INTERPRET or EXPLAIN settings rather than just show raw values.",
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


class MrCallAgent(SpecializedAgent):
    """Unified MrCall configuration agent with multiple tools.

    Inherits from SpecializedAgent for common functionality.

    This agent:
    1. Has a trained prompt that combines all feature knowledge
    2. Has multiple tools for different configuration actions
    3. Lets the LLM choose which tool to use based on user intent

    Tools available:
    - configure_welcome_inbound: Update inbound greeting settings
    - configure_welcome_outbound: Update outbound greeting settings
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

        Overrides SpecializedAgent.run() to add MrCall-specific checks and prompt format.

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
        logger.info(f"[MrCallAgent] Calling LLM with {len(self.TOOLS)} tools")

        # Call LLM with tools (uses inherited self.llm from SpecializedAgent)
        try:
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}],
                tools=self.TOOLS,
                max_tokens=2000
            )
            logger.info(f"[MrCallAgent] LLM response received: stop_reason={response.stop_reason}")
            logger.debug(f"[MrCallAgent] LLM response content blocks: {len(response.content)}")
            for i, block in enumerate(response.content):
                if hasattr(block, 'name'):
                    logger.info(f"[MrCallAgent] Content block {i}: tool_use name={block.name}")
                    logger.debug(f"[MrCallAgent] Content block {i}: tool_input={block.input}")
                elif hasattr(block, 'text'):
                    logger.debug(f"[MrCallAgent] Content block {i}: text={block.text[:200]}...")
                else:
                    logger.debug(f"[MrCallAgent] Content block {i}: type={type(block)}")
        except Exception as e:
            logger.error(f"[MrCallAgent] LLM call failed: {e}", exc_info=True)
            return {'error': f'LLM call failed: {str(e)}'}

        # Handle tool response (MrCall-specific processing)
        return await self._handle_tool_response(response)

    async def _handle_tool_response(self, response) -> Dict[str, Any]:
        """Handle the LLM's tool response.

        Args:
            response: LLMResponse from create_message

        Returns:
            Dict with tool_used, tool_input, and processed result
        """
        logger.info(f"[MrCallAgent] _handle_tool_response: stop_reason={response.stop_reason}")

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
                    logger.info(f"[MrCallAgent] Processing tool: {block.name}")
                    logger.debug(f"[MrCallAgent] Tool input: {block.input}")

                    # Process based on tool
                    if block.name == 'configure_welcome_inbound':
                        logger.info("[MrCallAgent] Calling _process_configure for welcome_inbound")
                        result['result'] = await self._process_configure(
                            block.input, 'welcome_inbound'
                        )
                    elif block.name == 'configure_welcome_outbound':
                        logger.info("[MrCallAgent] Calling _process_configure for welcome_outbound")
                        result['result'] = await self._process_configure(
                            block.input, 'welcome_outbound'
                        )
                    elif block.name == 'configure_booking':
                        logger.info("[MrCallAgent] Calling _process_configure for booking")
                        result['result'] = await self._process_configure(
                            block.input, 'booking'
                        )
                    elif block.name == 'configure_caller_followup':
                        logger.info("[MrCallAgent] Calling _process_configure for caller_followup")
                        result['result'] = await self._process_configure(
                            block.input, 'caller_followup'
                        )
                    elif block.name == 'configure_conversation':
                        logger.info("[MrCallAgent] Calling _process_configure for conversation")
                        result['result'] = await self._process_configure(
                            block.input, 'conversation'
                        )
                    elif block.name == 'configure_knowledge_base':
                        logger.info("[MrCallAgent] Calling _process_configure for knowledge_base")
                        result['result'] = await self._process_configure(
                            block.input, 'knowledge_base'
                        )
                    elif block.name == 'configure_notifications_business':
                        logger.info("[MrCallAgent] Calling _process_configure for notifications_business")
                        result['result'] = await self._process_configure(
                            block.input, 'notifications_business'
                        )
                    elif block.name == 'configure_runtime_data':
                        logger.info("[MrCallAgent] Calling _process_configure for runtime_data")
                        result['result'] = await self._process_configure(
                            block.input, 'runtime_data'
                        )
                    elif block.name == 'configure_call_transfer':
                        logger.info("[MrCallAgent] Calling _process_configure for call_transfer")
                        result['result'] = await self._process_configure(
                            block.input, 'call_transfer'
                        )
                    elif block.name == 'get_current_config':
                        logger.info("[MrCallAgent] Calling _process_get_config")
                        result['result'] = await self._process_get_config(block.input)
                    elif block.name == 'respond_text':
                        logger.info("[MrCallAgent] respond_text tool used")
                        result['result'] = {
                            'response': block.input.get('response', '')
                        }
                    else:
                        logger.warning(f"[MrCallAgent] Unknown tool: {block.name}")
                    break
        else:
            # No tool called - extract text response as fallback
            logger.info("[MrCallAgent] No tool_use, extracting text response")
            for block in response.content:
                if hasattr(block, 'text'):
                    result['tool_used'] = 'respond_text'
                    result['result'] = {'response': block.text}
                    logger.debug(f"[MrCallAgent] Text fallback: {block.text[:200]}...")
                    break

        logger.info(f"[MrCallAgent] _handle_tool_response result: tool_used={result['tool_used']}, has_result={result['result'] is not None}, error={result.get('error')}")
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
        logger.info(f"[MrCallAgent] _process_configure: feature={feature}, tool_input={tool_input}")

        changes = tool_input.get('changes', {})
        logger.info(f"[MrCallAgent] Changes to apply: {list(changes.keys())}")

        if not changes:
            logger.warning("[MrCallAgent] No changes specified in tool_input")
            return {'success': False, 'error': 'No changes specified'}

        if not self.starchat:
            logger.error("[MrCallAgent] StarChat client not available")
            return {'success': False, 'error': 'StarChat client not available'}

        # Validate variables belong to this feature
        valid_vars = set(MrCallConfiguratorTrainer.FEATURES.get(feature, {}).get('variables', []))
        logger.debug(f"[MrCallAgent] Valid variables for {feature}: {valid_vars}")

        invalid_vars = [v for v in changes.keys() if v not in valid_vars]
        if invalid_vars:
            logger.warning(f"[MrCallAgent] Invalid variables: {invalid_vars}")
            return {
                'success': False,
                'error': f'Invalid variables for {feature}: {invalid_vars}'
            }

        # Update each variable via StarChat
        updated = []
        errors = []

        for var_name, new_value in changes.items():
            logger.info(f"[MrCallAgent] Updating {var_name} to: {new_value[:100]}{'...' if len(new_value) > 100 else ''}")
            try:
                result = await self.starchat.update_business_variable(
                    self.business_id,
                    var_name,
                    new_value
                )
                logger.info(f"[MrCallAgent] update_business_variable result for {var_name}: {result.get('result', {}).get('variables', {}).get(var_name, 'variable not found')}")
                if result is not None:
                    updated.append(f"{var_name}={new_value}")
                    logger.info(f"[MrCallAgent] Successfully updated {var_name}")
                else:
                    errors.append(f"Failed to update {var_name}")
                    logger.warning(f"[MrCallAgent] update_business_variable returned None for {var_name}")
            except Exception as e:
                errors.append(f"{var_name}: {str(e)}")
                logger.error(f"[MrCallAgent] Error updating {var_name}: {e}", exc_info=True)

        final_result = {
            'success': len(errors) == 0,
            'updated': updated,
            'errors': errors if errors else None,
            'feature': feature
        }
        logger.info(f"[MrCallAgent] _process_configure final result: {final_result}")
        return final_result

    async def _process_get_config(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process get_current_config tool by fetching current values.

        Args:
            tool_input: Tool input with 'feature' selection

        Returns:
            Dict with current configuration values
        """
        feature = tool_input.get('feature', 'all')
        logger.debug(f"[MrCallAgent] _process_get_config: feature={feature}, business_id={self.business_id}")

        if not self.starchat:
            logger.debug(f"[MrCallAgent] _process_get_config: StarChat client not available")
            return {'error': 'StarChat client not available'}

        try:
            # Get business config
            logger.debug(f"[MrCallAgent] _process_get_config: get_business_config(business_id={self.business_id})")
            business = await self.starchat.get_business_config(self.business_id)
            current_values = business.get('variables', {})
            logger.debug(f"[MrCallAgent] _process_get_config: template={business.get('template')}, vars_count={len(current_values)}")

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
