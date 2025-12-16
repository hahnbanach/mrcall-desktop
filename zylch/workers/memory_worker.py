"""Memory Agent - Extract and store contact identifiers from emails.

Processes emails in background to extract phone numbers and LinkedIn URLs,
storing them in ZylchMemory with reconsolidation and identifier_map for O(1) lookup.

Uses regex for phone/LinkedIn extraction, optional Haiku for relationship context.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import anthropic

from zylch.config import settings
from zylch.storage.supabase_client import SupabaseStorage
from zylch_memory import ZylchMemory
from zylch_memory import BlobStorage
from zylch_memory import HybridSearchEngine

logger = logging.getLogger(__name__)


# ============================================================================
# REGEX PATTERNS
# ============================================================================

# US phone patterns: (555) 123-4567, 555-123-4567, +1-555-123-4567, etc.
US_PHONE_PATTERNS = [
    r'\+?1?[-.\s]?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
    r'\b([0-9]{3})[-.]([0-9]{3})[-.]([0-9]{4})\b',
]

# International phone patterns: +44 20 7946 0958, +86 10 1234 5678, etc.
INTL_PHONE_PATTERNS = [
    r'\+([0-9]{1,3})[-.\s]?([0-9]{1,4})[-.\s]?([0-9]{1,4})[-.\s]?([0-9]{1,9})',
]

# E.164 format: +15551234567 (strict format)
E164_PATTERN = r'\+[0-9]{7,15}\b'

# LinkedIn profile URLs
LINKEDIN_PATTERNS = [
    r'(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-]+)',
    r'(?:https?://)?(?:www\.)?linkedin\.com/pub/([a-zA-Z0-9\-/]+)',
]


def extract_phone_numbers(text: str) -> List[str]:
    """Extract phone numbers from text using multiple regex patterns.

    Args:
        text: Text to search for phone numbers

    Returns:
        List of normalized phone numbers in E.164 format
    """
    if not text:
        return []

    phones = set()

    # Try E.164 first (most strict)
    for match in re.finditer(E164_PATTERN, text):
        phone = match.group(0)
        digits = re.sub(r'\D', '', phone)
        if 7 <= len(digits) <= 15:
            phones.add(normalize_phone(digits))

    # Try US patterns
    for pattern in US_PHONE_PATTERNS:
        for match in re.finditer(pattern, text):
            if isinstance(match.groups(), tuple):
                # Reconstruct from groups
                phone = ''.join(match.groups())
            else:
                phone = match.group(0)

            digits = re.sub(r'\D', '', phone)
            if 7 <= len(digits) <= 15:
                phones.add(normalize_phone(digits))

    # Try international patterns
    for pattern in INTL_PHONE_PATTERNS:
        for match in re.finditer(pattern, text):
            if isinstance(match.groups(), tuple):
                phone = ''.join(match.groups())
            else:
                phone = match.group(0)

            digits = re.sub(r'\D', '', phone)
            if 7 <= len(digits) <= 15:
                phones.add(normalize_phone(digits))

    return list(phones)


def normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format (+1234567890).

    Args:
        phone: Phone number string (may contain non-digits)

    Returns:
        Normalized phone in E.164 format
    """
    # Remove all non-digits
    digits = re.sub(r'\D', '', phone)

    # Assume US/Canada if exactly 10 digits and no country code
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    elif len(digits) >= 7:
        # Keep as-is if has country code (or at least 7 digits)
        return f"+{digits}"
    else:
        # Invalid, return as-is with +
        return f"+{digits}"


def extract_linkedin_urls(text: str) -> List[str]:
    """Extract LinkedIn profile URLs from text.

    Args:
        text: Text to search for LinkedIn URLs

    Returns:
        List of normalized LinkedIn URLs (linkedin.com/in/username format)
    """
    if not text:
        return []

    urls = set()

    for pattern in LINKEDIN_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            username = match.group(1)
            # Normalize: always use /in/ format, strip trailing slashes
            normalized = f"linkedin.com/in/{username.strip('/')}"
            urls.add(normalized)

    return list(urls)


# ============================================================================
# MEMORY WORKER
# ============================================================================

