"""Emailer Agent Trainer - Generates personalized email writing agent from user's sent emails.

Analyzes the user's sent email history to understand:
- Writing style (greetings, sign-offs, tone)
- Language preferences
- Email structure patterns

Then generates a self-contained agent prompt for email composition that matches
the user's authentic style.

This trainer extends BaseAgentTrainer for shared initialization and methods.
"""

import logging
from typing import Any, Dict, List, Tuple

from zylch.agents.base_trainer import BaseAgentTrainer
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

# Meta-prompt used to generate the emailer agent
# Now includes multi-tool instructions for the agent
EMAILER_META_PROMPT = """You are analyzing a user's sent emails to create a personalized email writing assistant.

Your goal: Generate a prompt that enables an email agent to handle various email-related tasks.

=== USER'S PROFILE ===
{user_profile}

=== SAMPLE SENT EMAILS ===
{sent_email_samples}

=== AGENT CAPABILITIES ===
The agent you're creating will have these tools:
1. **write_email** - Compose and save an email as draft
2. **search_memory** - Search blobs for context about person/company/template
3. **get_email** - Fetch original email by ID when blob context is insufficient
4. **respond_text** - Return analysis/suggestions/answers (not an email)

=== BLOB MEMORY STRUCTURE ===
The system has entity blobs with 3 types:
- PERSON: #IDENTIFIERS (name, email, company) + #ABOUT (relationship) + #HISTORY (interactions)
- COMPANY: #IDENTIFIERS (name, website) + #ABOUT (what they do) + #HISTORY (our relationship)
- TEMPLATE: #IDENTIFIERS (name) + #ABOUT (offer/product/service details) + #HISTORY (who we discussed it with)

Each blob tracks which source emails the information came from (in event_description).

---

Generate a COMPLETE, SELF-CONTAINED prompt for an email agent. The prompt must include:

1. **USER'S WRITING STYLE**
   - Typical greeting style (formal/informal, language)
   - Sign-off patterns (name, title, signature format)
   - Tone and formality level
   - Typical email structure (short/long, paragraphs, bullet points)
   - Language preferences (Italian/English, mix patterns)

2. **TOOL SELECTION GUIDANCE**
   Instruct the agent when to use each tool:
   - Use `write_email` when: user wants to compose, write, reply, send an email
   - Use `search_memory` when: need more context before answering or composing
   - Use `get_email` when: blob references an email ID and more details are needed
   - Use `respond_text` when: user asks a question, wants analysis, suggestions, or information

3. **CONTEXT USAGE INSTRUCTIONS**
   The agent receives context sections and should use them appropriately:

   a) **ABOUT THE RECIPIENT** (PERSON blobs)
      - Who is this person?
      - What's our relationship history?
      - Use details from #HISTORY to personalize

   b) **RELEVANT COMPANY INFO** (COMPANY blobs)
      - What does their company do?
      - Our business relationship

   c) **TEMPLATES TO USE** (TEMPLATE blobs)
      - Previous similar emails we've sent
      - Offer details, pricing, terms
      - CRITICAL: Use these as reference for structure and content

   d) **SOURCE EMAILS** (from task)
      - Email thread we're replying to
      - Extract recipient preferences from their communication style

4. **OUTPUT RULES FOR EMAILS**
   - Match the user's writing style exactly
   - Personalize based on recipient context
   - Use appropriate language (match recipient's language if in thread)
   - Reference specific details from blobs (shows we remember them)
   - Keep the same tone and formality as the user's samples

The generated prompt will receive these context sections:
- ## ABOUT THE RECIPIENT (PERSON blobs)
- ## RELEVANT COMPANY INFO (COMPANY blobs)
- ## EMAIL THREAD / SOURCES (source emails from task)
- ## TEMPLATES TO USE (TEMPLATE blobs)

OUTPUT ONLY THE PROMPT TEXT. No explanations, no markdown code blocks. Just the prompt itself."""


class EmailerAgentTrainer(BaseAgentTrainer):
    """Builds personalized email writing agent by analyzing user's sent emails.

    Extends BaseAgentTrainer for shared initialization and methods.
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str
    ):
        """Initialize EmailerAgentTrainer.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            user_email: User's email address (for identifying sent emails)
            provider: LLM provider (anthropic, openai, mistral)
        """
        super().__init__(storage, owner_id, api_key, user_email, provider)

    async def build_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Build the emailer agent prompt.

        Implements the abstract method from BaseAgentTrainer.

        Returns:
            Tuple of (prompt_content, metadata)
        """
        return await self.build_emailer_prompt()

    async def build_emailer_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Analyze user's sent emails and generate personalized writing prompt.

        Returns:
            Tuple of (prompt_content, metadata)
        """
        logger.info(f"Building emailer prompt for {self.owner_id}")

        # Step 1: Get user's SENT emails using inherited method
        sent_emails = self._get_emails(limit=50, filter_sent=True)
        logger.info(f"Found {len(sent_emails)} sent emails")

        if not sent_emails:
            raise ValueError(
                "No sent emails found. Please sync your emails first with /sync email "
                "and ensure you have sent emails in your mailbox."
            )

        # Step 2: Analyze writing patterns using inherited method
        user_profile = self._analyze_user_profile(sent_emails)
        logger.debug(f"User profile: {user_profile}")

        # Step 3: Format samples for the meta-prompt using inherited method
        sent_samples = self._format_email_samples(sent_emails, max_samples=15, body_limit=800)

        # Step 4: Generate the prompt using inherited method
        meta_prompt = EMAILER_META_PROMPT.format(
            user_profile=user_profile,
            sent_email_samples=sent_samples
        )
        prompt_content = self._generate_prompt(meta_prompt, max_tokens=4000)

        # Step 5: Build metadata using inherited method
        metadata = self._build_metadata(sent_emails_analyzed=len(sent_emails))

        return prompt_content, metadata
