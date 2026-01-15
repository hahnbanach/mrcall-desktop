"""Emailer Agent - Multi-tool agent for email-related tasks.

This is a TRUE AGENT with multiple tools that can:
- Compose emails (write_email)
- Search memory for context (search_memory)
- Fetch original emails (get_email)
- Provide analysis/suggestions (respond_text)

The trained prompt instructs the agent when to use each tool based on
the user's request.

Key principle: "Find a balance between putting a bit more than necessary
in memory and not overloading the assistant."

Inherits from SpecializedAgent for common functionality (init, prompt loading, etc.)
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from zylch.agents.base_agent import SpecializedAgent
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig
from zylch.memory.hybrid_search import SearchResult

logger = logging.getLogger(__name__)


# Maximum characters for context to leave room for LLM generation
MAX_CONTEXT_CHARS = 8000

# Multi-tool schema for the email agent
# The agent chooses which tool to use based on the request
EMAIL_AGENT_TOOLS = [
    {
        "name": "write_email",
        "description": "Compose and save an email as draft. Use when the user wants to write, compose, reply, or send an email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Email subject line"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text"
                },
                "to": {
                    "type": "string",
                    "description": "Recipient email address (optional if already known from context)"
                }
            },
            "required": ["subject", "body"]
        }
    },
    {
        "name": "search_memory",
        "description": "Search memory blobs for context about a person, company, or template. Use when you need more information before answering or composing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (name, topic, company, etc.)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_email",
        "description": "Fetch the full content of an original email by ID. Use when blob context references an email ID and you need more details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email UUID to fetch"
                }
            },
            "required": ["email_id"]
        }
    },
    {
        "name": "respond_text",
        "description": "Return a text response with analysis, suggestions, or answers. Use when the user asks a question, wants advice, or needs information - NOT when they want to compose an email.",
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
    },
    {
        "name": "search_emails",
        "description": "Search actual emails for specific content. Use when memory blobs don't have enough info, or when looking for emails around a specific date/event. More comprehensive than search_memory but slower.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (keywords, names, topics)"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default: 30)",
                    "default": 30
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of emails to return (default: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
]

# Legacy single-tool for backwards compatibility (compose-only mode)
WRITE_EMAIL_TOOL = EMAIL_AGENT_TOOLS[0]


@dataclass
class EmailContext:
    """Context gathered for email composition.

    Contains all relevant information from hybrid search and task sources.
    """
    # Blobs from hybrid search, separated by entity type
    contact_blobs: List[SearchResult] = field(default_factory=list)
    template_blobs: List[SearchResult] = field(default_factory=list)
    company_blobs: List[SearchResult] = field(default_factory=list)

    # From task sources (if task_num provided)
    source_emails: List[dict] = field(default_factory=list)
    source_blobs: List[dict] = field(default_factory=list)


class EmailContextGatherer:
    """Gathers context for email composition using hybrid search.

    Strategy:
    1. If task_num provided, get task and its sources (emails, blobs)
    2. Run hybrid search with full user request
    3. Separate results by entity type (PERSON, COMPANY, TEMPLATE)
    4. If recipient_email provided, boost exact match results
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        search_engine: HybridSearchEngine,
        owner_id: str
    ):
        self.storage = storage
        self.search_engine = search_engine
        self.owner_id = owner_id

    async def gather(
        self,
        user_request: str,
        recipient_email: Optional[str] = None,
        task_num: Optional[int] = None,
    ) -> EmailContext:
        """Gather context for email composition.

        Args:
            user_request: The user's email request (e.g., "scrivi a Mario un'offerta")
            recipient_email: Optional email extracted from conversation
            task_num: Optional 1-indexed task number from /tasks

        Returns:
            EmailContext with all relevant blobs and sources
        """
        context = EmailContext()

        # STEP 1: If task_num provided, get task and its sources
        if task_num:
            from zylch.services.command_handlers import get_task_by_number
            task = await get_task_by_number(task_num, self.owner_id)
            if task:
                sources = task.get('sources') or {}
                logger.debug(f"[EMAILER] Task sources: {sources}")

                # Load source emails
                email_ids = sources.get('emails', [])
                if email_ids:
                    context.source_emails = self._get_emails_by_ids(email_ids)

                # Load source blobs
                blob_ids = sources.get('blobs', [])
                if blob_ids:
                    context.source_blobs = self._get_blobs_by_ids(blob_ids)

        # STEP 2: Hybrid search with full user request
        # If recipient_email provided and not already in request, add it for exact match
        search_query = user_request
        if recipient_email and recipient_email.lower() not in user_request.lower():
            search_query = f"{user_request} {recipient_email}"
            logger.debug(f"[EMAILER] Enhanced query with recipient_email: {search_query}")

        # Run hybrid search - finds PERSON, COMPANY, TEMPLATE blobs
        namespace = f"user:{self.owner_id}"
        results = self.search_engine.search(
            owner_id=self.owner_id,
            query=search_query,
            namespace=namespace,
            limit=10  # Get more results to have options
        )
        logger.debug(f"[EMAILER] Hybrid search returned {len(results)} results")

        # STEP 3: Separate by entity type
        for result in results:
            content = result.content
            if 'Entity type: PERSON' in content:
                context.contact_blobs.append(result)
            elif 'Entity type: TEMPLATE' in content:
                context.template_blobs.append(result)
            elif 'Entity type: COMPANY' in content:
                context.company_blobs.append(result)

        logger.info(
            f"[EMAILER] Gathered context: "
            f"{len(context.contact_blobs)} contacts, "
            f"{len(context.template_blobs)} templates, "
            f"{len(context.company_blobs)} companies, "
            f"{len(context.source_emails)} source emails"
        )

        return context

    def _get_emails_by_ids(self, email_ids: List[str]) -> List[dict]:
        """Load emails by their Supabase UUIDs."""
        emails = []
        for email_id in email_ids:
            email = self.storage.get_email_by_supabase_id(self.owner_id, email_id)
            if email:
                emails.append(email)
        return emails

    def _get_blobs_by_ids(self, blob_ids: List[str]) -> List[dict]:
        """Load blobs by their UUIDs."""
        blobs = []
        for blob_id in blob_ids:
            result = self.storage.client.table('blobs')\
                .select('*')\
                .eq('id', blob_id)\
                .limit(1)\
                .execute()
            if result.data:
                blobs.append(result.data[0])
        return blobs


