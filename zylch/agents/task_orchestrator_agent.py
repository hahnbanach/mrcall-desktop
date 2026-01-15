"""Task Orchestrator Agent - Stateful multi-turn orchestrator for task resolution.

This agent manages the conversation flow when a user enters "task mode" to work
on a specific task. It:

1. Understands the task context (from task_items)
2. Decides which sub-agent to call (EmailerAgent, MrCallAgent, etc.)
3. Manages the confirmation workflow for irreversible actions
4. Maintains state across conversation turns

Architecture:
- Inherits from BaseConversationalAgent for user interaction
- Orchestrates SpecializedAgents (EmailerAgent, MrCallAgent) via their run() method
- Uses SessionState for task mode persistence
"""

import logging
from typing import Any, Dict, Optional

from zylch.agents.base import BaseConversationalAgent
from zylch.agents.emailer_agent import EmailerAgent, EMAIL_AGENT_TOOLS
from zylch.agents.mrcall_agent import MrCallAgent, MRCALL_AGENT_TOOLS
from zylch.llm import LLMClient
from zylch.storage.supabase_client import SupabaseStorage
from zylch.tools.factory import SessionState

logger = logging.getLogger(__name__)


# Tool for LLM to decide which sub-agent to call
CALL_AGENT_TOOL = {
    "name": "call_agent",
    "description": "Call a specialized agent to perform an action. Use this to delegate work to EmailerAgent (for emails) or MrCallAgent (for assistant configuration).",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "enum": ["emailer", "mrcall"],
                "description": "Which agent to call: 'emailer' for email tasks, 'mrcall' for MrCall configuration"
            },
            "instructions": {
                "type": "string",
                "description": "Instructions for the agent - what to do with the task context"
            }
        },
        "required": ["agent_name", "instructions"]
    }
}

# Tool for direct text response without calling sub-agents
RESPOND_TOOL = {
    "name": "respond",
    "description": "Respond directly to the user with text. Use this for questions, clarifications, confirmations, or when no agent action is needed.",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to display to the user"
            }
        },
        "required": ["message"]
    }
}


def _build_agent_capabilities_prompt() -> str:
    """Build a prompt section describing available agents and their capabilities."""
    emailer_tools = "\n".join([f"  - {t['name']}: {t['description']}" for t in EMAIL_AGENT_TOOLS])
    mrcall_tools = "\n".join([f"  - {t['name']}: {t['description']}" for t in MRCALL_AGENT_TOOLS])

    return f"""## Available Agents

### EmailerAgent (agent_name: "emailer")
For all email-related tasks: composing, replying, drafting emails.
Capabilities:
{emailer_tools}

### MrCallAgent (agent_name: "mrcall")
For configuring MrCall voice assistants.
Capabilities:
{mrcall_tools}
"""


