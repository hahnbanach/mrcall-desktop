"""MrCall Agent - Unified multi-tool agent for MrCall configuration.

This is a TRUE AGENT with multiple tools that can:
- Configure 9 features (welcome, booking, knowledge base, transfer, etc.)
- Answer questions and explain settings (respond_text)

Architecture (post-refactor):
- Runtime templates replace train-time LLM-generated sub-prompts
- Live StarChat values fetched on every run() call (no stale data)
- Conversation history support for multi-turn context

Inherits from SpecializedAgent for common functionality (init, prompt loading, etc.)
"""

import logging
from typing import Any, Dict, List, Optional

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
        "name": "respond_text",
        "description": "Answer ANY question about the current configuration: 'how does it greet callers?', 'is booking enabled?', 'what are my settings?', 'does it answer formally?'. Always explain in human-friendly language, never show raw variable names or template syntax.",
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
    - respond_text: Answer questions and explain current settings

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

    async def _build_runtime_prompt(self) -> str:
        """Build system prompt with LIVE values from StarChat.

        Fetches current business config and variable schema, then fills
        runtime templates with live data. No train step required.

        Returns:
            Complete system prompt string with all feature knowledge + current values

        Raises:
            ValueError: If business not found or StarChat unavailable
        """
        from zylch.agents.mrcall_templates import FEATURE_TEMPLATES, UNIFIED_RUNTIME_TEMPLATE
        from zylch.agents.mrcall_context import (
            build_variables_context,
            build_conversation_variables_context,
            fetch_and_flatten_schema,
        )

        if not self.starchat:
            raise ValueError("StarChat client not available")

        # Single API call: fetch business config with all current variable values
        business = await self.starchat.get_business_config(self.business_id)
        if not business:
            raise ValueError(f"Business not found: {self.business_id}")
        logger.debug(
            f"[MrCallAgent] Fetched business config: "
            f"template={business.get('template')}, "
            f"vars_count={len(business.get('variables', {}))}"
        )

        # Single API call: fetch variable schema (types, descriptions, defaults)
        schema = await fetch_and_flatten_schema(self.starchat, business)
        logger.debug(f"[MrCallAgent] Fetched variable schema: {len(schema)} variables")

        # Build conversation variables context once (shared across features)
        conv_vars_ctx = await build_conversation_variables_context(
            self.starchat, self.business_id, business=business
        )

        # Fill each feature template with live values
        feature_sections = []
        for feature_name, template in FEATURE_TEMPLATES.items():
            variables = MrCallConfiguratorTrainer.FEATURES.get(
                feature_name, {}
            ).get("variables", [])

            vars_ctx = await build_variables_context(
                self.starchat,
                self.business_id,
                variables,
                business=business,
                schema=schema,
            )

            filled = template.format(
                variables_context=vars_ctx,
                conversation_variables_context=conv_vars_ctx,
            )
            display_name = MrCallConfiguratorTrainer.FEATURES.get(
                feature_name, {}
            ).get("display_name", feature_name)
            feature_sections.append(
                f"### {feature_name.upper()}\n**{display_name}**\n\n{filled}"
            )

        # Combine into unified prompt
        system_prompt = UNIFIED_RUNTIME_TEMPLATE.format(
            feature_sections="\n\n".join(feature_sections)
        )

        # Inject config memory (past configuration decisions)
        from zylch.agents.mrcall_memory import load_config_memory
        config_memory = load_config_memory(self.owner_id, self.business_id)
        if config_memory:
            system_prompt += (
                "\n\n## PREVIOUS CONFIGURATION DECISIONS\n\n"
                "The following changes were made in previous sessions. "
                "Use this context to understand the business's setup:\n\n"
                f"{config_memory}\n"
            )
            logger.info(
                f"[MrCallAgent] Injected config memory: {len(config_memory)} chars"
            )

        logger.info(
            f"[MrCallAgent] Built runtime prompt: {len(system_prompt)} chars, "
            f"{len(feature_sections)} features"
        )
        return system_prompt

    async def _gather_context(self, instructions: str, **kwargs) -> str:
        """Override - MrCall uses _build_runtime_prompt() instead."""
        return ""

    async def run(
        self,
        instructions: str,
        dry_run: bool = False,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute agent with given instructions and live StarChat values.

        Builds a runtime prompt with LIVE variable values (no train step needed)
        and supports multi-turn conversation history.

        Args:
            instructions: What the user wants to do
            dry_run: If True, validate and summarize changes but don't apply
            conversation_history: Previous messages for multi-turn context

        Returns:
            Dict with tool_used, tool_input, result, error
        """
        if not self.business_id:
            return {
                'error': 'No MrCall assistant linked. Run `/mrcall list` then `/mrcall link N` first.'
            }

        # Build system prompt with LIVE StarChat values
        try:
            system_prompt = await self._build_runtime_prompt()
        except ValueError as e:
            logger.error(f"[MrCallAgent] Failed to build runtime prompt: {e}")
            return {'error': str(e)}

        # Build messages list with conversation history
        messages: List[Dict[str, str]] = []

        if conversation_history:
            # Include recent history (last 10 messages to control prompt size)
            recent = conversation_history[-10:]
            messages.extend(recent)
            logger.debug(
                f"[MrCallAgent] Including {len(recent)} messages from conversation history"
            )

        # Current user instruction
        messages.append({"role": "user", "content": instructions})

        logger.debug(f"[MrCallAgent] System prompt: {len(system_prompt)} chars")
        logger.info(
            f"[MrCallAgent] Calling LLM with {len(self.TOOLS)} tools, "
            f"{len(messages)} messages"
        )

        # Call LLM with system prompt (feature knowledge) + messages (conversation)
        try:
            response = await self.llm.create_message(
                system=system_prompt,
                messages=messages,
                tools=self.TOOLS,
                max_tokens=2000,
            )
            logger.info(f"[MrCallAgent] LLM response: stop_reason={response.stop_reason}")
            for i, block in enumerate(response.content):
                if hasattr(block, 'name'):
                    logger.info(f"[MrCallAgent] Block {i}: tool_use name={block.name}")
                    logger.debug(f"[MrCallAgent] Block {i}: tool_input={block.input}")
                elif hasattr(block, 'text'):
                    logger.debug(f"[MrCallAgent] Block {i}: text={block.text}")
        except Exception as e:
            logger.error(f"[MrCallAgent] LLM call failed: {e}", exc_info=True)
            return {'error': f'LLM call failed: {str(e)}'}

        return await self._handle_tool_response(response, dry_run=dry_run)

    async def _handle_tool_response(self, response, dry_run: bool = False) -> Dict[str, Any]:
        """Handle the LLM's tool response.

        Args:
            response: LLMResponse from create_message
            dry_run: If True, don't apply configure changes to StarChat

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
                    if block.name.startswith('configure_'):
                        feature = block.name.replace('configure_', '')
                        logger.info(f"[MrCallAgent] Calling _process_configure for {feature}")
                        result['result'] = await self._process_configure(
                            block.input, feature, dry_run=dry_run
                        )
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
        feature: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Process configure_* tool by updating variables via StarChat.

        Args:
            tool_input: Tool input with 'changes' dict
            feature: Feature name for validation
            dry_run: If True, validate and summarize but don't call StarChat

        Returns:
            Dict with success status and updated variables
        """
        logger.info(f"[MrCallAgent] _process_configure: feature={feature}, dry_run={dry_run}, tool_input={tool_input}")

        changes = tool_input.get('changes', {})
        logger.info(f"[MrCallAgent] Changes to apply: {list(changes.keys())}")

        if not changes:
            logger.warning("[MrCallAgent] No changes specified in tool_input")
            return {'success': False, 'error': 'No changes specified'}

        if not dry_run and not self.starchat:
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

        # Dry run: return pending changes without calling StarChat
        if dry_run:
            pending = [
                {"variable_name": var, "new_value": val, "feature": feature}
                for var, val in changes.items()
            ]
            logger.info(f"[MrCallAgent] dry_run: {len(pending)} pending changes for {feature}")
            final_result = {
                'success': True,
                'dry_run': True,
                'pending_changes': pending,
                'feature': feature
            }
            # Still generate human-friendly summary
            final_result['response_text'] = await self._summarize_changes(feature, changes)
            return final_result

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

        # Generate human-friendly summary via a second LLM call
        if final_result['success'] and updated:
            summary = await self._summarize_changes(feature, changes)
            final_result['response_text'] = summary

            # Persist configuration decision as entity memory
            from zylch.agents.mrcall_memory import save_config_memory
            save_config_memory(self.owner_id, self.business_id, feature, summary)

        return final_result

    async def _summarize_changes(
        self, feature: str, changes: Dict[str, str]
    ) -> str:
        """Generate a human-friendly summary of configuration changes.

        Makes a lightweight LLM call to translate raw variable changes
        into a message the user can understand.

        Args:
            feature: Feature name (e.g. 'welcome_inbound')
            changes: Dict of variable_name -> new_value

        Returns:
            Human-readable summary string
        """
        feature_display = feature.replace('_', ' ').title()

        # Build a concise description of what changed
        changes_desc = "\n".join(
            f"- {var_name}: {value}" for var_name, value in changes.items()
        )

        prompt = f"""You just updated the "{feature_display}" configuration for a MrCall AI phone assistant.

The following variables were changed:
{changes_desc}

Write a SHORT, friendly confirmation message (2-4 sentences max) for the business owner explaining what was changed in plain language. Do NOT show variable names or technical details. Just explain the effect on how their assistant will behave.

Examples of good responses:
- "Done! Your assistant will now greet callers with a more formal tone, introducing itself as the reception of Mario's Restaurant."
- "Got it! Booking is now enabled with 30-minute appointment slots, available Monday through Friday from 9 AM to 5 PM."
- "Updated! After each call, callers will receive a WhatsApp message thanking them and providing your business address."

Write ONLY the confirmation message, nothing else."""

        try:
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            for block in response.content:
                if hasattr(block, 'text'):
                    logger.info(f"[MrCallAgent] Summary generated: {block.text}")
                    return block.text
        except Exception as e:
            logger.warning(f"[MrCallAgent] Summary generation failed: {e}")

        # Fallback: simple confirmation
        return f"{feature_display} updated successfully."

    # _process_get_config removed — raw variable dumps are not user-friendly.
    # Users who need raw values use StarChat directly.
    # "how does it greet callers?" etc. goes through respond_text.