class MemoryWorker:
    """Background worker for extracting contact identifiers from emails.

    Extracts phone numbers and LinkedIn URLs using regex patterns.
    Stores in ZylchMemory (with reconsolidation) and identifier_map (for O(1) lookup).
    Optional: Uses Haiku to extract relationship context (cheap, best-effort).
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        memory: ZylchMemory,
        anthropic_api_key: str = "",
        blob_storage: Optional[BlobStorage] = None
    ):
        """Initialize MemoryWorker.

        Args:
            storage: SupabaseStorage instance for email/identifier access
            memory: ZylchMemory instance for storing memories (legacy)
            anthropic_api_key: Anthropic API key (BYOK - from Supabase)
            blob_storage: Optional BlobStorage instance for new entity-memory system
        """
        self.storage = storage
        self.memory = memory
        self.blob_storage = blob_storage
        # Anthropic client is optional - memory extraction works without it
        self.anthropic = anthropic.Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None

        logger.info("MemoryWorker initialized (blob_storage: %s)", "enabled" if blob_storage else "disabled")

    async def process_email(self, email_id: str, owner_id: str) -> None:
        """Process single email to extract and store identifiers.

        Args:
            email_id: Email ID to process
            owner_id: Owner ID for namespacing

        Raises:
            Exception: On critical errors (logged but not re-raised)
        """
        try:
            logger.debug(f"Processing email {email_id} for owner {owner_id}")

            # Fetch email from storage
            email = self._fetch_email(email_id, owner_id)
            if not email:
                logger.warning(f"Email {email_id} not found for owner {owner_id}")
                return

            # Extract identifiers using regex
            phones = self._extract_phones(email)
            linkedin = self._extract_linkedin(email)

            logger.debug(
                f"Extracted from email {email_id}: "
                f"{len(phones)} phone(s), "
                f"{'1 LinkedIn' if linkedin else '0 LinkedIn'}"
            )

            # Determine contact_id (from email address)
            contact_email = email.get('from_email') or email.get('to_email', [''])[0]
            if not contact_email:
                logger.warning(f"No contact email found for email {email_id}")
                return

            contact_id = self._get_or_create_contact_id(owner_id, contact_email)

            # Store phone numbers
            for phone in phones:
                try:
                    self._store_phone_identifier(owner_id, contact_id, phone, email_id)
                except Exception as e:
                    logger.error(f"Failed to store phone {phone}: {e}", exc_info=True)

            # Store LinkedIn URL
            if linkedin:
                try:
                    self._store_linkedin_identifier(owner_id, contact_id, linkedin, email_id)
                except Exception as e:
                    logger.error(f"Failed to store LinkedIn {linkedin}: {e}", exc_info=True)

            # Optional: Extract relationship context using Haiku (best-effort)
            try:
                context = await self._extract_relationship_context(email)
                if context:
                    self._store_relationship_memory(
                        owner_id=owner_id,
                        contact_email=contact_email,
                        context=context,
                        email_id=email_id
                    )
            except Exception as e:
                logger.warning(f"Failed to extract relationship context: {e}")

            logger.info(f"Successfully processed email {email_id}")

        except Exception as e:
            logger.error(f"Error processing email {email_id}: {e}", exc_info=True)
            # Don't re-raise - continue processing other emails

    async def process_batch(self, email_ids: List[str], owner_id: str) -> None:
        """Process batch of emails (10 emails per Claude call for relationship context).

        Note: Phone/LinkedIn extraction is done via regex (no Claude calls).
        Claude Haiku is used ONLY for relationship context extraction (batched).

        Args:
            email_ids: List of email IDs to process
            owner_id: Owner ID
        """
        logger.info(f"Processing batch of {len(email_ids)} emails for owner {owner_id}")

        # Process each email individually for identifier extraction
        # (regex-based, no Claude needed)
        for email_id in email_ids:
            await self.process_email(email_id, owner_id)

        logger.info(f"Batch processing complete: {len(email_ids)} emails")

    # ------------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------------

    def _fetch_email(self, email_id: str, owner_id: str) -> Optional[Dict]:
        """Fetch email from storage.

        Args:
            email_id: Email ID
            owner_id: Owner ID

        Returns:
            Email dict or None if not found
        """
        try:
            result = self.storage.client.table('emails')\
                .select('*')\
                .eq('id', email_id)\
                .eq('owner_id', owner_id)\
                .execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"Failed to fetch email {email_id}: {e}")
            return None

    def _extract_phones(self, email: Dict) -> List[str]:
        """Extract phone numbers from email content.

        Args:
            email: Email dict with body_plain, body_html, snippet fields

        Returns:
            List of normalized phone numbers
        """
        # Combine all text fields
        text_parts = [
            email.get('body_plain', ''),
            email.get('snippet', ''),
            email.get('subject', ''),
        ]

        combined_text = '\n'.join(filter(None, text_parts))

        phones = extract_phone_numbers(combined_text)

        if phones:
            logger.debug(f"Extracted phones from email {email.get('id')}: {phones}")

        return phones

    def _extract_linkedin(self, email: Dict) -> Optional[str]:
        """Extract LinkedIn URL from email content.

        Args:
            email: Email dict

        Returns:
            Normalized LinkedIn URL or None
        """
        text_parts = [
            email.get('body_plain', ''),
            email.get('snippet', ''),
            email.get('subject', ''),
        ]

        combined_text = '\n'.join(filter(None, text_parts))

        urls = extract_linkedin_urls(combined_text)

        if urls:
            logger.debug(f"Extracted LinkedIn from email {email.get('id')}: {urls[0]}")
            return urls[0]  # Return first match

        return None

    def _get_or_create_contact_id(self, owner_id: str, email: str) -> str:
        """Get contact_id for email address (or create if not exists).

        Args:
            owner_id: Owner ID
            email: Contact email address

        Returns:
            contact_id (UUID string)
        """
        try:
            # Check identifier_map first
            result = self.storage.client.table('identifier_map')\
                .select('contact_id')\
                .eq('owner_id', owner_id)\
                .eq('identifier', email)\
                .eq('identifier_type', 'email')\
                .execute()

            if result.data:
                return result.data[0]['contact_id']

            # Not found - generate new contact_id
            # (In production, this would create a proper contact record)
            import uuid
            contact_id = str(uuid.uuid4())

            # Store email identifier
            self.storage.client.table('identifier_map').insert({
                'owner_id': owner_id,
                'identifier': email,
                'identifier_type': 'email',
                'contact_id': contact_id,
                'confidence': 1.0,
                'source': 'email_processor',
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).execute()

            logger.debug(f"Created new contact_id {contact_id} for email {email}")
            return contact_id

        except Exception as e:
            logger.error(f"Failed to get/create contact_id for {email}: {e}")
            # Fallback: use email as contact_id
            return email

    def _store_phone_identifier(
        self,
        owner_id: str,
        contact_id: str,
        phone: str,
        email_id: str
    ) -> None:
        """Store phone identifier in both Memory and identifier_map.

        Args:
            owner_id: Owner ID
            contact_id: Contact ID
            phone: Normalized phone number
            email_id: Source email ID
        """
        # Store in identifier_map for O(1) lookup
        self.storage.client.table('identifier_map').upsert({
            'owner_id': owner_id,
            'identifier': phone,
            'identifier_type': 'phone',
            'contact_id': contact_id,
            'confidence': 0.9,  # High confidence (regex-based)
            'source': 'memory_worker',
            'updated_at': datetime.now(timezone.utc).isoformat()
        }, on_conflict='owner_id,identifier').execute()

        # Store in new blob system if available
        if self.blob_storage:
            namespace = f"user:{owner_id}"
            content = f"Phone number for contact {contact_id}: {phone}"
            self.blob_storage.store_blob(
                owner_id=owner_id,
                namespace=namespace,
                content=content,
                event_description=f"Extracted phone from email {email_id}"
            )
        else:
            # Fallback to legacy ZylchMemory (with reconsolidation)
            namespace = f"contact:{contact_id}"
            self.memory.store_memory(
                namespace=namespace,
                category="contacts",
                context=f"Phone number for contact {contact_id}",
                pattern=f"Phone: {phone}",
                examples=[email_id],
                confidence=0.9
            )

        logger.info(f"Stored phone identifier: {phone} -> {contact_id}")

    def _store_linkedin_identifier(
        self,
        owner_id: str,
        contact_id: str,
        linkedin: str,
        email_id: str
    ) -> None:
        """Store LinkedIn identifier in both Memory and identifier_map.

        Args:
            owner_id: Owner ID
            contact_id: Contact ID
            linkedin: Normalized LinkedIn URL
            email_id: Source email ID
        """
        # Store in identifier_map
        self.storage.client.table('identifier_map').upsert({
            'owner_id': owner_id,
            'identifier': linkedin,
            'identifier_type': 'linkedin',
            'contact_id': contact_id,
            'confidence': 1.0,  # Perfect confidence (explicit URL)
            'source': 'memory_worker',
            'updated_at': datetime.now(timezone.utc).isoformat()
        }, on_conflict='owner_id,identifier').execute()

        # Store in new blob system if available
        if self.blob_storage:
            namespace = f"user:{owner_id}"
            content = f"LinkedIn profile for contact {contact_id}: {linkedin}"
            self.blob_storage.store_blob(
                owner_id=owner_id,
                namespace=namespace,
                content=content,
                event_description=f"Extracted LinkedIn from email {email_id}"
            )
        else:
            # Fallback to legacy ZylchMemory
            namespace = f"contact:{contact_id}"
            self.memory.store_memory(
                namespace=namespace,
                category="contacts",
                context=f"LinkedIn profile for contact {contact_id}",
                pattern=f"LinkedIn: {linkedin}",
                examples=[email_id],
                confidence=1.0
            )

        logger.info(f"Stored LinkedIn identifier: {linkedin} -> {contact_id}")

    async def _extract_relationship_context(self, email: Dict) -> Optional[str]:
        """Extract relationship context using Claude Haiku (cheap, best-effort).

        This is OPTIONAL and uses the cheapest model (Haiku) to extract
        high-level relationship context like:
        - "Working on project X together"
        - "Discussed collaboration opportunity"
        - "Follow-up on previous meeting"

        Args:
            email: Email dict

        Returns:
            Relationship context string or None
        """
        try:
            # Build prompt
            snippet = email.get('snippet', '')[:500]  # Limit to 500 chars
            subject = email.get('subject', '')
            from_email = email.get('from_email', '')

            if not snippet and not subject:
                return None

            prompt = f"""Analyze this email and extract a brief relationship context (1 sentence max).