class TaskOrchestratorAgent(BaseConversationalAgent):
    """Stateful orchestrator for task resolution.

    This agent is created when a user enters task mode (/tasks open <ID>)
    and manages the multi-turn conversation to resolve the task.

    Key responsibilities:
    1. Analyze the task and suggest actions
    2. Delegate to appropriate sub-agents (EmailerAgent, MrCallAgent)
    3. Present results and ask for confirmation
    4. Track state across conversation turns

    Usage:
        orchestrator = TaskOrchestratorAgent(
            session_state=session_state,
            owner_id=user_id,
            api_key=config.anthropic_api_key,
            provider=config.llm_provider,
            storage=storage
        )
        response = await orchestrator.process_message("draft a reply email")
    """

    def __init__(
        self,
        session_state: SessionState,
        owner_id: str,
        api_key: str,
        provider: str = "anthropic",
        storage: Optional[SupabaseStorage] = None,
        starchat_client=None,
    ):
        """Initialize TaskOrchestratorAgent.

        Args:
            session_state: SessionState with task context
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
            storage: SupabaseStorage instance
            starchat_client: Optional StarChat client for MrCall operations
        """
        self.session_state = session_state
        self.owner_id = owner_id
        self.api_key = api_key
        self.provider = provider
        self.storage = storage or SupabaseStorage.get_instance()
        self.starchat_client = starchat_client

        # LLM client for orchestration decisions
        self.llm = LLMClient(api_key=api_key, provider=provider)

        # Lazy-loaded sub-agents
        self._emailer_agent: Optional[EmailerAgent] = None
        self._mrcall_agent: Optional[MrCallAgent] = None

        # Conversation history for multi-turn
        self.conversation_history: list = []

        logger.info(f"TaskOrchestratorAgent initialized for owner={owner_id}, task={session_state.get_task_id()}")

    def _get_emailer_agent(self) -> EmailerAgent:
        """Lazy-load EmailerAgent."""
        if self._emailer_agent is None:
            self._emailer_agent = EmailerAgent(
                storage=self.storage,
                owner_id=self.owner_id,
                api_key=self.api_key,
                provider=self.provider
            )
        return self._emailer_agent

    def _get_mrcall_agent(self) -> MrCallAgent:
        """Lazy-load MrCallAgent."""
        if self._mrcall_agent is None:
            self._mrcall_agent = MrCallAgent(
                storage=self.storage,
                owner_id=self.owner_id,
                api_key=self.api_key,
                provider=self.provider,
                starchat_client=self.starchat_client
            )
        return self._mrcall_agent

    def _build_system_prompt(self) -> str:
        """Build the system prompt with task context and agent capabilities."""
        task_context = self.session_state.get_task_context()
        if not task_context:
            return "No task context available."

        # Format task details
        contact = task_context.get('contact_email') or task_context.get('contact_name') or 'Unknown'
        action = task_context.get('suggested_action', 'No action suggested')
        urgency = task_context.get('urgency', 'medium')
        sources = task_context.get('sources', {})

        task_details = f"""## Current Task

**Contact:** {contact}
**Suggested Action:** {action}
**Urgency:** {urgency}
**Task ID:** {task_context.get('id', 'unknown')}

### Sources
- Emails: {len(sources.get('emails', []))} source emails
- Blobs: {len(sources.get('blobs', []))} context blobs
"""

        # Last action result (for confirmation flow)
        last_result = self.session_state.get_last_action_result()
        if last_result:
            task_details += f"""
### Pending Action
Last action result awaiting confirmation:
```
{last_result}
```
If the user says "ok", "yes", "send it", "confirm" - proceed with the action.
If they want changes, call the agent again with new instructions.
"""

        agent_capabilities = _build_agent_capabilities_prompt()

        return f"""You are a Task Orchestrator helping the user resolve a specific task.

{task_details}

{agent_capabilities}

## Your Role

1. **Analyze** what the user wants to do with this task
2. **Delegate** to the appropriate agent using call_agent tool
3. **Present** results clearly and ask for confirmation before irreversible actions
4. **Track** conversation state across turns

## Guidelines

- For email tasks → call EmailerAgent
- For MrCall configuration → call MrCallAgent
- For questions/clarifications → use respond tool
- Always explain what you're about to do before calling an agent
- After an agent returns a draft/preview, ask for confirmation
- Keep responses concise but informative
"""

    async def process_message(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Process a user message in task mode.

        Args:
            user_message: The user's message
            context: Optional additional context

        Returns:
            Response string for the user
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Build system prompt with current task context
        system_prompt = self._build_system_prompt()

        # Call LLM to decide what to do
        tools = [CALL_AGENT_TOOL, RESPOND_TOOL]

        try:
            response = await self.llm.create_message(
                messages=self.conversation_history,
                system=system_prompt,
                tools=tools,
                max_tokens=2000
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return f"Error processing your request: {str(e)}"

        # Handle response
        result_message = await self._handle_response(response)

        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": result_message
        })

        return result_message

    async def _handle_response(self, response) -> str:
        """Handle LLM response - tool call or text.

        Args:
            response: LLMResponse from create_message

        Returns:
            Response string for the user
        """
        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):  # ToolUseBlock
                    if block.name == "call_agent":
                        return await self._handle_call_agent(block.input)
                    elif block.name == "respond":
                        return block.input.get("message", "")

        # Text response fallback
        for block in response.content:
            if hasattr(block, 'text'):
                return block.text

        return "I couldn't process your request. Please try again."

    async def _handle_call_agent(self, tool_input: Dict[str, Any]) -> str:
        """Handle call_agent tool by delegating to sub-agent.

        Args:
            tool_input: Tool input with agent_name and instructions

        Returns:
            Formatted response with agent result
        """
        agent_name = tool_input.get("agent_name")
        instructions = tool_input.get("instructions", "")

        logger.info(f"[TaskOrchestrator] Calling {agent_name} with: {instructions[:100]}...")

        try:
            if agent_name == "emailer":
                agent = self._get_emailer_agent()
                # Get task_num from context if available
                task_context = self.session_state.get_task_context()
                task_num = None  # Could extract from task_context if needed

                result = await agent.run(
                    instructions=instructions,
                    task_num=task_num
                )

                # Store result for confirmation flow
                self.session_state.set_last_action_result(result)

                return self._format_emailer_result(result)

            elif agent_name == "mrcall":
                agent = self._get_mrcall_agent()
                result = await agent.run(instructions=instructions)

                # Store result for confirmation flow
                self.session_state.set_last_action_result(result)

                return self._format_mrcall_result(result)

            else:
                return f"Unknown agent: {agent_name}"

        except Exception as e:
            logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)
            return f"Error calling {agent_name}: {str(e)}"

    def _format_emailer_result(self, result: Dict[str, Any]) -> str:
        """Format EmailerAgent result for display."""
        tool_used = result.get('tool_used', 'unknown')
        agent_result = result.get('result', {})

        if tool_used == 'write_email':
            subject = agent_result.get('subject', '(no subject)')
            body = agent_result.get('body', '')
            recipient = agent_result.get('recipient_email', '(not specified)')

            return f"""**📧 Email Draft Ready**

**To:** {recipient}
**Subject:** {subject}

---
{body}
---

Say "send it" to send, or tell me what to change."""

        elif tool_used == 'respond_text':
            return agent_result.get('response', 'No response from agent.')

        elif tool_used == 'search_memory':
            results = agent_result.get('results', [])
            return f"Found {len(results)} relevant items in memory."

        else:
            return f"Agent completed action: {tool_used}"

    def _format_mrcall_result(self, result: Dict[str, Any]) -> str:
        """Format MrCallAgent result for display."""
        if result.get('error'):
            return f"❌ Error: {result['error']}"

        tool_used = result.get('tool_used', 'unknown')
        agent_result = result.get('result', {})

        if tool_used in ['configure_welcome_message', 'configure_booking']:
            if agent_result.get('success'):
                updated = agent_result.get('updated', [])
                return f"✅ Configuration updated:\n" + "\n".join([f"- {u}" for u in updated])
            else:
                errors = agent_result.get('errors', ['Unknown error'])
                return f"❌ Failed to update:\n" + "\n".join([f"- {e}" for e in errors])

        elif tool_used == 'get_current_config':
            config = agent_result.get('config', {})
            return f"Current configuration:\n```\n{config}\n```"

        elif tool_used == 'respond_text':
            return agent_result.get('response', 'No response from agent.')

        else:
            return f"Agent completed action: {tool_used}"
