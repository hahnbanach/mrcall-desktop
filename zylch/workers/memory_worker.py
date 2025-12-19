"""Memory Agent - Extract facts from emails and store in entity-centric blobs.

Processes emails to extract relationship information about contacts,
storing in blobs with reconsolidation (merging with existing knowledge).

Uses hybrid search (FTS + semantic) to find existing blobs about the same entity,
then LLM-merges new information with existing knowledge.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import anthropic

from zylch.storage.supabase_client import SupabaseStorage
from zylch_memory import BlobStorage, HybridSearchEngine, LLMMergeService, EmbeddingEngine, ZylchMemoryConfig

logger = logging.getLogger(__name__)


# Default prompt to extract facts from email (used when no custom prompt exists)
DEFAULT_EXTRACT_FACTS_PROMPT = """Extract key facts about the contact from this email.

FROM: {from_email}
TO: {to_email}
CC: {cc_email}
SUBJECT: {subject}
DATE: {date}

BODY:
{body}

---

Write a concise summary of what we learned about {contact_email} from this email.
Include:
- Any personal details (phone, LinkedIn, location, company, role)
- Communication preferences or patterns
- Topics discussed or interests shown
- Action items or commitments made
- Relationship context (how they know the user)

Output ONLY the facts as natural language prose (2-5 sentences). If no meaningful facts, output "No significant facts."
"""


class MemoryWorker:
    """Worker for extracting facts from emails and storing in entity-centric blobs.

    Flow:
    1. Extract facts from email about the contact
    2. Search for existing blob about this entity (hybrid search)
    3. If found: LLM-merge new facts with existing knowledge
    4. If not found: create new blob
    5. Mark email as processed
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        anthropic_api_key: str = ""
    ):
        """Initialize MemoryWorker.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID for namespace
            anthropic_api_key: Anthropic API key for LLM operations
        """
        self.storage = storage
        self.owner_id = owner_id
        self.namespace = f"user:{owner_id}"

        # BYOK - API key must be provided, no env var fallback
        if not anthropic_api_key:
            raise ValueError(
                "Anthropic API key required for memory extraction. "
                "Please run `/connect anthropic` to configure your API key."
            )
        api_key = anthropic_api_key

        # Initialize components
        config = ZylchMemoryConfig()
        self.embedding_engine = EmbeddingEngine(config)
        self.blob_storage = BlobStorage(
            storage.client,
            self.embedding_engine
        )
        self.hybrid_search = HybridSearchEngine(
            storage.client,
            self.embedding_engine
        )
        self.llm_merge = LLMMergeService(api_key)

        # Also use Anthropic for fact extraction
        self.anthropic = anthropic.Anthropic(api_key=api_key)

        # Cache for user's custom prompt (lazy loaded)
        self._custom_prompt: Optional[str] = None
        self._custom_prompt_loaded: bool = False

        logger.info(f"MemoryWorker initialized for namespace={self.namespace}")

    def _get_extraction_prompt(self) -> str:
        """Get extraction prompt - user-specific or default.

        Loads user's custom prompt from DB on first call, caches for subsequent calls.

        Returns:
            The extraction prompt to use
        """
        if not self._custom_prompt_loaded:
            self._custom_prompt = self.storage.get_user_prompt(self.owner_id, 'memory_email')
            self._custom_prompt_loaded = True

            if self._custom_prompt:
                logger.info("Using user's custom memory_email prompt")
            else:
                logger.debug("No custom prompt found, using default")

        return self._custom_prompt if self._custom_prompt else DEFAULT_EXTRACT_FACTS_PROMPT

    def has_custom_prompt(self) -> bool:
        """Check if user has a custom extraction prompt.

        Returns:
            True if user has configured a custom prompt
        """
        if not self._custom_prompt_loaded:
            self._get_extraction_prompt()  # Trigger load
        return self._custom_prompt is not None

    async def process_email(self, email: Dict) -> bool:
        """Process single email to extract and store facts.

        Args:
            email: Email dict with id, from_email, to_email, subject, body_plain, date

        Returns:
            True if processed successfully, False otherwise
        """
        email_id = email.get("id", "unknown")
        try:
            logger.debug(f"Processing email {email_id}")

            # Determine the contact (the other party, not the user)
            from_email = email.get("from_email", "")
            to_emails = email.get("to_email", [])
            if isinstance(to_emails, str):
                to_emails = [to_emails]

            # Contact is whoever is not the user
            # For now, use from_email as the contact (most common case: incoming email)
            contact_email = from_email
            if not contact_email:
                logger.warning(f"No contact email for {email_id}")
                # Still mark as processed so we don't retry
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True

            # Step 1: Extract facts from email
            facts = self._extract_facts(email, contact_email)
            if not facts or facts == "No significant facts.":
                logger.debug(f"No facts extracted from {email_id}")
                # Still mark as processed so we don't retry
                self.storage.mark_email_processed(self.owner_id, email_id)
                return True

            # Step 2: Search for existing blob about this entity
            existing = self.hybrid_search.find_for_reconsolidation(
                owner_id=self.owner_id,
                content=facts,
                namespace=self.namespace
            )

            # Step 3: Reconsolidate or create new
            event_desc = f"Extracted from email {email_id} ({email.get('date', 'unknown date')})"

            if existing:
                # Merge with existing blob
                logger.debug(f"Found existing blob {existing.blob_id} for reconsolidation (score={existing.hybrid_score:.2f})")
                merged_content = self.llm_merge.merge(existing.content, facts)

                self.blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=self.owner_id,
                    content=merged_content,
                    event_description=event_desc
                )
                logger.info(f"Reconsolidated blob {existing.blob_id} with email {email_id}")
            else:
                # Create new blob
                blob = self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=self.namespace,
                    content=facts,
                    event_description=event_desc
                )
                logger.info(f"Created new blob {blob['id']} from email {email_id}")

            # Step 4: Mark email as processed
            self.storage.mark_email_processed(self.owner_id, email_id)
            return True

        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}", exc_info=True)
            return False

    async def process_batch(self, emails: List[Dict]) -> int:
        """Process batch of emails.

        Args:
            emails: List of email dicts (from get_unprocessed_emails)

        Returns:
            Number of successfully processed emails
        """
        logger.info(f"Processing batch of {len(emails)} emails")
        processed = 0

        for email in emails:
            success = await self.process_email(email)
            if success:
                processed += 1

        logger.info(f"Batch complete: {processed}/{len(emails)} processed")
        return processed

    def _extract_facts(self, email: Dict, contact_email: str) -> str:
        """Extract facts from email using LLM.

        Uses user's custom prompt if available, otherwise falls back to default.

        Args:
            email: Email dict
            contact_email: Email address of the contact

        Returns:
            Extracted facts as natural language string
        """
        try:
            # Get email body, prefer body_plain, fall back to snippet
            body = email.get("body_plain", "") or email.get("snippet", "")

            # Get the extraction prompt (user's custom or default)
            prompt_template = self._get_extraction_prompt()

            # Format cc_email (may be list or string or None)
            cc_raw = email.get("cc_email") or email.get("cc") or []
            if isinstance(cc_raw, list):
                cc_email = ", ".join(cc_raw) if cc_raw else "(none)"
            else:
                cc_email = cc_raw if cc_raw else "(none)"

            prompt = prompt_template.format(
                from_email=email.get("from_email", "unknown"),
                to_email=", ".join(email.get("to_email", [])) if isinstance(email.get("to_email"), list) else email.get("to_email", "unknown"),
                cc_email=cc_email,
                subject=email.get("subject", "(no subject)"),
                date=email.get("date", "unknown"),
                body=body[:4000],  # Limit body size
                contact_email=contact_email
            )

            response = self.anthropic.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Failed to extract facts: {e}")
            return ""

    async def process_calendar_event(self, event: Dict) -> bool:
        """Process single calendar event to extract and store facts.

        Args:
            event: Event dict with id, summary, description, location, start_time, end_time, attendees

        Returns:
            True if processed successfully, False otherwise
        """
        event_id = event.get("id", "unknown")
        try:
            logger.debug(f"Processing calendar event {event_id}")

            # Extract facts from event
            facts = self._extract_calendar_facts(event)
            if not facts or facts == "No significant facts.":
                logger.debug(f"No facts extracted from event {event_id}")
                self.storage.mark_calendar_event_processed(self.owner_id, event_id)
                return True

            # Search for existing blob about this meeting/attendees
            existing = self.hybrid_search.find_for_reconsolidation(
                owner_id=self.owner_id,
                content=facts,
                namespace=self.namespace
            )

            event_desc = f"Extracted from calendar event '{event.get('summary', '')}' ({event.get('start_time', '')})"

            if existing:
                merged_content = self.llm_merge.merge(existing.content, facts)
                self.blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=self.owner_id,
                    content=merged_content,
                    event_description=event_desc
                )
                logger.info(f"Reconsolidated blob {existing.blob_id} with event {event_id}")
            else:
                blob = self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=self.namespace,
                    content=facts,
                    event_description=event_desc
                )
                logger.info(f"Created new blob {blob['id']} from event {event_id}")

            self.storage.mark_calendar_event_processed(self.owner_id, event_id)
            return True

        except Exception as e:
            logger.error(f"Error processing event {event_id}: {e}", exc_info=True)
            return False

    async def process_calendar_batch(self, events: List[Dict]) -> int:
        """Process batch of calendar events.

        Args:
            events: List of event dicts (from get_unprocessed_calendar_events)

        Returns:
            Number of successfully processed events
        """
        logger.info(f"Processing batch of {len(events)} calendar events")
        processed = 0

        for event in events:
            success = await self.process_calendar_event(event)
            if success:
                processed += 1

        logger.info(f"Calendar batch complete: {processed}/{len(events)} processed")
        return processed

    def _extract_calendar_facts(self, event: Dict) -> str:
        """Extract facts from calendar event using LLM.

        Args:
            event: Calendar event dict

        Returns:
            Extracted facts as natural language string
        """
        try:
            attendees = event.get("attendees", [])
            attendees_str = ", ".join(attendees) if isinstance(attendees, list) else str(attendees)

            prompt = f"""Extract key facts about attendees from this calendar event.

TITLE: {event.get('summary', '(no title)')}
DATE/TIME: {event.get('start_time', '')} - {event.get('end_time', '')}
LOCATION: {event.get('location', '(no location)')}
ATTENDEES: {attendees_str}
DESCRIPTION: {event.get('description', '(no description)')[:2000]}

---

Write a concise summary of what we learned from this meeting.
Include:
- Who attended and their relationship to the meeting
- Meeting purpose and topics discussed
- Any action items or follow-ups implied
- Context about the attendees (companies, roles if mentioned)

Output ONLY the facts as natural language prose (2-5 sentences). If no meaningful facts, output "No significant facts."
"""

            response = self.anthropic.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Failed to extract calendar facts: {e}")
            return ""

    async def process_pipedrive_deal(self, deal: Dict) -> bool:
        """Process single Pipedrive deal to extract and store facts.

        Args:
            deal: Deal dict with id, deal_id, title, person_name, org_name, value, status, deal_data

        Returns:
            True if processed successfully, False otherwise
        """
        deal_id = deal.get("id", "unknown")
        try:
            logger.debug(f"Processing pipedrive deal {deal_id}")

            # Extract facts from deal
            facts = self._extract_pipedrive_facts(deal)
            if not facts or facts == "No significant facts.":
                logger.debug(f"No facts extracted from deal {deal_id}")
                self.storage.mark_pipedrive_deal_processed(self.owner_id, deal_id)
                return True

            # Search for existing blob about this deal/contact
            existing = self.hybrid_search.find_for_reconsolidation(
                owner_id=self.owner_id,
                content=facts,
                namespace=self.namespace
            )

            event_desc = f"Extracted from Pipedrive deal '{deal.get('title', '')}' (ID: {deal.get('deal_id', '')})"

            if existing:
                merged_content = self.llm_merge.merge(existing.content, facts)
                self.blob_storage.update_blob(
                    blob_id=existing.blob_id,
                    owner_id=self.owner_id,
                    content=merged_content,
                    event_description=event_desc
                )
                logger.info(f"Reconsolidated blob {existing.blob_id} with deal {deal_id}")
            else:
                blob = self.blob_storage.store_blob(
                    owner_id=self.owner_id,
                    namespace=self.namespace,
                    content=facts,
                    event_description=event_desc
                )
                logger.info(f"Created new blob {blob['id']} from deal {deal_id}")

            self.storage.mark_pipedrive_deal_processed(self.owner_id, deal_id)
            return True

        except Exception as e:
            logger.error(f"Error processing deal {deal_id}: {e}", exc_info=True)
            return False

    async def process_pipedrive_batch(self, deals: List[Dict]) -> int:
        """Process batch of Pipedrive deals.

        Args:
            deals: List of deal dicts (from get_unprocessed_pipedrive_deals)

        Returns:
            Number of successfully processed deals
        """
        logger.info(f"Processing batch of {len(deals)} pipedrive deals")
        processed = 0

        for deal in deals:
            success = await self.process_pipedrive_deal(deal)
            if success:
                processed += 1

        logger.info(f"Pipedrive batch complete: {processed}/{len(deals)} processed")
        return processed

    def _extract_pipedrive_facts(self, deal: Dict) -> str:
        """Extract facts from Pipedrive deal using LLM.

        Args:
            deal: Pipedrive deal dict

        Returns:
            Extracted facts as natural language string
        """
        try:
            deal_data = deal.get("deal_data", {}) or {}

            prompt = f"""Extract key facts about the contact/company from this CRM deal.

DEAL TITLE: {deal.get('title', '(no title)')}
CONTACT: {deal.get('person_name', '(unknown)')}
COMPANY: {deal.get('org_name', '(unknown)')}
VALUE: {deal.get('value', 0)} {deal.get('currency', 'USD')}
STATUS: {deal.get('status', 'unknown')}
STAGE: {deal.get('stage_name', '(unknown)')}
EXPECTED CLOSE: {deal_data.get('expected_close_date', '(not set)')}
NOTES: {str(deal_data.get('notes', ''))[:1000]}

---

Write a concise summary of what we know about this deal and the contact.
Include:
- Contact/company information
- Deal context (what they're interested in, value, stage)
- Any notes or context about the relationship
- Deal status and timeline if available

Output ONLY the facts as natural language prose (2-5 sentences). If no meaningful facts, output "No significant facts."
"""

            response = self.anthropic.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()

        except Exception as e:
            logger.error(f"Failed to extract pipedrive facts: {e}")
            return ""