def _format_person_blobs(blobs: List[SearchResult]) -> str:
    """Format PERSON blobs for prompt context."""
    if not blobs:
        return ""

    sections = []
    for blob in blobs:
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_template_blobs(blobs: List[SearchResult]) -> str:
    """Format TEMPLATE blobs for prompt context."""
    if not blobs:
        return ""

    sections = []
    for blob in blobs:
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_company_blobs(blobs: List[SearchResult]) -> str:
    """Format COMPANY blobs for prompt context."""
    if not blobs:
        return ""

    sections = []
    for blob in blobs:
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_source_emails(emails: List[dict]) -> str:
    """Format source emails for prompt context."""
    if not emails:
        return ""

    sections = []
    for email in emails:
        from_display = email.get('from_name') or email.get('from_email', 'Unknown')
        subject = email.get('subject', '(no subject)')
        body = email.get('body_plain') or email.get('snippet', '')
        sections.append(f"From: {from_display}\nSubject: {subject}\n\n{body}")

    return "\n\n---\n\n".join(sections)


def build_prompt_context(context: EmailContext) -> str:
    """Build prompt context from gathered email context.

    Uses priority order and respects token budget.
    """
    sections = []
    budget = MAX_CONTEXT_CHARS

    # Priority order (highest first)
    priority_items = [
        ("ABOUT THE RECIPIENT", _format_person_blobs(context.contact_blobs)),
        ("RELEVANT COMPANY INFO", _format_company_blobs(context.company_blobs)),
        ("EMAIL THREAD / SOURCES", _format_source_emails(context.source_emails)),
        ("TEMPLATES TO USE", _format_template_blobs(context.template_blobs)),
    ]

    for label, content in priority_items:
        if content and budget > 0:
            truncated = content[:budget]
            sections.append(f"## {label}\n{truncated}")
            budget -= len(truncated)

    return "\n\n".join(sections)


