"""MrCall Orchestrator Agent - Workflow manager for MrCall configuration.

This orchestrator:
- Maintains conversation_history for multi-turn context
- Guides user through complex configurations ("thinking loop")
- Delegates execution to MrCallAgent (stateless tool)
- Auto-trains on session entry if needed

Pattern: TaskOrchestratorAgent (conversation management, tool delegation)

Architecture:
    MrCallOrchestratorAgent (Workflow Manager)
           │
           │ delegate_to_mrcall("enable booking with 30-min slots")
           ▼
    MrCallAgent (Stateless Executor)
           │
           │ configure_booking(...)
           ▼
    StarChat API
"""

import logging
from typing import Any, Dict, List, Optional

from zylch.llm import LLMClient
from zylch.storage.supabase_client import SupabaseStorage
from zylch.tools.factory import SessionState

logger = logging.getLogger(__name__)


# Only 2 tools - keep orchestrator focused on workflow, not feature details
ORCHESTRATOR_TOOLS = [
    {
        "name": "delegate_to_mrcall",
        "description": """Execute a MrCall configuration command. Use when you have
gathered ALL necessary information from the user and are ready to make changes.
Pass a complete, unambiguous natural language command.

Examples:
- "enable booking with 30-minute appointments, Monday to Friday 9am-5pm"
- "disable booking"
- "change the welcome message to: Hello, thank you for calling Mario's Restaurant"
- "show current booking configuration"

Do NOT use this if the user's intent is still unclear - use respond_to_user instead.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Complete natural language command for MrCallAgent"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "respond_to_user",
        "description": """Respond directly to the user. Use for:
- Asking clarifying questions when intent is ambiguous
- Confirming what you understood before executing
- Explaining options or capabilities
- Providing feedback after an action

Always prefer asking questions over making assumptions.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Your response to the user"
                }
            },
            "required": ["message"]
        }
    }
]


