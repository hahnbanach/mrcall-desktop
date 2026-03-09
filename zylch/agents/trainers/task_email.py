"""Task Agent Builder - Generates personalized task detection agent from user's behavior patterns.

Analyzes the user's email threads and memory blobs to understand:
- How quickly they respond to different contacts
- Who are their VIP contacts (frequent, quick responses)
- What patterns indicate they ignore something
- Commitment phrases they use ("I'll call you", "let me check")

Then generates a self-contained agent prompt for identifying actionable items.
"""

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zylch.config import settings
from zylch.llm import LLMClient, PROVIDER_MODELS
from zylch.storage.supabase_client import SupabaseStorage
from zylch.memory import HybridSearchEngine, EmbeddingEngine, MemoryConfig

logger = logging.getLogger(__name__)

# Truncation limits to avoid context window overflow
MAX_EMAIL_BODY_CHARS = 5000
MAX_BLOB_CONTENT_CHARS = 2000


# Meta-prompt used to generate the task detection agent
TASK_AGENT_META_PROMPT = """You are analyzing a user's communication history to create a personalized prompt for identifying actionable items.

Your goal: Generate a prompt that an AI agent will use to analyze individual events and decide if the user needs to take action.

=== LAST {search_limit} EMAIL THREADS ===
{threads}

=== MEMORY BLOBS FOR CONTACTS IN THESE THREADS ===
{blobs}

---

Analyze the above material to understand:
1. How quickly does this user typically respond to emails? (Look at time gaps between received and sent)
2. Does the user send automatic responses? If so, do not consider them as actual answers. 
3. What patterns indicate they ignore something? (Cold outreach, newsletters, certain domains)
4. Do they use commitment phrases like "I'll call you", "let me check", "I'll send you"?
5. What commitments did they make that they followed up on vs forgot?

Then generate a SELF-CONTAINED prompt that will be used to analyze ONE event at a time.

The generated prompt must:

1. **ENCODE LEARNED PATTERNS**
   Based on the above analysis, embed specific knowledge about this user:
   - Their typical response time to important contacts
   - VIP contact patterns or specific contacts (if identifiable)
   - Noise/ignore signals specific to this user
   - Commitment phrases this user tends to use

2. **DECISION CRITERIA**
   The prompt should instruct the agent to consider:
   - Is there an unanswered question directed at the user? (Do not take automatic reply as answers!)
   - Did the user make a commitment that needs follow-up? If yes, it needs a task
   - Did the user answer without commitment to follow-up? DEFINITELY not an open task!
   - Is this from someone the user typically responds to quickly?
   - Has unusual time passed without response (based on this user's pattern)?
   - Is there a deadline or time-sensitive element?

3. **OUTPUT FORMAT**
   For each event analyzed, output exactly ONE of:
   - `ACTION: [urgency] | [suggested action] | [brief reason]`
   - `NO_ACTION: [reason]`

   Where urgency is: high, medium, or low

   Examples:
   - `ACTION: high | Reply to proposal | John asked a direct question 3 days ago, user typically responds within 24h`
   - `ACTION: medium | Follow up on call promise | User said "I'll call you this week" 5 days ago`
   - `NO_ACTION: Newsletter from marketing platform, user ignores these`

The generated prompt will receive these template variables:
- {{event_type}} - "email" | "calendar" | "mrcall"
- {{event_data}} - The event to analyze (JSON with from_email, subject, body, date, etc.)
- {{blob_context}} - Memory blob for this contact (if exists), or "(no prior context)"
- {{user_email}} - User's email address (to identify their own messages)
- {{calendar_context}} - Upcoming and recent meetings with this contact (if any)

**CRITICAL RULES FOR THE GENERATED PROMPT:**
1. NEVER suggest action for emails FROM {{user_email}} - these are the user's own sent messages
2. NEVER list {{user_email}} as a contact to follow up with - the user doesn't follow up with themselves
3. When {{event_data}} shows from_email matches {{user_email}}, output NO_ACTION

**CALENDAR CONTEXT RULES:**
When {{calendar_context}} is provided, consider:
1. **Upcoming meeting exists** → Don't create "schedule call" or "set up meeting" tasks - a meeting is already planned
2. **Recent meeting happened (past 7 days)** → Consider if follow-up is needed based on meeting type:
   - "Proposal Review", "Sales Demo" → likely needs follow-up
   - "Quick sync", "1:1", "Team standup" → likely no follow-up needed
3. **Email + Meeting combination** → If someone emails "let's discuss" but you already have a meeting with them, output NO_ACTION for scheduling

**EXECUTIVE ASSISTANT MINDSET:**
The agent acts as a real human assistant to an executive:
- The executive's time is valuable - don't create noise
- Provide enough context to understand AND act, not just a one-liner
- The suggested_action should be specific enough that the executive knows exactly what to do
- The reason should explain WHY this matters now

**OUTPUT QUALITY:**
- suggested_action must be non-empty and actionable
- reason must provide sufficient context (2-3 sentences if needed)
- If you can't determine a clear action, output NO_ACTION

OUTPUT ONLY THE PROMPT TEXT. No explanations, no markdown code blocks. Just the prompt itself."""