Subject: {subject}
From: {from_email}
Content: {snippet}

What is the nature of this interaction? (e.g., "discussing project collaboration", "follow-up meeting", "sales inquiry")
Reply with ONLY the context phrase, nothing else."""

            response = self.anthropic.messages.create(
                model="claude-3-5-haiku-20241022",  # Cheapest model
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}]
            )

            context = response.content[0].text.strip()

            logger.debug(f"Extracted relationship context: {context}")
            return context

        except Exception as e:
            logger.warning(f"Failed to extract relationship context: {e}")
            return None

    def _store_relationship_memory(
        self,
        owner_id: str,
        contact_email: str,
        context: str,
        email_id: str
    ) -> None:
        """Store relationship context in Memory system.

        Args:
            owner_id: Owner ID
            contact_email: Contact email address
            context: Relationship context string
            email_id: Source email ID
        """
        try:
            # Store in new blob system if available
            if self.blob_storage:
                namespace = f"user:{owner_id}"
                content = f"Relationship with {contact_email}: {context}"
                self.blob_storage.store_blob(
                    owner_id=owner_id,
                    namespace=namespace,
                    content=content,
                    event_description=f"Extracted from email {email_id}"
                )
            else:
                # Fallback to legacy ZylchMemory
                namespace = f"contact:{contact_email}"
                self.memory.store_memory(
                    namespace=namespace,
                    category="relationships",
                    context=f"Relationship with {contact_email}",
                    pattern=context,
                    examples=[email_id],
                    confidence=0.7  # Moderate confidence (LLM-based)
                )

            logger.debug(f"Stored relationship memory for {contact_email}: {context}")

        except Exception as e:
            logger.error(f"Failed to store relationship memory: {e}")


# ============================================================================
# CLI Entry Point
# ============================================================================

async def main():
    """Main entry point for testing."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 60)
    logger.info("Memory Worker Test")
    logger.info("=" * 60)

    # Initialize services
    storage = SupabaseStorage.get_instance()
    memory = ZylchMemory()

    worker = MemoryWorker(storage, memory)

    # Example: Process a single email
    # await worker.process_email("email_id_here", "owner_id_here")

    # Example: Process batch
    # await worker.process_batch(["email1", "email2"], "owner_id")

    logger.info("=" * 60)
    logger.info("Memory Worker Test Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
