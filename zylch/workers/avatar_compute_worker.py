"""Background worker for avatar computation.

Runs as Railway cron job every 5 minutes.
Processes avatar_compute_queue in batches.
"""

import asyncio
import logging
import os
import sys
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import anthropic

from zylch.config import settings
from zylch.services.avatar_aggregator import AvatarAggregator
from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)


# Phone number extraction patterns
PHONE_PATTERNS = [
    r'\+?1?[-.\s]?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',  # US/Canada
    r'\+([0-9]{1,3})[-.\s]?([0-9]{1,4})[-.\s]?([0-9]{1,4})[-.\s]?([0-9]{1,9})',  # International
    r'\+[0-9]{7,15}',  # E.164
]

LINKEDIN_PATTERNS = [
    r'linkedin\.com/in/([a-zA-Z0-9\-]+)',
    r'linkedin\.com/pub/([a-zA-Z0-9\-]+)',
]


def extract_phone_numbers(text: str) -> List[str]:
    """Extract phone numbers from text.

    Args:
        text: Text to search for phone numbers

    Returns:
        List of normalized phone numbers
    """
    if not text:
        return []

    phones = set()
    for pattern in PHONE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                # Reconstruct phone from groups
                phone = ''.join(match)
            else:
                phone = match

            # Normalize: remove non-digits except leading +
            digits = re.sub(r'[^\d+]', '', phone)
            if len(digits) >= 7 and len(digits) <= 15:
                phones.add(normalize_phone(digits))

    return list(phones)


def extract_linkedin_urls(text: str) -> List[str]:
    """Extract LinkedIn profile URLs from text.

    Args:
        text: Text to search for LinkedIn URLs

    Returns:
        List of normalized LinkedIn URLs
    """
    if not text:
        return []

    urls = set()
    for pattern in LINKEDIN_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Normalize: linkedin.com/in/username
            normalized = f"linkedin.com/in/{match}"
            urls.add(normalized)

    return list(urls)


def normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format.

    Args:
        phone: Phone number string

    Returns:
        Normalized phone in E.164 format (+1234567890)
    """
    digits = re.sub(r'\D', '', phone)

    # Assume US if no country code and 10 digits
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    else:
        # Keep as-is if has country code
        return f"+{digits}"


class AvatarComputeWorker:
    """Background worker for avatar computation.

    Runs as Railway cron job every 5 minutes.
    Processes avatar_compute_queue in batches.
    """

    def __init__(
        self,
        storage: SupabaseStorage,
        anthropic_client: anthropic.Anthropic,
        batch_size: int = 10
    ):
        """Initialize worker.

        Args:
            storage: Supabase storage client
            anthropic_client: Anthropic API client
            batch_size: Number of avatars to process per batch
        """
        self.storage = storage
        self.anthropic = anthropic_client
        self.aggregator = AvatarAggregator(storage)
        self.batch_size = batch_size

    async def run_once(self):
        """Process one batch from queue.

        Called by Railway cron: */5 * * * *
        """
        logger.info("Avatar compute worker starting...")

        # Fetch batch from queue (ordered by priority)
        try:
            batch = self.storage.client.table('avatar_compute_queue')\
                .select('*')\
                .order('priority', desc=True)\
                .order('scheduled_at', desc=False)\
                .limit(self.batch_size)\
                .execute()

            if not batch.data:
                logger.info("No avatars to compute")
                return

            logger.info(f"Processing {len(batch.data)} avatars...")

            for item in batch.data:
                try:
                    await self._process_avatar(item)
                except Exception as e:
                    logger.error(f"Error processing {item['contact_id']}: {e}")
                    self._handle_retry(item)

            logger.info(f"Batch complete: {len(batch.data)} avatars updated")

        except Exception as e:
            logger.error(f"Failed to fetch queue: {e}")

    async def _process_avatar(self, queue_item: Dict):
        """Process single avatar from queue.

        Args:
            queue_item: Queue entry with owner_id, contact_id, trigger_type, priority
        """
        start_time = datetime.now(timezone.utc)
        contact_id = queue_item['contact_id']
        owner_id = queue_item['owner_id']

        logger.info(f"Processing avatar: {contact_id} (trigger: {queue_item['trigger_type']})")

        # Get user's encrypted Anthropic API key
        user_api_key = self.storage.get_anthropic_key(owner_id)
        if not user_api_key:
            logger.warning(f"No Anthropic key for owner {owner_id}, skipping avatar {contact_id}")
            # Remove from queue but don't process
            self.storage.client.table('avatar_compute_queue')\
                .delete()\
                .eq('id', queue_item['id'])\
                .execute()
            return

        # Create per-user Anthropic client
        user_anthropic = anthropic.Anthropic(api_key=user_api_key)

        # 1. Build context (NO LLM - just data aggregation)
        context = self.aggregator.build_context(
            owner_id=owner_id,
            contact_id=contact_id
        )

        # 2. Call Claude ONCE for relationship analysis (using user's key)
        analysis = await self._analyze_relationship(context, user_anthropic)

        # 3. Update avatar in database
        avatar_data = {
            'owner_id': owner_id,
            'contact_id': contact_id,
            'display_name': analysis.get('contact_name', context['display_name']),
            'identifiers': context['identifiers'],
            'relationship_summary': analysis['relationship_summary'],
            'relationship_status': analysis['status'],
            'relationship_score': analysis['priority'],
            'suggested_action': analysis.get('action'),
            'interaction_summary': {
                'thread_count': context['thread_count'],
                'email_count': context['email_count'],
                'last_interaction': context['threads'][0]['date'] if context['threads'] else None
            },
            'preferred_tone': analysis.get('preferred_tone', 'professional'),
            'response_latency': context['response_latency'],
            'relationship_strength': context['relationship_strength'],
            'last_computed': datetime.now(timezone.utc).isoformat(),
            'compute_trigger': queue_item['trigger_type'],
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        # Upsert avatar
        self.storage.client.table('avatars').upsert(
            avatar_data,
            on_conflict='owner_id,contact_id'
        ).execute()

        # 4. Store extracted phone numbers in identifier_map
        for phone in analysis.get('extracted_phones', []):
            try:
                self.storage.client.table('identifier_map').upsert({
                    'owner_id': owner_id,
                    'identifier': phone,
                    'identifier_type': 'phone',
                    'contact_id': contact_id,
                    'confidence': 0.9,  # Claude extracted, high confidence but not 100%
                    'source': 'claude_avatar_analysis',
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }, on_conflict='owner_id,identifier').execute()
                logger.info(f"Stored phone identifier: {phone} for contact {contact_id}")
            except Exception as e:
                logger.warning(f"Failed to store phone {phone}: {e}")

        # 5. Store extracted LinkedIn URL in identifier_map
        if analysis.get('extracted_linkedin'):
            try:
                self.storage.client.table('identifier_map').upsert({
                    'owner_id': owner_id,
                    'identifier': analysis['extracted_linkedin'],
                    'identifier_type': 'linkedin',
                    'contact_id': contact_id,
                    'confidence': 1.0,  # LinkedIn URLs are explicit
                    'source': 'claude_avatar_analysis',
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }, on_conflict='owner_id,identifier').execute()
                logger.info(f"Stored LinkedIn identifier: {analysis['extracted_linkedin']} for contact {contact_id}")
            except Exception as e:
                logger.warning(f"Failed to store LinkedIn: {e}")

        # 6. Generate embedding for semantic search (using sentence-transformers)
        # TODO: Implement embedding generation
        # embedding = self._generate_embedding(analysis['relationship_summary'])
        # self.storage.update_avatar_embedding(owner_id, contact_id, embedding)

        # 7. Remove from queue
        self.storage.client.table('avatar_compute_queue')\
            .delete()\
            .eq('id', queue_item['id'])\
            .execute()

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(f"✓ Updated avatar for {contact_id} in {duration:.1f}s")

    async def _analyze_relationship(self, context: Dict, anthropic_client: anthropic.Anthropic) -> Dict:
        """Analyze relationship using Claude with user's API key.

        This is the ONLY LLM call in the avatar computation flow.

        Args:
            context: Aggregated context from AvatarAggregator
            anthropic_client: Per-user Anthropic client

        Returns:
            Dict with:
            - contact_name: Display name
            - relationship_summary: Narrative summary
            - status: 'open', 'waiting', 'closed'
            - priority: 1-10
            - action: Suggested next step
            - preferred_tone: 'formal', 'casual', 'professional'
        """
        prompt = self._build_avatar_prompt(context)

        try:
            response = anthropic_client.messages.create(
                model=settings.default_model,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            content = response.content[0].text
            return self._parse_analysis(content, context)

        except Exception as e:
            logger.error(f"Failed to analyze relationship: {e}")
            # Return fallback analysis
            return self._fallback_analysis(context)

    def _build_avatar_prompt(self, context: Dict) -> str:
        """Build prompt for relationship analysis.

        Args:
            context: Aggregated context

        Returns:
            Prompt string for Claude
        """
        # Build thread summaries with snippet for context
        thread_summaries = []
        for t in context['threads'][:10]:
            summary = f"- {t.get('date', 'Unknown date')}: {t.get('subject', 'No subject')} ({t.get('from_email', 'Unknown sender')})"
            if t.get('snippet'):
                summary += f"\n  Preview: {t.get('snippet')[:200]}"
            thread_summaries.append(summary)

        threads_text = "\n".join(thread_summaries) if thread_summaries else "No recent emails"

        # Build calendar summaries
        event_summaries = []
        for e in context['calendar_events'][:5]:
            event_summaries.append(
                f"- {e.get('start_time', 'Unknown date')}: {e.get('summary', 'No title')}"
            )

        events_text = "\n".join(event_summaries) if event_summaries else "No recent meetings"

        # Combine email bodies for identifier extraction (first 5 emails, 500 chars each)
        all_email_content = []
        for t in context['threads'][:5]:
            if t.get('body_plain'):
                all_email_content.append(t['body_plain'][:500])

        combined_content = "\n---\n".join(all_email_content) if all_email_content else "No email content available"

        prompt = f"""Analyze this professional relationship and provide a concise summary.