class EmailTaskAgentTrainer:
    """Builds personalized task detection prompt by analyzing user email patterns."""

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        user_email: str,
        provider: str
    ):
        """Initialize EmailTaskAgentTrainer.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            user_email: User's email address (for identifying sent vs received)
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.storage = storage
        self.owner_id = owner_id
        self.provider = provider
        self.model = PROVIDER_MODELS.get(provider, settings.default_model)
        self.client = LLMClient(api_key=api_key, provider=provider)
        self.user_email = user_email.lower() if user_email else ''
        self.user_domain = user_email.split('@')[1].lower() if user_email and '@' in user_email else ''

        # Initialize hybrid search for blob retrieval
        config = MemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        from zylch.storage.database import get_session
        self.hybrid_search = HybridSearchEngine(
            get_session,
            self.embedding_engine
        )
        self.search_limit = 20  # Reduced from 100 to avoid context window overflow

    async def build_task_prompt(self) -> Tuple[str, Dict[str, Any]]:
        """Analyze user's history and generate task detection prompt.

        Returns:
            Tuple of (prompt_content, metadata)
        """
        logger.info(f"Building task detection prompt for {self.owner_id}")

        # Step 1: Get last self.search_limit threads with full conversation context
        threads = self._get_recent_threads(limit=self.search_limit)
        logger.info(f"Found {len(threads)} threads for analysis")

        # Step 2: Extract contacts from these threads
        contact_emails = self._extract_contacts(threads)
        logger.info(f"Found {len(contact_emails)} unique contacts")

        # Step 3: Get blobs for these contacts from memory
        blobs = self._get_blobs_for_contacts(contact_emails)
        logger.info(f"Found {len(blobs)} memory blobs")

        # Step 4: Format for META_PROMPT
        threads_text = self._format_threads(threads)
        blobs_text = self._format_blobs(blobs)

        # Step 5: Generate the prompt using Claude
        prompt_content = self._generate_prompt(threads_text, blobs_text)

        metadata = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'user_domain': self.user_domain,
            'threads_analyzed': len(threads),
            'frequent_contacts_count': len(contact_emails),
            'blobs_found': len(blobs)
        }

        return prompt_content, metadata

    def _get_recent_threads(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent email threads with full conversation context.

        Returns threads (grouped emails) rather than individual emails,
        so the LLM can see response patterns.
        """
        # Fetch enough emails to get ~self.search_limit threads
        emails = self.storage.get_emails(self.owner_id, limit=self.search_limit*3)

        # Group by thread_id
        threads: Dict[str, List[Dict]] = {}
        for email in emails:
            tid = email.get('thread_id', email.get('id', ''))  # Fallback to id if no thread
            if tid:
                if tid not in threads:
                    threads[tid] = []
                threads[tid].append(email)

        # Sort emails within each thread by date
        for tid in threads:
            threads[tid].sort(key=lambda e: e.get('date_timestamp', 0))

        # Sort threads by most recent email
        thread_list = []
        for tid, emails in threads.items():
            if emails:
                most_recent = max(e.get('date_timestamp', 0) for e in emails)
                thread_list.append({
                    'thread_id': tid,
                    'emails': emails,
                    'most_recent': most_recent
                })

        thread_list.sort(key=lambda t: t['most_recent'], reverse=True)

        return thread_list[:limit]

    def _extract_contacts(self, threads: List[Dict[str, Any]]) -> List[str]:
        """Extract unique contact emails from threads."""
        contacts = set()

        for thread in threads:
            for email in thread.get('emails', []):
                from_email = email.get('from_email', '').lower()
                # Exclude user's own domain
                if from_email and self.user_domain and self.user_domain not in from_email:
                    contacts.add(from_email)

        return list(contacts)

    def _get_blobs_for_contacts(self, contact_emails: List[str]) -> List[Dict[str, Any]]:
        """Get memory blobs for the given contacts."""
        blobs = []
        namespace = f"user:{self.owner_id}"

        for email in contact_emails[:self.search_limit]:  # Limit to avoid too many searches
            try:
                results = self.hybrid_search.search(
                    owner_id=self.owner_id,
                    query=email,  # Search by email address
                    namespace=namespace,
                    limit=1
                )
                if results:
                    blobs.append({
                        'contact_email': email,
                        'content': results[0].content,
                        'blob_id': results[0].blob_id
                    })
            except Exception as e:
                logger.warning(f"Failed to search blob for {email}: {e}")

        return blobs

    def _format_threads(self, threads: List[Dict[str, Any]]) -> str:
        """Format threads as text for the meta-prompt.

        Only includes the last email per thread since it typically contains
        the quoted conversation history.
        """
        formatted = []

        for i, thread in enumerate(threads, 1):
            emails = thread.get('emails', [])
            if not emails:
                continue

            # Get subject from first email, but use LAST email for content
            subject = emails[0].get('subject', '(no subject)')
            last_email = emails[-1]  # Last email has the full thread context

            from_email = last_email.get('from_email', 'unknown')
            date = last_email.get('date', 'unknown')
            body = last_email.get('body_plain', '') or last_email.get('snippet', '')
            if len(body) > MAX_EMAIL_BODY_CHARS:
                body = body[:MAX_EMAIL_BODY_CHARS] + '...[truncated]'

            is_user = self.user_domain and self.user_domain in from_email.lower()
            sender_label = f"{from_email} [USER]" if is_user else from_email

            thread_text = f"""
--- Thread {i}: {subject} ({len(emails)} emails) ---
From: {sender_label}
Date: {date}
Body: {body}
"""
            formatted.append(thread_text)

        return '\n'.join(formatted) if formatted else "No threads available."

    def _format_blobs(self, blobs: List[Dict[str, Any]]) -> str:
        """Format memory blobs as text for the meta-prompt."""
        if not blobs:
            return "No memory blobs found for these contacts."

        formatted = []
        for blob in blobs:
            content = blob['content']
            if len(content) > MAX_BLOB_CONTENT_CHARS:
                content = content[:MAX_BLOB_CONTENT_CHARS] + '...[truncated]'
            formatted.append(f"""
--- Blob for {blob['contact_email']} ---
{content}
""")

        return '\n'.join(formatted)

    def _generate_prompt(self, threads_text: str, blobs_text: str) -> str:
        """Generate the final task detection prompt using LLM."""
        meta_prompt = TASK_AGENT_META_PROMPT.format(
            threads=threads_text,
            blobs=blobs_text,
            search_limit=self.search_limit
        )

        logger.info(f"Training task detection agent (provider: {self.provider})...")
        logger.debug(f"Prompt size: {len(meta_prompt)} chars (~{len(meta_prompt)//4} tokens)")

        response = self.client.create_message_sync(
            model=self.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": meta_prompt}]
        )

        prompt_content = response.content[0].text.strip()
        logger.info(f"Generated task prompt ({len(prompt_content)} chars)")
        return prompt_content
