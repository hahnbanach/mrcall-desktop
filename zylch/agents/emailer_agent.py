"""Emailer Agent - Write emails with full context from memory.

Gathers context (emails, blobs, templates) using hybrid search and generates
contextual email drafts. No complex conditional logic - uses a single unified
context gathering strategy.

Key principle: "Find a balance between putting a bit more than necessary
in memory and not overloading the assistant."
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from zylch.llm import LLMClient
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, ZylchMemoryConfig
from zylch.memory.hybrid_search import SearchResult

logger = logging.getLogger(__name__)


# Maximum characters for context to leave room for LLM generation
MAX_CONTEXT_CHARS = 8000


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
    """Specialized agent for writing emails with full context.

    Gathers context using hybrid search (PERSON, COMPANY, TEMPLATE blobs)
    and task sources, then uses LLM to generate contextual emails.
    """

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
        config = ZylchMemoryConfig()
        embedding_engine = EmbeddingEngine(config)
        search_engine = HybridSearchEngine(
            supabase_client=storage.client,
            embedding_engine=embedding_engine
        )

        self.gatherer = EmailContextGatherer(storage, search_engine, owner_id)
        self.llm = LLMClient(api_key=api_key, provider=provider)

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
            Dict with 'subject' and 'body' keys
        """
        # Gather context
        context = await self.gatherer.gather(
            user_request=user_request,
            recipient_email=recipient_email,
            task_num=task_num
        )

        # Build prompt context
        context_text = build_prompt_context(context)

        # Generate email
        prompt = f"""You are writing an email for the user.

{context_text}

---

USER REQUEST: {user_request}

Write the email in the appropriate language (match the request language).
If templates are provided, use them as reference for tone and structure.
If recipient info is available, personalize the email appropriately.

Output ONLY valid JSON with this exact structure:
{{"subject": "...", "body": "..."}}

Do not include any other text or markdown formatting."""

        logger.debug(f"[EMAILER] Sending prompt ({len(prompt)} chars)")

        response = await self.llm.create_message(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000
        )

        # Extract text from LLMResponse object
        text = response.content[0].text if response.content else ""

        # Parse response
        return self._parse_response(text)

    def _parse_response(self, response: str) -> Dict[str, str]:
        """Parse LLM response to extract subject and body."""
        import json

        try:
            # Clean response - remove markdown code blocks if present
            text = response.strip()
            if text.startswith("```"):
                # Remove ```json and ``` markers
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])

            result = json.loads(text)
            return {
                "subject": result.get("subject", ""),
                "body": result.get("body", "")
            }
        except json.JSONDecodeError as e:
            logger.error(f"[EMAILER] Failed to parse response: {e}")
            logger.debug(f"[EMAILER] Raw response: {response[:500]}")
            # Fallback: treat entire response as body
            return {
                "subject": "(draft email)",
                "body": response
            }