class EmailerAgent(SpecializedAgent):
    """Multi-tool agent for email-related tasks.

    Inherits from SpecializedAgent for common functionality.

    This is a TRUE AGENT that:
    1. Has a trained prompt that learns the user's writing style
    2. Has multiple tools it can choose from based on the request
    3. Can autonomously seek more information when context is insufficient

    Tools available:
    - write_email: Compose and save as draft
    - search_memory: Search blobs for context
    - get_email: Fetch original email by ID
    - respond_text: Return analysis/suggestions

    If trained via `/agent email train`, uses personalized writing style.
    Otherwise falls back to generic behavior.
    """

    PROMPT_KEY = 'emailer'  # Key in agent_prompts table
    TOOLS = EMAIL_AGENT_TOOLS

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        provider: str = "anthropic"
    ):
        """Initialize EmailerAgent.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: API key for LLM
            provider: LLM provider (anthropic, openai, mistral)
        """
        super().__init__(storage, owner_id, api_key, provider)

        # Email-specific: context gatherer for email composition
        self.gatherer = EmailContextGatherer(storage, self.search_engine, owner_id)

        logger.info(f"EmailerAgent initialized for owner={owner_id}")

    async def compose(
        self,
        user_request: str,
        recipient_email: Optional[str] = None,
        task_num: Optional[int] = None,
    ) -> Dict[str, str]:
        """Compose an email based on user request and gathered context.

        Args:
            user_request: What the user wants to write (e.g., "scrivi a Mario un'offerta")
            recipient_email: Optional email extracted from conversation
            task_num: Optional 1-indexed task number from /tasks

        Returns:
            Dict with 'subject', 'body', and optionally threading headers:
            - in_reply_to: Message-ID for threading
            - references: List of message IDs for threading
            - thread_id: Gmail thread ID
            - recipient_email: Extracted from source email if not provided
        """
        # Gather context
        context = await self.gatherer.gather(
            user_request=user_request,
            recipient_email=recipient_email,
            task_num=task_num
        )

        # Build prompt context
        context_text = build_prompt_context(context)

        # Check for trained prompt (personalized style)
        trained_prompt = self._get_trained_prompt()

        if trained_prompt:
            # Use trained prompt - already contains style instructions
            prompt = f"""{trained_prompt}

---

CONTEXT:
{context_text}

---

USER REQUEST: {user_request}

Use the write_email tool to output your composed email."""
        else:
            # Fallback to generic prompt (no personalized style)
            prompt = f"""You are writing an email for the user.

{context_text}

---

USER REQUEST: {user_request}

Write the email in the appropriate language:
- as requested by the user (if specified)
- in the same language used by the recipient in other exchanges (if any)
- try to infer if no clue!

If TEMPLATE entities are provided, use them as reference for tone and structure.
If recipient info is available, personalize the email appropriately.

Use the write_email tool to output your composed email."""

        logger.debug(f"[EMAILER] Sending prompt ({len(prompt)} chars)")

        response = await self.llm.create_message(
            messages=[{"role": "user", "content": prompt}],
            tools=[WRITE_EMAIL_TOOL],
            tool_choice={"type": "tool", "name": "write_email"},
            max_tokens=2000
        )

        # Extract result from ToolUseBlock - no JSON parsing needed
        result = {"subject": "(error)", "body": "Failed to generate email"}

        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):  # ToolUseBlock
                    result = {
                        "subject": block.input.get("subject", ""),
                        "body": block.input.get("body", "")
                    }
                    break
        else:
            logger.error(f"[EMAILER] Unexpected response: stop_reason={response.stop_reason}")

        # Add threading headers if replying to task with source emails
        if context.source_emails:
            # Get the most recent email to reply to (ordered by date_timestamp ASC)
            latest_email = context.source_emails[-1]

            # For reply: in_reply_to = message_id of the email we're replying to
            result["in_reply_to"] = latest_email.get("message_id_header")

            # Build references: existing references + message_id we're replying to
            existing_refs = latest_email.get("references") or []
            msg_id = latest_email.get("message_id_header")
            if msg_id:
                result["references"] = existing_refs + [msg_id]
            else:
                result["references"] = existing_refs

            # Gmail thread ID
            result["thread_id"] = latest_email.get("thread_id")

            # Extract recipient from original email if not provided
            if not recipient_email:
                result["recipient_email"] = latest_email.get("from_email")

            logger.info(
                f"[EMAILER] Threading info: in_reply_to={result.get('in_reply_to')}, "
                f"thread_id={result.get('thread_id')}, recipient={result.get('recipient_email')}"
            )

        return result

    async def run(
        self,
        instructions: str,
        recipient_email: Optional[str] = None,
        task_num: Optional[int] = None,
        previous_draft: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the email agent with given instructions.

        This is the main entry point for the multi-tool agent. The agent uses
        an agentic loop - it can call intermediate tools (search_memory, get_email)
        to gather information, then continue until it produces a final output
        (write_email or respond_text).

        Flow examples:
        - "scrivi a Mario un'offerta" → write_email
        - "What can I answer to this guy?" → respond_text
        - "cerca info su Acme Corp" → search_memory → respond_text
        - "cerca risposte simili e rispondi" → search_memory → write_email
        - "aggiungi il numero..." + previous_draft → modified write_email

        Args:
            instructions: What the user wants to do
            recipient_email: Optional recipient email (for email composition)
            task_num: Optional 1-indexed task number from /tasks
            previous_draft: Optional previous email draft to modify (from TaskOrchestratorAgent)
                           Dict with keys: recipient_email, subject, body

        Returns:
            Dict with:
            - tool_used: Name of the tool the agent chose
            - tool_input: Input the agent provided to the tool
            - result: Processed result (email dict for write_email, text for respond_text)
        """
        # Gather initial context
        context = await self.gatherer.gather(
            user_request=instructions,
            recipient_email=recipient_email,
            task_num=task_num
        )

        # Accumulated context from intermediate tool calls
        accumulated_context = []

        # Agentic loop - continue until we get a final output
        MAX_ITERATIONS = 5
        for iteration in range(MAX_ITERATIONS):
            logger.debug(f"[EMAILER] run() iteration {iteration + 1}/{MAX_ITERATIONS}")

            # Build prompt with current context
            prompt = self._build_run_prompt(instructions, context, accumulated_context, previous_draft)
            logger.debug(f"[EMAILER] run() sending prompt ({len(prompt)} chars)")

            # Call LLM with all tools
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}],
                tools=self.TOOLS,
                max_tokens=2000
            )

            # Handle tool response
            result = self._handle_tool_response(response, context, recipient_email)
            tool_used = result.get('tool_used')

            logger.debug(f"[EMAILER] run() iteration {iteration + 1}: tool_used={tool_used}")

            # Final output tools - return immediately
            if tool_used in ['write_email', 'respond_text']:
                return result

            # Intermediate tools - accumulate context and continue
            if tool_used == 'search_memory':
                search_results = result.get('result', {}).get('results', [])
                if search_results:
                    accumulated_context.append({
                        'type': 'search_memory',
                        'query': result.get('tool_input', {}).get('query', ''),
                        'results': search_results
                    })
                    logger.debug(f"[EMAILER] Accumulated {len(search_results)} search results")
                else:
                    # No results found - add note so LLM knows
                    accumulated_context.append({
                        'type': 'search_memory',
                        'query': result.get('tool_input', {}).get('query', ''),
                        'results': [],
                        'note': 'No results found in memory blobs'
                    })

            elif tool_used == 'search_emails':
                email_results = result.get('result', {}).get('emails', [])
                if email_results:
                    accumulated_context.append({
                        'type': 'search_emails',
                        'query': result.get('tool_input', {}).get('query', ''),
                        'emails': email_results
                    })
                    logger.debug(f"[EMAILER] Accumulated {len(email_results)} email search results")
                else:
                    accumulated_context.append({
                        'type': 'search_emails',
                        'query': result.get('tool_input', {}).get('query', ''),
                        'emails': [],
                        'note': 'No emails found matching the query'
                    })

            elif tool_used == 'get_email':
                email_data = result.get('result', {})
                if not email_data.get('error'):
                    accumulated_context.append({
                        'type': 'get_email',
                        'email_id': result.get('tool_input', {}).get('email_id', ''),
                        'email': email_data
                    })
                    logger.debug(f"[EMAILER] Accumulated email: {email_data.get('subject', 'no subject')}")

            else:
                # Unknown tool or no tool - return as-is
                logger.warning(f"[EMAILER] Unknown tool: {tool_used}, returning result")
                return result

        # Max iterations reached - return last result with warning
        logger.warning(f"[EMAILER] Max iterations ({MAX_ITERATIONS}) reached without final output")
        return {
            'tool_used': 'respond_text',
            'tool_input': {},
            'result': {'response': 'I gathered some information but could not complete the task. Please try being more specific about what you want me to do.'}
        }

    def _build_run_prompt(
        self,
        instructions: str,
        context: EmailContext,
        accumulated_context: List[Dict[str, Any]],
        previous_draft: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the prompt for run() with current context.

        Args:
            instructions: Original user instructions
            context: Initial EmailContext from gatherer
            accumulated_context: Results from intermediate tool calls
            previous_draft: Optional previous email draft to modify

        Returns:
            Complete prompt string
        """
        # Build base context
        context_text = build_prompt_context(context)

        # Add previous draft if modifying an existing email
        if previous_draft:
            draft_recipient = previous_draft.get('recipient_email', '(unknown)')
            draft_subject = previous_draft.get('subject', '(no subject)')
            draft_body = previous_draft.get('body', '')
            context_text = f"""## ⚠️ PREVIOUS DRAFT (MODIFY THIS - DO NOT START FROM SCRATCH)

**To:** {draft_recipient}
**Subject:** {draft_subject}

---
{draft_body}
---

The user wants to MODIFY this draft. Apply the requested changes while preserving the rest of the email.
Do NOT rewrite from scratch - edit the existing draft.

---

{context_text}"""

        # Add accumulated context from previous iterations
        if accumulated_context:
            context_text += "\n\n---\n\n## Additional Context (from previous searches)\n\n"
            for item in accumulated_context:
                if item['type'] == 'search_memory':
                    query = item.get('query', '')
                    results = item.get('results', [])
                    note = item.get('note', '')
                    if results:
                        context_text += f"**Search for '{query}':** Found {len(results)} results:\n"
                        for r in results[:3]:  # Limit to top 3
                            content = r.get('content', '')[:500]  # Truncate long content
                            context_text += f"- {content}\n"
                    elif note:
                        context_text += f"**Search for '{query}':** {note}\n"
                elif item['type'] == 'get_email':
                    email = item.get('email', {})
                    context_text += f"**Email from {email.get('from_email', 'unknown')}:**\n"
                    context_text += f"Subject: {email.get('subject', '(no subject)')}\n"
                    context_text += f"Date: {email.get('date', 'unknown')}\n"
                    body = email.get('body', '')[:1000]  # Truncate
                    context_text += f"Body: {body}\n"
                elif item['type'] == 'search_emails':
                    query = item.get('query', '')
                    emails = item.get('emails', [])
                    note = item.get('note', '')
                    if emails:
                        context_text += f"**Email search for '{query}':** Found {len(emails)} emails:\n"
                        for e in emails[:5]:  # Limit to top 5
                            context_text += f"- From: {e.get('from_email', 'unknown')}\n"
                            context_text += f"  Subject: {e.get('subject', '(no subject)')}\n"
                            context_text += f"  Date: {e.get('date', 'unknown')}\n"
                            body = e.get('body', '')[:300]  # Truncate
                            context_text += f"  Body: {body}...\n"
                    elif note:
                        context_text += f"**Email search for '{query}':** {note}\n"

        # Check for trained prompt (personalized style)
        trained_prompt = self._get_trained_prompt()

        if trained_prompt:
            return f"""{trained_prompt}

---

CONTEXT:
{context_text}

---

INSTRUCTIONS: {instructions}

Choose the appropriate tool based on what the user wants:
- Use write_email if they want to compose/write/reply/send an email
- Use search_memory if you need more information before answering
- Use get_email if context references an email ID you need to read
- Use respond_text for questions, analysis, suggestions, or anything else

IMPORTANT: Your goal is to COMPLETE the user's request. If you searched for information,
use that information to write the email or provide the answer. Don't just report search results."""
        else:
            return f"""You are an AI email assistant helping the user.

CONTEXT:
{context_text}

---

INSTRUCTIONS: {instructions}

Choose the appropriate tool based on what the user wants:
- Use write_email if they want to compose/write/reply/send an email
- Use search_memory if you need more information before answering
- Use get_email if context references an email ID you need to read
- Use respond_text for questions, analysis, suggestions, or anything else

If writing an email:
- Use appropriate language (match recipient's language if known)
- If TEMPLATE entities are provided, use them as reference for tone and structure
- If recipient info is available, personalize appropriately

IMPORTANT: Your goal is to COMPLETE the user's request. If you searched for information,
use that information to write the email or provide the answer. Don't just report search results."""

    def _handle_tool_response(
        self,
        response,
        context: EmailContext,
        recipient_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Handle the LLM's tool response.

        Args:
            response: LLMResponse from create_message
            context: EmailContext with gathered data
            recipient_email: Optional recipient for emails

        Returns:
            Dict with tool_used, tool_input, and processed result
        """
        result = {
            'tool_used': None,
            'tool_input': {},
            'result': None
        }

        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):  # ToolUseBlock
                    result['tool_used'] = block.name
                    result['tool_input'] = block.input

                    # Process based on tool
                    if block.name == 'write_email':
                        result['result'] = self._process_write_email(
                            block.input, context, recipient_email
                        )
                    elif block.name == 'search_memory':
                        result['result'] = self._process_search_memory(block.input)
                    elif block.name == 'get_email':
                        result['result'] = self._process_get_email(block.input)
                    elif block.name == 'respond_text':
                        result['result'] = {
                            'response': block.input.get('response', '')
                        }
                    elif block.name == 'search_emails':
                        result['result'] = self._process_search_emails(block.input)
                    break
        else:
            # No tool called - extract text response as fallback
            for block in response.content:
                if hasattr(block, 'text'):
                    result['tool_used'] = 'respond_text'
                    result['result'] = {'response': block.text}
                    break

        return result

    def _process_write_email(
        self,
        tool_input: Dict[str, Any],
        context: EmailContext,
        recipient_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process write_email tool output.

        Adds threading headers if replying to a task with source emails.
        SAVES the draft to the database so it can be sent later via draft_id.

        Args:
            tool_input: The write_email tool's input (subject, body, to)
            context: EmailContext with source emails for threading
            recipient_email: Optional recipient override

        Returns:
            Email dict with subject, body, draft_id, and optional threading headers
        """
        subject = tool_input.get('subject', '')
        body = tool_input.get('body', '')

        # Use recipient from tool input or parameter
        to_email = tool_input.get('to') or recipient_email

        # Threading headers
        in_reply_to = None
        references = []
        thread_id = None

        # Add threading headers if replying to task with source emails
        if context.source_emails:
            latest_email = context.source_emails[-1]

            in_reply_to = latest_email.get('message_id_header')

            existing_refs = latest_email.get('references') or []
            msg_id = latest_email.get('message_id_header')
            if msg_id:
                references = existing_refs + [msg_id]
            else:
                references = existing_refs

            thread_id = latest_email.get('thread_id')

            # Extract recipient from original email if not provided
            if not to_email:
                to_email = latest_email.get('from_email')

        # Get user's email provider
        from zylch.api.token_storage import get_provider
        provider = get_provider(self.owner_id) or 'google'

        # SAVE DRAFT TO DATABASE
        draft_id = None
        if to_email:
            try:
                draft = self.storage.create_draft(
                    owner_id=self.owner_id,
                    to=to_email,
                    subject=subject,
                    body=body,
                    in_reply_to=in_reply_to,
                    references=references,
                    thread_id=thread_id,
                    provider=provider
                )
                if draft:
                    draft_id = draft.get('id')
                    logger.info(f"[EMAILER] Draft saved to DB with id={draft_id}")
            except Exception as e:
                logger.error(f"[EMAILER] Failed to save draft to DB: {e}")
                # Continue without draft_id - the email can still be shown but not sent

        result = {
            'subject': subject,
            'body': body,
            'recipient_email': to_email,
            'in_reply_to': in_reply_to,
            'references': references,
            'thread_id': thread_id,
            'draft_id': draft_id,  # NEW: For sending later
        }

        return result

    def _process_search_memory(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process search_memory tool by executing the search.

        Args:
            tool_input: The search_memory tool's input (query)

        Returns:
            Dict with search results
        """
        query = tool_input.get('query', '')
        if not query:
            return {'results': [], 'message': 'No search query provided'}

        namespace = f"user:{self.owner_id}"
        results = self.search_engine.search(
            owner_id=self.owner_id,
            query=query,
            namespace=namespace,
            limit=5
        )

        formatted = []
        for r in results:
            formatted.append({
                'content': r.content,
                'score': r.score if hasattr(r, 'score') else None
            })

        return {
            'results': formatted,
            'message': f"Found {len(results)} results for '{query}'"
        }

    def _process_get_email(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process get_email tool by fetching the email.

        Args:
            tool_input: The get_email tool's input (email_id)

        Returns:
            Dict with email content or error
        """
        email_id = tool_input.get('email_id', '')
        if not email_id:
            return {'error': 'No email ID provided'}

        email = self.storage.get_email_by_supabase_id(self.owner_id, email_id)
        if not email:
            return {'error': f'Email not found: {email_id}'}

        return {
            'from_email': email.get('from_email'),
            'to_email': email.get('to_email'),
            'subject': email.get('subject'),
            'date': email.get('date'),
            'body': email.get('body_plain', '')
        }

    def _process_search_emails(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process search_emails tool by searching actual emails.

        Args:
            tool_input: The search_emails tool's input (query, days_back, limit)

        Returns:
            Dict with email results
        """
        query = tool_input.get('query', '')
        limit = tool_input.get('limit', 5)

        if not query:
            return {'emails': [], 'message': 'No search query provided'}

        logger.debug(f"[EMAILER] _process_search_emails: query='{query}', limit={limit}")

        # Search emails using storage (hybrid FTS + semantic search)
        try:
            emails = self.storage.search_emails(
                owner_id=self.owner_id,
                query=query,
                limit=limit
            )
        except Exception as e:
            logger.error(f"[EMAILER] Email search failed: {e}")
            emails = []

        formatted = []
        for email in emails:
            formatted.append({
                'from_email': email.get('from_email', ''),
                'to_email': email.get('to_email', ''),
                'subject': email.get('subject', ''),
                'date': email.get('date', ''),
                'body': email.get('body_plain', '')[:500],  # Truncate for context
                'id': email.get('id', '')
            })

        logger.debug(f"[EMAILER] _process_search_emails found {len(formatted)} emails")

        return {
            'emails': formatted,
            'message': f"Found {len(formatted)} emails for '{query}'"
        }
