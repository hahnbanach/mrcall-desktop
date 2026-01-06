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
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from zylch.llm import LLMClient
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
    for blob in blobs[:3]:  # Limit to top 3
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_template_blobs(blobs: List[SearchResult]) -> str:
    """Format TEMPLATE blobs for prompt context."""
    if not blobs:
        return ""

    sections = []
    for blob in blobs[:2]:  # Limit to top 2 templates
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_company_blobs(blobs: List[SearchResult]) -> str:
    """Format COMPANY blobs for prompt context."""
    if not blobs:
        return ""

    sections = []
    for blob in blobs[:2]:  # Limit to top 2
        sections.append(blob.content)

    return "\n\n".join(sections)


def _format_source_emails(emails: List[dict]) -> str:
    """Format source emails for prompt context."""
    if not emails:
        return ""

    sections = []
    for email in emails[:3]:  # Limit to 3 most relevant
        from_display = email.get('from_name') or email.get('from_email', 'Unknown')
        subject = email.get('subject', '(no subject)')
        body = email.get('body_plain') or email.get('snippet', '')[:500]
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


class EmailerAgent:
    """Multi-tool agent for email-related tasks.

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
        self.storage = storage
        self.owner_id = owner_id

        # Initialize hybrid search
        config = MemoryConfig()
        embedding_engine = EmbeddingEngine(config)
        self.search_engine = HybridSearchEngine(
            supabase_client=storage.client,
            embedding_engine=embedding_engine
        )

        self.gatherer = EmailContextGatherer(storage, self.search_engine, owner_id)
        self.llm = LLMClient(api_key=api_key, provider=provider)

        # Cache for trained prompt (lazy loaded)
        self._trained_prompt: Optional[str] = None
        self._prompt_loaded: bool = False

        logger.info(f"EmailerAgent initialized for owner={owner_id}")

    def _get_trained_prompt(self) -> Optional[str]:
        """Get trained email writing prompt from storage.

        Loads user's trained prompt from DB on first call, caches for subsequent calls.
        Returns None if no trained prompt exists (user hasn't run /agent email train).

        Returns:
            The trained prompt, or None if not configured
        """
        if not self._prompt_loaded:
            self._trained_prompt = self.storage.get_agent_prompt(self.owner_id, 'emailer')
            self._prompt_loaded = True

            if self._trained_prompt:
                logger.info("Using user's trained emailer prompt")
            else:
                logger.debug("No trained emailer prompt - using generic")

        return self._trained_prompt

    def has_trained_prompt(self) -> bool:
        """Check if user has a trained emailer prompt.

        Returns:
            True if user has trained the emailer agent
        """
        if not self._prompt_loaded:
            self._get_trained_prompt()  # Trigger load
        return self._trained_prompt is not None

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
    ) -> Dict[str, Any]:
        """Execute the email agent with given instructions.

        This is the main entry point for the multi-tool agent. The agent
        decides which tool to use based on the instructions:

        - "scrivi a Mario un'offerta" → write_email
        - "What can I answer to this guy?" → respond_text
        - "cerca info su Acme Corp" → search_memory → respond_text
        - "reply to task 3" → gather context → write_email

        Args:
            instructions: What the user wants to do
            recipient_email: Optional recipient email (for email composition)
            task_num: Optional 1-indexed task number from /tasks

        Returns:
            Dict with:
            - tool_used: Name of the tool the agent chose
            - tool_input: Input the agent provided to the tool
            - result: Processed result (email dict for write_email, text for respond_text)
        """
        # Gather context
        context = await self.gatherer.gather(
            user_request=instructions,
            recipient_email=recipient_email,
            task_num=task_num
        )

        # Build prompt context
        context_text = build_prompt_context(context)

        # Check for trained prompt (personalized style)
        trained_prompt = self._get_trained_prompt()

        if trained_prompt:
            # Use trained prompt - already contains style and tool selection instructions
            prompt = f"""{trained_prompt}

---

CONTEXT:
{context_text}

---

INSTRUCTIONS: {instructions}

Choose the appropriate tool based on what the user wants:
- Use write_email if they want to compose/write/reply/send an email
- Use search_memory if you need more information before answering
- Use get_email if context references an email ID you need to read
- Use respond_text for questions, analysis, suggestions, or anything else"""
        else:
            # Fallback to generic prompt (no personalized style)
            prompt = f"""You are an AI email assistant helping the user.

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
- If recipient info is available, personalize appropriately"""

        logger.debug(f"[EMAILER] run() sending prompt ({len(prompt)} chars)")

        # Call LLM with all tools - let it choose
        response = await self.llm.create_message(
            messages=[{"role": "user", "content": prompt}],
            tools=self.TOOLS,
            max_tokens=2000
        )

        # Handle tool response
        result = self._handle_tool_response(response, context, recipient_email)

        return result

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

        Args:
            tool_input: The write_email tool's input (subject, body, to)
            context: EmailContext with source emails for threading
            recipient_email: Optional recipient override

        Returns:
            Email dict with subject, body, and optional threading headers
        """
        result = {
            'subject': tool_input.get('subject', ''),
            'body': tool_input.get('body', ''),
        }

        # Use recipient from tool input or parameter
        to_email = tool_input.get('to') or recipient_email
        if to_email:
            result['recipient_email'] = to_email

        # Add threading headers if replying to task with source emails
        if context.source_emails:
            latest_email = context.source_emails[-1]

            result['in_reply_to'] = latest_email.get('message_id_header')

            existing_refs = latest_email.get('references') or []
            msg_id = latest_email.get('message_id_header')
            if msg_id:
                result['references'] = existing_refs + [msg_id]
            else:
                result['references'] = existing_refs

            result['thread_id'] = latest_email.get('thread_id')

            # Extract recipient from original email if not provided
            if not to_email:
                result['recipient_email'] = latest_email.get('from_email')

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
            'body': email.get('body_plain', '')[:2000]
        }