**Contact:** {context['display_name']}
**Emails:** {', '.join(context['identifiers']['emails'])}

**Communication Stats:**
- Email threads: {context['thread_count']}
- Total emails: {context['email_count']}
- Emails per week: {context['communication_frequency']['emails_per_week']}
- Recent meetings: {context['communication_frequency']['events_per_month']}
- Last contact: {context['communication_frequency'].get('last_contact_days_ago', 'Unknown')} days ago
- Relationship strength: {context['relationship_strength']:.2f}/1.0

**Recent Email Threads (last 10):**
{threads_text}

**Recent Meetings (last 5):**
{events_text}

**Email Content Sample (for contact info extraction):**
{combined_content}

**Response Time:**
{context['response_latency'] or 'Insufficient data'}

---

Please provide:
1. **Name:** Best guess for their name (if different from {context['display_name']})
2. **Phone:** Any phone numbers found in email signatures/content (format: +1234567890 or comma-separated)
3. **LinkedIn:** LinkedIn profile URL if found in emails (format: linkedin.com/in/username)
4. **Summary:** 2-3 sentence narrative of the relationship context and recent interactions
5. **Status:** One of:
   - "open" - needs action from me (I need to respond/follow up)
   - "waiting" - waiting for them (I responded, ball in their court)
   - "closed" - no action needed (conversation complete or no pending items)
6. **Priority:** 1-10 score (10 = most urgent/important)
7. **Action:** Suggested next step (or "No action needed")
8. **Tone:** Their preferred communication style: "formal", "casual", or "professional"

