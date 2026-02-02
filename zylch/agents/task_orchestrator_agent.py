# Task Orchestrator Agent - Stateful multi-turn orchestrator for task resolution.
#
# This agent manages the conversation flow when a user enters \"task mode\" to work
# on a specific task. It:
#
# 1. Understands the task context (from task_items)
# 2. Decides which sub-agent to call (EmailerAgent, MrCallAgent, etc.)
# 3. Manages the confirmation workflow for irreversible actions
# 4. Maintains state across conversation turns
#
# Architecture:
# - Inherits from BaseConversationalAgent for user interaction
# - Orchestrates SpecializedAgents (EmailerAgent, MrCallAgent) via their run() method
# - Uses SessionState for task mode persistence


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

# Tool to send the pending email draft
SEND_EMAIL_TOOL = {
    "name": "send_email",
    "description": "Send the pending email draft. Use when user confirms with 'send it', 'ok', 'yes', 'invia', 'conferma', etc. Only works if there's a pending email draft from a previous call_agent to emailer.",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


def _build_agent_capabilities_prompt() -> str:
    """Build a prompt section describing available agents and their capabilities."""
    emailer_tools = "\n".join([f"  - {t['name']}: {t['description']}" for t in EMAIL_AGENT_TOOLS])
    mrcall_tools = "\n".join([f"  - {t['name']}: {t['description']}" for t in MRCALL_AGENT_TOOLS])

    return f"""## Available Agents

### EmailerAgent (agent_name: \"emailer\")
For all email-related tasks: composing, replying, drafting emails.
Capabilities:
{emailer_tools}

### MrCallAgent (agent_name: \"mrcall\")
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
        response = await orchestrator.process_message(\"draft a reply email\")
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
        """Build the system prompt with task context and agent capabilities.

        Uses Observation/Thought/Action cycle for structured reasoning.
        Includes task creation date for temporal context ("quel giorno").
        """
        task_context = self.session_state.get_task_context()
        if not task_context:
            return "Error: No active task. Use `/tasks open <ID>` to start."

        # 1. ENRICH CONTEXT WITH DATE
        contact = task_context.get('contact_email') or task_context.get('contact_name') or 'Unknown'
        action = task_context.get('suggested_action', 'No action suggested')
        urgency = task_context.get('urgency', 'medium')
        sources = task_context.get('sources', {})

        # Extract task creation date for temporal context
        task_creation_date = task_context.get('created_at', 'unknown date')
        if task_creation_date != 'unknown date':
            task_creation_date = task_creation_date.split('T')[0]  # Get just the date part

        task_details = f"""## 🎯 Current Task (ID: {task_context.get('id', 'unknown')})

**Task Date:** {task_creation_date}
**Contact:** {contact}
**Suggested Action:** {action}
**Urgency:** {urgency}

### Sources
- Emails: {len(sources.get('emails', []))} source emails
- Blobs: {len(sources.get('blobs', []))} context blobs
"""

        # 2. IMPROVED PENDING ACTION HANDLING
        pending_action_prompt = ""
        last_result = self.session_state.get_last_action_result()
        if last_result:
            pending_action_prompt = f"""
### ⚠️ Pending Action
Previous action produced this result. User must confirm, modify, or cancel.

**Previous Result:**
{last_result}

**User Response Handling:**
- \"ok\", \"yes\", \"send it\", \"confirm\", \"va bene\" → Proceed with the action
- Changes requested → Call the agent again with modified instructions
- \"no\", \"cancel\", \"annulla\" → Abandon the action and ask what to do next
- NEW information provided (e.g., \"there was an outage that day\") → USE this info to improve the output
"""

        agent_capabilities = _build_agent_capabilities_prompt()

        # 3. STRUCTURED REASONING CYCLE
        return f"""You are a Task Orchestrator guiding the user to complete a specific task.
You are NOT a generic chatbot - your only purpose is to complete the current task.

{task_details}
{agent_capabilities}
{pending_action_prompt}

## ⚙️ Your Reasoning Process (REQUIRED at each turn)

1. **Observation:** Summarize the user's last request and current state.

2. **Thought:** Based on observation and task goal, think step by step:
   - Do I need more context? (search memory, search emails, get source emails)
   - Should I delegate to a sub-agent? (EmailerAgent, MrCallAgent)
   - Should I just respond to the user?
   - If user provides NEW context (e.g., \"there was an outage\"), think how to USE it.

3. **Action:** Execute ONE tool to implement your thought.

## ⚠️ Critical Rules

- **One Step at a Time:** Execute one action per turn.
- **Use Context:** If user says \"that day\" or \"quel giorno\", use Task Date ({task_creation_date}) as reference.
- **Always Confirm:** No irreversible actions without explicit user confirmation.
- **Delegate, Don't Do:** Your job is to orchestrate. Call EmailerAgent to write emails, don't write them yourself.
- **Complete the Request:** Your goal is a usable output (email draft, config change, answer) - not just search results.

## 🔧 How to Delegate

When calling EmailerAgent or MrCallAgent, pass COMPLETE instructions:

✅ GOOD: \"Search memory for similar responses about outages on {task_creation_date}, then compose a reply to {contact} apologizing for the delay\"
❌ BAD: \"Search memory for outages\" (incomplete - doesn't say what to do with results)

The sub-agents can handle multi-step workflows. Give them the full picture.
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
        tools = [CALL_AGENT_TOOL, RESPOND_TOOL, SEND_EMAIL_TOOL]

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
                    elif block.name == "send_email":
                        return await self._handle_send_email()

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

                # Get previous draft if this is a modification request
                previous_draft = None
                last_result = self.session_state.get_last_action_result()
                if last_result and last_result.get('tool_used') == 'write_email':
                    previous_draft = last_result.get('result', {})
                    logger.debug(f"[TaskOrchestrator] Passing previous_draft to EmailerAgent: subject={previous_draft.get('subject', '?')}")

                result = await agent.run(
                    instructions=instructions,
                    task_num=task_num,
                    previous_draft=previous_draft,
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

    async def _handle_send_email(self) -> str:
        """Handle send_email tool - send the pending draft from database.

        Uses the draft_id from last_action_result to fetch and send the
        email via the user's connected email provider (Gmail or Outlook).

        Returns:
            Success/error message for the user
        """
        from zylch.storage.supabase_client import SupabaseStorage
        from zylch.api.token_storage import get_provider, get_email, get_graph_token

        # 1. Get draft_id from session state (or try to find latest draft)
        draft_id = None
        last_result = self.session_state.get_last_action_result()

        if last_result and last_result.get('tool_used') == 'write_email':
            draft_id = last_result.get('result', {}).get('draft_id')
            logger.debug(f"[TaskOrchestrator] send_email: draft_id from last_action_result = {draft_id}")

        # 2. If no draft_id in memory, try to get most recent draft from DB
        if not draft_id:
            logger.debug("[TaskOrchestrator] No draft_id in memory, checking DB for recent drafts")
            try:
                supabase = SupabaseStorage.get_instance()
                drafts = supabase.list_drafts(self.owner_id, status='draft')
                if drafts:
                    # Get the most recent draft
                    draft_id = drafts[0].get('id')
                    logger.debug(f"[TaskOrchestrator] Found most recent draft in DB: {draft_id}")
            except Exception as e:
                logger.error(f"[TaskOrchestrator] Failed to query drafts: {e}")

        if not draft_id:
            return "⚠️ No pending email draft to send.\n\nPlease compose an email first, or check `/email list --draft` to see your drafts."

        # 3. Fetch draft from database
        try:
            supabase = SupabaseStorage.get_instance()
            result = (
                supabase.client.table('drafts')
                .select('*')
                .eq('id', draft_id)
                .eq('owner_id', self.owner_id)
                .single()
                .execute()
            )

            if not result.data:
                return f"⚠️ Draft not found (id: {draft_id}). It may have been deleted."

            draft = result.data
        except Exception as e:
            logger.error(f"[TaskOrchestrator] Failed to fetch draft {draft_id}: {e}")
            return f"❌ Failed to load draft: {str(e)}"

        # 4. Get email provider for this user
        provider = get_provider(self.owner_id)
        user_email = get_email(self.owner_id)

        if not provider:
            return "❌ No email provider connected.\n\nUse `/connect google` or `/connect microsoft` first."

        # 5. Extract draft fields
        to_addresses = draft.get('to_addresses', [])
        to_str = ', '.join(to_addresses) if isinstance(to_addresses, list) else to_addresses
        subject = draft.get('subject', '')
        body = draft.get('body', '')
        in_reply_to = draft.get('in_reply_to')
        references = draft.get('references', [])
        thread_id = draft.get('thread_id')

        if not to_str:
            return "❌ No recipient specified in the email draft."

        logger.info(f"[TaskOrchestrator] Sending email to {to_str} via {provider} (draft_id={draft_id})")

        # Mark draft as sending
        try:
            supabase.client.table('drafts').update({
                'status': 'sending',
                'provider': provider
            }).eq('id', draft_id).execute()
        except Exception as e:
            logger.warning(f"[TaskOrchestrator] Failed to update draft status: {e}")

        try:
            # 6. Send via appropriate provider
            if provider == 'google':
                from zylch.tools.gmail import GmailClient

                gmail = GmailClient(
                    account=user_email,
                    owner_id=self.owner_id
                )

                # Convert references list to string if needed
                refs_str = None
                if references:
                    refs_str = ' '.join(references) if isinstance(references, list) else references

                sent_message = gmail.send_message(
                    to=to_str,
                    subject=subject,
                    body=body,
                    in_reply_to=in_reply_to,
                    references=refs_str,
                    thread_id=thread_id,
                )

                sent_id = sent_message.get('id', '')

            elif provider == 'microsoft':
                from zylch.tools.outlook import OutlookClient

                graph_token = get_graph_token(self.owner_id)
                if not graph_token:
                    return "❌ Microsoft token expired. Please reconnect with `/connect microsoft`."

                outlook = OutlookClient(
                    graph_token=graph_token['access_token'],
                    account=user_email
                )

                sent_message = outlook.send_message(
                    to=to_str,
                    subject=subject,
                    body=body,
                )

                sent_id = sent_message.get('id', '')

            else:
                return f"❌ Unknown email provider: {provider}"

            # 7. Delete draft after successful send
            try:
                supabase.client.table('drafts').delete().eq('id', draft_id).execute()
                logger.debug(f"[TaskOrchestrator] Deleted draft {draft_id} after sending")
            except Exception as e:
                logger.warning(f"[TaskOrchestrator] Failed to delete draft after send: {e}")

            # 8. Clear the pending draft from session state
            self.session_state.set_last_action_result(None)

            logger.info(f"[TaskOrchestrator] Email sent successfully: {sent_id}")

            return f"""✅ **Email sent!**

**To:** {to_str}
**Subject:** {subject}
**Via:** {provider.title()}

The task may now be complete. Use `/tasks exit` to return to normal chat, or continue working on this task."""

        except Exception as e:
            # Restore draft status on failure
            try:
                supabase.client.table('drafts').update({
                    'status': 'draft',
                    'error_message': str(e),
                }).eq('id', draft_id).execute()
            except:
                pass

            logger.error(f"[TaskOrchestrator] Failed to send email: {e}", exc_info=True)
            return f"❌ **Failed to send email:** {str(e)}\n\nThe draft is still saved. Try again with `/email send {draft_id}` or modify the email."

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

Say \"send it\" to send, or tell me what to change."""

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