class MrCallOrchestratorAgent:
    """Workflow manager for MrCall configuration.

    Manages conversational context and delegates execution to MrCallAgent.

    Responsibilities:
    - Maintains conversation_history for multi-turn context
    - Guides user through complex configurations ("thinking loop")
    - Delegates execution to MrCallAgent (stateless tool)
    - Auto-trains on session entry if needed

    Usage:
        orchestrator = MrCallOrchestratorAgent(session_state, owner_id, ...)
        welcome = await orchestrator.enter_session()  # Auto-trains if needed
        response = await orchestrator.process_message("enable booking")
    """

    TOOLS = ORCHESTRATOR_TOOLS

    def __init__(
        self,
        session_state: SessionState,
        owner_id: str,
        api_key: str,
        provider: str,
        storage: SupabaseStorage,
        starchat_client,
    ):
        """Initialize the orchestrator.

        Args:
            session_state: SessionState for mode management
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
            storage: SupabaseStorage instance
            starchat_client: StarChat client for API calls
        """
        self.session_state = session_state
        self.owner_id = owner_id
        self.storage = storage
        self.starchat = starchat_client
        self.api_key = api_key
        self.provider = provider

        self.llm = LLMClient(api_key=api_key, provider=provider)
        self.conversation_history: List[Dict] = []

        # Lazy-loaded executor
        self._mrcall_agent = None

        # Get business info
        self.business_id = storage.get_mrcall_link(owner_id)

        logger.info(f"[MrCallOrchestrator] Initialized for owner={owner_id}, business={self.business_id}")

    def _get_mrcall_agent(self):
        """Lazy-load MrCallAgent executor."""
        if self._mrcall_agent is None:
            from zylch.agents.mrcall_agent import MrCallAgent
            self._mrcall_agent = MrCallAgent(
                storage=self.storage,
                owner_id=self.owner_id,
                api_key=self.api_key,
                provider=self.provider,
                starchat_client=self.starchat,
            )
        return self._mrcall_agent

    async def enter_session(self) -> str:
        """Enter MrCall config mode. Verifies StarChat connectivity.

        Returns:
            Welcome message or error string
        """
        if not self.business_id:
            return "❌ **No assistant linked**\n\nRun `/mrcall list` to see available assistants, then `/mrcall link <ID>` to link one."

        # Get business name for welcome message
        business_name = "your assistant"
        try:
            business = await self.starchat.get_business_config(self.business_id)
            business_name = business.get('nickname', business_name)
        except Exception as e:
            logger.warning(f"[MrCallOrchestrator] Could not get business name: {e}")

        return f"""**MrCall Configuration Mode**

Configuring: **{business_name}**

I can help you configure your MrCall assistant. Tell me what you'd like to change:
- "Enable booking with 30-minute appointments"
- "Change the greeting to be more formal"
- "Show me the current settings"
- "What can I configure?" """

    async def process_message(self, user_message: str, context: Optional[Dict] = None) -> str:
        """Process user message with full conversation context.

        Args:
            user_message: User's message
            context: Optional additional context

        Returns:
            Response string
        """
        # Add to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Build system prompt
        system_prompt = self._build_system_prompt()

        # Call LLM with full history
        try:
            response = await self.llm.create_message(
                messages=self.conversation_history,
                system=system_prompt,
                tools=self.TOOLS,
                max_tokens=2000
            )
            logger.debug(f"[MrCallOrchestrator] LLM response: stop_reason={response.stop_reason}")
        except Exception as e:
            logger.error(f"[MrCallOrchestrator] LLM call failed: {e}", exc_info=True)
            return f"Error: {str(e)}"

        # Handle response
        result = await self._handle_response(response)

        # Add to history
        self.conversation_history.append({
            "role": "assistant",
            "content": result
        })

        return result

    def _build_system_prompt(self) -> str:
        """Build system prompt for orchestrator."""
        return """You are a MrCall Configuration Assistant helping users configure their AI phone assistant.

## Your Role

You are a WORKFLOW MANAGER, not an executor. Your job is to:
1. Understand what the user wants to configure
2. Ask clarifying questions when their intent is ambiguous
3. Gather all necessary information before making changes
4. Delegate execution to the MrCall system via delegate_to_mrcall

## Available Features

You can help configure:
- **Welcome Message**: How the assistant greets callers (formal/informal, what info to ask)
- **Booking**: Appointment scheduling (enable/disable, duration, hours, days)
- More features coming soon...

## Thinking Process

For each user message, think:
1. What does the user want to do?
2. Do I have ALL the information needed to execute this?
3. If NO → Use respond_to_user to ask clarifying questions
4. If YES → Use delegate_to_mrcall with a complete command

## Examples

User: "enable booking"
Think: Missing info - what duration? what hours?
Action: respond_to_user("I can enable booking for you. A few questions:
1. What appointment duration? (15, 30, or 60 minutes)
2. What days and hours should be available?")

User: "30 minutes, weekdays 9 to 5"
Think: Now I have everything needed
Action: delegate_to_mrcall("enable booking with 30-minute appointments, Monday to Friday, 9:00-17:00")

User: "is booking enabled?"
Think: User wants information, not to make changes
Action: delegate_to_mrcall("show current booking configuration")

User: "change the greeting"
Think: Missing info - change to what?
Action: respond_to_user("What would you like the new greeting to be? For example:
- More formal: 'Good morning, thank you for calling...'
- More casual: 'Hi! How can I help you today?'")

## Rules

- ALWAYS prefer asking questions over making assumptions
- When delegating, pass COMPLETE commands with all details
- After successful changes, briefly confirm what was done
- Use conversation history to maintain context across messages"""

    async def _handle_response(self, response) -> str:
        """Handle LLM response and execute tools.

        Args:
            response: LLMResponse from create_message

        Returns:
            Formatted response string
        """
        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):
                    tool_name = block.name
                    tool_input = block.input
                    logger.info(f"[MrCallOrchestrator] Tool used: {tool_name}")

                    if tool_name == "delegate_to_mrcall":
                        return await self._handle_delegate(tool_input)
                    elif tool_name == "respond_to_user":
                        return tool_input.get("message", "")

        # Fallback to text response
        for block in response.content:
            if hasattr(block, 'text'):
                return block.text

        return "I couldn't process your request. Please try again."

    async def _handle_delegate(self, tool_input: Dict[str, Any]) -> str:
        """Delegate command to MrCallAgent and format result.

        Passes conversation_history so the executor has full context.

        Args:
            tool_input: Dict with 'command' key

        Returns:
            Formatted result string
        """
        command = tool_input.get("command", "")
        logger.info(f"[MrCallOrchestrator] Delegating to MrCallAgent: {command}")

        agent = self._get_mrcall_agent()

        try:
            result = await agent.run(
                instructions=command,
                conversation_history=self.conversation_history,
            )
            logger.debug(f"[MrCallOrchestrator] MrCallAgent result: {result}")
        except Exception as e:
            logger.error(f"[MrCallOrchestrator] MrCallAgent execution failed: {e}", exc_info=True)
            return f"❌ Failed to execute command: {str(e)}"

        return self._format_result(result)

    def _format_result(self, result: Dict[str, Any]) -> str:
        """Format MrCallAgent result for user display.

        Args:
            result: Dict from MrCallAgent.run()

        Returns:
            Formatted string for display
        """
        if result.get('error'):
            return f"❌ {result['error']}"

        tool_used = result.get('tool_used', '')
        agent_result = result.get('result', {})

        if not agent_result:
            return "No result returned from configuration agent."

        if tool_used == 'respond_text':
            return agent_result.get('response', '')

        if tool_used and tool_used.startswith('configure_'):
            if agent_result.get('success'):
                # Use human-friendly summary if available
                response_text = agent_result.get('response_text')
                if response_text:
                    return f"✅ {response_text}"
                # Fallback
                feature = agent_result.get('feature', 'settings')
                feature_display = feature.replace('_', ' ').title()
                return f"✅ **{feature_display}** updated successfully."
            else:
                errors = agent_result.get('errors', [])
                error_msg = agent_result.get('error', '')
                if errors:
                    return f"⚠️ Some changes failed:\n" + "\n".join(f"- {e}" for e in errors)
                if error_msg:
                    return f"⚠️ {error_msg}"
                return "⚠️ Configuration update failed. Please try again."

        # Fallback: return raw result
        return str(agent_result)

    # _ensure_trained() removed — MrCallAgent now builds runtime prompts
    # with live StarChat values, no train step required.