Format your response as:
NAME: [name]
PHONE: [phone numbers, comma-separated, or "Not found"]
LINKEDIN: [linkedin.com/in/username or "Not found"]
SUMMARY: [relationship summary]
STATUS: [open/waiting/closed]
PRIORITY: [1-10]
ACTION: [suggested action]
TONE: [formal/casual/professional]
"""

        return prompt

    def _parse_analysis(self, content: str, context: Dict) -> Dict:
        """Parse Claude's response into structured data.

        Args:
            content: Raw response from Claude
            context: Original context (for fallback)

        Returns:
            Parsed analysis dict with extracted identifiers
        """
        try:
            name_match = re.search(r'NAME:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
            phone_match = re.search(r'PHONE:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
            linkedin_match = re.search(r'LINKEDIN:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
            summary_match = re.search(r'SUMMARY:\s*(.+?)(?:\nSTATUS:|$)', content, re.IGNORECASE | re.DOTALL)
            status_match = re.search(r'STATUS:\s*(open|waiting|closed)', content, re.IGNORECASE)
            priority_match = re.search(r'PRIORITY:\s*(\d+)', content)
            action_match = re.search(r'ACTION:\s*(.+?)(?:\nTONE:|$)', content, re.IGNORECASE | re.DOTALL)
            tone_match = re.search(r'TONE:\s*(formal|casual|professional)', content, re.IGNORECASE)

            # Parse phone numbers
            extracted_phones = []
            if phone_match:
                phone_text = phone_match.group(1).strip()
                if phone_text.lower() != 'not found':
                    # Split comma-separated phones
                    for p in phone_text.split(','):
                        p = p.strip()
                        if p and len(p) >= 7:
                            extracted_phones.append(normalize_phone(p))

            # Parse LinkedIn URL
            extracted_linkedin = None
            if linkedin_match:
                linkedin_text = linkedin_match.group(1).strip()
                if linkedin_text.lower() != 'not found':
                    # Normalize URL
                    linkedin_text = linkedin_text.replace('https://', '').replace('http://', '')
                    linkedin_text = linkedin_text.replace('www.', '')
                    linkedin_text = linkedin_text.rstrip('/')
                    if 'linkedin.com/in/' in linkedin_text:
                        extracted_linkedin = linkedin_text

            return {
                'contact_name': name_match.group(1).strip() if name_match else context['display_name'],
                'extracted_phones': extracted_phones,
                'extracted_linkedin': extracted_linkedin,
                'relationship_summary': summary_match.group(1).strip() if summary_match else content[:500],
                'status': status_match.group(1).lower() if status_match else 'unknown',
                'priority': int(priority_match.group(1)) if priority_match else 5,
                'action': action_match.group(1).strip() if action_match else None,
                'preferred_tone': tone_match.group(1).lower() if tone_match else 'professional'
            }

        except Exception as e:
            logger.warning(f"Failed to parse analysis: {e}")
            return self._fallback_analysis(context, content)

    def _fallback_analysis(self, context: Dict, content: str = '') -> Dict:
        """Generate fallback analysis when LLM fails.

        Args:
            context: Aggregated context
            content: Raw LLM response (for regex extraction attempt)

        Returns:
            Basic analysis dict
        """
        # Still attempt regex extraction on raw content
        extracted_phones = extract_phone_numbers(content) if content else []
        extracted_linkedin = extract_linkedin_urls(content)

        return {
            'contact_name': context['display_name'],
            'extracted_phones': extracted_phones[:3],  # Max 3
            'extracted_linkedin': extracted_linkedin[0] if extracted_linkedin else None,
            'relationship_summary': f"Contact with {context['email_count']} emails across {context['thread_count']} threads.",
            'status': 'unknown',
            'priority': 5,
            'action': 'Review manually',
            'preferred_tone': 'professional'
        }

    def _handle_retry(self, item: Dict):
        """Handle failed avatar computation with exponential backoff.

        Args:
            item: Queue item that failed
        """
        retry_count = item.get('retry_count', 0) + 1

        if retry_count >= 3:
            # Max retries exceeded - remove from queue
            self.storage.client.table('avatar_compute_queue')\
                .delete()\
                .eq('id', item['id'])\
                .execute()
            logger.warning(f"✗ Max retries exceeded for {item['contact_id']}")
        else:
            # Schedule retry with exponential backoff
            delay_hours = 2 ** retry_count  # 2h, 4h, 8h
            scheduled_at = datetime.now(timezone.utc) + timedelta(hours=delay_hours)

            self.storage.client.table('avatar_compute_queue')\
                .update({
                    'retry_count': retry_count,
                    'scheduled_at': scheduled_at.isoformat()
                })\
                .eq('id', item['id'])\
                .execute()

            logger.info(f"↻ Retry {retry_count}/3 for {item['contact_id']} in {delay_hours}h")


# CLI entry point for Railway cron
async def main():
    """Main entry point for Railway cron job."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("="*60)
    logger.info("Avatar Compute Worker Starting")
    logger.info("="*60)

    # Initialize services
    storage = SupabaseStorage.get_instance()

    anthropic_client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key
    )

    worker = AvatarComputeWorker(storage, anthropic_client, batch_size=10)

    # Run one batch
    await worker.run_once()

    logger.info("="*60)
    logger.info("Avatar Compute Worker Complete")
    logger.info("="*60)


if __name__ == "__main__":
    asyncio.run(main())
